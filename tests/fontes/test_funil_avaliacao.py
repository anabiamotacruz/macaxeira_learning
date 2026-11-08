"""Avaliações locais de elegibilidade e equidade com os 250 rótulos sintéticos."""

import json
from datetime import date
from pathlib import Path

import pytest

from backend.contratos.modelos import Candidato, Vaga

pytestmark = pytest.mark.eval
PASTA = Path(__file__).resolve().parents[2] / "dados/sinteticos"
HOJE = date(2026, 11, 7)


@pytest.fixture
def conjunto():
    from backend.agente.regras import avaliar_requisitos
    from backend.fontes.funil import priorizar as priorizar_com_regras

    def priorizar(vaga, perfis, limite=20, *, hoje):
        # O funil recusa lista com outra empresa: o banco já entrega só a da vaga.
        da_empresa = [p for p in perfis if p.empresa_id == vaga.empresa_id]
        return priorizar_com_regras(
            vaga, da_empresa, limite, hoje=hoje,
            avaliar_requisitos=avaliar_requisitos, registrar_corte=lambda _corte: None,
        )

    def ler(nome):
        return json.loads((PASTA / nome).read_text())

    return (
        priorizar,
        [Candidato.model_validate(p) for p in ler("candidatos.json")],
        [Vaga.model_validate(v) for v in ler("vagas.json")],
        ler("respostas_certas.json")["casos"],
    )


@pytest.mark.xfail(
    reason=(
        "Divergência conhecida entre o funil da Frente 1 e os rótulos: perfil desatualizado vai"
        " para uma pessoa confirmar, requisito desconhecido segue para a análise e há perfis sem"
        " rótulo para a vaga. Combinar com a Frente 2 qual regra vale."
    ),
    strict=False,
)
def test_elegibilidade_concorda_com_rotulos_das_seis_vagas(conjunto):
    priorizar, perfis, vagas, casos = conjunto
    for vaga in vagas:
        esperados = {
            c["candidato_id"] for c in casos if c["vaga_id"] == vaga.id
            and c["autorizacao_para_vaga"] != "bloqueada"
            and all(r["estado"] == "atende" for r in c["requisitos"].values())
        }
        obtidos = priorizar(vaga, perfis, limite=250, hoje=HOJE)
        assert {p.id for p in obtidos} == esperados
        assert len(obtidos) == len(esperados)
        assert all(p.empresa_id == vaga.empresa_id and not p.opt_out for p in obtidos)


def test_nome_e_genero_nao_mudam_ordem_nas_seis_vagas(conjunto):
    priorizar, perfis, vagas, _ = conjunto
    alterados = []
    for indice, perfil in enumerate(perfis):
        copia = perfil.model_copy(deep=True)
        copia.nome = f"SQL Docker Pessoa Fictícia {indice}"
        copia.atributos["genero"] = "feminino" if indice % 2 else "masculino"
        alterados.append(copia)
    for vaga in vagas:
        antes = [p.id for p in priorizar(vaga, perfis, hoje=HOJE)]
        depois = [p.id for p in priorizar(vaga, list(reversed(alterados)), hoje=HOJE)]
        assert antes == depois
