"""Elegibilidade e pares no funil real; não mede precisão do modelo."""

from datetime import date

import pytest

from backend.contratos.modelos import Candidato, Vaga
from backend.fontes.funil import priorizar
from dados.avaliacao_v3 import construir

HOJE = date(2026, 11, 7)


@pytest.mark.eval
def test_120_familias_indicaveis_da_prova_passam_pelo_funil():
    dados = construir()
    pessoas = [Candidato.model_validate(p) for p in dados["candidatos"]]
    familias = set()
    for vaga_dados in dados["vagas"]:
        vaga = Vaga.model_validate(vaga_dados)
        casos = [c for c in dados["gabarito"]["casos"] if c["particao"] == "prova"
                 and c["conta_independencia"] and c["vaga_id"] == vaga.id]
        candidatos = [pessoas[c["indice"]] for c in casos]
        esperados = {c["candidato_id"] for c in casos if c["resultado_esperado"] == "indicar"}
        encontrados = priorizar(vaga, candidatos, limite=len(candidatos), hoje=HOJE)
        assert {p.id for p in encontrados} == esperados
        familias.update(c["grupo_independencia"] for c in casos
                        if c["candidato_id"] in esperados)
    assert len(familias) == 120


@pytest.mark.eval
def test_pares_vies_preservam_elegibilidade_no_funil():
    dados = construir()
    vagas = {v["id"]: Vaga.model_validate(v) for v in dados["vagas"]}
    pares = {}
    for caso in dados["gabarito"]["casos"]:
        if caso["par_vies"]:
            pessoa = Candidato.model_validate(dados["candidatos"][caso["indice"]])
            resultado = priorizar(vagas[caso["vaga_id"]], [pessoa], hoje=HOJE)
            pares.setdefault(caso["par_vies"], []).append([p.id for p in resultado])
    assert len(pares) == 12
    assert all(len(resultados) == 2 and resultados[0] == resultados[1] != []
               for resultados in pares.values())
