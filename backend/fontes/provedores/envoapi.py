"""EnvoAPI: e-mail que a própria pessoa publicou no perfil do LinkedIn (envoapi.com).

Pedido do dono do produto em 8/11/2026. A EnvoAPI é um serviço independente, sem vínculo com o
LinkedIn. Dois endpoints são usados:
- o de contato, só para quem o agente já indicou: na busca real, nenhuma outra fonte traz o e-mail
  publicado pela pessoa, e sem ele o convite não sai;
- o de perfil completo, pelo `ExtratorPerfilEnvo`, para o provedor `linkedin_brave`: a Brave acha o
  link do perfil, e a EnvoAPI devolve experiência, competências e resumo. É o extrator principal; a
  LinkdAPI é a reserva (decisão do dono do produto em 8/11/2026).

A URL do LinkedIn só vai como identificador, no parâmetro `url` do pedido à EnvoAPI: nenhum pedido
sai para o LinkedIn.

Referências consultadas em 8/11/2026:
- docs.envoapi.com/api/operations/getprofilecontactbyurl/: `GET
  https://api.envoapi.com/v1/profiles/contact/by-url?url=<perfil>`, com `Authorization: Bearer
  <chave>` e `Accept: application/json`. O usuário no caminho `/in/` escolhe o perfil. Resposta
  `data` com `emailAddress` (texto ou nulo), `phoneNumbers`, `websites`, `socialHandles`,
  `birthdate` e `address`, e `meta.creditCost`. Custa 1 crédito por chamada.
- docs.envoapi.com/api/operations/getprofiledetailsbyurl/: `GET
  https://api.envoapi.com/v1/profiles/details/by-url?url=<perfil>`, 1 crédito. Resposta `data` com
  `fullName`, `headline`, `about`, `location` (`displayName`, `locality`, `country`,
  `countryCode`), `experience[]` (`title`, `company.name`, `dateRange.start` e `dateRange.end` com
  `year`, `month` e `day`), `education[]` (`school.name`, `degree`) e `skills` (texto).
- docs.envoapi.com/guides/errors/: envelope `error.code`, `error.message`, `error.retryable`,
  `error.details` e `meta.requestId`. 400 `invalid_request`, 401 `invalid_api_key`, 402
  `insufficient_credits`, 404 `resource_not_found` e 429 `rate_limit_exceeded`.
- docs.envoapi.com/guides/rate-limits/: limite por conta, não por chave; o 429 traz `Retry-After`
  em segundos inteiros e não entra em fila.

Decisões:
- Só o e-mail sai daqui. Telefone, sites, aniversário e endereço são ignorados.
- O 404 vira lista vazia. O 429 espera o `Retry-After` (com teto): uma vez no
  contato, até duas no perfil. Um limitador por processo (30 pedidos por minuto) evita o 429.
- Medido em 8/11: o firewall devolve 403 sem envelope ao agente de usuário padrão do Python
  (o transporte manda `macaxeira-learning/0.1`). Esse 403 é recusa do provedor, sem repetir.
- A chave fica só no cabeçalho: nunca em URL, log, rastro, exceção ou `repr`.
- Plano grátis de 100 créditos, 1 crédito por chamada, mesmo sem e-mail: a consulta é rara.

Suposição: a documentação não publica o preço do crédito. `CUSTO_CREDITO_USD` é o teto que
usamos para a LinkdAPI, US$ 0,01, até conferir no painel.
"""

import json
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, NoReturn
from urllib.parse import urlencode

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.linkdapi import registro_de_perfil
from backend.fontes.provedores.modelos import limpar_texto_externo
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte

logger = logging.getLogger(__name__)

NOME = "envoapi"
ETAPA_ENVOAPI = "provedor_envoapi_contato"
ETAPA_ENVOAPI_PERFIL = "provedor_envoapi_perfil"
URL_BASE = "https://api.envoapi.com"
URL_CONTATO = f"{URL_BASE}/v1/profiles/contact/by-url"
URL_DETALHES = f"{URL_BASE}/v1/profiles/details/by-url"
CREDITOS_POR_CONSULTA = 1
CUSTO_CREDITO_USD = 0.01
"""Preço não publicado na documentação: teto suposto, o mesmo da LinkdAPI."""
ESPERA_MAXIMA_S = 30.0
"""Teto da espera do `Retry-After`: o limite é da conta, e o fluxo não fica parado mais que isso."""
PEDIDOS_POR_MINUTO_PADRAO = 30
"""Limite por minuto do plano; `ENVO_PEDIDOS_POR_MINUTO` troca. O pedido acima dele volta 429."""
TENTATIVAS_APOS_429 = 2
USUARIO_LINKEDIN = re.compile(r"[A-Za-z0-9_%.-]{1,100}")
_URL_PERFIL = re.compile(r"https://(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9_%.-]{1,100})/?")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_TAMANHO_MAXIMO_EMAIL = 254


def pedidos_por_minuto() -> int:
    """`ENVO_PEDIDOS_POR_MINUTO`, ou 30 quando falta ou vem fora do formato."""
    try:
        valor = int(os.environ.get("ENVO_PEDIDOS_POR_MINUTO", ""))
    except ValueError:
        return PEDIDOS_POR_MINUTO_PADRAO
    return valor if valor >= 1 else PEDIDOS_POR_MINUTO_PADRAO


