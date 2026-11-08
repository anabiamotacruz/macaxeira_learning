"""Campanha única com os números que o recrutador assina.

O encaminhamento (max_indicacoes) é quem segue para a próxima fase, não uma
lista de contratação. Quem fica além desse número continua disponível para o RH.
A meta é quantas posições a mesma campanha preenche.
"""

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-campanha"}
POSICOES = 3
ENCAMINHAR = 10
ENCAMINHAR_APERTADO = 1


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "campanha.db")))


def _software(cliente: TestClient) -> dict:
    modelos = cliente.get("/vagas/modelos", headers=SESSAO)
    assert modelos.status_code == 200, modelos.text
    return next(m for m in modelos.json()["itens"] if m["titulo"] == "Software Engineer")


def _campanha(cliente: TestClient, encaminhar: int = ENCAMINHAR) -> str:
    pedido = {**_software(cliente), "meta_candidatos": POSICOES}
    criada = cliente.post("/vagas", headers=SESSAO, json=pedido)
    assert criada.status_code == 201, criada.text
    vaga = criada.json()["vaga"]["id"]
    mandato = cliente.post(
        f"/vagas/{vaga}/mandato",
        headers=SESSAO,
        json=pedido_mandato(max_indicacoes=encaminhar, aceitar_declarada=True),
    )
    assert mandato.status_code == 201, mandato.text
    return vaga


def _itens(cliente: TestClient, vaga: str) -> list[dict]:
    resposta = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["itens"]


def _regra(cliente: TestClient, vaga: str, candidato_id: str) -> str:
    resposta = cliente.get(
        f"/candidatos/{candidato_id}/decisao?vaga_id={vaga}", headers=SESSAO
    )
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["decisao"]["regra"]


def test_uma_campanha_guarda_posicoes_e_encaminhamento(cliente):
    vaga = _campanha(cliente)

    consulta = cliente.get(f"/vagas/{vaga}", headers=SESSAO)

    assert consulta.status_code == 200, consulta.text
    corpo = consulta.json()
    assert corpo["vaga"]["meta_candidatos"] == POSICOES
    assert corpo["vaga"]["titulo"] == "Software Engineer"
    assert corpo["mandato"]["politica"]["max_indicacoes"] == ENCAMINHAR
    assert corpo["simulado"] is True


def test_encaminhamento_nao_passa_do_numero_do_recrutador(cliente):
    vaga = _campanha(cliente)
    itens = _itens(cliente, vaga)
    encaminhados = [i for i in itens if i["decisao"] == "indicar"]

    assert encaminhados
    assert len(encaminhados) <= ENCAMINHAR
    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO)
    assert convites.status_code == 200, convites.text
    assert len(convites.json()["itens"]) <= ENCAMINHAR


def test_quem_passa_do_encaminhamento_fica_com_o_rh(cliente):
    # Encaminhamento menor que a faixa verde da base: sempre sobra alguém além do número.
    vaga = _campanha(cliente, encaminhar=ENCAMINHAR_APERTADO)
    itens = _itens(cliente, vaga)

    encaminhados = [i for i in itens if i["decisao"] == "indicar"]
    na_fila = [i for i in itens if i["decisao"] == "pedir_humano"]
    alem_do_numero = [
        i for i in na_fila if _regra(cliente, vaga, i["candidato"]["id"]) == "nao_priorizado"
    ]

    assert len(encaminhados) == ENCAMINHAR_APERTADO
    assert alem_do_numero, "ninguém ficou além do encaminhamento: o teste não prova o excesso"
    descartados = {i["candidato"]["id"] for i in itens if i["decisao"] == "descartar"}
    assert not descartados & {i["candidato"]["id"] for i in alem_do_numero}


def test_outra_empresa_nao_ve_a_campanha(cliente):
    vaga = _campanha(cliente)

    alheia = cliente.get(f"/vagas/{vaga}", headers={"X-Empresa-Id": "empresa-vizinha"})

    assert alheia.status_code == 404
    assert alheia.json()["erro"]["codigo"] == "vaga_nao_encontrada"
