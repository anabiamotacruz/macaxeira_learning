"""A demonstração é sempre sintética (FR-E009), mesmo com chaves no ambiente e `MODO_DADOS` vazio.

As chaves sozinhas não ligam nada. A busca real só entra com `AGENTE_BUSCA_REAL=1`, um opt-in
explícito, e o modelo só com `AGENTE_COM_MODELO=1`. Os valores abaixo são falsos, de teste.
"""

import socket

import pytest
from fastapi.testclient import TestClient

from backend.agente import montagem
from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo, montar_servico
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-sintetica"}
CHAVES_FALSAS = {
    "BRAVE_API_KEY": "valor-de-teste",
    "BRIGHTDATA_API_TOKEN": "valor-de-teste",
    "PDL_API_KEY": "valor-de-teste",
    "FEATHERLESS_API_KEY": "valor-de-teste",
}


@pytest.fixture
def sem_rede(monkeypatch):
    """Qualquer conexão de rede falha o teste: a demo não pode sair da máquina."""

    def recusar(*args, **kwargs):
        raise AssertionError("a demonstração tentou abrir conexão de rede")

    monkeypatch.setattr(socket.socket, "connect", recusar)
    monkeypatch.setattr(socket, "create_connection", recusar)


@pytest.fixture
def sem_fonte_externa(monkeypatch):
    """Montar a fonte externa já é falha: as chaves não podem ligá-la sozinhas."""

    def recusar(*args, **kwargs):
        raise AssertionError("a demonstração montou a fonte externa")

    monkeypatch.setattr(montagem, "montar_fonte_externa", recusar)


@pytest.fixture
def chaves_no_ambiente(monkeypatch):
    for nome, valor in CHAVES_FALSAS.items():
        monkeypatch.setenv(nome, valor)
    monkeypatch.setenv("MODO_DADOS", "")
    for nome in ("AGENTE_COM_MODELO", "AGENTE_BUSCA_REAL", "NARA_MCP_URL"):
        monkeypatch.delenv(nome, raising=False)


def _candidatos(servico) -> list[dict]:
    cliente = TestClient(criar_app(servico))
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    assinado = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    assert assinado.status_code == 201, assinado.text
    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    assert itens, "a demonstração precisa ter pessoas para analisar"
    return [item["candidato"] for item in itens]


@pytest.mark.usefixtures("chaves_no_ambiente", "sem_rede", "sem_fonte_externa")
def test_montar_demo_e_sintetica_com_chaves_no_ambiente(tmp_path):
    candidatos = _candidatos(montar_demo(tmp_path / "demo.db"))

    assert all(c["simulado"] for c in candidatos)


@pytest.mark.usefixtures("chaves_no_ambiente", "sem_rede", "sem_fonte_externa")
def test_montagem_pelo_ambiente_sem_opt_in_fica_sintetica(tmp_path):
    def sem_cliente(*args, **kwargs):
        raise AssertionError("sem AGENTE_COM_MODELO=1, a chave não liga o modelo")

    servico = montar_servico(tmp_path / "demo.db", criar_cliente=sem_cliente)

    assert all(c["simulado"] for c in _candidatos(servico))


@pytest.mark.usefixtures("chaves_no_ambiente", "sem_rede", "sem_fonte_externa")
@pytest.mark.parametrize("valor", ["0", "sim", "true", " "])
def test_so_o_valor_1_liga_a_busca_real(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("AGENTE_BUSCA_REAL", valor)

    servico = montar_servico(tmp_path / "demo.db")

    assert all(c["simulado"] for c in _candidatos(servico))
