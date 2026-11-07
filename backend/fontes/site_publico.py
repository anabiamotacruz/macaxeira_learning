"""Leitura de site público, só de URL indicada pela própria pessoa.

A URL é dado não confiável. Antes de cada conexão: esquema, porta e destino são conferidos, todo
endereço resolvido precisa ser público, e o pedido vai ao IP conferido, para o DNS não trocar a
resposta entre a conferência e a conexão. Redirecionamento repete tudo isso. `robots.txt` é
respeitado, e o robô se identifica. Login, CAPTCHA ou bloqueio encerram a leitura, sem contorno.

LinkedIn nunca é buscado, nem por serviço de terceiros, mesmo quando a própria pessoa indica.
PDF do LinkedIn entra só como arquivo enviado pela pessoa, em `documentos.py`.
"""

import ipaddress
import logging
import re
import socket
import time
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from threading import Lock
from typing import Any
from urllib.parse import unquote
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from bs4.element import Comment

from backend.agente.auditoria import rastreado
from backend.agente.neutralizacao import MAXIMO_DE_CARACTERES_DO_PERFIL
from backend.contratos.erros import ErroContrato, FonteIndisponivel
from backend.contratos.modelos import (
    Candidato,
    ContatoColetado,
    FatoColetado,
    PerfilColetado,
    TipoContato,
    TipoFato,
)
from backend.fontes.analisador import FIM_DE_FRASE, tem_instrucao, texto_permitido
from backend.fontes.anonimizador import Categoria, encontrar_contatos
from backend.fontes.perfis import candidato_de_perfil, combina_com_consulta

logger = logging.getLogger(__name__)

ETAPA_LER_SITE = "ler_site_indicado"
ETAPA_BUSCAR_SITE = "buscar_site_indicado"
FONTE_SITE = "site_indicado"
AGENTE = "macaxeira-learning-sourcing/0.1"
"""Nome real do robô. É o que `robots.txt` confere; nunca se passa por navegador."""

MAX_BYTES_PAGINA = 2 * 1024 * 1024
MAX_BYTES_ROBOTS = 512 * 1024
"""RFC 9309, seção 2.5: limite de leitura de pelo menos 500 KiB."""
MAX_REDIRECIONAMENTOS = 3
MAX_REDIRECIONAMENTOS_ROBOTS = 5
"""RFC 9309, seção 2.3.1.2: seguir pelo menos cinco redirecionamentos."""
TEMPO_LIMITE_LEITURA_S = 10.0
TEMPO_LIMITE_CONEXAO_S = 5.0
TEMPO_LIMITE = httpx.Timeout(TEMPO_LIMITE_LEITURA_S, connect=TEMPO_LIMITE_CONEXAO_S)
"""Vale por pedaço lido: um servidor que manda um byte por vez nunca passaria dele."""
PRAZO_TOTAL_PAGINA_S = 20.0
"""O tempo da página inteira, com `robots.txt` e redirecionamentos. A busca segura a vaga."""
VALIDADE_DO_CACHE_S = 300.0
"""Uma execução faz várias consultas: cada site é lido uma vez, e o resto usa o guardado."""
MAX_CARACTERES_PAGINA = MAXIMO_DE_CARACTERES_DO_PERFIL
MAX_ROTULO_DE_HOST = 63
MAX_HOST = 253
MIN_PALAVRAS_PARA_ALERTA = 5
"""Abaixo disso é rótulo de acessibilidade ou menu, e não uma afirmação escondida."""
MAX_SELETORES_COMPOSTOS = 20
MAX_ETIQUETAS_PARA_SELETOR_COMPOSTO = 20_000
PORTAS_PERMITIDAS = {"http": 80, "https": 443}
TIPOS_DE_CONTEUDO = ("text/html", "application/xhtml+xml", "text/plain")

ALERTA_INSTRUCAO_PAGINA = (
    "instrucao_na_pagina: a página traz texto dirigido ao avaliador, visível ou escondido; "
    "ele foi retirado."
)
ALERTA_TEXTO_ESCONDIDO_PAGINA = (
    "texto_escondido_na_pagina: a página esconde texto de quem lê, por estilo; ele foi retirado."
)

