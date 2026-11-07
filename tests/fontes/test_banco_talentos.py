"""Comportamentos da T2.6, sem depender do mecanismo de persistência."""

from datetime import date
from importlib import import_module

import pytest

from backend.contratos.interfaces import BancoTalentos as ContratoBancoTalentos
from backend.contratos.modelos import EstadoBanco
from backend.contratos.simulacoes import candidato_simulado

HOJE = date(2026, 11, 7)


@pytest.fixture
def banco():
    classe = import_module("backend.fontes.banco_talentos").BancoTalentos
    return classe(hoje=HOJE)


def registro(identificador="pessoa-1", empresa="empresa-1", **campos):
    return candidato_simulado(identificador, empresa, **campos).model_dump(mode="json")


def test_implementa_interface(banco):
    assert isinstance(banco, ContratoBancoTalentos)


def test_importa_base_e_remove_duplicatas(banco):
    primeiro = registro(origem="planilha_sintetica")
    banco.importar("empresa-1", [primeiro, primeiro])
    encontrados = banco.buscar("empresa-1", "")
    assert len(encontrados) == 1
    assert encontrados[0].origem == "planilha_sintetica"
    banco.importar("empresa-1", [primeiro])
    assert len(banco.buscar("empresa-1", "")) == 1


def test_empresas_nao_veem_dados_uma_da_outra(banco):
    banco.importar("empresa-1", [registro(perfil_texto="Python")])
    banco.importar("empresa-2", [registro(empresa="empresa-2", perfil_texto="Java")])
    assert {c.empresa_id for c in banco.buscar("empresa-1", "")} == {"empresa-1"}
    assert banco.buscar("empresa-1", "Java") == []
    banco.atualizar("empresa-1", "pessoa-1", {"cloud": "sim"})
    assert "cloud" not in banco.buscar("empresa-2", "")[0].atributos
    banco.remover("empresa-1", "pessoa-1")
    assert len(banco.buscar("empresa-2", "")) == 1


@pytest.mark.parametrize(
    "campos",
    [
        {"autorizou_contato": False},
        {"autorizacao_valida_ate": None},
        {"autorizacao_valida_ate": date(2026, 11, 6)},
        {"opt_out": True},
        {"estado": EstadoBanco.PENDENTE},
        {"estado": EstadoBanco.EXPIRADO},
        {"estado": EstadoBanco.REMOVIDO},
    ],
)
def test_busca_ignora_quem_nao_tem_autorizacao_valida(banco, campos):
    banco.importar("empresa-1", [registro(**campos)])
    assert banco.buscar("empresa-1", "") == []


def test_autorizacao_vale_ate_o_dia_inclusive(banco):
    banco.importar("empresa-1", [registro(autorizacao_valida_ate=HOJE)])
    assert len(banco.buscar("empresa-1", "")) == 1


def test_remover_apaga_dados_e_impede_novo_contato(banco):
    original = registro()
    banco.importar("empresa-1", [original])
    banco.remover("empresa-1", "pessoa-1")
    assert banco.buscar("empresa-1", "") == []
    assert banco.vencendo("empresa-1", date(2030, 1, 1)) == []
    with pytest.raises(KeyError):
        banco.atualizar("empresa-1", "pessoa-1", {"cloud": "sim"})
    with pytest.raises(KeyError):
        banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2027, 1, 1))
    banco.importar("empresa-1", [original])
    assert banco.buscar("empresa-1", "") == []


def test_registra_autorizacao_e_atualiza_perfil(banco):
    banco.importar(
        "empresa-1",
        [registro(autorizou_contato=False, autorizacao_valida_ate=None,
                  estado=EstadoBanco.PENDENTE)],
    )
    autorizado = banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2027, 1, 1))
    assert autorizado.autorizou_contato
    assert autorizado.estado == EstadoBanco.ATIVO
    atualizado = banco.atualizar("empresa-1", "pessoa-1", {"cloud": "sim"})
    assert atualizado.atributos["cloud"] == "sim"
    assert atualizado.atualizado_em == HOJE
    assert banco.vencendo("empresa-1", date(2027, 1, 1))[0].id == "pessoa-1"
