"""Transporte HTTP dos provedores: só hosts oficiais, sem redirecionar e com teto de tamanho.

Erros do cliente HTTP podem copiar URL e cabeçalhos: aqui viram erros sem nenhum texto dele.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx2

from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca

logger = logging.getLogger(__name__)

TEMPO_LIMITE_PADRAO_S = 60.0
"""Abaixo do `TEMPO_LIMITE_INTEGRACAO_S` de `com_tentativas`, como ele exige."""
TAMANHO_MAXIMO_PADRAO = 2 * 1024 * 1024
HOSTS_OFICIAIS = frozenset(
    {"api.brightdata.com", "api.peopledatalabs.com", "sandbox.api.peopledatalabs.com"}
)
"""A chave só sai para estes hosts."""


@dataclass(frozen=True)
class PedidoHttp:
    """Chave e corpo ficam fora do `repr`, para não chegarem a log nem a traceback."""

    metodo: str
    url: str
    cabecalhos: dict[str, str] = field(default_factory=dict, repr=False)
    corpo_json: dict[str, Any] | None = field(default=None, repr=False)
    tempo_limite_s: float = TEMPO_LIMITE_PADRAO_S
    tamanho_maximo: int = TAMANHO_MAXIMO_PADRAO


@dataclass(frozen=True)
class RespostaHttp:
    status: int
    cabecalhos: dict[str, str] = field(default_factory=dict, repr=False)
    corpo: bytes = field(default=b"", repr=False)


class Transporte(Protocol):
    def enviar(self, pedido: PedidoHttp) -> RespostaHttp: ...


class TransporteHttp:
    """Implementação real. Lê do ambiente nem proxy nem certificados: `trust_env=False`."""

    def __init__(
        self,
        cliente: httpx2.Client | None = None,
        *,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cliente = cliente or httpx2.Client(follow_redirects=False, trust_env=False)
        self._relogio = relogio

    def enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        if urlsplit(pedido.url).hostname not in HOSTS_OFICIAIS:
            raise ErroProvedor(MotivoTroca.RECUSADO_PELO_PROVEDOR)
        try:
            with self._cliente.stream(
                pedido.metodo,
                pedido.url,
                headers=pedido.cabecalhos,
                json=pedido.corpo_json,
                timeout=pedido.tempo_limite_s,
                follow_redirects=False,
            ) as resposta:
                corpo = self._ler_com_teto(resposta, pedido)
                return RespostaHttp(
                    status=resposta.status_code,
                    cabecalhos={k.casefold(): v for k, v in resposta.headers.items()},
                    corpo=corpo,
                )
        except httpx2.TimeoutException:
            raise TimeoutError("provedor passou do tempo limite") from None
        except httpx2.HTTPError as erro:
            logger.warning("falha de conexão com provedor: %s", type(erro).__name__)
            raise ConnectionError("falha de conexão com o provedor") from None

    def _ler_com_teto(self, resposta: httpx2.Response, pedido: PedidoHttp) -> bytes:
        """Conta os bytes a cada pedaço e limita o tempo total, contra resposta que pinga."""
        inicio = self._relogio()
        partes: list[bytes] = []
        total = 0
        for parte in resposta.iter_bytes():
            total += len(parte)
            if total > pedido.tamanho_maximo:
                raise ErroProvedor(MotivoTroca.RESPOSTA_GRANDE_DEMAIS)
            if self._relogio() - inicio > pedido.tempo_limite_s:
                raise TimeoutError("provedor passou do tempo limite")
            partes.append(parte)
        return b"".join(partes)
