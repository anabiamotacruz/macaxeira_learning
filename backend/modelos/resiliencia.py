"""Repetição de chamadas instáveis. Espera e relógio são injetados, para testar sem tempo real."""

import time
from collections.abc import Callable

from backend.contratos.erros import FonteIndisponivel

ERROS_TEMPORARIOS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    FonteIndisponivel,
)
"""Só o que pode passar sozinho. `ModeloIndisponivel` já vem depois de tentativas e alternativa."""


def com_tentativas[T](
    funcao: Callable[[], T],
    tentativas: int = 3,
    espera: float = 1.0,
    *,
    temporarios: tuple[type[Exception], ...] = ERROS_TEMPORARIOS,
    dormir: Callable[[float], None] = time.sleep,
) -> T:
    """Repete erros temporários, com espera que dobra a cada vez. `funcao` precisa ser idempotente.

    Erros permanentes sobem na hora; esgotadas as tentativas, sobe o último erro.
    """
    if tentativas < 1:
        raise ValueError("tentativas precisa ser de pelo menos 1")
    if espera < 0:
        raise ValueError("espera não pode ser negativa")
    falha: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            return funcao()
        except temporarios as erro:
            falha = erro
        if tentativa < tentativas:
            dormir(espera * 2 ** (tentativa - 1))
    raise falha
