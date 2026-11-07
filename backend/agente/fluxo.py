"""Máquina de estados de uma vaga.

Este módulo só define os estados e as transições permitidas. Os estados não citam
um destino específico: agendamento e retorno da entrevista são opcionais.
"""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from backend.agente.mandato import Mandato, mandato_valido
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import EventoFluxo, Vaga


class TransicaoInvalida(ErroContrato):
    """Transição fora da tabela ou sem a guarda exigida."""


class EstadoFluxo(StrEnum):
    RASCUNHO = "rascunho"
    AGUARDANDO_MANDATO = "aguardando_mandato"
    BUSCANDO = "buscando"
    ANALISANDO = "analisando"
    REVISANDO = "revisando"
    DECIDINDO = "decidindo"
    META_EM_RISCO = "meta_em_risco"
    CONVIDANDO = "convidando"
    ENTREGANDO = "entregando"
    PAUSADA = "pausada"
    CONCLUIDA = "concluida"


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


def _transitar(
    estado: EstadoFluxo,
    destino: EstadoFluxo,
    *,
    vaga: Vaga,
    mandato: Mandato | None,
    agora: datetime,
    estado_anterior: EstadoFluxo | None = None,
    motivo: str = "",
) -> tuple[EstadoFluxo, EventoFluxo]:
    """Devolve o novo estado e o evento da transição, ou levanta `TransicaoInvalida`.

    `estado_anterior` é o estado salvo ao pausar, exigido só para sair de `PAUSADA`.
    Pausar e concluir não exigem mandato, para o fluxo sempre poder parar quando ele
    deixa de valer. As demais guardas da tabela ficam com quem chama.
    """
    if destino not in TRANSICOES.get(estado, frozenset()):
        raise TransicaoInvalida(f"transição não listada: {estado} -> {destino}")
    if estado == EstadoFluxo.PAUSADA and destino != estado_anterior:
        raise TransicaoInvalida(
            f"retomada só volta ao estado anterior: {destino} != {estado_anterior}"
        )
    if destino in ESTADOS_ATIVOS and (mandato is None or not mandato_valido(mandato, vaga, agora)):
        raise TransicaoInvalida(f"{estado} -> {destino} exige mandato válido para a vaga")

    novo = EstadoFluxo(destino)
    mensagem = f"{estado} -> {novo}"
    if motivo:
        mensagem = f"{mensagem}: {motivo}"
    evento = EventoFluxo(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        etapa=novo.value,
        mensagem=mensagem,
        momento=agora,
    )
    return novo, evento
