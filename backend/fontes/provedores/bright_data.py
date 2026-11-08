"""Bright Data: leitura de páginas públicas por URL (Web Unlocker) e busca (SERP API).

Referências: docs.brightdata.com/api-reference/rest-api/unlocker/unlock-website,
/products/web-unlocker/features, /products/web-unlocker/error-codes e
/products/serp-api/parsed-json-results.

A busca padrão do sistema é a Brave. A SERP daqui só entra com `zona_busca`, que a configuração só
passa com `BRIGHTDATA_ZONA_BUSCA` e `BRIGHTDATA_BUSCA_HABILITADA=1`. Essa opção usa alvo Google, que
a arquitetura deixa de fora, e a montagem avisa no estado das fontes sempre que ela estiver ligada.

Sobre desbloqueio: a API não tem parâmetro para desligar CAPTCHA nem desbloqueio. O resolvedor de
CAPTCHA se desliga só no painel, em Configuration da zona; a troca de proxies e o tratamento de
impressão digital continuam ligados, pois são o próprio produto. Por isso este código nunca manda
cabeçalhos, cookies nem `render`, que além de tudo passariam a zona a cobrar 100% das chamadas.

A API não documenta se segue redirecionamentos sozinha. O 3xx do envelope é validado salto a
salto; além disso, a página entregue é recusada quando se declara de um domínio proibido.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca, UrlRecusada
from backend.fontes.provedores.modelos import (
    ConfiancaDado,
    ConsultaProvedor,
    ItemColetado,
    RespostaProvedor,
)
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte
from backend.fontes.provedores.url_segura import (
    Resolvedor,
    resolver_dns,
    validar_forma,
    validar_texto_de_busca,
    validar_url_publica,
)

NOME = "bright_data"
ETAPA_BRIGHT_DATA = "provedor_bright_data"
URL_API = "https://api.brightdata.com/request"
URL_BUSCA = "https://www.google.com/search"
CUSTO_REQUISICAO_USD = 0.0015
"""Pague conforme o uso: US$ 1,50 por mil requisições bem-sucedidas (brightdata.com/pricing)."""
MAX_REDIRECIONAMENTOS = 3
RESULTADOS_POR_PAGINA = 10
"""A Google devolve cerca de dez por página, e `num` foi descontinuado: a paginação usa `start`."""
EXCLUSAO_NA_BUSCA = "-site:linkedin.com"
TIPOS_DE_TEXTO = ("text/html", "text/plain", "application/xhtml+xml")
ETIQUETAS_IGNORADAS = frozenset({"script", "style", "noscript", "template", "svg", "iframe"})
_CAMINHO_DE_LOGIN = re.compile(
    r"/(?:login|logon|signin|sign-in|sign_in|entrar|auth|sso|oauth)\b", re.IGNORECASE
)
_DESTINO_REFRESH = re.compile(r"url\s*=\s*['\"]?([^'\";]+)", re.IGNORECASE)


class _LeitorHtml(HTMLParser):
    """Texto visível e o que a página diz sobre si. Nada aqui segue link ou executa algo."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.titulo: list[str] = []
        self.destinos: list[str] = []
        self.pede_senha = False
        self._ignorando = 0
        self._no_titulo = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ETIQUETAS_IGNORADAS:
            self._ignorando += 1
        self._no_titulo = tag == "title" or self._no_titulo
        atributos = {nome.casefold(): (valor or "") for nome, valor in attrs}
        if tag == "input" and atributos.get("type", "").casefold() == "password":
            self.pede_senha = True
        self._guardar_destino(tag, atributos)

    def _guardar_destino(self, tag: str, atributos: dict[str, str]) -> None:
        if tag == "base" or (tag == "link" and atributos.get("rel", "").casefold() == "canonical"):
            self.destinos.append(atributos.get("href", ""))
        elif tag == "meta" and atributos.get("property", "").casefold() == "og:url":
            self.destinos.append(atributos.get("content", ""))
        elif tag == "meta" and atributos.get("http-equiv", "").casefold() == "refresh":
            achado = _DESTINO_REFRESH.search(atributos.get("content", ""))
            if achado:
                self.destinos.append(achado.group(1).strip())

    def handle_endtag(self, tag: str) -> None:
        if tag in ETIQUETAS_IGNORADAS and self._ignorando:
            self._ignorando -= 1
        if tag == "title":
            self._no_titulo = False

    def handle_data(self, data: str) -> None:
        if self._ignorando or not data.strip():
            return
        (self.titulo if self._no_titulo else self.partes).append(" ".join(data.split()))


