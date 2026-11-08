"""Faixa de potencial: sem meta na faixa verde, os melhores abaixo do limiar completam.

Decisão de 8/11: entra quem tem nota entre o piso e o limiar, com evidência conferida e sem
requisito eliminatório reprovado, da maior nota para a menor, até a meta. A pessoa é indicada e
convidada como as da faixa verde, com regra própria, e o RH pode reverter.
"""

from pathlib import Path

from backend.agente.regras import REGRA_POTENCIAL
from backend.contratos.modelos import TipoDecisao
from tests.agente.apoio import AnalisadorComEvidencias, candidato_exemplo, vaga_exemplo
from tests.agente.test_fluxo import (
    AnalisadorSemEvidencias,
    Montagem,
    _assinar_fluxo,
    _convites_por_candidato,
    _decisoes,
)


def _rodar(tmp_path: Path, candidatos, notas, **campos_vaga):
    vaga = vaga_exemplo(**campos_vaga)
    m = Montagem(tmp_path, candidatos, vaga=vaga, analisador=AnalisadorComEvidencias(notas=notas))
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo)
    return m, fluxo


def test_potencial_completa_a_meta_pela_maior_nota(tmp_path):
    candidatos = [candidato_exemplo(f"c{i}") for i in range(1, 6)]
    notas = {"c2": 0.5, "c3": 0.6, "c4": 0.4, "c5": 0.2}

    m, fluxo = _rodar(tmp_path, candidatos, notas, meta_candidatos=3)

    decisoes = _decisoes(m)
    assert decisoes["c1"].regra == "faixa_verde_v1"
    assert decisoes["c3"].regra == REGRA_POTENCIAL
    assert decisoes["c2"].regra == REGRA_POTENCIAL
    assert decisoes["c4"].regra == "abaixo_do_limiar"
    assert decisoes["c5"].regra == "abaixo_do_piso"
    assert {c for c, d in decisoes.items() if d.tipo is TipoDecisao.INDICAR} == {"c1", "c2", "c3"}
    assert set(_convites_por_candidato(m)) == {"c1", "c2", "c3"}
    [evento] = [e for e in fluxo.eventos if "faixa de potencial" in e.mensagem]
    assert "2" in evento.mensagem


def test_decisao_de_potencial_diz_nota_limiar_e_que_o_rh_pode_reverter(tmp_path):
    candidatos = [candidato_exemplo("c1"), candidato_exemplo("c2")]

    m, _ = _rodar(tmp_path, candidatos, {"c2": 0.55})

    decisao = _decisoes(m)["c2"]
    assert decisao.tipo is TipoDecisao.INDICAR
    assert decisao.entrada["faixa"] == "potencial"
    assert decisao.entrada["nota"] == "0.55"
    assert "0.55" in decisao.motivo and "limiar" in decisao.motivo
    assert "potencial" in decisao.motivo and "reverter" in decisao.motivo
    assert decisao.evidencias


def test_requisito_eliminatorio_reprovado_nunca_entra_como_potencial(tmp_path):
    candidatos = [
        candidato_exemplo("c1"),
        candidato_exemplo("c2", atributos={"python": "nao"}),
    ]

    m, _ = _rodar(tmp_path, candidatos, {"c2": 0.6}, meta_candidatos=5)

    assert _decisoes(m)["c2"].regra == "requisito_eliminatorio:r1"
    assert set(_convites_por_candidato(m)) == {"c1"}


def test_abaixo_do_piso_nunca_entra_como_potencial(tmp_path):
    m, _ = _rodar(tmp_path, [candidato_exemplo("c1"), candidato_exemplo("c2")], {"c2": 0.1})

    assert _decisoes(m)["c2"].regra == "abaixo_do_piso"


def test_sem_evidencia_conferida_nao_entra_como_potencial(tmp_path):
    vaga = vaga_exemplo()
    m = Montagem(
        tmp_path,
        [candidato_exemplo("c1"), candidato_exemplo("c2")],
        vaga=vaga,
        analisador=AnalisadorSemEvidencias(),
    )
    _assinar_fluxo(m.fluxo())

    assert {d.regra for d in _decisoes(m).values()} == {"abaixo_do_limiar"}
    assert _convites_por_candidato(m) == {}


def test_com_a_meta_atingida_na_faixa_verde_nao_ha_potencial(tmp_path):
    candidatos = [candidato_exemplo("c1"), candidato_exemplo("c2"), candidato_exemplo("c3")]

    m, fluxo = _rodar(tmp_path, candidatos, {"c3": 0.6})

    assert _decisoes(m)["c3"].regra == "abaixo_do_limiar"
    assert not any("faixa de potencial" in e.mensagem for e in fluxo.eventos)


def test_sem_ninguem_na_faixa_a_meta_continua_em_risco(tmp_path):
    m, fluxo = _rodar(tmp_path, [candidato_exemplo("c1")], {}, meta_candidatos=3)

    assert any("meta em risco: 1 de 3" in e.mensagem for e in fluxo.eventos)
    assert set(_convites_por_candidato(m)) == {"c1"}
