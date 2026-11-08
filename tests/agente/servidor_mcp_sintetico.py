"""Servidor MCP local e sintético, criado só para os testes do conector.

Fala Streamable HTTP de verdade, em `127.0.0.1`, para o teste passar pelo mesmo transporte
da integração real. Não é a Nara simulada da Frente 3 e não guarda dados reais.
"""

import asyncio
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn
from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent


class DestinoSintetico:
    """Ferramentas de um agente recrutador fictício, que descartam entrega repetida."""

    def __init__(self, link: str | None = "https://destino.simulado.local/agendar/v1/c1") -> None:
        self.link = link
        self.resultados_prontos: list[dict[str, Any]] = []
        self.chamadas: list[tuple[str, dict[str, Any]]] = []
        self.entregues: dict[str, dict[str, Any]] = {}

    def entregar(self, pacote: dict[str, Any], chave_idempotencia: str) -> dict[str, Any]:
        self.chamadas.append(
            ("entregar", {"pacote": pacote, "chave_idempotencia": chave_idempotencia})
        )
        self.entregues.setdefault(chave_idempotencia, pacote)
        return {"entregue": True, "chave_idempotencia": chave_idempotencia}

    async def entregar_e_perder_a_resposta(
        self, pacote: dict[str, Any], chave_idempotencia: str
    ) -> dict[str, Any]:
        """Guarda o pacote e demora a responder na primeira vez, como uma resposta perdida."""
        primeira = chave_idempotencia not in self.entregues
        resposta = self.entregar(pacote, chave_idempotencia)
        if primeira:
            await asyncio.sleep(30)
        return resposta

    def agendar(self, empresa_id: str, vaga_id: str, candidato_id: str) -> dict[str, Any]:
        self.chamadas.append(
            (
                "agendar",
                {"empresa_id": empresa_id, "vaga_id": vaga_id, "candidato_id": candidato_id},
            )
        )
        return {"link": self.link}

    def resultados(self, empresa_id: str, vaga_id: str) -> dict[str, Any]:
        self.chamadas.append(("resultados", {"empresa_id": empresa_id, "vaga_id": vaga_id}))
        return {"resultados": self.resultados_prontos}


def resposta_fixa(
    estruturado: Any = None, texto: str = "", erro: bool = False
) -> Callable[..., CallToolResult]:
    """Ferramenta que ignora os argumentos e devolve exatamente o resultado pedido."""

    def responder() -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=texto)],
            structured_content=estruturado,
            is_error=erro,
        )

    return responder


def porta_livre() -> int:
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        return soquete.getsockname()[1]


def url_da_porta(porta: int) -> str:
    return f"http://127.0.0.1:{porta}/mcp"


@contextmanager
def servidor_mcp(
    ferramentas: dict[str, Callable[..., Any]], porta: int | None = None
) -> Iterator[str]:
    """Sobe o servidor numa thread e devolve a URL. As ferramentas têm os nomes das chaves."""
    servidor = MCPServer("destino-sintetico")
    for nome, ferramenta in ferramentas.items():
        servidor.add_tool(ferramenta, name=nome)
    porta_usada = porta or porta_livre()
    config = uvicorn.Config(
        servidor.streamable_http_app(),
        host="127.0.0.1",
        port=porta_usada,
        log_level="critical",
        timeout_graceful_shutdown=1,
    )
    uvicorn_servidor = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_servidor.run, daemon=True)
    thread.start()
    limite = time.monotonic() + 10
    while not uvicorn_servidor.started:
        if time.monotonic() > limite:
            raise RuntimeError("servidor sintético não subiu a tempo")
        time.sleep(0.01)
    try:
        yield url_da_porta(porta_usada)
    finally:
        uvicorn_servidor.should_exit = True
        thread.join(timeout=10)
