"""Repetição de chamadas instáveis. Espera e relógio são injetados, para testar sem tempo real."""

import time
from collections.abc import Callable

from backend.contratos.erros import ErroContrato, FonteIndisponivel

TEMPO_LIMITE_PADRAO_S = 30.0

ERROS_TEMPORARIOS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    FonteIndisponivel,
)
"""Só o que pode passar sozinho. `ModeloIndisponivel` já vem depois de tentativas e alternativa."""


class TempoLimiteExcedido(ErroContrato, TimeoutError):
    """A chamada passou do tempo limite em todas as tentativas."""


def com_tentativas[T](
    funcao: Callable[[], T],
    tentativas: int = 3,
    espera: float = 1.0,
    tempo_limite: float = TEMPO_LIMITE_PADRAO_S,
    *,
    etapa: str = "sem etapa",
    temporarios: tuple[type[Exception], ...] = ERROS_TEMPORARIOS,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], float] = time.monotonic,
) -> T:
    """Repete erros temporários, com espera que dobra a cada vez. `funcao` precisa ser idempotente.

    Erros permanentes sobem na hora; esgotadas as tentativas, sobe o último erro.

    O tempo limite não interrompe `funcao`, pois uma thread abandonada continuaria rodando: quem
    interrompe é o tempo limite do cliente HTTP dela, que deve ser igual ou menor. Aqui, o estouro
    desse tempo, ou um retorno atrasado, vira `TempoLimiteExcedido`, com etapa e limite. Uma função
    sem tempo limite próprio pode travar o chamador.
    """
    if tentativas < 1:
        raise ValueError("tentativas precisa ser de pelo menos 1")
    if espera < 0:
        raise ValueError("espera não pode ser negativa")
    if tempo_limite <= 0:
        raise ValueError("tempo_limite precisa ser positivo")
    excedido = f"etapa {etapa!r}: passou do tempo limite de {tempo_limite:g} s"
    falha: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        inicio = relogio()
        try:
            resultado = funcao()
        except TimeoutError:
            falha = TempoLimiteExcedido(excedido)
        except temporarios as erro:
            falha = erro
        else:
            if relogio() - inicio <= tempo_limite:
                return resultado
            falha = TempoLimiteExcedido(excedido)
        if tentativa < tentativas:
            dormir(espera * 2 ** (tentativa - 1))
    raise falha
