"""Gera `docs/contratos/perfil_coletado.schema.json` a partir do contrato.

Uso: `uv run python -m backend.contratos.gerar_esquema_perfil`
"""

import json
from pathlib import Path

from backend.contratos.modelos import PerfilColetado

PASTA = Path(__file__).resolve().parents[2] / "docs" / "contratos"
ARQUIVO_ESQUEMA = PASTA / "perfil_coletado.schema.json"
ARQUIVO_EXEMPLO = PASTA / "perfil_coletado.exemplo.json"
"""O exemplo é escrito à mão, com dados sintéticos, e os testes o validam contra o contrato."""


def texto_esquema() -> str:
    return json.dumps(PerfilColetado.model_json_schema(), ensure_ascii=False, indent=2) + "\n"


def gerar(destino: Path = ARQUIVO_ESQUEMA) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto_esquema(), encoding="utf-8")


if __name__ == "__main__":
    gerar()
