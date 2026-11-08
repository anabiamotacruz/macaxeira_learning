"""Catálogo de vagas pela API: só as vagas da empresa da sessão, das mais novas às mais antigas."""

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from tests.agente.apoio import PEDIDO_VAGA, pedido_mandato, servico_de_teste

SESSAO = {"X-Empresa-Id": "empresa-a"}
OUTRA_EMPRESA = {"X-Empresa-Id": "empresa-outra"}
CAMPOS = {
    "id",
    "titulo",
    "estado",
    "meta_candidatos",
    "analisados",
    "indicados",
    "descartados",
    "gasto_usd",
}


@pytest.fixture
def cliente(tmp_path) -> TestClient:
    return TestClient(criar_app(servico_de_teste(tmp_path / "agente.db")))


def _criar(cliente: TestClient, titulo: str, cabecalhos: dict = SESSAO) -> str:
    resposta = cliente.post("/vagas", headers=cabecalhos, json={**PEDIDO_VAGA, "titulo": titulo})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["vaga"]["id"]


def test_sem_vagas_a_lista_vem_vazia_e_identificada(cliente):
    resposta = cliente.get("/vagas", headers=SESSAO)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["itens"] == []
    assert corpo["simulado"] is True
    assert corpo["exemplo_fixo"] is False


def test_lista_as_vagas_da_empresa_das_mais_novas_para_as_mais_antigas(cliente):
    primeira = _criar(cliente, "Primeira vaga")
    segunda = _criar(cliente, "Segunda vaga")

    itens = cliente.get("/vagas", headers=SESSAO).json()["itens"]

    assert [item["id"] for item in itens] == [segunda, primeira]
    assert [item["titulo"] for item in itens] == ["Segunda vaga", "Primeira vaga"]
    for item in itens:
        assert set(item) == CAMPOS
        assert item["estado"] == "aguardando_mandato"
        assert item["meta_candidatos"] == PEDIDO_VAGA["meta_candidatos"]
        assert item["analisados"] == item["indicados"] == item["descartados"] == 0
        assert item["gasto_usd"] == 0


def test_contagens_reaproveitam_o_resumo_da_vaga(cliente):
    vaga = _criar(cliente, "Vaga executada")
    assinada = cliente.post(f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato())
    assert assinada.status_code == 201, assinada.text

    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]
    (item,) = cliente.get("/vagas", headers=SESSAO).json()["itens"]

    assert item["estado"] == resumo["estado"]
    for campo in ("analisados", "indicados", "descartados", "gasto_usd"):
        assert item[campo] == resumo[campo], campo
    assert item["analisados"] > 0


def test_uma_empresa_nunca_ve_as_vagas_de_outra(cliente):
    da_empresa = _criar(cliente, "Vaga da empresa A")
    da_outra = _criar(cliente, "Vaga da outra empresa", OUTRA_EMPRESA)

    ids_a = [item["id"] for item in cliente.get("/vagas", headers=SESSAO).json()["itens"]]
    ids_outra = [
        item["id"] for item in cliente.get("/vagas", headers=OUTRA_EMPRESA).json()["itens"]
    ]

    assert ids_a == [da_empresa]
    assert ids_outra == [da_outra]


def test_empresa_na_consulta_nao_substitui_a_sessao(cliente):
    _criar(cliente, "Vaga da outra empresa", OUTRA_EMPRESA)
    resposta = cliente.get("/vagas?empresa_id=empresa-outra", headers=SESSAO)
    assert resposta.json()["itens"] == []


@pytest.mark.parametrize("cabecalhos", [{}, {"X-Empresa-Id": "   "}])
def test_sem_sessao_valida_recebe_401(cliente, cabecalhos):
    resposta = cliente.get("/vagas", headers=cabecalhos)
    assert resposta.status_code == 401
    assert resposta.json()["simulado"] is True
