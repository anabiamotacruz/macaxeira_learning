"""EnvoAPI: e-mail que a própria pessoa publicou no perfil do LinkedIn (envoapi.com).

Pedido do dono do produto em 8/11/2026. A EnvoAPI é um serviço independente, sem vínculo com o
LinkedIn. Só o endpoint de contato é usado, e só para quem o agente já indicou: na busca real,
nenhuma outra fonte traz o e-mail publicado pela pessoa, e sem ele o convite não sai.

Referências consultadas em 8/11/2026:
- docs.envoapi.com/api/operations/getprofilecontactbyurl/: `GET
  https://api.envoapi.com/v1/profiles/contact/by-url?url=<perfil>`, com `Authorization: Bearer
  <chave>` e `Accept: application/json`. O usuário no caminho `/in/` escolhe o perfil. Resposta
  `data` com `emailAddress` (texto ou nulo), `phoneNumbers`, `websites`, `socialHandles`,
  `birthdate` e `address`, e `meta.creditCost`. Custa 1 crédito por chamada.
- docs.envoapi.com/guides/errors/: envelope `error.code`, `error.message`, `error.retryable`,
  `error.details` e `meta.requestId`. 400 `invalid_request`, 401 `invalid_api_key`, 402
  `insufficient_credits`, 404 `resource_not_found` e 429 `rate_limit_exceeded`.
- docs.envoapi.com/guides/rate-limits/: limite por conta, não por chave; o 429 traz `Retry-After`
  em segundos inteiros e não entra em fila.

Decisões:
- Só o e-mail sai daqui. Telefone, sites, aniversário e endereço são ignorados.
- O 404 vira lista vazia. O 429 espera o `Retry-After` uma vez (com teto) e desiste.
- Medido em 8/11: o firewall devolve 403 sem envelope ao agente de usuário padrão do Python
  (o transporte manda `macaxeira-learning/0.1`). Esse 403 é recusa do provedor, sem repetir.
- A chave fica só no cabeçalho: nunca em URL, log, rastro, exceção ou `repr`.
- Plano grátis de 100 créditos, 1 crédito por chamada, mesmo sem e-mail: a consulta é rara.

Suposição: a documentação não publica o preço do crédito. `CUSTO_CREDITO_USD` é o teto que
usamos para a LinkdAPI, US$ 0,01, até conferir no painel.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.modelos import limpar_texto_externo
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte

logger = logging.getLogger(__name__)

NOME = "envoapi"
ETAPA_ENVOAPI = "provedor_envoapi_contato"
URL_BASE = "https://api.envoapi.com"
URL_CONTATO = f"{URL_BASE}/v1/profiles/contact/by-url"
CREDITOS_POR_CONSULTA = 1
CUSTO_CREDITO_USD = 0.01
"""Preço não publicado na documentação: teto suposto, o mesmo da LinkdAPI."""
ESPERA_MAXIMA_S = 30.0
"""Teto da espera do `Retry-After`: o limite é da conta, e o fluxo não fica parado mais que isso."""
USUARIO_LINKEDIN = re.compile(r"[A-Za-z0-9_%.-]{1,100}")
_URL_PERFIL = re.compile(r"https://(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9_%.-]{1,100})/?")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_TAMANHO_MAXIMO_EMAIL = 254


def url_perfil_linkedin(usuario: str) -> str:
    """A página pública do perfil: é a origem do e-mail publicado."""
    return f"https://www.linkedin.com/in/{usuario}/"


def usuario_de(usuario_ou_url: str) -> str | None:
    """O usuário do LinkedIn, vindo puro ou dentro da URL do perfil. Fora do formato, `None`."""
    texto = usuario_ou_url.strip() if isinstance(usuario_ou_url, str) else ""
    achado = _URL_PERFIL.fullmatch(texto)
    if achado is not None:
        return achado.group(1)
    return texto if USUARIO_LINKEDIN.fullmatch(texto) else None


def email_valido(valor: Any) -> str | None:
    """O e-mail limpo como texto externo e conferido pelo formato. Fora dele, `None`."""
    if not isinstance(valor, str):
        return None
    email = limpar_texto_externo(valor)
    if len(email) > _TAMANHO_MAXIMO_EMAIL or not _EMAIL.fullmatch(email):
        return None
    return email


def _ler_json(resposta: RespostaHttp) -> Any:
    try:
        return json.loads(resposta.corpo)
    except (ValueError, RecursionError):
        return None


def _codigo_de_erro(corpo: Any) -> str:
    erro = corpo.get("error") if isinstance(corpo, dict) else None
    codigo = erro.get("code") if isinstance(erro, dict) else None
    return codigo if isinstance(codigo, str) else ""


def _espera(resposta: RespostaHttp) -> float:
    cabecalhos = {nome.casefold(): valor for nome, valor in resposta.cabecalhos.items()}
    try:
        segundos = float(cabecalhos.get("retry-after", "1"))
    except ValueError:
        segundos = 1.0
    return min(max(segundos, 0.0), ESPERA_MAXIMA_S)


class BuscadorContatoEnvo:
    """E-mails publicados pela pessoa no perfil do LinkedIn. Lista vazia quando não há."""

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        dormir: Callable[[float], None] = time.sleep,
        custo_credito_usd: float = CUSTO_CREDITO_USD,
    ) -> None:
        self._chave = chave
        self._transporte = transporte
        self._dormir = dormir
        self._custo = custo_credito_usd
        self.creditos_usados = 0

    def __repr__(self) -> str:
        return f"BuscadorContatoEnvo(creditos_usados={self.creditos_usados})"

    @property
    def custo_total_usd(self) -> float:
        return self.creditos_usados * self._custo

    def _pedido(self, usuario: str) -> PedidoHttp:
        return PedidoHttp(
            metodo="GET",
            url=f"{URL_CONTATO}?{urlencode({'url': url_perfil_linkedin(usuario)})}",
            cabecalhos={"Authorization": f"Bearer {self._chave}", "Accept": "application/json"},
        )

    @rastreado(ETAPA_ENVOAPI)
    def emails_publicados(self, usuario_ou_url: str) -> list[str]:
        usuario = usuario_de(usuario_ou_url)
        if usuario is None:
            return []
        resposta = self._transporte.enviar(self._pedido(usuario))
        if resposta.status == 429:
            espera = _espera(resposta)
            logger.warning("envoapi: limite de ritmo, nova tentativa em %.0f s", espera)
            self._dormir(espera)
            resposta = self._transporte.enviar(self._pedido(usuario))
        return self._emails(resposta)

    def _cobrar(self) -> None:
        self.creditos_usados += CREDITOS_POR_CONSULTA
        logger.info(
            "envoapi: consulta de contato, %s crédito(s), total %s",
            CREDITOS_POR_CONSULTA,
            self.creditos_usados,
        )

    def _emails(self, resposta: RespostaHttp) -> list[str]:
        """Erro sobe só com o motivo: nunca com o texto da resposta."""
        status = resposta.status
        corpo = _ler_json(resposta)
        if status == 200:
            self._cobrar()
            dados = corpo.get("data") if isinstance(corpo, dict) else None
            if not isinstance(dados, dict):
                raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo)
            email = email_valido(dados.get("emailAddress"))
            return [] if email is None else [email]
        if status == 404:
            self._cobrar()
            return []
        if status == 429:
            raise FonteIndisponivel(f"{NOME}: limite de requisições excedido (status 429)")
        if status >= 500:
            raise FonteIndisponivel(f"{NOME}: status {status}")
        codigo = _codigo_de_erro(corpo)
        if status == 402 or codigo == "insufficient_credits":
            motivo = MotivoTroca.SEM_CREDITOS
        elif status == 401 or codigo == "invalid_api_key":
            motivo = MotivoTroca.AUTENTICACAO
        elif status == 400:
            motivo = MotivoTroca.CONSULTA_INVALIDA
        else:  # inclui o 403 do firewall, sem envelope
            motivo = MotivoTroca.RECUSADO_PELO_PROVEDOR
        logger.warning("envoapi recusou a consulta: status=%s motivo=%s", status, motivo.value)
        raise ErroProvedor(motivo)
