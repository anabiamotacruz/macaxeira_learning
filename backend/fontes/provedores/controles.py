"""Orçamento, caches e métricas dos provedores. Em memória: recomeçam quando o processo reinicia."""

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from backend.fontes.provedores.erros import MotivoTroca
from backend.fontes.provedores.modelos import ResultadoCadeia

TTL_CACHE_PADRAO_S = 24 * 60 * 60.0
CACHE_MAXIMO_PADRAO = 1000
TTL_DESCOBERTAS_S = 5 * 60.0
CACHE_DESCOBERTAS_MAXIMO = 32
"""Prazo e limite do cache das descobertas da Brave. Ver `CacheDescobertas`."""


def _exigir_limite(limite: float, nome: str) -> float:
    if not math.isfinite(limite) or limite < 0:
        raise ValueError(f"{nome} precisa ser um número finito e não negativo")
    return limite


@dataclass(frozen=True)
class Reserva:
    empresa_id: str
    execucao_id: str
    valor: float


class OrcamentoProvedores:
    """Reserva antes de chamar e liquida pelo custo real, por empresa e por execução."""

    def __init__(self, *, limite_empresa_usd: float, limite_execucao_usd: float) -> None:
        self._limite_empresa = _exigir_limite(limite_empresa_usd, "limite_empresa_usd")
        self._limite_execucao = _exigir_limite(limite_execucao_usd, "limite_execucao_usd")
        self._trava = threading.Lock()
        self._gasto_empresa: dict[str, float] = {}
        self._gasto_execucao: dict[tuple[str, str], float] = {}

    def reservar(self, empresa_id: str, execucao_id: str, valor: float) -> Reserva | None:
        """`None` quando a chamada, no pior caso, passaria de algum dos limites."""
        execucao = (empresa_id, execucao_id)
        with self._trava:
            total_empresa = self._gasto_empresa.get(empresa_id, 0.0) + valor
            total_execucao = self._gasto_execucao.get(execucao, 0.0) + valor
            if total_empresa > self._limite_empresa or total_execucao > self._limite_execucao:
                return None
            self._gasto_empresa[empresa_id] = total_empresa
            self._gasto_execucao[execucao] = total_execucao
        return Reserva(empresa_id, execucao_id, valor)

    def liquidar(self, reserva: Reserva, custo_real: float) -> None:
        ajuste = custo_real - reserva.valor
        execucao = (reserva.empresa_id, reserva.execucao_id)
        with self._trava:
            self._gasto_empresa[reserva.empresa_id] += ajuste
            self._gasto_execucao[execucao] += ajuste

    def gasto_empresa(self, empresa_id: str) -> float:
        with self._trava:
            return self._gasto_empresa.get(empresa_id, 0.0)

    def gasto_execucao(self, empresa_id: str, execucao_id: str) -> float:
        with self._trava:
            return self._gasto_execucao.get((empresa_id, execucao_id), 0.0)


