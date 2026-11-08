"""Orçamento, cache e métricas dos provedores. Em memória: recomeçam quando o processo reinicia."""

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


class MetricasProvedores:
    """Contagens e custo por provedor, sem nada que identifique consulta ou pessoa."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._provedores: dict[str, dict] = {}
        self._acertos_de_cache = 0

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

    def fotografia(self) -> dict:
        with self._trava:
            return {
                "cache_acertos": self._acertos_de_cache,
                "provedores": {
                    nome: {**metricas, "trocas": dict(metricas["trocas"])}
                    for nome, metricas in self._provedores.items()
                },
            }
