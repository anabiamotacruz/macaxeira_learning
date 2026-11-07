"""Validação mecânica de citações nas seis vagas; não mede precisão semântica."""

import json
from datetime import date
from pathlib import Path

import pytest

from backend.contratos.modelos import Analise, Candidato, Evidencia, Vaga
from backend.contratos.simulacoes import ClienteModeloSimulado
from backend.fontes.funil import priorizar
from backend.fontes.revisor import Revisor

RAIZ = Path(__file__).resolve().parents[2] / "dados" / "sinteticos"
VAGAS = json.loads((RAIZ / "vagas.json").read_text())
PERFIS = json.loads((RAIZ / "candidatos.json").read_text())


@pytest.mark.eval
@pytest.mark.parametrize("vaga_dados", VAGAS, ids=[v["id"] for v in VAGAS])
@pytest.mark.parametrize("adulterar", [False, True], ids=["literal", "citacao_inventada"])
def test_revisao_de_citacoes_nas_seis_vagas(vaga_dados, adulterar):
    vaga = Vaga.model_validate(vaga_dados)
    perfis = [Candidato.model_validate(p) for p in PERFIS]
    candidato = priorizar(vaga, perfis, limite=1, hoje=date(2026, 11, 7))[0]
    evidencia = Evidencia(
        criterio=vaga.competencias[0].nome, fonte=candidato.fonte,
        trecho=candidato.perfil_texto.split(". ")[1],
    )
    analise = Analise(
        empresa_id=vaga.empresa_id, vaga_id=vaga.id, candidato_id=candidato.id,
        requisitos_ok={r.id: True for r in vaga.requisitos},
        notas={evidencia.criterio: 0.5}, evidencias=[evidencia.model_copy(deep=True)],
        lacunas=[], pontos_a_aprofundar=[], alertas=[],
    )
    cliente = ClienteModeloSimulado({"revisar_perfil": {
        "evidencias": [evidencia.model_dump()], "ressalvas": [],
    }})
    if adulterar:
        analise.evidencias[0].trecho = "Experiência inventada ausente do perfil sintético."
    antes = analise.model_dump()
    resultado = Revisor(cliente, hoje=date(2026, 11, 7)).revisar(vaga, candidato, analise)
    assert bool(resultado.ressalvas_revisor) is adulterar
    assert resultado.notas == analise.notas
    assert analise.model_dump() == antes
