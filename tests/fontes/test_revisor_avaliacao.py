"""Avaliação mecânica de citações do revisor nas seis vagas; não mede precisão semântica.

O revisor confere trecho por trecho contra o perfil. Citação inventada precisa virar ressalva,
e nota sem evidência conferida também, para nenhuma afirmação do modelo desaparecer calada.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from backend.agente.regras import avaliar_requisitos
from backend.contratos.modelos import Analise, Candidato, Evidencia, Vaga
from backend.contratos.simulacoes import ClienteModeloSimulado
from backend.fontes.funil import priorizar
from backend.fontes.revisor import (
    ETAPA_REVISAO,
    RESSALVA_NOTA_SEM_EVIDENCIA,
    RevisorIndependente,
)

pytestmark = pytest.mark.eval
RAIZ = Path(__file__).resolve().parents[2] / "dados" / "sinteticos"
VAGAS = json.loads((RAIZ / "vagas.json").read_text())
PERFIS = [Candidato.model_validate(p) for p in json.loads((RAIZ / "candidatos.json").read_text())]
HOJE = date(2026, 11, 7)
TRECHO_INVENTADO = "Experiência inventada ausente do perfil sintético."


def _primeiro_da_vaga(vaga: Vaga) -> Candidato:
    escolhidos = priorizar(
        vaga,
        [p for p in PERFIS if p.empresa_id == vaga.empresa_id],
        1,
        hoje=HOJE,
        avaliar_requisitos=avaliar_requisitos,
        registrar_corte=lambda _: None,
    )
    return escolhidos[0]


def _analise(vaga: Vaga, candidato: Candidato, evidencia: Evidencia) -> Analise:
    return Analise(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        requisitos_ok={r.id: True for r in vaga.requisitos},
        notas={evidencia.criterio: 0.5},
        evidencias=[evidencia.model_copy(deep=True)],
        lacunas=[],
        pontos_a_aprofundar=[],
        alertas=[],
    )


@pytest.mark.parametrize("vaga_dados", VAGAS, ids=[v["id"] for v in VAGAS])
@pytest.mark.parametrize("adulterar", [False, True], ids=["literal", "citacao_inventada"])
def test_revisao_de_citacoes_nas_seis_vagas(vaga_dados, adulterar):
    vaga = Vaga.model_validate(vaga_dados)
    candidato = _primeiro_da_vaga(vaga)
    evidencia = Evidencia(
        criterio=vaga.competencias[0].nome,
        fonte=candidato.fonte,
        trecho=candidato.perfil_texto.split(". ")[1],
    )
    analise = _analise(vaga, candidato, evidencia)
    if adulterar:
        analise.evidencias[0].trecho = TRECHO_INVENTADO
    antes = analise.model_dump()

    cliente = ClienteModeloSimulado({ETAPA_REVISAO: {"ressalvas": []}})
    resultado = RevisorIndependente(cliente).revisar(vaga, candidato, analise)

    assert resultado.notas == analise.notas
    assert analise.model_dump() == antes, "o revisor não pode alterar a análise que recebeu"
    sem_evidencia = [
        r for r in resultado.ressalvas_revisor if r.startswith(RESSALVA_NOTA_SEM_EVIDENCIA)
    ]
    assert bool(sem_evidencia) is adulterar


@pytest.mark.parametrize("vaga_dados", VAGAS, ids=[v["id"] for v in VAGAS])
def test_revisor_nao_recebe_a_justificativa_do_analisador(vaga_dados):
    """O revisor só vê nota e trecho conferido: lacuna e pergunta são leitura do analisador."""
    vaga = Vaga.model_validate(vaga_dados)
    candidato = _primeiro_da_vaga(vaga)
    evidencia = Evidencia(
        criterio=vaga.competencias[0].nome,
        fonte=candidato.fonte,
        trecho=candidato.perfil_texto.split(". ")[1],
    )
    analise = _analise(vaga, candidato, evidencia)
    analise = analise.model_copy(
        update={
            "lacunas": ["lacuna fictícia que o revisor não deve ler"],
            "pontos_a_aprofundar": ["pergunta fictícia que o revisor não deve ler"],
        }
    )

    cliente = ClienteModeloSimulado({ETAPA_REVISAO: {"ressalvas": []}})
    RevisorIndependente(cliente).revisar(vaga, candidato, analise)

    enviado = cliente.chamadas[0]["usuario"]
    assert "lacuna fictícia" not in enviado
    assert "pergunta fictícia" not in enviado
