"""Nara simulada exposta como servidor MCP local (#42; spec 002, história 8; FR-C030).

Oferece três ferramentas no formato combinado com o `ConectorMCP` da Frente 1 (T1.12):

- `nara_link_agendamento(empresa_id, vaga_id, candidato_id)` devolve `link`;
- `nara_entregar_pacote(pacote, chave_idempotencia)` devolve `entregue` e a mesma chave;
- `nara_resultados(empresa_id, vaga_id)` devolve `resultados`.

Toda resposta leva `simulado: true`. Mensagens de erro são genéricas e nunca repetem o
conteúdo recebido. Para rodar: `uv run python -m backend.nara_simulada.mcp --porta 8765`.
"""

import argparse
import logging
from typing import Any

from mcp.server import MCPServer
from pydantic import ValidationError

from backend.contratos.modelos import PacoteContexto
from backend.nara_simulada.servico import NaraSimulada

logger = logging.getLogger(__name__)

NOME_SERVIDOR = "nara-simulada"
FERRAMENTA_AGENDA = "nara_link_agendamento"
FERRAMENTA_ENTREGA = "nara_entregar_pacote"
FERRAMENTA_RESULTADOS = "nara_resultados"
PORTA_PADRAO = 8765


def _exigir_empresa(empresa_id: str) -> None:
    if not empresa_id or not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório")


def criar_servidor(nara: NaraSimulada) -> MCPServer:
    """Servidor MCP com as ferramentas da Nara simulada, ligadas à instância dada."""
    servidor = MCPServer(
        NOME_SERVIDOR,
        instructions="Nara simulada para a demo: nada aqui é a Nara real.",
    )

    def link_agendamento(empresa_id: str, vaga_id: str, candidato_id: str) -> dict[str, Any]:
        """Link de agendamento simulado da Nara para o candidato na vaga."""
        _exigir_empresa(empresa_id)
        return {"link": nara.link_agendamento(vaga_id, candidato_id), "simulado": True}

    def entregar_pacote(pacote: dict[str, Any], chave_idempotencia: str) -> dict[str, Any]:
        """Recebe o pacote de contexto na Nara simulada. Chave repetida não duplica."""
        try:
            contexto = PacoteContexto.model_validate(pacote)
        except ValidationError:
            raise ValueError("pacote fora do formato") from None
        if contexto.chave_idempotencia != chave_idempotencia:
            raise ValueError("a chave não corresponde ao pacote")
        if not contexto.simulado:
            raise ValueError("a Nara simulada só recebe pacotes simulados")
        entregue = nara.entregar(contexto)
        logger.info("entrega na Nara simulada: chave=%s entregue=%s", chave_idempotencia, entregue)
        return {"entregue": entregue, "chave_idempotencia": chave_idempotencia, "simulado": True}

    def resultados(empresa_id: str, vaga_id: str) -> dict[str, Any]:
        """Resultados simulados e reproduzíveis das entrevistas da vaga."""
        _exigir_empresa(empresa_id)
        lista = nara.resultados(empresa_id, vaga_id)
        return {"resultados": [r.model_dump(mode="json") for r in lista], "simulado": True}

    servidor.add_tool(link_agendamento, name=FERRAMENTA_AGENDA)
    servidor.add_tool(entregar_pacote, name=FERRAMENTA_ENTREGA)
    servidor.add_tool(resultados, name=FERRAMENTA_RESULTADOS)
    return servidor


def configuracao_destino(empresa_id: str, url: str) -> dict[str, Any]:
    """Campos do `DestinoMCP` da Frente 1 para usar este servidor."""
    return {
        "nome": "nara",
        "empresa_id": empresa_id,
        "url": url,
        "ferramenta_entrega": FERRAMENTA_ENTREGA,
        "ferramenta_agenda": FERRAMENTA_AGENDA,
        "ferramenta_resultados": FERRAMENTA_RESULTADOS,
        "simulado": True,
    }


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Nara simulada como servidor MCP local.")
    parser.add_argument("--porta", type=int, default=PORTA_PADRAO)
    parser.add_argument("--semente", type=int, default=0)
    argumentos = parser.parse_args()
    servidor = criar_servidor(NaraSimulada(semente=argumentos.semente))
    print(f"Nara simulada em http://127.0.0.1:{argumentos.porta}/mcp")
    uvicorn.run(servidor.streamable_http_app(), host="127.0.0.1", port=argumentos.porta)


if __name__ == "__main__":
    main()
