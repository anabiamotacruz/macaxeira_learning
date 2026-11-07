"""Leitura de site público, só de URL indicada pela própria pessoa.

A URL é dado não confiável. Antes de cada conexão: esquema, porta e destino são conferidos, todo
endereço resolvido precisa ser público, e o pedido vai ao IP conferido, para o DNS não trocar a
resposta entre a conferência e a conexão. Redirecionamento repete tudo isso. `robots.txt` é
respeitado, e o robô se identifica. Login, CAPTCHA ou bloqueio encerram a leitura, sem contorno.

LinkedIn nunca é buscado, nem por serviço de terceiros, mesmo quando a própria pessoa indica.
PDF do LinkedIn entra só como arquivo enviado pela pessoa, em `documentos.py`.
"""

import ipaddress
import re
import socket
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import unquote
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from bs4.element import Comment

from backend.agente.auditoria import rastreado
from backend.contratos.erros import ErroContrato, FonteIndisponivel
from backend.contratos.modelos import (
    Candidato,
    ContatoColetado,
    FatoColetado,
    PerfilColetado,
    TipoContato,
    TipoFato,
)
from backend.fontes.analisador import FIM_DE_FRASE, INSTRUCAO, normalizar, texto_permitido
from backend.fontes.anonimizador import Categoria, encontrar_contatos
from backend.fontes.perfis import candidato_de_perfil, combina_com_consulta

ETAPA_LER_SITE = "ler_site_indicado"
FONTE_SITE = "site_indicado"
AGENTE = "macaxeira-learning-sourcing/0.1"
"""Nome real do robô. É o que `robots.txt` confere; nunca se passa por navegador."""

MAX_BYTES_PAGINA = 2 * 1024 * 1024
MAX_BYTES_ROBOTS = 512 * 1024
"""RFC 9309, seção 2.5: limite de leitura de pelo menos 500 KiB."""
MAX_REDIRECIONAMENTOS = 3
MAX_REDIRECIONAMENTOS_ROBOTS = 5
"""RFC 9309, seção 2.3.1.2: seguir pelo menos cinco redirecionamentos."""
TEMPO_LIMITE = httpx.Timeout(10.0, connect=5.0)
PORTAS_PERMITIDAS = {"http": 80, "https": 443}
TIPOS_DE_CONTEUDO = ("text/html", "application/xhtml+xml", "text/plain")

ALERTA_INSTRUCAO_PAGINA = (
    "instrucao_na_pagina: a página traz texto dirigido ao avaliador, visível ou escondido; "
    "ele foi retirado."
)

_HOSTS_PROIBIDOS = ("linkedin.com", "lnkd.in", "licdn.com")
_TERMOS_PROIBIDOS = ("linkedin", "lnkd.in", "licdn")
_ESTILO_OCULTO = re.compile(
    r"display:none|visibility:hidden|visibility:collapse|opacity:0(?:\.0+)?(?:;|$)"
    r"|font-size:0(?:px|em|rem|pt)?(?:;|$)"
)
_ETIQUETAS_SEM_TEXTO = ("script", "style", "noscript", "template", "head")
_REDIRECIONAMENTOS = (301, 302, 303, 307, 308)


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
        elif ip.sixtofour is not None or ip.teredo is not None:
            return False
    return ip.is_global and not ip.is_multicast


