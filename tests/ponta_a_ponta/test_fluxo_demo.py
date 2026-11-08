"""A demonstração de ponta a ponta (T4.6), com a montagem real e o modelo simulado."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from backend.contratos.simulacoes import FonteSimulada
from tests.agente.apoio import PEDIDO_VAGA, candidatos_de_teste, pedido_mandato, servico_de_teste

JURADO_A = {"X-Empresa-Id": "jurado-a"}
JURADO_B = {"X-Empresa-Id": "jurado-b"}


@pytest.fixture(autouse=True)
def sem_chave(monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    monkeypatch.delenv("AGENTE_COM_MODELO", raising=False)


def _abrir_vaga(cliente: TestClient, sessao: dict, modelo: dict | None = None) -> str:
    if modelo is None:
        modelo = cliente.get("/vagas/modelos", headers=sessao).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=sessao, json=modelo).json()["vaga"]["id"]
    assinado = cliente.post(
        f"/vagas/{vaga}/mandato", headers=sessao, json=pedido_mandato(aceitar_declarada=True)
    )
    assert assinado.status_code == 201, assinado.text
    return vaga


def _convites(cliente: TestClient, sessao: dict, vaga: str) -> list[dict]:
    return cliente.get(f"/vagas/{vaga}/convites", headers=sessao).json()["itens"]


def _aceitar(cliente: TestClient, sessao: dict, vaga: str, convite: dict) -> None:
    resposta = cliente.post(
        f"/convites/{convite['id']}/resposta",
        headers=sessao,
        json={"vaga_id": vaga, "tipo": "aceite", "chave_idempotencia": f"a-{convite['id']}"},
    )
    assert resposta.status_code == 200, resposta.text


def test_da_base_baguncada_a_entrega_na_nara(tmp_path):
    cliente = TestClient(criar_app(montar_demo(tmp_path / "demo.db")))
    vaga = _abrir_vaga(cliente, JURADO_A)

    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=JURADO_A).json()["itens"]
    convites = _convites(cliente, JURADO_A, vaga)
    convidados = {c["candidato_id"] for c in convites}
    por_id = {i["candidato"]["id"]: i for i in itens}
    assert convites, "a base bagunçada ainda rende indicados"
    assert all(por_id[c]["decisao"] == "indicar" for c in convidados)
    assert not any(i["candidato"]["opt_out"] and i["candidato"]["id"] in convidados for i in itens)
    assert {i["decisao"] for i in itens} >= {"indicar", "descartar"}

    _aceitar(cliente, JURADO_A, vaga, next(c for c in convites if c["estado"] == "aguardando"))
    pacotes = cliente.get(f"/vagas/{vaga}/entrega", headers=JURADO_A).json()["saida"]["pacotes"]
    retornos = cliente.post(
        f"/vagas/{vaga}/retornos", headers=JURADO_A, json={"chave_idempotencia": "r1"}
    ).json()["itens"]

    assert len(pacotes) == 1
    assert pacotes[0]["motivo_por_criterio"]
    assert [r["candidato_id"] for r in retornos] == [pacotes[0]["candidato_id"]]
    assert all(c["simulado"] for c in convites)


def test_jurado_altera_vaga_e_plano_muda(tmp_path):
    cliente = TestClient(criar_app(montar_demo(tmp_path / "demo.db")))
    modelo = cliente.get("/vagas/modelos", headers=JURADO_A).json()["itens"][0]
    sem_presencial = {
        **modelo,
        "requisitos": [r for r in modelo["requisitos"] if r["id"] != "presencial_sp"],
    }
    assert len(sem_presencial["requisitos"]) == len(modelo["requisitos"]) - 1

    original = _abrir_vaga(cliente, JURADO_A, modelo)
    alterada = _abrir_vaga(cliente, JURADO_A, sem_presencial)

    def motivos(vaga: str) -> str:
        itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=JURADO_A).json()
        textos = []
        for item in itens["itens"]:
            decisao = cliente.get(
                f"/candidatos/{item['candidato']['id']}/decisao?vaga_id={vaga}", headers=JURADO_A
            ).json()["decisao"]
            textos.append(f"{decisao['regra']} {decisao['motivo']}")
        return " ".join(textos)

    assert "presencial_sp" in motivos(original)
    assert "presencial_sp" not in motivos(alterada)


def test_fonte_cai_e_execucao_continua(tmp_path):
    caida = FonteSimulada([])
    caida.falhar = True
    servico = servico_de_teste(
        tmp_path / "a.db", fontes=[caida, FonteSimulada(candidatos_de_teste())]
    )
    cliente = TestClient(criar_app(servico))
    sessao = {"X-Empresa-Id": "empresa-a"}
    vaga = cliente.post("/vagas", headers=sessao, json=PEDIDO_VAGA).json()["vaga"]["id"]

    assinado = cliente.post(f"/vagas/{vaga}/mandato", headers=sessao, json=pedido_mandato())

    assert assinado.status_code == 201
    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=sessao).json()["resumo"]
    assert resumo["estado"] != "pausada"
    assert resumo["indicados"] >= 1
    eventos = cliente.get(f"/vagas/{vaga}/eventos?limite=100", headers=sessao).json()["itens"]
    assert any("fonte" in e["mensagem"].casefold() for e in eventos)


def test_reinicio_nao_duplica_convite_nem_entrega(tmp_path):
    banco = tmp_path / "demo.db"
    antes = TestClient(criar_app(montar_demo(banco)))
    vaga = _abrir_vaga(antes, JURADO_A)
    convites = _convites(antes, JURADO_A, vaga)
    _aceitar(antes, JURADO_A, vaga, next(c for c in convites if c["estado"] == "aguardando"))

    reiniciado = montar_demo(banco)
    depois = TestClient(criar_app(reiniciado))
    reiniciado.entregar(JURADO_A["X-Empresa-Id"], vaga)

    assert [c["id"] for c in _convites(depois, JURADO_A, vaga)] == [c["id"] for c in convites]
    pacotes = depois.get(f"/vagas/{vaga}/entrega", headers=JURADO_A).json()["saida"]["pacotes"]
    assert len(pacotes) == 1
    nara_nova = reiniciado._dependencias.destino
    assert nara_nova.entregues(JURADO_A["X-Empresa-Id"]) == []


def test_dois_jurados_nao_se_afetam(tmp_path):
    cliente = TestClient(criar_app(montar_demo(tmp_path / "demo.db")))

    with ThreadPoolExecutor(max_workers=2) as executor:
        vaga_a, vaga_b = executor.map(lambda s: _abrir_vaga(cliente, s), [JURADO_A, JURADO_B])

    assert cliente.get(f"/vagas/{vaga_b}", headers=JURADO_A).status_code == 404
    assert cliente.get(f"/vagas/{vaga_a}", headers=JURADO_B).status_code == 404
    convites_b = _convites(cliente, JURADO_B, vaga_b)
    assert convites_b
    assert all("@jurado-b" in c["candidato_id"] for c in convites_b)

    assert cliente.post("/sessoes/reiniciar", headers=JURADO_A).status_code == 200

    assert cliente.get(f"/vagas/{vaga_b}", headers=JURADO_B).status_code == 200
    assert [c["id"] for c in _convites(cliente, JURADO_B, vaga_b)] == [c["id"] for c in convites_b]
