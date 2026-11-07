"""Recuperação paginada e falha transitória sobre os 250 registros sintéticos."""

import json
from datetime import date
from pathlib import Path

import pytest

from backend.contratos.erros import FonteIndisponivel
from backend.contratos.modelos import Candidato
from backend.fontes.rede_simulada import RedeSimulada

PASTA = Path(__file__).resolve().parents[2] / "dados" / "sinteticos"


@pytest.mark.eval
@pytest.mark.parametrize("falhas", [0, 1])
def test_rede_recupera_todas_as_pessoas_autorizadas_sem_duplicar(falhas):
    pessoas = [Candidato.model_validate(p) for p in json.loads(
        (PASTA / "candidatos.json").read_text()
    )]
    casos = json.loads((PASTA / "respostas_certas.json").read_text())["casos"]
    fonte = RedeSimulada(pessoas, hoje=date(2026, 11, 7), por_pagina=7, falhas_restantes=falhas)
    if falhas:
        with pytest.raises(FonteIndisponivel):
            fonte.buscar("empresa-demo-1", "", 1)
    for empresa in {p.empresa_id for p in pessoas}:
        esperados = {c["candidato_id"] for c in casos if c["empresa_id"] == empresa
                     and c["autorizacao_para_vaga"] == "valida_na_data_referencia"}
        encontrados = []
        pagina = 1
        while lote := fonte.buscar(empresa, "", pagina):
            assert all(p.empresa_id == empresa and not p.opt_out and p.simulado for p in lote)
            encontrados.extend(p.id for p in lote)
            pagina += 1
        assert len(encontrados) == len(set(encontrados))
        assert set(encontrados) == esperados