def _texto_em_json(resposta: RespostaHttp) -> Any:
    try:
        return json.loads(resposta.corpo)
    except (ValueError, RecursionError):
        raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA) from None


def _destino_seguivel(atual: str, localizacao: str | None) -> str | None:
    """O próximo salto. Sem destino legível ou rumo a uma tela de login, a leitura para aqui."""
    if not localizacao:
        return None
    try:
        destino = urljoin(atual, localizacao)
        caminho = urlsplit(destino).path
    except ValueError:
        return None
    return None if _CAMINHO_DE_LOGIN.search(caminho) else destino


class ProvedorBrightData:
    """Implementa `ProvedorDados`. Sem zona, responde com configuração incompleta, sem chamar."""

    nome = NOME

    def __init__(
        self,
        token: str,
        transporte: Transporte,
        *,
        zona_web: str | None,
        zona_busca: str | None,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
        resolver: Resolvedor = resolver_dns,
        custo_requisicao_usd: float = CUSTO_REQUISICAO_USD,
    ) -> None:
        self._token = token
        self._transporte = transporte
        self._zona_web = zona_web
        self._zona_busca = zona_busca
        self._relogio = relogio
        self._resolver = resolver
        self._custo = custo_requisicao_usd

    def aceita(self, consulta: ConsultaProvedor) -> bool:
        return consulta.url is not None or (consulta.texto is not None and bool(self._zona_busca))

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        saltos = MAX_REDIRECIONAMENTOS + 1 if consulta.url is not None else 1
        return saltos * self._custo

    @rastreado(ETAPA_BRIGHT_DATA)
    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor:
        if consulta.url is not None:
            return self._ler_pagina(consulta.url)
        if consulta.texto is not None:
            return self._buscar(consulta.texto, consulta.pagina)
        raise ErroProvedor(MotivoTroca.CONSULTA_NAO_SUPORTADA)

    def _pedir(self, corpo: dict[str, Any]) -> RespostaHttp:
        resposta = self._transporte.enviar(
            PedidoHttp(
                metodo="POST",
                url=URL_API,
                cabecalhos={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                corpo_json=corpo,
            )
        )
        self._conferir_status(resposta.status)
        return resposta

    @staticmethod
    def _conferir_status(status: int) -> None:
        if status in (401, 407):
            raise ErroProvedor(MotivoTroca.AUTENTICACAO)
        if status == 429 or status >= 500:
            raise FonteIndisponivel(f"{NOME}: status {status}")
        if status >= 400:
            raise ErroProvedor(MotivoTroca.RECUSADO_PELO_PROVEDOR)
        if not 200 <= status < 300:
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA)

    def _ler_pagina(self, url: str) -> RespostaProvedor:
        if not self._zona_web:
            raise ErroProvedor(MotivoTroca.CONFIGURACAO_INCOMPLETA)
        custo = 0.0
        atual = url
        for _ in range(MAX_REDIRECIONAMENTOS + 1):
            try:
                validar_url_publica(atual, self._resolver)
                resposta = self._pedir({"zone": self._zona_web, "url": atual, "format": "json"})
            except UrlRecusada as erro:
                raise UrlRecusada(erro.motivo, custo) from None
            except (FonteIndisponivel, ConnectionError, TimeoutError):
                if custo:  # repetir tudo cobraria de novo os saltos já pagos
                    raise ErroProvedor(MotivoTroca.FALHA_TEMPORARIA, custo) from None
                raise
            except ErroProvedor as erro:
                raise ErroProvedor(erro.motivo, custo) from None
            custo += self._custo
            status, cabecalhos, corpo = self._envelope(resposta, custo)
            if 300 <= status < 400:
                destino = _destino_seguivel(atual, cabecalhos.get("location"))
                if destino is None:
                    return RespostaProvedor(custo_usd=custo)
                atual = destino
                continue
            return self._pagina(atual, status, cabecalhos, corpo, custo)
        return RespostaProvedor(custo_usd=custo)

    @staticmethod
    def _envelope(resposta: RespostaHttp, custo: float) -> tuple[int, dict[str, str], str]:
        """`format: json` traz `status_code`, `headers` e `body` da página pedida."""
        try:
            dados = _texto_em_json(resposta)
        except ErroProvedor:
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, custo) from None
        if not isinstance(dados, dict):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, custo)
        status = dados.get("status_code")
        cabecalhos = dados.get("headers", {})
        corpo = dados.get("body")
        if (
            not isinstance(status, int)
            or isinstance(status, bool)
            or not isinstance(cabecalhos, dict)
            or not isinstance(corpo, str)
        ):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, custo)
        return status, {str(k).casefold(): str(v) for k, v in cabecalhos.items()}, corpo

    def _pagina(
        self, url: str, status: int, cabecalhos: dict[str, str], corpo: str, custo: float
    ) -> RespostaProvedor:
        if status == 429 or status >= 500:
            if custo > self._custo:
                raise ErroProvedor(MotivoTroca.FALHA_TEMPORARIA, custo)
            raise FonteIndisponivel(f"{NOME}: página respondeu {status}")
        if not 200 <= status < 300 or "www-authenticate" in cabecalhos:
            return RespostaProvedor(custo_usd=custo)  # inclui 401 e 403: não tenta entrar
        tipo = cabecalhos.get("content-type", "text/html").split(";")[0].strip().casefold()
        if tipo not in TIPOS_DE_TEXTO:
            return RespostaProvedor(custo_usd=custo)

        leitor = _LeitorHtml()
        try:
            leitor.feed(corpo)
            leitor.close()
        except AssertionError:  # a biblioteca padrão levanta isso em marcação malformada
            return RespostaProvedor(custo_usd=custo)
        self._recusar_se_for_de_dominio_proibido(url, leitor.destinos, custo)
        texto = " ".join(leitor.partes)
        if leitor.pede_senha or not texto:
            return RespostaProvedor(custo_usd=custo)
        return RespostaProvedor(
            itens=[
                ItemColetado(
                    provedor=NOME,
                    fonte=f"{NOME}:pagina",
                    coletado_em=self._relogio(),
                    url=url,
                    confianca=ConfiancaDado.DECLARADO,
                    texto=texto,
                    atributos={"titulo": " ".join(leitor.titulo)} if leitor.titulo else {},
                )
            ],
            custo_usd=custo,
        )

    @staticmethod
    def _recusar_se_for_de_dominio_proibido(url: str, destinos: list[str], custo: float) -> None:
        for destino in destinos:
            try:
                validar_forma(urljoin(url, destino))
            except UrlRecusada as erro:
                if erro.motivo == MotivoTroca.DOMINIO_RECUSADO:
                    raise UrlRecusada(erro.motivo, custo) from None
            except ValueError:
                continue

    def _buscar(self, texto: str, pagina: int) -> RespostaProvedor:
        validar_texto_de_busca(texto)
        if not self._zona_busca:
            raise ErroProvedor(MotivoTroca.CONFIGURACAO_INCOMPLETA)
        parametros = urlencode(
            {
                "q": f"{texto} {EXCLUSAO_NA_BUSCA}",
                "start": (pagina - 1) * RESULTADOS_POR_PAGINA,
                "hl": "pt",
                "gl": "br",
            }
        )
        resposta = self._pedir(
            {
                "zone": self._zona_busca,
                "url": f"{URL_BUSCA}?{parametros}",
                "format": "raw",
                "data_format": "parsed_light",
            }
        )
        self._conferir_status_da_busca(resposta)
        dados = _texto_em_json(resposta)
        organicos = dados.get("organic") if isinstance(dados, dict) else None
        if not isinstance(organicos, list):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo)
        return RespostaProvedor(
            itens=[item for item in map(self._item_de_busca, organicos) if item is not None],
            custo_usd=self._custo,
        )

    def _conferir_status_da_busca(self, resposta: RespostaHttp) -> None:
        """Na API direta, o status real pode vir só em `x-brd-status-code`."""
        codigo = resposta.cabecalhos.get("x-brd-status-code", "")
        if codigo.isdigit():
            self._conferir_status(int(codigo))

    def _item_de_busca(self, organico: Any) -> ItemColetado | None:
        if not isinstance(organico, dict):
            return None
        link, titulo, descricao = (organico.get(c) for c in ("link", "title", "description"))
        if not isinstance(link, str):
            return None
        try:
            validar_forma(link)
        except UrlRecusada:
            return None
        partes = [valor for valor in (titulo, descricao) if isinstance(valor, str) and valor]
        return ItemColetado(
            provedor=NOME,
            fonte=f"{NOME}:busca",
            coletado_em=self._relogio(),
            url=link,
            confianca=ConfiancaDado.INFERIDO,
            texto=". ".join(partes),
        )
