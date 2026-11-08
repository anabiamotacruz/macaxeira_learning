"""O ConectorMCP entrega o pacote à Nara simulada e lê o resultado de volta.

Sobe o servidor MCP da Nara simulada em Streamable HTTP, só em 127.0.0.1.
Os dados são sintéticos e a simulação fica identificada.
"""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import uvicorn

from backend.agente.conector_mcp import ConectorMCP, DestinoMCP, EmpresaForaDoEscopo
from backend.contratos.modelos import PacoteContexto, ResultadoEntrevista
from backend.nara_simulada.mcp import configuracao_destino, criar_servidor
from backend.nara_simulada.servico import NaraSimulada

EMPRESA = "empresa-a"
OUTRA_EMPRESA = "empresa-b"
CHAVE = "empresa-a:v1:c1:entrega"


def _pacote(**campos: Any) -> PacoteContexto:
    dados: dict[str, Any] = {
        "empresa_id": EMPRESA,
        "vaga_id": "v1",
        "candidato_id": "c1",
        "motivo_por_criterio": {"mensageria": "Liderou a migração para Kafka."},
        "historico": [],
        "evidencias": [],
        "lacunas": [],
        "pontos_a_aprofundar": [],
        "ressalvas_revisor": [],
        "autorizacao": "contato autorizado, válido até 07/11/2027",
        "fonte": "simulada",
        "rastro_id": "execucao:v1:c1",
        "chave_idempotencia": CHAVE,
        "simulado": True,
    }
    dados.update(campos)
    return PacoteContexto(**dados)


def _porta_livre() -> int:
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        return int(soquete.getsockname()[1])


@contextmanager
def _servidor_nara(nara: NaraSimulada) -> Iterator[str]:
    """Sobe a Nara simulada numa thread e devolve a URL. Encerra no finally."""
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


def _conector(url: str) -> ConectorMCP:
    return ConectorMCP(DestinoMCP(**configuracao_destino(EMPRESA, url)))


def test_entrega_o_pacote_na_nara_simulada() -> None:
    nara = NaraSimulada(semente=7)
    pacote = _pacote()

    with _servidor_nara(nara) as url:
        assert _conector(url).entregar(pacote) is True

    assert nara.entregues(EMPRESA) == [pacote]
    assert pacote.simulado is True


def test_mesma_chave_nao_duplica_o_pacote() -> None:
    nara = NaraSimulada(semente=7)
    pacote = _pacote()

    with _servidor_nara(nara) as url:
        conector = _conector(url)
        assert conector.entregar(pacote) is True
        assert conector.entregar(pacote) is True

    entregues = nara.entregues(EMPRESA)
    assert len(entregues) == 1
    assert entregues[0].chave_idempotencia == CHAVE


def test_empresa_fora_do_escopo_nao_entra_na_nara() -> None:
    nara = NaraSimulada(semente=7)
    outra = _pacote(
        empresa_id=OUTRA_EMPRESA,
        chave_idempotencia="empresa-b:v1:c1:entrega",
    )

    with _servidor_nara(nara) as url:
        conector = _conector(url)
        with pytest.raises(EmpresaForaDoEscopo):
            conector.entregar(outra)
        with pytest.raises(EmpresaForaDoEscopo):
            conector.resultados(OUTRA_EMPRESA, "v1")

    assert nara.entregues(EMPRESA) == []
    assert nara.entregues(OUTRA_EMPRESA) == []


def test_resultados_da_entrevista_voltam_marcados_como_simulacao() -> None:
    nara = NaraSimulada(semente=7)
    pacote = _pacote()

    with _servidor_nara(nara) as url:
        conector = _conector(url)
        assert conector.entregar(pacote) is True
        resultados = conector.resultados(EMPRESA, "v1")

    esperado = nara.resultados(EMPRESA, "v1")
    assert resultados == esperado
    assert len(resultados) == 1
    assert isinstance(resultados[0], ResultadoEntrevista)
    assert resultados[0].candidato_id == pacote.candidato_id
    assert resultados[0].simulado is True
