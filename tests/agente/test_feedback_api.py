"""A pessoa pede feedback pela conversa e o agente responde pela API, só a pedido e sem nota."""

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-feedback"}


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "feedback.db")))


def _vaga(cliente: TestClient) -> str:
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    resposta = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    assert resposta.status_code == 201, resposta.text
    return vaga


def _pedir(
    cliente: TestClient, vaga: str, candidato_id: str, texto: str = "Por que fui escolhida?"
):
    return cliente.post(
        f"/candidatos/{candidato_id}/feedback",
        headers=SESSAO,
        json={"vaga_id": vaga, "texto": texto, "chave_idempotencia": f"fb-{candidato_id}-{texto}"},
    )


def _itens(cliente: TestClient, vaga: str) -> list[dict]:
    return cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]


def test_indicada_que_pergunta_recebe_os_criterios_sem_nota(cliente: TestClient) -> None:
    vaga = _vaga(cliente)
    indicada = next(i for i in _itens(cliente, vaga) if i["decisao"] == "indicar")

    resposta = _pedir(cliente, vaga, indicada["candidato"]["id"])

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["simulado"] is True
    assert corpo["status"] in ("gerado", "encaminhado")
    texto = (corpo["saudacao"] + corpo["texto"]).lower()
    for proibido in ("nota", "ranking", "score", "outros candidatos"):
        assert proibido not in texto
    if corpo["status"] == "gerado":
        assert corpo["motivos"]
        assert all(m["trecho"] for m in corpo["motivos"])


def test_contestacao_vai_para_uma_pessoa(cliente: TestClient) -> None:
    vaga = _vaga(cliente)
    alguem = next(i for i in _itens(cliente, vaga) if i["decisao"])

    corpo = _pedir(
        cliente, vaga, alguem["candidato"]["id"], "Quero contestar, isso foi injusto"
    ).json()

    assert corpo["status"] == "encaminhado"
    assert corpo["motivos"] == []


def test_resposta_nao_mostra_quem_responde_internamente(cliente: TestClient) -> None:
    vaga = _vaga(cliente)
    alguem = next(i for i in _itens(cliente, vaga) if i["decisao"])

    corpo = _pedir(cliente, vaga, alguem["candidato"]["id"]).json()

    assert "responsavel" not in corpo
    assert "encaminhado_por" not in corpo


def test_pessoa_sem_decisao_ou_de_outra_empresa_e_recusada(cliente: TestClient) -> None:
    vaga = _vaga(cliente)

    assert 400 <= _pedir(cliente, vaga, "pessoa-inexistente").status_code < 500
    alheia = cliente.post(
        "/candidatos/x/feedback",
        headers={"X-Empresa-Id": "outra"},
        json={"vaga_id": vaga, "texto": "oi", "chave_idempotencia": "k"},
    )
    assert alheia.status_code == 404


def test_pedido_fica_no_diario_sem_o_texto(cliente: TestClient) -> None:
    vaga = _vaga(cliente)
    alguem = next(i for i in _itens(cliente, vaga) if i["decisao"])

    _pedir(cliente, vaga, alguem["candidato"]["id"], "Por que? Minha mãe está doente")

    eventos = cliente.get(f"/vagas/{vaga}/eventos?limite=100", headers=SESSAO).json()["itens"]
    assert any(e["etapa"] == "feedback" for e in eventos)
    assert all("mãe" not in e["mensagem"] for e in eventos)
