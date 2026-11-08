"""Campanha nova lembra o Talent Garden da empresa. O RH escolhe quem recebe o convite especial."""

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.fluxo import GARDEN_ALEM_DO_ENCAMINHAMENTO, GARDEN_NAO_AGORA
from backend.agente.montagem import montar_demo
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-garden"}


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "campanha.db")))


def _vaga(cliente: TestClient, indice: int) -> str:
    modelos = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelos[indice]).json()["vaga"]["id"]
    resposta = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    assert resposta.status_code == 201, resposta.text
    return vaga


def _convites(cliente: TestClient, vaga: str) -> list[dict]:
    return cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]


def _responder(cliente: TestClient, vaga: str, convite: dict, tipo: str, texto: str = "") -> None:
    resposta = cliente.post(
        f"/convites/{convite['id']}/resposta",
        headers=SESSAO,
        json={
            "vaga_id": vaga,
            "tipo": tipo,
            "texto": texto,
            "chave_idempotencia": f"{tipo}:{convite['id']}",
        },
    )
    assert resposta.status_code == 200, resposta.text


def _garden_na_primeira_vaga(cliente: TestClient) -> tuple[str, list[str]]:
    origem = _vaga(cliente, 0)
    abertos = [c for c in _convites(cliente, origem) if c["estado"] == "aguardando"]
    assert abertos
    for convite in abertos:
        _responder(cliente, origem, convite, "recusa", "Agora não, talvez mais para frente")
    return origem, [c["candidato_id"] for c in abertos]


def _sugestoes(cliente: TestClient, vaga: str) -> list[dict]:
    resposta = cliente.get(f"/vagas/{vaga}/talent-garden/sugestoes", headers=SESSAO)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["simulado"] is True
    return corpo["itens"]


def _convidar(cliente: TestClient, vaga: str, ids: list[str], **campos):
    pedido = {
        "candidato_ids": ids,
        "responsavel": "Ana Recrutadora",
        "chave_idempotencia": "garden-1",
        **campos,
    }
    return cliente.post(f"/vagas/{vaga}/talent-garden/convites", headers=SESSAO, json=pedido)


def test_campanha_nova_sugere_quem_esta_no_garden_de_outra_vaga(cliente: TestClient) -> None:
    origem, guardados = _garden_na_primeira_vaga(cliente)
    nova = _vaga(cliente, 1)

    sugestoes = _sugestoes(cliente, nova)

    assert sugestoes
    ja_convidados = {c["candidato_id"] for c in _convites(cliente, nova)}
    for item in sugestoes:
        assert item["candidato_id"] not in ja_convidados
        assert item["vaga_origem_id"] == origem
        assert item["vaga_origem_titulo"]
        assert item["motivo"] in (GARDEN_NAO_AGORA, GARDEN_ALEM_DO_ENCAMINHAMENTO)
        assert item["canal"] == "email"
    nao_agora = [i for i in sugestoes if i["motivo"] == GARDEN_NAO_AGORA]
    assert nao_agora
    assert all(i["candidato_id"] in guardados for i in nao_agora)


def test_rh_manda_o_convite_especial_pelo_canal_do_primeiro_contato(cliente: TestClient) -> None:
    _garden_na_primeira_vaga(cliente)
    nova = _vaga(cliente, 1)
    [primeira, *_] = _sugestoes(cliente, nova)

    resposta = _convidar(cliente, nova, [primeira["candidato_id"]])

    assert resposta.status_code == 200, resposta.text
    [convite] = resposta.json()["itens"]
    assert convite["candidato_id"] == primeira["candidato_id"]
    assert convite["canal"] == primeira["canal"]
    assert "Talent Garden" in convite["mensagem"]
    assert "SAIR" in convite["mensagem"]
    assert convite["link_destino"] is None
    assert convite["simulado"] is True
    assert any(c["id"] == convite["id"] for c in _convites(cliente, nova))
    assert all(i["candidato_id"] != primeira["candidato_id"] for i in _sugestoes(cliente, nova))


def test_aceite_do_convite_especial_traz_o_link_de_agendamento(cliente: TestClient) -> None:
    _garden_na_primeira_vaga(cliente)
    nova = _vaga(cliente, 1)
    [primeira, *_] = _sugestoes(cliente, nova)
    [convite] = _convidar(cliente, nova, [primeira["candidato_id"]]).json()["itens"]

    _responder(cliente, nova, convite, "aceite")

    aceito = next(c for c in _convites(cliente, nova) if c["id"] == convite["id"])
    assert aceito["estado"] == "aceito"
    assert aceito["link_destino"]


def test_repetir_o_pedido_nao_manda_de_novo(cliente: TestClient) -> None:
    _garden_na_primeira_vaga(cliente)
    nova = _vaga(cliente, 1)
    [primeira, *_] = _sugestoes(cliente, nova)

    _convidar(cliente, nova, [primeira["candidato_id"]])
    _convidar(cliente, nova, [primeira["candidato_id"]])

    especiais = [
        c for c in _convites(cliente, nova) if c["candidato_id"] == primeira["candidato_id"]
    ]
    assert len(especiais) == 1


def test_quem_pediu_para_sair_nao_e_sugerido(cliente: TestClient) -> None:
    origem, _ = _garden_na_primeira_vaga(cliente)
    convite = next(c for c in _convites(cliente, origem) if c["estado"] != "aceito")
    _responder(cliente, origem, convite, "opt_out")
    nova = _vaga(cliente, 1)

    assert all(i["candidato_id"] != convite["candidato_id"] for i in _sugestoes(cliente, nova))


def test_so_uma_pessoa_do_rh_autoriza(cliente: TestClient) -> None:
    _garden_na_primeira_vaga(cliente)
    nova = _vaga(cliente, 1)
    [primeira, *_] = _sugestoes(cliente, nova)

    resposta = _convidar(cliente, nova, [primeira["candidato_id"]], responsavel="Agente")

    assert 400 <= resposta.status_code < 500


def test_nao_convida_quem_nao_esta_nas_sugestoes(cliente: TestClient) -> None:
    _garden_na_primeira_vaga(cliente)
    nova = _vaga(cliente, 1)

    resposta = _convidar(cliente, nova, ["pessoa-inexistente"])

    assert 400 <= resposta.status_code < 500


def test_outra_empresa_nao_ve_as_sugestoes(cliente: TestClient) -> None:
    _garden_na_primeira_vaga(cliente)
    nova = _vaga(cliente, 1)

    alheia = cliente.get(
        f"/vagas/{nova}/talent-garden/sugestoes", headers={"X-Empresa-Id": "outra"}
    )

    assert alheia.status_code == 404