_HOSTS_PROIBIDOS = ("linkedin.com", "lnkd.in", "licdn.com")
_TERMOS_PROIBIDOS = ("linkedin", "lnkd.in", "licdn")
_ETIQUETAS_SEM_TEXTO = ("script", "style", "noscript", "template", "head")
_ETIQUETAS_FORA_DO_TEXTO = (
    "canvas",
    "datalist",
    "embed",
    "iframe",
    "noembed",
    "noframes",
    "object",
    "select",
    "svg",
    "textarea",
)
"""Não mostram texto corrido ao abrir a página: nada delas vira fato do perfil."""
_ATRIBUTOS_COM_TEXTO = ("alt", "title", "aria-label", "value", "placeholder")
_CORES_IGUAIS = {"#fff": "#ffffff", "white": "#ffffff", "#000": "#000000", "black": "#000000"}
_MEDIDA = re.compile(r"(-?\d*\.?\d+)([a-z%]*)")
_REGRA_CSS = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COMENTARIO_CSS = re.compile(r"/\*.*?\*/", re.S)
_BLOCO_DE_IMPRESSAO = re.compile(r"@media[^{]*\bprint\b[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", re.I)
_SELETOR_SIMPLES = re.compile(r"([a-z][\w-]*)?(?:#([\w-]+))?((?:\.[\w-]+)*)", re.I)
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_IPV4_EMBUTIDO = ipaddress.ip_network("::/96")
_SITE_LOCAL = ipaddress.ip_network("fec0::/10")
_REDIRECIONAMENTOS = (301, 302, 303, 307, 308)
_CATEGORIAS_DE_LINK = (Categoria.LINK, Categoria.PERFIL)


class UrlRecusada(ErroContrato):
    """A URL não pode ser lida. Nada foi pedido à rede por causa dela."""


class FonteProibida(UrlRecusada):
    """LinkedIn não é buscado, nem por terceiros."""


class EnderecoInterno(UrlRecusada):
    """Esquema, porta, credencial ou destino fora do permitido: proteção contra SSRF."""


class UrlNaoIndicada(UrlRecusada):
    """A própria pessoa não indicou esta URL."""


class BloqueadoPorRobots(ErroContrato):
    """`robots.txt` proíbe a leitura ou não pôde ser lido."""


class ConteudoRecusado(ErroContrato):
    """Resposta de tipo não textual ou maior que o limite."""


def _sem_www(host: str) -> str:
    return host.removeprefix("www.")


def _exigir_nao_proibida(url: str, host: str) -> None:
    """Também olha o resto da URL: tradutor, cache ou leitor de terceiros levam o alvo no texto."""
    em_host = any(host == h or host.endswith(f".{h}") for h in _HOSTS_PROIBIDOS)
    texto = url
    for _ in range(3):
        texto = unquote(texto)
    em_texto = any(termo in texto.casefold() for termo in _TERMOS_PROIBIDOS)
    if em_host or em_texto:
        raise FonteProibida("LinkedIn não é buscado, nem por terceiros.")


def _validar(url: str) -> httpx.URL:
    try:
        analisada = httpx.URL(url.strip())
    except (httpx.InvalidURL, TypeError) as erro:
        raise EnderecoInterno("URL inválida.") from erro
    host = analisada.host.casefold().rstrip(".")
    _exigir_nao_proibida(str(url), host)
    if len(host) > MAX_HOST or any(len(rotulo) > MAX_ROTULO_DE_HOST for rotulo in host.split(".")):
        raise EnderecoInterno("O nome do site passa do tamanho permitido.")
    if analisada.scheme not in PORTAS_PERMITIDAS or not host:
        raise EnderecoInterno("Só http e https, com um destino.")
    if analisada.userinfo:
        raise EnderecoInterno("URL com credencial é recusada.")
    if analisada.port not in (None, PORTAS_PERMITIDAS[analisada.scheme]):
        raise EnderecoInterno("Só as portas padrão de http e https.")
    return analisada


