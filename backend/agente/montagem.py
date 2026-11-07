"""Liga as implementações das frentes às interfaces do fluxo. Só aqui o agente as conhece."""

from collections.abc import Sequence
from datetime import date

from backend.agente.fluxo import Priorizador, ProvedorConsultas, RegistrarCorte
from backend.agente.regras import avaliar_requisitos
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Candidato, Vaga
from backend.fontes.consultas import ampliar_consultas, gerar_consultas
from backend.fontes.funil import priorizar

LIMITE_ANALISES_POR_RODADA = 20
"""Quantas pessoas cada rodada leva às análises por modelo. As demais vão para a fila humana."""


def consultas_por_modelo(cliente_modelo: ClienteModelo) -> ProvedorConsultas:
    """Primeira rodada gera; as seguintes ampliam, sem abandonar as consultas anteriores.

    As anteriores seguem na lista para o fluxo ler a página seguinte delas.
    """

    def consultas(vaga: Vaga, rodada: int, anteriores: Sequence[str]) -> list[str]:
        if rodada == 0 or not anteriores:
            return gerar_consultas(vaga, cliente_modelo)
        return [*ampliar_consultas(vaga, list(anteriores), cliente_modelo), *anteriores]

    return consultas


def priorizador_do_funil(limite: int = LIMITE_ANALISES_POR_RODADA) -> Priorizador:
    """Aplica `funil.priorizar` com a regra determinística de requisitos do agente."""

    def priorizador(
        vaga: Vaga, candidatos: list[Candidato], hoje: date, registrar_corte: RegistrarCorte
    ) -> list[Candidato]:
        return priorizar(
            vaga,
            candidatos,
            limite,
            hoje=hoje,
            avaliar_requisitos=avaliar_requisitos,
            registrar_corte=registrar_corte,
        )

    return priorizador
