"""Gera `docs/api/openapi.json` a partir do código da API.

Uso: `uv run python -m backend.agente.gerar_openapi`
"""

import json
from pathlib import Path

from backend.agente.api import app

ARQUIVO_OPENAPI = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def texto_openapi() -> str:
    """Devolve o OpenAPI da API como texto estável, na ordem em que as rotas são declaradas."""
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"


def gerar(destino: Path = ARQUIVO_OPENAPI) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto_openapi(), encoding="utf-8")


if __name__ == "__main__":
    gerar()