def resolver_dns(host: str, porta: int) -> list[str]:
    try:
        respostas = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except OSError as erro:
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
    ) -> None:
        self._resolver = resolver
        # Sem proxy do ambiente: ele faria a conexão sair do IP conferido.
        self._http = http_client or httpx.Client(
            timeout=TEMPO_LIMITE, follow_redirects=False, trust_env=False
        )
        self._max_bytes = max_bytes

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

    def _pedir(self, url: httpx.URL, limite: int) -> tuple[int, httpx.Headers, bytes]:
        """Um pedido, ao IP conferido, mantendo `Host` e o nome usado na conferência do TLS."""
        ip = self._ip_conferido(url)
        cabecalhos = {"Host": url.netloc.decode("ascii"), "User-Agent": AGENTE, "Accept": "text/*"}
        pedido = self._http.build_request(
            "GET",
            url.copy_with(host=ip),
            headers=cabecalhos,
            timeout=TEMPO_LIMITE,
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
            return resposta.status_code, resposta.headers, bytes(corpo)
        except httpx.HTTPError as erro:
            raise FonteIndisponivel("O site não terminou a resposta.") from erro
        finally:
            resposta.close()

    def _robots_permite(self, url: httpx.URL) -> bool:
        """RFC 9309: indisponível (4xx) libera; inalcançável (5xx ou falha) proíbe.

        401, 403 e 429 também proíbem: quem recusa o `robots.txt` não está convidando a ler.
        """
        alvo = url.copy_with(path="/robots.txt", query=None, fragment=None)
        for _ in range(MAX_REDIRECIONAMENTOS_ROBOTS + 1):
            try:
                status, cabecalhos, corpo = self._pedir(alvo, MAX_BYTES_ROBOTS)
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
        if not self._robots_permite(atual):
            raise BloqueadoPorRobots("robots.txt não permite ler esta página.")
        for _ in range(MAX_REDIRECIONAMENTOS + 1):
            status, cabecalhos, corpo = self._pedir(atual, self._max_bytes)
            if status not in _REDIRECIONAMENTOS:
                break
            atual = _validar(str(atual.join(cabecalhos.get("location", ""))))
            if _sem_www(atual.host.casefold()) != host_indicado:
                raise UrlNaoIndicada("O site redireciona para um endereço não indicado.")
            if not self._robots_permite(atual):
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


def _oculto(tag: Any) -> bool:
    estilo = re.sub(r"\s", "", str(tag.get("style") or "")).casefold()
    return (
        bool(_ESTILO_OCULTO.search(estilo))
        or tag.has_attr("hidden")
        or str(tag.get("aria-hidden", "")).casefold() == "true"
    )


@rastreado(ETAPA_LER_SITE)
def extrair_de_pagina_html(html: str, url_origem: str) -> PaginaLida:
    """Texto visível, links e contatos. Instrução, visível ou escondida, vira alerta."""
    sopa = BeautifulSoup(html, "html.parser")
    escondidos: list[str] = []

    for comentario in sopa.find_all(string=lambda t: isinstance(t, Comment)):
        escondidos.append(str(comentario))
        comentario.extract()
    for tag in sopa.find_all(True):
        for atributo in ("alt", "title", "aria-label"):
            if tag.has_attr(atributo):
                escondidos.append(str(tag[atributo]))
    for tag in sopa.find_all(True):
        if tag.parent is not None and _oculto(tag):
            escondidos.append(tag.get_text(" ", strip=True))
            tag.decompose()
    for tag in sopa(_ETIQUETAS_SEM_TEXTO):
        if tag.name in ("template", "noscript"):
            escondidos.append(tag.get_text(" ", strip=True))
        tag.decompose()

    tem_instrucao = any(INSTRUCAO.search(normalizar(t)) for t in escondidos)
    enderecos = [str(a["href"]).strip() for a in sopa.find_all("a", href=True)]
    frases: list[str] = []
    # Texto corrido, sem quebrar nas etiquetas: `<b>` no meio não pode esconder uma instrução.
    for frase in FIM_DE_FRASE.split(" ".join(sopa.stripped_strings)):
        limpa = " ".join(frase.split())
        if not limpa:
            continue
        if INSTRUCAO.search(normalizar(limpa)):
            tem_instrucao = True
        elif texto_permitido(limpa):
            frases.append(limpa)
    texto = " ".join(frases)
    return PaginaLida(
        url=url_origem,
        texto=texto,
        contatos=_contatos_da_pagina(texto, enderecos),
        alertas=[ALERTA_INSTRUCAO_PAGINA] if tem_instrucao else [],
    )


def _contatos_da_pagina(texto: str, enderecos: Iterable[str]) -> dict[str, str]:
    contatos: dict[str, str] = {}
    links: list[str] = []
    for categoria, valor in encontrar_contatos(texto):
        if categoria is Categoria.EMAIL:
            contatos.setdefault("email", valor)
        elif categoria is Categoria.TELEFONE:
            contatos.setdefault("telefone", valor)
        elif valor not in links:
            links.append(valor)
    for endereco in enderecos:
        minusculo = endereco.casefold()
        if minusculo.startswith("mailto:"):
            contatos.setdefault("email", endereco[7:].split("?")[0].strip().casefold())
        elif minusculo.startswith("tel:"):
            contatos.setdefault("telefone", endereco[4:].strip())
        elif minusculo.startswith(("http://", "https://")) and endereco not in links:
            links.append(endereco)
    if links:
        contatos["links"] = ", ".join(links)
    return contatos


@dataclass(frozen=True)
class IndicacaoSite:
    """A pessoa informou este endereço como dela: é o registro que libera a leitura."""

    empresa_id: str
    candidato_id: str
    nome: str
    url: str


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
    ) -> None:
        self.indicacoes = list(indicacoes)
        self._leitor = leitor
        self._hoje = hoje

    def perfil_coletado(self, indicacao: IndicacaoSite) -> PerfilColetado:
        pagina = self._leitor.ler(indicacao.url, urls_indicadas=(indicacao.url,))
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
        contatos = [
            ContatoColetado(**origem, tipo=tipo, valor=valor, publicado_pela_pessoa=True)
            for chave, tipo in tipos.items()
            if chave in pagina.contatos
            for valor in pagina.contatos[chave].split(", ")
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

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        """Site que falha ou recusa a leitura fica de fora: não derruba as demais pessoas."""
        if pagina > 1:
            return []
        achados = []
        for indicacao in self.indicacoes:
            if indicacao.empresa_id != empresa_id:
                continue
            try:
                perfil = self.perfil_coletado(indicacao)
            except (ErroContrato, httpx.HTTPError):
                continue
            atributos = {"portfolio": indicacao.url}
            if perfil.alertas:
                atributos["alerta_site"] = perfil.alertas[0]
            candidato = candidato_de_perfil(
                perfil, origem=indicacao.url, fonte=FONTE_SITE, atributos=atributos
            )
            if combina_com_consulta(candidato, consulta):
                achados.append(candidato)
        return achados