def _endereco_publico(endereco: str) -> bool:
    try:
        ip = ipaddress.ip_address(endereco.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif (
            ip.sixtofour is not None
            or ip.teredo is not None
            or ip in _IPV4_EMBUTIDO
            or ip in _SITE_LOCAL
            or any(ip in rede for rede in _NAT64)
        ):
            return False
    return ip.is_global and not ip.is_multicast


def resolver_dns(host: str, porta: int) -> list[str]:
    try:
        respostas = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as erro:
        raise FonteIndisponivel("Não foi possível resolver o endereço do site.") from erro
    return list(dict.fromkeys(str(r[4][0]) for r in respostas))


@dataclass(frozen=True)
class PaginaLida:
    url: str
    texto: str = field(repr=False)
    contatos: dict[str, str] = field(repr=False)
    alertas: list[str]


class LeitorSitePublico:
    def __init__(
        self,
        *,
        resolver: Callable[[str, int], Sequence[str]] = resolver_dns,
        http_client: httpx.Client | None = None,
        max_bytes: int = MAX_BYTES_PAGINA,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._resolver = resolver
        # Sem proxy do ambiente: ele faria a conexão sair do IP conferido.
        self._http = http_client or httpx.Client(
            timeout=TEMPO_LIMITE, follow_redirects=False, trust_env=False
        )
        self._max_bytes = max_bytes
        self._relogio = relogio

    def _restante(self, prazo: float) -> float:
        restante = prazo - self._relogio()
        if restante <= 0:
            raise FonteIndisponivel("O site passou do prazo total de leitura.")
        return restante

    def _ip_conferido(self, url: httpx.URL) -> str:
        porta = url.port or PORTAS_PERMITIDAS[url.scheme]
        host = url.host.casefold().rstrip(".")
        try:
            enderecos = [str(ipaddress.ip_address(host))]
        except ValueError:
            enderecos = list(self._resolver(host, porta))
        if not enderecos or not all(_endereco_publico(e) for e in enderecos):
            raise EnderecoInterno("O endereço do site não é público.")
        return enderecos[0]

    def _pedir(self, url: httpx.URL, limite: int, prazo: float) -> tuple[int, httpx.Headers, bytes]:
        """Um pedido, ao IP conferido, mantendo `Host` e o nome usado na conferência do TLS."""
        restante = self._restante(prazo)
        ip = self._ip_conferido(url)
        cabecalhos = {"Host": url.netloc.decode("ascii"), "User-Agent": AGENTE, "Accept": "text/*"}
        pedido = self._http.build_request(
            "GET",
            url.copy_with(host=ip),
            headers=cabecalhos,
            timeout=httpx.Timeout(
                min(TEMPO_LIMITE_LEITURA_S, restante),
                connect=min(TEMPO_LIMITE_CONEXAO_S, restante),
            ),
            extensions={"sni_hostname": url.host},
        )
        try:
            resposta = self._http.send(pedido, stream=True, follow_redirects=False)
        except httpx.HTTPError as erro:
            raise FonteIndisponivel("O site não respondeu.") from erro
        try:
            declarado = resposta.headers.get("content-length", "")
            if declarado.isdigit() and int(declarado) > limite:
                raise ConteudoRecusado("A resposta passa do limite de tamanho.")
            corpo = bytearray()
            for pedaco in resposta.iter_bytes():
                corpo += pedaco
                if len(corpo) > limite:
                    raise ConteudoRecusado("A resposta passa do limite de tamanho.")
                self._restante(prazo)
            return resposta.status_code, resposta.headers, bytes(corpo)
        except httpx.HTTPError as erro:
            raise FonteIndisponivel("O site não terminou a resposta.") from erro
        finally:
            resposta.close()

    def _robots_permite(self, url: httpx.URL, prazo: float) -> bool:
        """RFC 9309: indisponível (4xx) libera; inalcançável (5xx ou falha) proíbe.

        401, 403 e 429 também proíbem: quem recusa o `robots.txt` não está convidando a ler.
        """
        alvo = url.copy_with(path="/robots.txt", query=None, fragment=None)
        for _ in range(MAX_REDIRECIONAMENTOS_ROBOTS + 1):
            try:
                status, cabecalhos, corpo = self._pedir(alvo, MAX_BYTES_ROBOTS, prazo)
            except (FonteIndisponivel, ConteudoRecusado):
                return False
            if status not in _REDIRECIONAMENTOS:
                break
            try:
                alvo = _validar(str(alvo.join(cabecalhos.get("location", ""))))
            except UrlRecusada:
                return False
        else:
            return True
        if status in (401, 403, 429) or status >= 500:
            return False
        if status >= 400:
            return True
        leitor = RobotFileParser()
        leitor.parse(corpo.decode("utf-8", errors="replace").splitlines())
        return leitor.can_fetch(AGENTE, str(url))

    def ler(self, url: str, *, urls_indicadas: Collection[str]) -> PaginaLida:
        """Lê a página. Toda recusa acontece antes do pedido, e erro não traz a URL."""
        atual = _validar(url)
        indicadas = {_chave_de_url(u) for u in urls_indicadas if u.strip()}
        if _chave_de_url(url) not in indicadas:
            raise UrlNaoIndicada("A própria pessoa não indicou esta URL.")
        host_indicado = _sem_www(atual.host.casefold())
        prazo = self._relogio() + PRAZO_TOTAL_PAGINA_S
        if not self._robots_permite(atual, prazo):
            raise BloqueadoPorRobots("robots.txt não permite ler esta página.")
        for _ in range(MAX_REDIRECIONAMENTOS + 1):
            status, cabecalhos, corpo = self._pedir(atual, self._max_bytes, prazo)
            if status not in _REDIRECIONAMENTOS:
                break
            atual = _validar(str(atual.join(cabecalhos.get("location", ""))))
            if _sem_www(atual.host.casefold()) != host_indicado:
                raise UrlNaoIndicada("O site redireciona para um endereço não indicado.")
            if not self._robots_permite(atual, prazo):
                raise BloqueadoPorRobots("robots.txt não permite ler esta página.")
        else:
            raise FonteIndisponivel("O site redireciona demais.")
        if status != 200:
            raise FonteIndisponivel(f"O site respondeu {status}: a leitura termina aqui.")
        tipo = cabecalhos.get("content-type", "").split(";")[0].strip().casefold()
        if tipo not in TIPOS_DE_CONTEUDO:
            raise ConteudoRecusado("Só páginas de texto são lidas.")
        return extrair_de_pagina_html(corpo.decode("utf-8", errors="replace"), str(url))


def _chave_de_url(url: str) -> str:
    """Compara sem protocolo, `www` e barra final: é a mesma página para a pessoa."""
    texto = re.sub(r"^https?://", "", url.strip().casefold())
    return texto.removeprefix("www.").rstrip("/")


class _Ocultacao(Enum):
    INTERFACE = "interface"
    """Menu fechado e afins: comum em site honesto. Sai do texto, sem alerta por si só."""
    CAMUFLAGEM = "camuflagem"
    """Está na página, mas ninguém enxerga: não é como se fecha um menu. Sai, com alerta."""


def _declaracoes(estilo: str) -> dict[str, str]:
    limpo = re.sub(r"\s|!important", "", estilo.casefold())
    pares = (declaracao.partition(":") for declaracao in limpo.split(";"))
    return {nome: valor for nome, _, valor in pares if valor}


def _medida(valor: str | None) -> tuple[float, str] | None:
    achado = _MEDIDA.fullmatch(valor or "")
    return (float(achado.group(1)), achado.group(2)) if achado else None


def _em_pixels(valor: str | None) -> float | None:
    medida = _medida(valor)
    if medida is None:
        return None
    numero, unidade = medida
    return numero * {"pt": 4 / 3, "em": 16, "rem": 16, "%": 0.16}.get(unidade, 1)


def _fora_da_tela(declaracoes: dict[str, str]) -> bool:
    deslocamentos = [declaracoes.get(nome) for nome in ("text-indent", "margin-left", "margin-top")]
    if declaracoes.get("position") in ("absolute", "fixed"):
        deslocamentos += [declaracoes.get(nome) for nome in ("left", "right", "top", "bottom")]
    transformacao = declaracoes.get("transform", "")
    return (
        any((medida := _em_pixels(d)) is not None and medida <= -100 for d in deslocamentos)
        or "scale(0" in transformacao
        or bool(re.search(r"translate[xy3d]*\([^)]*-\d{3,}", transformacao))
    )


def _recortado(declaracoes: dict[str, str]) -> bool:
    if re.fullmatch(r"rect\(0[a-z]*,?0[a-z]*,?0[a-z]*,?0[a-z]*\)", declaracoes.get("clip", "")):
        return True
    recorte = declaracoes.get("clip-path", "")
    if re.match(r"(inset\((50|100)%|circle\(0)", recorte):
        return True
    if declaracoes.get("overflow") not in ("hidden", "clip"):
        return False
    return any(
        (medida := _em_pixels(declaracoes.get(nome))) is not None and medida <= 1
        for nome in ("width", "height")
    )


def _cor_igual_ao_fundo(declaracoes: dict[str, str]) -> bool:
    cor = declaracoes.get("color")
    if cor == "transparent":
        return declaracoes.get("background-clip") != "text"
    fundo = declaracoes.get("background-color") or declaracoes.get("background")
    return bool(cor and fundo) and _CORES_IGUAIS.get(cor, cor) == _CORES_IGUAIS.get(fundo, fundo)


def _tecnica_de_ocultacao(estilo: str) -> _Ocultacao | None:
    """O que o estilo faz com o texto. Só lê o que está escrito: a página não é renderizada."""
    declaracoes = _declaracoes(estilo)
    if (
        declaracoes.get("display") == "none"
        or declaracoes.get("visibility") in ("hidden", "collapse")
        or declaracoes.get("content-visibility") == "hidden"
    ):
        return _Ocultacao.INTERFACE
    if declaracoes.get("max-height") == "0" and declaracoes.get("overflow") == "hidden":
        return _Ocultacao.INTERFACE
    opacidade = _medida(declaracoes.get("opacity"))
    tamanho = _em_pixels(declaracoes.get("font-size"))
    if (
        (opacidade is not None and opacidade[0] <= 0.05)
        or (tamanho is not None and tamanho <= 2)
        or _fora_da_tela(declaracoes)
        or _recortado(declaracoes)
        or _cor_igual_ao_fundo(declaracoes)
    ):
        return _Ocultacao.CAMUFLAGEM
    return None


def _ocultacao_da_etiqueta(tag: Any) -> _Ocultacao | None:
    tecnica = _tecnica_de_ocultacao(str(tag.get("style") or ""))
    if tecnica is not None:
        return tecnica
    if (
        tag.has_attr("hidden")
        or str(tag.get("aria-hidden", "")).casefold() == "true"
        or (tag.name == "dialog" and not tag.has_attr("open"))
    ):
        return _Ocultacao.INTERFACE
    return None


class _Etiquetas:
    """Índice das etiquetas: consultar a folha de estilo não pode custar uma varredura por regra."""

    def __init__(self, sopa: BeautifulSoup) -> None:
        self.sopa = sopa
        self.todas = sopa.find_all(True)
        self.por_nome: dict[str, list[Any]] = {}
        self.por_id: dict[str, list[Any]] = {}
        self.por_classe: dict[str, list[Any]] = {}
        for tag in self.todas:
            self.por_nome.setdefault(tag.name, []).append(tag)
            if tag.get("id"):
                self.por_id.setdefault(str(tag["id"]).casefold(), []).append(tag)
            for classe in tag.get("class") or []:
                self.por_classe.setdefault(classe.casefold(), []).append(tag)
        self.compostos_usados = 0

    def _simples(self, nome: str | None, ident: str | None, classes: list[str]) -> list[Any]:
        if ident:
            grupo = self.por_id.get(ident.casefold(), [])
        elif classes:
            grupo = self.por_classe.get(classes[0].casefold(), [])
        else:
            grupo = self.por_nome.get((nome or "").casefold(), [])
        return [
            tag
            for tag in grupo
            if (not nome or tag.name == nome.casefold())
            and all(c.casefold() in map(str.casefold, tag.get("class") or []) for c in classes)
        ]

    def selecionar(self, seletor: str) -> tuple[list[Any], bool]:
        """As etiquetas do seletor, e se foi possível conferir tudo o que ele pede."""
        simples = _SELETOR_SIMPLES.fullmatch(seletor)
        if simples and any(simples.groups()):
            classes = [c for c in simples.group(3).split(".") if c]
            return self._simples(simples.group(1), simples.group(2), classes), True
        if (
            self.compostos_usados >= MAX_SELETORES_COMPOSTOS
            or len(self.todas) > MAX_ETIQUETAS_PARA_SELETOR_COMPOSTO
        ):
            return [], False
        self.compostos_usados += 1
        try:
            return self.sopa.select(seletor), True
        except Exception as erro:  # seletor é texto da página: a biblioteca recusa de vários modos
            logger.info("seletor de estilo não avaliado: %s", type(erro).__name__)
            return [], False


def _ocultos_pela_folha(sopa: BeautifulSoup, etiquetas: _Etiquetas) -> tuple[list[tuple], bool]:
    """O que os `<style>` da página escondem, e se sobrou regra que não deu para conferir."""
    achados: list[tuple[Any, _Ocultacao]] = []
    sem_conferir = False
    for folha in sopa.find_all("style"):
        css = _BLOCO_DE_IMPRESSAO.sub("", _COMENTARIO_CSS.sub("", folha.get_text()))
        for regra in _REGRA_CSS.finditer(css):
            tecnica = _tecnica_de_ocultacao(regra.group(2))
            if tecnica is None:
                continue
            for seletor in regra.group(1).split(","):
                limpo = " ".join(seletor.split())
                if not limpo or limpo.startswith("@") or ":" in limpo:
                    continue  # estado como `:hover` não diz como a página abre
                selecionadas, conferido = etiquetas.selecionar(limpo)
                sem_conferir = sem_conferir or not conferido
                achados += [(tag, tecnica) for tag in selecionadas]
    return achados, sem_conferir


def _texto_fechado_em_details(tag: Any) -> tuple[list[Any], bool]:
    """O que só aparece ao abrir, e se o `summary` está vazio: sem ele, não há o que abrir."""
    resumo = tag.find("summary", recursive=False)
    filhos = [filho for filho in tag.children if filho is not resumo]
    return filhos, resumo is None or not resumo.get_text(strip=True)


def _retirar_escondido(sopa: BeautifulSoup) -> tuple[list[str], bool]:
    """Tira da página o que não aparece. Devolve o texto retirado e se houve camuflagem."""
    escondidos: list[str] = []
    camuflagem = False

    def retirar(tag: Any, tecnica: _Ocultacao) -> None:
        nonlocal camuflagem
        if tag.parent is None:
            return
        texto = tag.get_text(" ", strip=True)
        escondidos.append(texto)
        if tecnica is _Ocultacao.CAMUFLAGEM and len(texto.split()) >= MIN_PALAVRAS_PARA_ALERTA:
            camuflagem = True
        tag.decompose()

    etiquetas = _Etiquetas(sopa)
    pela_folha, sem_conferir = _ocultos_pela_folha(sopa, etiquetas)
    camuflagem = sem_conferir
    for tag in etiquetas.todas:
        for atributo in _ATRIBUTOS_COM_TEXTO:
            if tag.has_attr(atributo):
                escondidos.append(str(tag[atributo]))
    for tag, tecnica in pela_folha:
        retirar(tag, tecnica)
    for tag in etiquetas.todas:
        if tag.parent is None:
            continue
        tecnica = _ocultacao_da_etiqueta(tag)
        if tecnica is not None:
            retirar(tag, tecnica)
        elif tag.name in _ETIQUETAS_FORA_DO_TEXTO:
            sem_tamanho = tag.name == "svg" and "0" in (tag.get("width"), tag.get("height"))
            retirar(tag, _Ocultacao.CAMUFLAGEM if sem_tamanho else _Ocultacao.INTERFACE)
        elif tag.name == "details" and not tag.has_attr("open"):
            filhos, sem_resumo = _texto_fechado_em_details(tag)
            texto = " ".join(str(f.get_text(" ", strip=True) if f.name else f) for f in filhos)
            escondidos.append(texto)
            if sem_resumo and len(texto.split()) >= MIN_PALAVRAS_PARA_ALERTA:
                camuflagem = True
            for filho in filhos:
                filho.extract()
    return escondidos, camuflagem


@rastreado(ETAPA_LER_SITE)
def extrair_de_pagina_html(html: str, url_origem: str) -> PaginaLida:
    """Texto visível, links e contatos. Instrução, visível ou escondida, vira alerta.

    Só o estilo escrito na própria página é conferido. Folha externa e script não são lidos: texto
    escondido por eles passa, e não há como saber sem abrir a página num navegador.
    """
    sopa = BeautifulSoup(html, "html.parser")
    escondidos: list[str] = []

    for comentario in sopa.find_all(string=lambda t: isinstance(t, Comment)):
        escondidos.append(str(comentario))
        comentario.extract()
    retirados, camuflagem = _retirar_escondido(sopa)
    escondidos += retirados
    for tag in sopa(_ETIQUETAS_SEM_TEXTO):
        if tag.name in ("template", "noscript"):
            escondidos.append(tag.get_text(" ", strip=True))
        tag.decompose()

    achou_instrucao = any(tem_instrucao(t) for t in escondidos)
    enderecos = [str(a["href"]).strip() for a in sopa.find_all("a", href=True)]
    frases: list[str] = []
    # Texto corrido, sem quebrar nas etiquetas: `<b>` no meio não pode esconder uma instrução.
    for frase in FIM_DE_FRASE.split(" ".join(sopa.stripped_strings)):
        limpa = " ".join(frase.split())
        if not limpa:
            continue
        if tem_instrucao(limpa):
            achou_instrucao = True
        elif texto_permitido(limpa):
            frases.append(limpa)
    texto = " ".join(frases)
    if len(texto) > MAX_CARACTERES_PAGINA:
        raise ConteudoRecusado("A página passa do limite de caracteres.")
    alertas = [ALERTA_INSTRUCAO_PAGINA] if achou_instrucao else []
    if camuflagem:
        alertas.append(ALERTA_TEXTO_ESCONDIDO_PAGINA)
    return PaginaLida(
        url=url_origem,
        texto=texto,
        contatos=_contatos_da_pagina(texto, enderecos),
        alertas=alertas,
    )


def _contatos_da_pagina(texto: str, enderecos: Iterable[str]) -> dict[str, str]:
    """Só `mailto:` e `tel:` dizem a quem o contato pertence, e só quando há um único.

    E-mail no texto corrido pode ser de outra pessoa, como a gestora citada: fica de fora e, com
    dois endereços diferentes, a dúvida também não grava nada.
    """
    links = [
        valor for categoria, valor in encontrar_contatos(texto) if categoria in _CATEGORIAS_DE_LINK
    ]
    emails: set[str] = set()
    telefones: set[str] = set()
    for endereco in enderecos:
        minusculo = endereco.casefold()
        if minusculo.startswith("mailto:"):
            destino = unquote(endereco[7:]).split("?")[0]
            emails |= {e.strip().casefold() for e in destino.split(",") if "@" in e}
        elif minusculo.startswith("tel:"):
            numero = unquote(endereco[4:]).strip()
            if any(caractere.isdigit() for caractere in numero):
                telefones.add(numero)
        elif minusculo.startswith(("http://", "https://")) and endereco not in links:
            links.append(endereco)
    contatos: dict[str, str] = {}
    if len(emails) == 1:
        contatos["email"] = next(iter(emails))
    if len(telefones) == 1:
        contatos["telefone"] = next(iter(telefones))
    if links:
        contatos["links"] = ", ".join(dict.fromkeys(links))
    return contatos


@dataclass(frozen=True)
class IndicacaoSite:
    """A pessoa informou este endereço como dela: é o registro que libera a leitura.

    `contato` é o e-mail ou telefone que a pessoa confirmou ao indicar: vale mais que a página.
    """

    empresa_id: str
    candidato_id: str
    nome: str
    url: str
    contato: str = ""


def _hoje() -> date:
    return datetime.now(UTC).date()


class FonteSitesIndicados:
    """Implementa `FonteCandidatos` sobre os sites que as próprias pessoas indicaram."""

    def __init__(
        self,
        indicacoes: Sequence[IndicacaoSite],
        leitor: LeitorSitePublico,
        *,
        hoje: Callable[[], date] = _hoje,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.indicacoes = list(indicacoes)
        self._leitor = leitor
        self._hoje = hoje
        self._relogio = relogio
        self._cache: dict[IndicacaoSite, tuple[float, Candidato | None]] = {}
        self._trava_do_cache = Lock()

    def limpar_cache(self) -> None:
        """Para o fluxo chamar no começo de uma execução ou quando uma pessoa sai do banco."""
        with self._trava_do_cache:
            self._cache.clear()

    def _urls_registradas(self, indicacao: IndicacaoSite) -> list[str]:
        """Só o que está no registro da fonte: a indicação não pode confirmar a si mesma."""
        return [
            registrada.url
            for registrada in self.indicacoes
            if (registrada.empresa_id, registrada.candidato_id)
            == (indicacao.empresa_id, indicacao.candidato_id)
        ]

    def perfil_coletado(self, indicacao: IndicacaoSite) -> PerfilColetado:
        pagina = self._leitor.ler(indicacao.url, urls_indicadas=self._urls_registradas(indicacao))
        hoje = self._hoje()
        origem = {"fonte": FONTE_SITE, "url": indicacao.url, "coletado_em": hoje}
        fatos = [
            FatoColetado(**origem, texto=frase, trecho=frase, tipo=TipoFato.DECLARADO)
            for frase in FIM_DE_FRASE.split(pagina.texto)
            if frase.strip()
        ]
        tipos = {
            "email": TipoContato.EMAIL,
            "telefone": TipoContato.TELEFONE,
            "links": TipoContato.LINK,
        }
        informados = dict(pagina.contatos)
        if indicacao.contato.strip():
            chave = "email" if "@" in indicacao.contato else "telefone"
            informados[chave] = indicacao.contato.strip()
        contatos = [
            ContatoColetado(**origem, tipo=tipo, valor=valor, publicado_pela_pessoa=True)
            for chave, tipo in tipos.items()
            if chave in informados
            for valor in informados[chave].split(", ")
            if valor.strip()
        ]
        return PerfilColetado(
            empresa_id=indicacao.empresa_id,
            candidato_id=indicacao.candidato_id,
            simulado=False,
            coletado_em=hoje,
            nome=indicacao.nome,
            fatos=fatos,
            contatos=contatos,
            alertas=pagina.alertas,
        )

    def _candidato(self, indicacao: IndicacaoSite) -> Candidato:
        perfil = self.perfil_coletado(indicacao)
        atributos = {"portfolio": indicacao.url}
        if perfil.alertas:
            atributos["alerta_site"] = " | ".join(perfil.alertas)
        return candidato_de_perfil(
            perfil, origem=indicacao.url, fonte=FONTE_SITE, atributos=atributos
        )

    def _ler_com_isolamento(self, indicacao: IndicacaoSite) -> Candidato | None:
        """Quem escreve a página é quem concorre: o erro de uma não para a busca das demais."""
        try:
            return rastreado(ETAPA_BUSCAR_SITE)(self._candidato)(indicacao)
        except (ErroContrato, httpx.HTTPError) as erro:
            logger.info("site indicado fora da busca: %s", type(erro).__name__)
        except Exception as erro:
            logger.warning("erro inesperado ao ler site indicado: %s", type(erro).__name__)
        return None

    def _em_cache(self, indicacao: IndicacaoSite) -> Candidato | None:
        """Falha também fica guardada: um site lento não pode atrasar cada consulta da execução."""
        agora = self._relogio()
        with self._trava_do_cache:
            guardado = self._cache.get(indicacao)
        if guardado is not None and agora < guardado[0]:
            return guardado[1]
        candidato = self._ler_com_isolamento(indicacao)
        with self._trava_do_cache:
            self._cache[indicacao] = (agora + VALIDADE_DO_CACHE_S, candidato)
        return candidato

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        """Site que falha ou recusa a leitura fica de fora: não derruba as demais pessoas."""
        if pagina > 1:
            return []
        achados = []
        for indicacao in self.indicacoes:
            if indicacao.empresa_id != empresa_id:
                continue
            candidato = self._em_cache(indicacao)
            if candidato is not None and combina_com_consulta(candidato, consulta):
                achados.append(candidato)
        return achados
