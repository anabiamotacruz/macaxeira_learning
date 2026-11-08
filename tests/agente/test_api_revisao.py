"""O RH resolve a fila humana pela API: indica para contato ou descarta, sempre com motivo."""

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-revisao"}
PESSOA_RH = "Ana do RH (fictícia)"


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "demo.db")))


@pytest.fixture
def vaga(cliente) -> str:
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    politica = {"aceitar_declarada": True, "max_indicacoes": 2}
    assinado = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(**politica)
    )
    assert assinado.status_code == 201, assinado.text
    return vaga


def _na_fila(cliente, vaga, motivo_contem: str) -> str:
    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    for item in itens:
        if item["decisao"] != "pedir_humano":
            continue
        candidato_id = item["candidato"]["id"]
        decisao = cliente.get(
            f"/candidatos/{candidato_id}/decisao?vaga_id={vaga}", headers=SESSAO
        ).json()["decisao"]
        if motivo_contem in decisao["motivo"]:
            return candidato_id
    raise AssertionError(f"ninguém na fila com {motivo_contem!r}")


def _revisar(cliente, vaga, candidato_id, decisao, chave="r1", responsavel=PESSOA_RH):
    return cliente.post(
        f"/candidatos/{candidato_id}/revisao",
        headers=SESSAO,
        json={
            "vaga_id": vaga,
            "decisao": decisao,
            "motivo": "Conferi o perfil.",
            "responsavel": responsavel,
            "chave_idempotencia": chave,
        },
    )


def test_rh_indica_quem_passou_do_limite_e_o_agente_convida(cliente, vaga):
    candidato_id = _na_fila(cliente, vaga, "limite")

    resposta = _revisar(cliente, vaga, candidato_id, "indicar")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["decisao"]["tipo"] == "indicar"
    assert corpo["decisao"]["responsavel"].startswith("humano:")
    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    assert candidato_id in {c["candidato_id"] for c in convites}


def test_rh_descarta_e_ninguem_e_contatado(cliente, vaga):
    candidato_id = _na_fila(cliente, vaga, "limite")

    resposta = _revisar(cliente, vaga, candidato_id, "descartar")

    assert resposta.status_code == 200, resposta.text
    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    assert candidato_id not in {c["candidato_id"] for c in convites}
    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    assert next(i for i in itens if i["candidato"]["id"] == candidato_id)["decisao"] == "descartar"


def test_quem_nao_esta_na_fila_nao_pode_ser_revisado(cliente, vaga):
    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    indicado = next(i["candidato"]["id"] for i in itens if i["decisao"] == "indicar")

    resposta = _revisar(cliente, vaga, indicado, "descartar")

    assert resposta.status_code == 409
    assert resposta.json()["erro"]["codigo"] == "acao_recusada"


def test_revisao_exige_uma_pessoa_responsavel(cliente, vaga):
    candidato_id = _na_fila(cliente, vaga, "limite")

    resposta = _revisar(cliente, vaga, candidato_id, "indicar", responsavel="agente automático")

    assert resposta.status_code in (409, 422)


def test_revisao_repetida_com_a_mesma_chave_nao_duplica(cliente, vaga):
    candidato_id = _na_fila(cliente, vaga, "limite")

    primeira = _revisar(cliente, vaga, candidato_id, "indicar", chave="igual")
    segunda = _revisar(cliente, vaga, candidato_id, "indicar", chave="igual")

    assert primeira.json() == segunda.json()


def test_revisao_so_aceita_indicar_ou_descartar(cliente, vaga):
    candidato_id = _na_fila(cliente, vaga, "limite")

    resposta = _revisar(cliente, vaga, candidato_id, "pedir_humano")

    assert resposta.status_code == 422
