"""A demonstração entrega à Nara por MCP: um conector por empresa, sem misturar empresas."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.auditoria import contexto_rastro
from backend.agente.conector_mcp import DestinoPorEmpresa, EmpresaForaDoEscopo
from backend.agente.montagem import NARA_MCP_URL, montar_servico
from backend.contratos.modelos import PacoteContexto
from backend.contratos.simulacoes import ClienteNaraSimulado
from backend.nara_simulada.mcp import criar_servidor
from backend.nara_simulada.servico import NaraSimulada
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-mcp"}


def _pacote(empresa_id: str) -> PacoteContexto:
    return PacoteContexto(
        empresa_id=empresa_id,
        vaga_id="v1",
        candidato_id="c1",
        motivo_por_criterio={"apis": "Construiu APIs em Python."},
        historico=[],
        evidencias=[],
        lacunas=[],
        pontos_a_aprofundar=[],
        ressalvas_revisor=[],
        autorizacao="contato autorizado",
        fonte="simulada",
        rastro_id="execucao:v1:c1",
        chave_idempotencia=f"{empresa_id}:v1:c1:entrega",
        simulado=True,
    )


class Criador:
    """Um destino simulado por empresa, para ver para onde cada chamada foi."""

    def __init__(self) -> None:
        self.destinos: dict[str, ClienteNaraSimulado] = {}

    def __call__(self, empresa_id: str) -> ClienteNaraSimulado:
        self.destinos[empresa_id] = ClienteNaraSimulado()
        return self.destinos[empresa_id]


def test_cada_empresa_entrega_no_proprio_destino():
    criador = Criador()
    destino = DestinoPorEmpresa(criador)

    destino.entregar(_pacote("empresa-a"))
    destino.entregar(_pacote("empresa-b"))

    assert set(criador.destinos) == {"empresa-a", "empresa-b"}
    assert [k for k, _ in criador.destinos["empresa-a"].entregues] == ["empresa-a"]


def test_o_conector_da_empresa_e_criado_uma_vez():
    criador = Criador()
    destino = DestinoPorEmpresa(criador)

    destino.entregar(_pacote("empresa-a"))
    primeiro = criador.destinos["empresa-a"]
    destino.resultados("empresa-a", "v1")

    assert criador.destinos["empresa-a"] is primeiro


def test_link_usa_a_empresa_do_contexto():
    criador = Criador()
    destino = DestinoPorEmpresa(criador)

    with contexto_rastro(empresa_id="empresa-a", vaga_id="v1"):
        link = destino.link_agendamento("v1", "c1")

    assert link
    assert set(criador.destinos) == {"empresa-a"}


def test_link_sem_empresa_no_contexto_e_recusado():
    destino = DestinoPorEmpresa(Criador())

    with pytest.raises(EmpresaForaDoEscopo):
        destino.link_agendamento("v1", "c1")


def _porta_livre() -> int:
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        return int(soquete.getsockname()[1])


@contextmanager
def _servidor_nara(nara: NaraSimulada) -> Iterator[str]:
    porta = _porta_livre()
    config = uvicorn.Config(
        criar_servidor(nara).streamable_http_app(),
        host="127.0.0.1",
        port=porta,
        log_level="critical",
        timeout_graceful_shutdown=1,
    )
    http = uvicorn.Server(config)
    thread = threading.Thread(target=http.run, daemon=True)
    thread.start()
    limite = time.monotonic() + 10
    while not http.started:
        if time.monotonic() > limite:
            raise RuntimeError("Nara simulada não subiu a tempo")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{porta}/mcp"
    finally:
        http.should_exit = True
        thread.join(timeout=10)


def test_demo_entrega_e_le_o_resultado_pela_nara_mcp(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    nara = NaraSimulada(semente=3)
    with _servidor_nara(nara) as url:
        servico = montar_servico(tmp_path / "a.db", ambiente={NARA_MCP_URL: url})
        cliente = TestClient(criar_app(servico))
        modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
        vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
        cliente.post(
            f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
        )
        convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
        convite = next(c for c in convites if c["estado"] == "aguardando")
        cliente.post(
            f"/convites/{convite['id']}/resposta",
            headers=SESSAO,
            json={"vaga_id": vaga, "tipo": "aceite", "chave_idempotencia": "a1"},
        )
        retornos = cliente.post(
            f"/vagas/{vaga}/retornos", headers=SESSAO, json={"chave_idempotencia": "r1"}
        ).json()["itens"]

    assert convite["link_destino"].startswith("https://nara.simulada.local/")
    [pacote] = nara.entregues("empresa-mcp")
    assert pacote.candidato_id == convite["candidato_id"]
    assert [r["candidato_id"] for r in retornos] == [convite["candidato_id"]]
