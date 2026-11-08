"""Na demonstração, o convite é o e-mail inicial: chama para o WhatsApp com o código da vaga."""

import re

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from backend.contato.prompts import PALAVRA_SAIDA
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-convite"}


@pytest.fixture
def convites(tmp_path, monkeypatch) -> list[dict]:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    cliente = TestClient(criar_app(montar_demo(tmp_path / "convite.db")))
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    itens = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    enviados = [c for c in itens if c["estado"] == "aguardando"]
    assert enviados
    return enviados


def test_convite_chama_para_o_whatsapp_com_o_codigo(convites) -> None:
    for convite in convites:
        mensagem = convite["mensagem"]
        link = re.search(r"https://wa\.me/\d+\?text=Vaga%20([A-Z2-7]{6})", mensagem)
        assert link, mensagem
        assert f"código {link.group(1)}" in mensagem


def test_convite_diz_a_origem_e_como_sair(convites) -> None:
    for convite in convites:
        mensagem = convite["mensagem"]
        assert "Por que você recebeu este e-mail" in mensagem
        assert "exemplo.invalid" not in mensagem.split("Por que")[0]
        assert PALAVRA_SAIDA in mensagem
        assert "Mensagem simulada" in mensagem
        assert convite["canal"] == "email"
        assert convite["link_destino"] is None


def test_codigo_e_diferente_por_pessoa(convites) -> None:
    codigos = {re.search(r"text=Vaga%20([A-Z2-7]{6})", c["mensagem"]).group(1) for c in convites}
    assert len(codigos) == len(convites)
