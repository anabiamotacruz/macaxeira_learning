"""Montagem com o modelo de verdade, atrás de chave e opt-in. Os dados seguem sintéticos."""

import logging

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import COM_MODELO, montar_com_modelo, montar_servico
from backend.contratos.erros import ModeloIndisponivel
from backend.contratos.simulacoes import ClienteModeloSimulado
from backend.fontes.analisador import ETAPA_ANALISE
from backend.fontes.consultas import ETAPA_GERAR
from backend.fontes.revisor import ETAPA_REVISAO
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-modelo"}

RESPOSTAS = {
    ETAPA_GERAR: {"consultas": ["python"]},
    ETAPA_ANALISE: {"notas": {}, "evidencias": []},
    ETAPA_REVISAO: {"ressalvas": []},
}


def _nao_cria(**_):
    raise AssertionError("sem opt-in, o cliente do modelo não pode ser criado")


def _rodar_vaga(servico) -> tuple[TestClient, str]:
    cliente = TestClient(criar_app(servico))
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    assinado = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    assert assinado.status_code == 201, assinado.text
    return cliente, vaga


def test_sem_opt_in_a_demo_nao_cria_cliente_de_modelo(tmp_path):
    servico = montar_servico(tmp_path / "a.db", ambiente={}, criar_cliente=_nao_cria)

    _, vaga = _rodar_vaga(servico)

    assert vaga


def test_opt_in_sem_chave_volta_para_a_demo_com_aviso(tmp_path, caplog):
    def sem_chave(**_):
        raise ModeloIndisponivel("defina a variável de ambiente FEATHERLESS_API_KEY")

    with caplog.at_level(logging.WARNING):
        servico = montar_servico(
            tmp_path / "a.db", ambiente={COM_MODELO: "1"}, criar_cliente=sem_chave
        )

    _, vaga = _rodar_vaga(servico)
    assert vaga
    assert "demonstração sem modelo" in caplog.text


def test_com_modelo_analise_revisao_e_consultas_passam_pelo_modelo(tmp_path):
    modelo = ClienteModeloSimulado(RESPOSTAS)
    servico = montar_com_modelo(tmp_path / "a.db", cliente=modelo, medidor_gasto=lambda: 0.0)

    _rodar_vaga(servico)

    etapas = {chamada["etapa"] for chamada in modelo.chamadas}
    assert {ETAPA_GERAR, ETAPA_ANALISE} <= etapas


def test_com_modelo_os_dados_seguem_sinteticos(tmp_path):
    modelo = ClienteModeloSimulado(RESPOSTAS)
    servico = montar_com_modelo(tmp_path / "a.db", cliente=modelo, medidor_gasto=lambda: 0.0)

    cliente, vaga = _rodar_vaga(servico)

    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    assert itens
    assert all(item["candidato"]["simulado"] for item in itens)


def test_com_modelo_o_gasto_do_cliente_pausa_a_vaga(tmp_path):
    modelo = ClienteModeloSimulado(RESPOSTAS)
    servico = montar_com_modelo(tmp_path / "a.db", cliente=modelo, medidor_gasto=lambda: 999.0)

    cliente, vaga = _rodar_vaga(servico)

    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]
    assert resumo["estado"] == "pausada"
    assert resumo["gasto_usd"] == pytest.approx(999.0)


def test_opt_in_com_chave_usa_o_cliente_criado(tmp_path):
    modelo = ClienteModeloSimulado(RESPOSTAS)
    servico = montar_servico(
        tmp_path / "a.db", ambiente={COM_MODELO: "1"}, criar_cliente=lambda **_: modelo
    )

    _rodar_vaga(servico)

    assert modelo.chamadas
