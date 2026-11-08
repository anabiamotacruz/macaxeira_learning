"""Quem vem da busca real, sem autorização registrada, segue para a análise (decisão de 8/11).

Opt-out, supressão, remoção e autorização que existiu e venceu continuam cortando por código.
"""

from datetime import date

import pytest

from backend.agente.regras import avaliar_requisitos
from backend.contratos.modelos import EstadoBanco
from backend.contratos.simulacoes import candidato_simulado
from backend.fontes.funil import Corte, RegraCorte, priorizar
from tests.fontes.test_funil import EMPRESA, HOJE, _vaga

ATRIBUTOS = {"producao": "sim", "presencial_sp": "sim"}


def _externo(candidato_id: str, **campos):
    """Como `candidato_de_item` entrega quem vem de provedor: real, pendente e sem autorização."""
    dados = {
        "fonte": "brave",
        "simulado": False,
        "origem": f"https://exemplo.invalid/{candidato_id}",
        "autorizacao_valida_ate": None,
        "autorizou_contato": False,
        "estado": EstadoBanco.PENDENTE,
        "atributos": dict(ATRIBUTOS),
    }
    dados.update(campos)
    return candidato_simulado(candidato_id, EMPRESA, **dados)


def _do_banco(candidato_id: str, **campos):
    return candidato_simulado(candidato_id, EMPRESA, atributos=dict(ATRIBUTOS), **campos)


def _priorizar(candidatos):
    cortes: list[Corte] = []
    selecionados = priorizar(
        _vaga(),
        candidatos,
        20,
        hoje=HOJE,
        avaliar_requisitos=avaliar_requisitos,
        registrar_corte=cortes.append,
    )
    regras = {c.candidato_id: c.regra for c in cortes if c.regra != RegraCorte.DUPLICATA}
    return [c.id for c in selecionados], regras


def test_externo_sem_autorizacao_segue_para_a_analise():
    selecionados, cortes = _priorizar([_externo("ext"), _do_banco("banco")])

    assert selecionados == ["banco", "ext"]
    assert cortes == {}


def test_externo_com_opt_out_continua_cortado():
    _, cortes = _priorizar([_externo("ext", opt_out=True)])

    assert cortes == {"ext": RegraCorte.OPT_OUT}


def test_opt_out_em_outra_fonte_corta_o_registro_externo():
    outra_fonte = _externo("ext", fonte="github", origem="https://github.invalid/ext", opt_out=True)

    selecionados, cortes = _priorizar([_externo("ext"), outra_fonte])

    assert selecionados == []
    assert cortes["ext"] == RegraCorte.OPT_OUT


def test_externo_removido_continua_cortado():
    _, cortes = _priorizar([_externo("ext"), _do_banco("ext", estado=EstadoBanco.REMOVIDO)])

    assert cortes["ext"] == RegraCorte.ESTADO_BLOQUEADO


def test_autorizacao_vencida_no_banco_corta_mesmo_com_registro_externo():
    vencida = _do_banco("ext", fonte="banco", autorizacao_valida_ate=date(2026, 11, 6))

    selecionados, cortes = _priorizar([_externo("ext"), vencida])

    assert selecionados == []
    assert cortes["ext"] == RegraCorte.AUTORIZACAO_VENCIDA


def test_autorizacao_vencida_de_quem_veio_de_fora_continua_cortando():
    vencida = _externo("ext", autorizou_contato=True, autorizacao_valida_ate=date(2026, 11, 6))

    _, cortes = _priorizar([vencida])

    assert cortes == {"ext": RegraCorte.AUTORIZACAO_VENCIDA}


@pytest.mark.parametrize(
    "campos",
    [
        {"simulado": True},
        {"estado": EstadoBanco.EXPIRADO},
        {"autorizou_contato": True},
        {"autorizacao_valida_ate": date(2027, 1, 1)},
    ],
    ids=["banco_simulado", "expirado", "autorizou_sem_validade", "validade_sem_autorizar"],
)
def test_quem_nao_e_externo_sem_autorizacao_continua_como_hoje(campos):
    _, cortes = _priorizar([_externo("ext", **campos)])

    assert cortes["ext"] in (RegraCorte.SEM_AUTORIZACAO, RegraCorte.ESTADO_BLOQUEADO)
