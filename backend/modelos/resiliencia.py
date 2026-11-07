"""Repetição de chamadas instáveis e disjuntor de fontes, com espera e relógio injetados."""

import threading
import time
from collections.abc import Callable
from enum import StrEnum

from backend.contratos.erros import ErroContrato, FonteIndisponivel

TEMPO_LIMITE_PADRAO_S = 30.0
LIMITE_DE_FALHAS_PADRAO = 5
ESPERA_DO_DISJUNTOR_PADRAO_S = 60.0

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


class EstadoDisjuntor(StrEnum):
    FECHADO = "fechado"
    ABERTO = "aberto"
    MEIO_ABERTO = "meio_aberto"


class DisjuntorFonte:
    """Para de chamar uma fonte depois de falhas seguidas e testa de novo após a espera.

    Só os erros temporários contam: erro permanente mostra que a fonte respondeu. Use por fora da
    repetição, em `disjuntor.chamar(lambda: com_tentativas(...))`, para cada série de tentativas
    contar como uma falha.
    """

    def __init__(
        self,
        fonte: str,
        *,
        limite_falhas: int = LIMITE_DE_FALHAS_PADRAO,
        espera: float = ESPERA_DO_DISJUNTOR_PADRAO_S,
        temporarios: tuple[type[Exception], ...] = ERROS_TEMPORARIOS,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        if not fonte.strip():
            raise ValueError("fonte é obrigatória")
        if limite_falhas < 1:
            raise ValueError("limite_falhas precisa ser de pelo menos 1")
        if espera <= 0:
            raise ValueError("espera precisa ser positiva")
        self.fonte = fonte
        self._limite_falhas = limite_falhas
        self._espera = espera
        self._temporarios = temporarios
        self._relogio = relogio
        self._trava = threading.Lock()
        self._falhas = 0
        self._aberto_em: float | None = None
        self._teste_em_andamento = False

    @property
    def estado(self) -> EstadoDisjuntor:
        if self._aberto_em is None:
            return EstadoDisjuntor.FECHADO
        if self._relogio() - self._aberto_em >= self._espera:
            return EstadoDisjuntor.MEIO_ABERTO
        return EstadoDisjuntor.ABERTO

    def chamar[T](self, funcao: Callable[[], T]) -> T:
        """Chama `funcao` ou levanta `FonteIndisponivel` sem chamar, se o disjuntor não deixar."""
        self._autorizar()
        try:
            resultado = funcao()
        except self._temporarios:
            self._registrar_falha()
            raise
        except BaseException:
            with self._trava:
                self._teste_em_andamento = False
            raise
        self._registrar_sucesso()
        return resultado

    def _autorizar(self) -> None:
        with self._trava:
            estado = self.estado
            if estado is EstadoDisjuntor.FECHADO:
                return
            if estado is EstadoDisjuntor.MEIO_ABERTO and not self._teste_em_andamento:
                self._teste_em_andamento = True
                return
        raise FonteIndisponivel(f"fonte {self.fonte!r}: pausada depois de falhas seguidas")

    def _registrar_falha(self) -> None:
        with self._trava:
            self._falhas += 1
            self._teste_em_andamento = False
            if self._aberto_em is not None or self._falhas >= self._limite_falhas:
                self._aberto_em = self._relogio()

    def _registrar_sucesso(self) -> None:
        with self._trava:
            self._falhas = 0
            self._teste_em_andamento = False
            self._aberto_em = None
