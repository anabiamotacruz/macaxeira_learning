"""Envio real do convite por e-mail pelo Resend (decisão de 8/11), só com opt-in na montagem.

Só o convite que o fluxo marcou como real sai daqui, e só com o destinatário e o conteúdo que o
fluxo conferiu (contato publicado pela pessoa, sem opt-out nem supressão). Convite simulado vai
para a caixa simulada e nunca para a rede.

A chave fica só no cabeçalho `Authorization`, fora de `repr`, log e exceção. O mesmo convite não
sai duas vezes: a caixa guarda as chaves enviadas, e o pedido leva `Idempotency-Key` com a chave
do convite. O Resend aceita esse cabeçalho e, por 24 horas, devolve a mesma resposta para a mesma
chave sem enviar de novo, o que cobre a confirmação perdida no meio do envio.

O transporte dos provedores (`backend/fontes`) só fala com os hosts da Frente 2, e por isso este
módulo tem um cliente mínimo, que só fala com `api.resend.com`.
"""

import base64
import logging
import threading
from email.utils import parseaddr
from urllib.parse import urlsplit

import httpx2

from backend.contato.convite_html import (
    CID_LOGO,
    LOGO,
    NOME_ANEXO_LOGO,
    ConteudoConvite,
    assunto_convite,
    html_convite,
    texto_convite,
)
from backend.contato.mensageiro import MensageiroSimulado
from backend.contato.prompts import PALAVRA_SAIDA
from backend.contratos.interfaces import Mensageiro
from backend.contratos.modelos import Convite
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte

logger = logging.getLogger(__name__)
logging.getLogger("httpx2").setLevel(logging.WARNING)

HOST_RESEND = "api.resend.com"
URL_RESEND = f"https://{HOST_RESEND}/emails"
USER_AGENT = "macaxeira-learning/0.1"
TEMPO_LIMITE_S = 30.0


class TransporteResend:
    """Cliente mínimo: só `api.resend.com`, sem redirecionar e sem ler proxy do ambiente."""

    def __init__(self, cliente: httpx2.Client | None = None) -> None:
        self._cliente = cliente or httpx2.Client(follow_redirects=False, trust_env=False)

    def enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        if urlsplit(pedido.url).hostname != HOST_RESEND:
            raise ConnectionError("host fora do Resend")
        try:
            resposta = self._cliente.post(
                pedido.url,
                headers=pedido.cabecalhos,
                json=pedido.corpo_json,
                timeout=pedido.tempo_limite_s,
                follow_redirects=False,
            )
        except httpx2.TimeoutException:
            raise TimeoutError("o Resend passou do tempo limite") from None
        except httpx2.HTTPError as erro:
            logger.warning("falha de conexão com o Resend: %s", type(erro).__name__)
            raise ConnectionError("falha de conexão com o Resend") from None
        return RespostaHttp(status=resposta.status_code, corpo=resposta.content)


class MensageiroResend:
    """Cumpre `Mensageiro`. `enviar_email` envia de verdade; `enviar` só cuida do simulado."""

    def __init__(
        self,
        chave: str,
        remetente: str,
        *,
        transporte: Transporte | None = None,
        simulado: Mensageiro | None = None,
    ) -> None:
        if not chave or not chave.strip():
            raise ValueError("a chave do Resend é obrigatória")
        if not remetente or not remetente.strip() or "@" not in remetente:
            raise ValueError("o remetente (EMAIL_FROM) é obrigatório")
        self.__chave = chave.strip()
        self.remetente = remetente.strip()
        self._transporte = transporte or TransporteResend()
        self._simulado = simulado or MensageiroSimulado()
        self._enviados: dict[str, str] = {}
        self._trava = threading.Lock()
        self._logo = base64.b64encode(LOGO.read_bytes()).decode()

    def __repr__(self) -> str:
        return f"MensageiroResend(remetente={self.remetente!r}, enviados={len(self._enviados)})"

    __str__ = __repr__

    def enviar(self, convite: Convite) -> bool:
        """Convite simulado vai para a caixa simulada. O real precisa de `enviar_email`."""
        if convite.simulado:
            return self._simulado.enviar(convite)
        if convite.chave_idempotencia in self._enviados:
            return True
        logger.warning("convite %s não saiu: sem destinatário conferido pelo fluxo", convite.id)
        return False

    def enviar_email(self, convite: Convite, para: str, conteudo: ConteudoConvite) -> bool:
        """Envia o convite real pelo Resend. Falha volta como `False`, registrada sem dados."""
        if convite.simulado or conteudo.simulado:
            return self._simulado.enviar(convite)
        with self._trava:
            if convite.chave_idempotencia in self._enviados:
                return True
            try:
                resposta = self._transporte.enviar(self._pedido(convite, para, conteudo))
            except (OSError, ValueError) as erro:
                logger.warning(
                    "envio do convite %s pelo Resend falhou: %s", convite.id, type(erro).__name__
                )
                return False
            if not 200 <= resposta.status < 300:
                logger.warning(
                    "envio do convite %s pelo Resend falhou: status %d", convite.id, resposta.status
                )
                return False
            self._enviados[convite.chave_idempotencia] = convite.id
        logger.info("convite %s enviado pelo Resend", convite.id)
        return True

    def _pedido(self, convite: Convite, para: str, conteudo: ConteudoConvite) -> PedidoHttp:
        _, endereco = parseaddr(self.remetente)
        saida = f"mailto:{endereco}?subject={PALAVRA_SAIDA}"
        corpo = {
            "from": self.remetente,
            "to": [para],
            "subject": assunto_convite(conteudo),
            "html": html_convite(conteudo, saida),
            "text": texto_convite(conteudo),
            "attachments": [
                {"filename": NOME_ANEXO_LOGO, "content": self._logo, "content_id": CID_LOGO}
            ],
        }
        return PedidoHttp(
            metodo="POST",
            url=URL_RESEND,
            cabecalhos={
                "Authorization": f"Bearer {self.__chave}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Idempotency-Key": convite.chave_idempotencia,
            },
            corpo_json=corpo,
            tempo_limite_s=TEMPO_LIMITE_S,
        )
