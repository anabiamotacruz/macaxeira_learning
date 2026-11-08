"""Dublês sem rede dos testes de provedores. Todos os dados são sintéticos."""

import json
from collections.abc import Callable
from datetime import UTC, datetime

from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp

MOMENTO = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TOKEN_BRIGHT = "token-sintetico-bright-0123456789"
CHAVE_PDL = "chave-sintetica-pdl-0123456789"
CHAVE_BRAVE = "chave-sintetica-brave-0123456789"
IP_PUBLICO = "93.184.216.34"


def relogio_fixo() -> datetime:
    return MOMENTO


def resolver_publico(_host: str) -> list[str]:
    return [IP_PUBLICO]


def resposta_json(dados: object, status: int = 200, **cabecalhos: str) -> RespostaHttp:
    return RespostaHttp(
        status=status,
        cabecalhos={chave.replace("_", "-"): valor for chave, valor in cabecalhos.items()},
        corpo=json.dumps(dados).encode(),
    )


class TransporteSimulado:
    """Devolve as respostas na ordem e guarda os pedidos. Exceção na fila é levantada."""

    def __init__(
        self, *respostas: RespostaHttp | Exception | Callable[[PedidoHttp], RespostaHttp]
    ) -> None:
        self.respostas = list(respostas)
        self.pedidos: list[PedidoHttp] = []

    def enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        self.pedidos.append(pedido)
        if not self.respostas:
            raise AssertionError("pedido inesperado ao transporte")
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta(pedido) if callable(resposta) else resposta