class CacheConsultas:
    """Evita pagar duas vezes pela mesma consulta. Cada empresa tem as próprias entradas."""

    def __init__(
        self,
        *,
        ttl_s: float = TTL_CACHE_PADRAO_S,
        maximo: int = CACHE_MAXIMO_PADRAO,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._maximo = maximo
        self._relogio = relogio
        self._trava = threading.Lock()
        self._entradas: OrderedDict[tuple[str, str], tuple[float, ResultadoCadeia]] = OrderedDict()

    def obter(self, empresa_id: str, chave: str) -> ResultadoCadeia | None:
        with self._trava:
            entrada = self._entradas.get((empresa_id, chave))
            if entrada is None:
                return None
            if self._relogio() - entrada[0] > self._ttl_s:
                del self._entradas[(empresa_id, chave)]
                return None
            return entrada[1]

    def guardar(self, empresa_id: str, chave: str, resultado: ResultadoCadeia) -> None:
        with self._trava:
            self._entradas[(empresa_id, chave)] = (self._relogio(), resultado)
            self._entradas.move_to_end((empresa_id, chave))
            while len(self._entradas) > self._maximo:
                self._entradas.popitem(last=False)

    def esquecer(self, empresa_id: str, chave: str) -> None:
        with self._trava:
            self._entradas.pop((empresa_id, chave), None)


class CacheDescobertas:
    """Cache transitório do que a Brave devolve: só em memória, só da execução, curto e pequeno.

    Os termos da Brave Search API (seção 3(b)(i)) proíbem guardar, fazer cache ou montar base com
    os resultados, salvo armazenamento transitório. Por isso o resultado dela não vai ao
    `CacheConsultas`, que dura 24 horas e serve a todas as execuções: fica aqui, com a chave presa
    à execução, prazo de minutos e poucas entradas, e nunca em disco. Cada acesso varre o que
    venceu, mesmo de outra execução, para nada ficar além do prazo. Uma execução nunca lê a
    entrada de outra. Se a execução não é conhecida, a cadeia nem chega a guardar.
    """

    def __init__(
        self,
        *,
        ttl_s: float = TTL_DESCOBERTAS_S,
        maximo: int = CACHE_DESCOBERTAS_MAXIMO,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._maximo = maximo
        self._relogio = relogio
        self._trava = threading.Lock()
        self._entradas: OrderedDict[tuple[str, str, str], tuple[float, ResultadoCadeia]] = (
            OrderedDict()
        )

    def __len__(self) -> int:
        with self._trava:
            self._varrer()
            return len(self._entradas)

    def _varrer(self) -> None:
        """Chamado com a trava. As entradas estão em ordem de gravação: a mais antiga vem antes."""
        limite = self._relogio() - self._ttl_s
        while self._entradas:
            gravado_em, _ = next(iter(self._entradas.values()))
            if gravado_em >= limite:
                break
            self._entradas.popitem(last=False)

    def obter(self, empresa_id: str, execucao_id: str, chave: str) -> ResultadoCadeia | None:
        with self._trava:
            self._varrer()
            entrada = self._entradas.get((empresa_id, execucao_id, chave))
            return None if entrada is None else entrada[1]

    def guardar(
        self, empresa_id: str, execucao_id: str, chave: str, resultado: ResultadoCadeia
    ) -> None:
        with self._trava:
            self._varrer()
            self._entradas[(empresa_id, execucao_id, chave)] = (self._relogio(), resultado)
            self._entradas.move_to_end((empresa_id, execucao_id, chave))
            while len(self._entradas) > self._maximo:
                self._entradas.popitem(last=False)

    def esquecer(self, empresa_id: str, execucao_id: str, chave: str) -> None:
        with self._trava:
            self._entradas.pop((empresa_id, execucao_id, chave), None)


class MetricasProvedores:
    """Contagens e custo por provedor, sem nada que identifique consulta ou pessoa."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._provedores: dict[str, dict] = {}
        self._acertos_de_cache = 0
        self._descobertas_sem_leitura = 0

    def _de(self, provedor: str) -> dict:
        return self._provedores.setdefault(
            provedor,
            {"acertos": 0, "nao_encontrados": 0, "falhas": 0, "trocas": {}, "custo_usd": 0.0},
        )

    def _somar(self, provedor: str, campo: str, custo_usd: float) -> None:
        with self._trava:
            metricas = self._de(provedor)
            metricas[campo] += 1
            metricas["custo_usd"] += custo_usd

    def registrar_acerto(self, provedor: str, custo_usd: float) -> None:
        self._somar(provedor, "acertos", custo_usd)

    def registrar_nao_encontrado(self, provedor: str, custo_usd: float) -> None:
        self._somar(provedor, "nao_encontrados", custo_usd)

    def registrar_falha(self, provedor: str, custo_usd: float) -> None:
        self._somar(provedor, "falhas", custo_usd)

    def registrar_troca(self, provedor: str, motivo: MotivoTroca) -> None:
        with self._trava:
            trocas = self._de(provedor)["trocas"]
            trocas[motivo.value] = trocas.get(motivo.value, 0) + 1

    def registrar_acerto_de_cache(self) -> None:
        with self._trava:
            self._acertos_de_cache += 1

    def registrar_descobertas_sem_leitura(self, quantidade: int) -> None:
        """Só a contagem: nem a URL nem o texto da descoberta entram aqui."""
        with self._trava:
            self._descobertas_sem_leitura += quantidade

    def fotografia(self) -> dict:
        with self._trava:
            return {
                "cache_acertos": self._acertos_de_cache,
                "descobertas_sem_leitura": self._descobertas_sem_leitura,
                "provedores": {
                    nome: {**metricas, "trocas": dict(metricas["trocas"])}
                    for nome, metricas in self._provedores.items()
                },
            }
