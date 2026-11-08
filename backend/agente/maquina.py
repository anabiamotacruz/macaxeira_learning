"""Tabela de transições da vaga. `fluxo.py` conduz, e `auditoria.py` consulta quem pode pausar."""

from collections.abc import Mapping
from types import MappingProxyType

from backend.contratos.modelos import EstadoFluxo

ESTADOS_ATIVOS = frozenset(
    {
        EstadoFluxo.BUSCANDO,
        EstadoFluxo.ANALISANDO,
        EstadoFluxo.REVISANDO,
        EstadoFluxo.DECIDINDO,
        EstadoFluxo.META_EM_RISCO,
        EstadoFluxo.CONVIDANDO,
        EstadoFluxo.ENTREGANDO,
    }
)
"""Estados em execução, depois da assinatura: só eles pausam e só eles exigem mandato válido."""


def _ou_pausa(*destinos: EstadoFluxo) -> frozenset[EstadoFluxo]:
    return frozenset({*destinos, EstadoFluxo.PAUSADA})


TRANSICOES: Mapping[EstadoFluxo, frozenset[EstadoFluxo]] = MappingProxyType(
    {
        EstadoFluxo.RASCUNHO: frozenset({EstadoFluxo.AGUARDANDO_MANDATO}),
        EstadoFluxo.AGUARDANDO_MANDATO: frozenset({EstadoFluxo.BUSCANDO, EstadoFluxo.RASCUNHO}),
        EstadoFluxo.BUSCANDO: _ou_pausa(EstadoFluxo.ANALISANDO, EstadoFluxo.META_EM_RISCO),
        EstadoFluxo.ANALISANDO: _ou_pausa(EstadoFluxo.REVISANDO),
        EstadoFluxo.REVISANDO: _ou_pausa(EstadoFluxo.DECIDINDO),
        EstadoFluxo.DECIDINDO: _ou_pausa(
            EstadoFluxo.BUSCANDO,
            EstadoFluxo.META_EM_RISCO,
            EstadoFluxo.CONVIDANDO,
            EstadoFluxo.ENTREGANDO,
        ),
        EstadoFluxo.META_EM_RISCO: _ou_pausa(
            EstadoFluxo.CONVIDANDO, EstadoFluxo.ENTREGANDO, EstadoFluxo.CONCLUIDA
        ),
        EstadoFluxo.CONVIDANDO: _ou_pausa(EstadoFluxo.ENTREGANDO),
        EstadoFluxo.ENTREGANDO: _ou_pausa(EstadoFluxo.CONCLUIDA),
        # A tabela lista os destinos possíveis; `_transitar` só aceita o estado anterior salvo.
        EstadoFluxo.PAUSADA: ESTADOS_ATIVOS,
        EstadoFluxo.CONCLUIDA: frozenset(),
    }
)
