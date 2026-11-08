"""Rotina do banco (T1.7): quem atualizar, dentro do limite, e quem sai por autorização vencida."""

from datetime import date, timedelta

import pytest

from backend.agente.persistencia import Repositorio
from backend.agente.rotina_banco import (
    REGRA_VENCIDA,
    VAGA_DO_BANCO,
    RotinaBanco,
)
from backend.contratos.modelos import EstadoBanco, TipoDecisao
from backend.contratos.simulacoes import candidato_simulado
from backend.fontes.banco_talentos import BancoTalentos as BancoTalentosReal

HOJE = date(2026, 11, 8)
EMPRESA = "empresa-rotina"


def _registro(
    identificador: str, *, dias_sem_atualizar: int = 10, validade_dias: int = 300, **campos
):
    dados = {
        "atualizado_em": HOJE - timedelta(days=dias_sem_atualizar),
        "autorizacao_valida_ate": HOJE + timedelta(days=validade_dias),
        "perfil_texto": "Desenvolve em Python.",
    }
    dados.update(campos)
    return candidato_simulado(identificador, EMPRESA, **dados).model_dump()


@pytest.fixture
def banco() -> BancoTalentosReal:
    """O banco da Frente 2 (T2.6). O simulado do contrato importa todo mundo como pendente."""
    return BancoTalentosReal(hoje=HOJE, confiar_autorizacao_sintetica=True)


@pytest.fixture
def repositorio(tmp_path) -> Repositorio:
    return Repositorio(tmp_path / "agente.db")


def _ids(candidatos) -> list[str]:
    return [c.id for c in candidatos]


def test_seleciona_perfis_desatualizados_dentro_do_limite(banco, repositorio):
    banco.importar(
        EMPRESA,
        [
            _registro("recente", dias_sem_atualizar=10),
            _registro("antigo-1", dias_sem_atualizar=400),
            _registro("antigo-2", dias_sem_atualizar=300),
            _registro("antigo-3", dias_sem_atualizar=200),
        ],
    )
    rotina = RotinaBanco(banco, repositorio, limite=2)

    selecionados = rotina.selecionar_para_contato(EMPRESA, HOJE)

    ids = _ids(selecionados)
    assert len(ids) == 2
    assert "antigo-1" in ids[0]
    assert "antigo-2" in ids[1]


def test_selecao_e_reproduzivel(banco, repositorio):
    banco.importar(EMPRESA, [_registro(f"antigo-{i}", dias_sem_atualizar=365) for i in range(5)])
    rotina = RotinaBanco(banco, repositorio, limite=3)

    assert _ids(rotina.selecionar_para_contato(EMPRESA, HOJE)) == _ids(
        rotina.selecionar_para_contato(EMPRESA, HOJE)
    )


def test_nao_contata_quem_saiu_ou_foi_removido(banco, repositorio):
    importados = banco.importar(
        EMPRESA,
        [
            _registro("saiu", dias_sem_atualizar=400),
            _registro("removido", dias_sem_atualizar=400),
            _registro("fica", dias_sem_atualizar=400),
        ],
    )
    ids = {c.id for c in importados}
    saiu = next(i for i in ids if "saiu" in i)
    removido = next(i for i in ids if "removido" in i)
    banco.registrar_opt_out(EMPRESA, saiu)
    banco.remover(EMPRESA, removido)
    rotina = RotinaBanco(banco, repositorio, limite=10)

    selecionados = _ids(rotina.selecionar_para_contato(EMPRESA, HOJE))

    assert saiu not in selecionados
    assert removido not in selecionados
    assert any("fica" in c for c in selecionados)


def test_autorizacao_vencida_sai_da_busca(banco, repositorio):
    importados = banco.importar(
        EMPRESA,
        [_registro("vencida", validade_dias=-1), _registro("valida", validade_dias=30)],
    )
    vencida = next(c.id for c in importados if "vencida" in c.id)
    rotina = RotinaBanco(banco, repositorio, limite=10)

    decisoes = rotina.processar_vencidos(EMPRESA, HOJE)

    assert [d.candidato_id for d in decisoes] == [vencida]
    [decisao] = decisoes
    assert decisao.tipo == TipoDecisao.DESCARTAR
    assert decisao.regra == REGRA_VENCIDA
    assert decisao.vaga_id == VAGA_DO_BANCO
    assert decisao.entrada["autorizacao_valida_ate"] == (HOJE - timedelta(days=1)).isoformat()
    assert repositorio.listar_decisoes(EMPRESA, VAGA_DO_BANCO) == decisoes
    assert vencida not in _ids(banco.buscar(EMPRESA, ""))
    assert vencida not in _ids(rotina.selecionar_para_contato(EMPRESA, HOJE))


def test_vencida_processada_duas_vezes_registra_uma_decisao(banco, repositorio):
    banco.importar(EMPRESA, [_registro("vencida", validade_dias=-5)])
    rotina = RotinaBanco(banco, repositorio, limite=10)

    rotina.processar_vencidos(EMPRESA, HOJE)
    segunda = rotina.processar_vencidos(EMPRESA, HOJE)

    assert segunda == []
    assert len(repositorio.listar_decisoes(EMPRESA, VAGA_DO_BANCO)) == 1


def test_autorizacao_que_vence_hoje_ainda_vale(banco, repositorio):
    banco.importar(EMPRESA, [_registro("hoje", validade_dias=0)])
    rotina = RotinaBanco(banco, repositorio, limite=10)

    assert rotina.processar_vencidos(EMPRESA, HOJE) == []


def test_empresas_nao_se_misturam(banco, repositorio):
    banco.importar(EMPRESA, [_registro("vencida", validade_dias=-1)])
    rotina = RotinaBanco(banco, repositorio, limite=10)

    assert rotina.processar_vencidos("outra-empresa", HOJE) == []
    assert rotina.selecionar_para_contato("outra-empresa", HOJE) == []


def test_limite_precisa_ser_positivo(banco, repositorio):
    with pytest.raises(ValueError):
        RotinaBanco(banco, repositorio, limite=0)


def test_desatualizado_pelo_estado_tambem_entra(repositorio):
    banco = BancoTalentosReal(hoje=HOJE, confiar_autorizacao_sintetica=True)
    banco.importar(
        EMPRESA, [_registro("marcado", dias_sem_atualizar=5, estado=EstadoBanco.DESATUALIZADO)]
    )
    rotina = RotinaBanco(banco, repositorio, limite=10)

    assert len(rotina.selecionar_para_contato(EMPRESA, HOJE)) == 1
