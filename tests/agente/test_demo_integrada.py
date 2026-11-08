"""Demonstração com os dados sintéticos da Frente 2 e o contato e a Nara simulada da Frente 3."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from backend.contato.prompts import PALAVRA_SAIDA
from backend.nara_simulada.servico import BASE_LINK
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-teste"}
RAIZ = Path(__file__).resolve().parents[2]
PERFIS_SINTETICOS = json.loads((RAIZ / "dados/sinteticos/candidatos.json").read_text())


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "demo.db")))


def _modelos(cliente: TestClient) -> list[dict]:
    resposta = cliente.get("/vagas/modelos", headers=SESSAO)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["itens"]


def _vaga_do_modelo(cliente: TestClient, indice: int = 0, **politica) -> str:
    pedido = _modelos(cliente)[indice]
    vaga = cliente.post("/vagas", headers=SESSAO, json=pedido).json()["vaga"]["id"]
    # O banco de talentos é autodeclarado: sem aceitar declarada, ninguém entra na faixa verde.
    politica = {"aceitar_declarada": True, **politica}
    mandato = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(**politica)
    )
    assert mandato.status_code == 201, mandato.text
    return vaga


def test_modelos_de_vaga_vem_dos_dados_sinteticos(cliente):
    modelos = _modelos(cliente)

    assert len(modelos) >= 2
    assert all("id" not in m and "empresa_id" not in m for m in modelos)
    assert {m["titulo"] for m in modelos} >= {"Software Engineer"}


def test_busca_usa_os_perfis_sinteticos_da_frente_2(cliente):
    vaga = _vaga_do_modelo(cliente)

    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]

    originais = {p["id"] for p in PERFIS_SINTETICOS}
    vindos_da_frente_2 = [i for i in itens if i["candidato"]["id"].rsplit("@", 1)[0] in originais]
    assert len(vindos_da_frente_2) > 4
    assert all(i["candidato"]["empresa_id"] == "empresa-teste" for i in itens)
    assert all(i["candidato"]["simulado"] for i in itens)


def test_convite_diz_o_que_interessou_e_traz_o_link_da_nara(cliente):
    vaga = _vaga_do_modelo(cliente)

    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]

    enviados = [c for c in convites if c["estado"] == "aguardando"]
    assert enviados
    for convite in enviados:
        assert "chamou nossa atenção por" in convite["mensagem"]
        assert PALAVRA_SAIDA in convite["mensagem"]
        assert convite["link_destino"].startswith(BASE_LINK)
        assert convite["link_destino"] in convite["mensagem"]
        assert "{" not in convite["mensagem"]


def test_aceite_entrega_o_contexto_a_nara_simulada(cliente):
    vaga = _vaga_do_modelo(cliente)
    convite = next(
        c
        for c in cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
        if c["estado"] == "aguardando"
    )

    resposta = cliente.post(
        f"/convites/{convite['id']}/resposta",
        headers=SESSAO,
        json={"vaga_id": vaga, "tipo": "aceite", "chave_idempotencia": "a1"},
    )

    assert resposta.status_code == 200, resposta.text
    pacotes = cliente.get(f"/vagas/{vaga}/entrega", headers=SESSAO).json()["saida"]["pacotes"]
    assert convite["candidato_id"] in {p["candidato_id"] for p in pacotes}
    assert all(p["simulado"] and p["evidencias"] for p in pacotes)


def test_evidencia_da_demo_e_um_trecho_do_perfil(cliente):
    vaga = _vaga_do_modelo(cliente)
    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    indicados = [i for i in itens if i["decisao"] == "indicar"]
    assert indicados

    for item in indicados:
        candidato = item["candidato"]
        decisao = cliente.get(
            f"/candidatos/{candidato['id']}/decisao?vaga_id={vaga}", headers=SESSAO
        ).json()["decisao"]
        assert decisao["evidencias"]
        for evidencia in decisao["evidencias"]:
            if evidencia["fonte"] == candidato["fonte"]:
                assert evidencia["trecho"] in candidato["perfil_texto"]
                assert evidencia["trecho"] != candidato["perfil_texto"]


def test_vaga_que_a_regra_recusa_nao_vira_modelo(cliente):
    for modelo in _modelos(cliente):
        assert cliente.post("/vagas", headers=SESSAO, json=modelo).status_code == 201


def test_perfil_com_instrucao_nao_vira_evidencia(cliente):
    vaga = _vaga_do_modelo(cliente)
    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]

    for item in itens:
        decisao = cliente.get(
            f"/candidatos/{item['candidato']['id']}/decisao?vaga_id={vaga}", headers=SESSAO
        ).json()["decisao"]
        assert not any("ignore" in e["trecho"].casefold() for e in decisao["evidencias"])