class LimitadorDePedidos:
    """Janela deslizante de 60 s. Thread-safe: o pedido espera a sua vez em vez de falhar."""

    JANELA_S = 60.0

    def __init__(
        self,
        limite: int,
        *,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._limite = limite
        self._relogio = relogio
        self._dormir = dormir
        self._saidas: deque[float] = deque()
        self._trava = threading.Lock()

    def esperar_a_vez(self) -> None:
        # A trava fica durante a espera: quem chega depois fica atrás, na ordem.
        with self._trava:
            while True:
                agora = self._relogio()
                while self._saidas and agora - self._saidas[0] >= self.JANELA_S:
                    self._saidas.popleft()
                if len(self._saidas) < self._limite:
                    self._saidas.append(agora)
                    return
                self._dormir(self._saidas[0] + self.JANELA_S - agora)


_limitador: LimitadorDePedidos | None = None
_trava_do_limitador = threading.Lock()


def limitador_do_processo() -> LimitadorDePedidos:
    """Um só por processo: perfil e contato dividem o mesmo limite da conta."""
    global _limitador
    with _trava_do_limitador:
        if _limitador is None:
            _limitador = LimitadorDePedidos(pedidos_por_minuto())
        return _limitador


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


def _levantar_erro(resposta: RespostaHttp, corpo: Any) -> NoReturn:
    """Erro sobe só com o motivo: nunca com o texto da resposta."""
    status = resposta.status
    if status == 429:
        logger.warning("envoapi indisponível: status 429 (limite de pedidos)")
        raise FonteIndisponivel(f"{NOME}: limite de requisições excedido (status 429)")
    if status >= 500:
        logger.warning("envoapi indisponível: status %s", status)
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


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def registro_de_perfil_envo(dados: dict[str, Any]) -> dict[str, Any]:
    """Leva o perfil da EnvoAPI ao formato da LinkdAPI e converte como ela. Contato não entra."""
    adaptado = dict(dados)
    local = dados.get("location")
    if isinstance(local, dict):
        adaptado["location"] = _texto(local.get("displayName")) or {
            "city": local.get("locality"),
            "country": local.get("country"),
        }
    experiencias = []
    brutas = dados.get("experience")
    for bruta in brutas if isinstance(brutas, list) else []:
        if not isinstance(bruta, dict):
            continue
        datas = bruta.get("dateRange")
        datas = datas if isinstance(datas, dict) else {}
        experiencias.append({**bruta, "start": datas.get("start"), "end": datas.get("end")})
    adaptado["experience"] = experiencias
    return registro_de_perfil(adaptado)


class BuscadorContatoEnvo:
    """E-mails publicados pela pessoa no perfil do LinkedIn. Lista vazia quando não há."""

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        dormir: Callable[[float], None] = time.sleep,
        custo_credito_usd: float = CUSTO_CREDITO_USD,
        limitador: LimitadorDePedidos | None = None,
    ) -> None:
        self._chave = chave
        self._transporte = transporte
        self._dormir = dormir
        self._limitador = limitador or limitador_do_processo()
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
        self._limitador.esperar_a_vez()
        resposta = self._transporte.enviar(self._pedido(usuario))
        if resposta.status == 429:
            espera = _espera(resposta)
            logger.warning("envoapi: limite de ritmo, nova tentativa em %.0f s", espera)
            self._dormir(espera)
            self._limitador.esperar_a_vez()
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
        _levantar_erro(resposta, corpo)


class ExtratorPerfilEnvo:
    """Perfil completo pelo usuário do LinkedIn, para o provedor `linkedin_brave`."""

    nome = NOME
    origem = NOME

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        custo_credito_usd: float = CUSTO_CREDITO_USD,
        dormir: Callable[[float], None] = time.sleep,
        limitador: LimitadorDePedidos | None = None,
    ) -> None:
        self._chave = chave
        self._transporte = transporte
        self._custo = custo_credito_usd
        self._dormir = dormir
        self._limitador = limitador or limitador_do_processo()

    def __repr__(self) -> str:
        return "ExtratorPerfilEnvo()"

    @property
    def custo_por_perfil_usd(self) -> float:
        return CREDITOS_POR_CONSULTA * self._custo

    def _enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        self._limitador.esperar_a_vez()
        try:
            return self._transporte.enviar(pedido)
        except (ConnectionError, TimeoutError) as erro:
            logger.warning("envoapi indisponível: erro de rede (%s)", type(erro).__name__)
            raise FonteIndisponivel(f"{NOME}: erro de rede") from None

    @rastreado(ETAPA_ENVOAPI_PERFIL)
    def perfil(self, usuario_ou_url: str) -> tuple[dict[str, Any] | None, float]:
        """O registro e o custo. `None` quando o perfil não existe ou veio fora do formato.

        Falta de crédito, chave recusada e indisponibilidade sobem como erro, para a reserva
        assumir.
        """
        usuario = usuario_de(usuario_ou_url)
        if usuario is None:
            return None, 0.0
        pedido = PedidoHttp(
            metodo="GET",
            url=f"{URL_DETALHES}?{urlencode({'url': url_perfil_linkedin(usuario)})}",
            cabecalhos={"Authorization": f"Bearer {self._chave}", "Accept": "application/json"},
        )
        resposta = self._enviar(pedido)
        for _ in range(TENTATIVAS_APOS_429):
            if resposta.status != 429:
                break
            espera = _espera(resposta)
            logger.warning("envoapi: limite de ritmo, nova tentativa em %.0f s", espera)
            self._dormir(espera)
            resposta = self._enviar(pedido)
        corpo = _ler_json(resposta)
        if resposta.status == 200:
            dados = corpo.get("data") if isinstance(corpo, dict) else None
            registro = registro_de_perfil_envo(dados) if isinstance(dados, dict) else None
            return registro, self.custo_por_perfil_usd
        if resposta.status == 404:
            return None, self.custo_por_perfil_usd
        _levantar_erro(resposta, corpo)
