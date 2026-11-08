"""Avalia a interpretação da conversa com as mensagens de `dados/mensagens_conversa.json`.

Uso, a partir da raiz do repositório:

    python -m evals.interpretacao_conversa             # só regras, sem custo
    python -m evals.interpretacao_conversa --modelo    # regras + modelo (precisa da chave)
    python -m evals.interpretacao_conversa --jev       # regras + Jev (precisa de TYPESAFE_API_KEY)

O modelo é `MODELO_INTERPRETACAO` ou, sem ela, o padrão de `backend.agente.interpretacao`.
Nenhuma mensagem é de pessoa real.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from backend.agente.interpretacao import (
    CHAVE_JEV,
    MODELO_INTERPRETACAO_PADRAO,
    NAO_AGORA,
    DecisorJev,
    interpretar_com_jev,
    interpretar_com_modelo,
    interpretar_mensagem,
)
from backend.contratos.modelos import TipoResposta

ARQUIVO = Path(__file__).resolve().parent / "dados" / "mensagens_conversa.json"

_ROTULO = {
    TipoResposta.ACEITE: "seguir",
    TipoResposta.RECUSA: "nao_seguir",
    NAO_AGORA: "agora_nao",
    TipoResposta.OPT_OUT: "sair",
    None: "duvida",
}
PERIGOSOS = {
    ("nao_seguir", "seguir"),
    ("sair", "seguir"),
    ("agora_nao", "seguir"),
    ("duvida", "seguir"),
}
"""Erros que levariam alguém que não quer, ou ainda não decidiu, a receber o link."""


def mensagens() -> list[dict]:
    return json.loads(ARQUIVO.read_text(encoding="utf-8"))["mensagens"]


def rotulo(resultado: TipoResposta | str | None) -> str:
    return _ROTULO.get(resultado, str(resultado))


def avaliar(interpretar: Callable[[str], TipoResposta | str | None]) -> dict:
    casos = mensagens()
    erros = []
    por_rotulo: Counter[str] = Counter()
    acertos_por_rotulo: Counter[str] = Counter()
    inicio = time.perf_counter()
    for caso in casos:
        obtido = rotulo(interpretar(caso["texto"]))
        por_rotulo[caso["esperado"]] += 1
        if obtido == caso["esperado"]:
            acertos_por_rotulo[caso["esperado"]] += 1
        else:
            erros.append({"texto": caso["texto"], "esperado": caso["esperado"], "obtido": obtido})
    acertos = len(casos) - len(erros)
    return {
        "casos": len(casos),
        "acertos": acertos,
        "precisao": round(acertos / len(casos), 3),
        "por_rotulo": {r: f"{acertos_por_rotulo[r]}/{n}" for r, n in sorted(por_rotulo.items())},
        "perigosos": [e for e in erros if (e["esperado"], e["obtido"]) in PERIGOSOS],
        "erros": erros,
        "segundos": round(time.perf_counter() - inicio, 2),
    }


def _imprimir(titulo: str, resultado: dict) -> None:
    print(f"\n== {titulo}")
    print(f"acertos: {resultado['acertos']}/{resultado['casos']} ({resultado['precisao']:.0%})")
    print("por rótulo:", resultado["por_rotulo"])
    print(f"erros perigosos: {len(resultado['perigosos'])}")
    for erro in resultado["erros"]:
        print(f"  - esperado {erro['esperado']}, veio {erro['obtido']}: {erro['texto']}")
    for chave in ("custo_usd", "chamadas", "modelo"):
        if chave in resultado:
            print(f"{chave}: {resultado[chave]}")
    print(f"tempo: {resultado['segundos']}s")


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument(
        "--modelo", action="store_true", help="usa o modelo onde as regras não decidem"
    )
    argumentos.add_argument(
        "--jev", action="store_true", help="usa o Jev (TypeSafe) onde as regras não decidem"
    )
    opcoes = argumentos.parse_args()

    _imprimir("só regras", avaliar(interpretar_mensagem))
    if opcoes.jev:
        _rodar_jev()
    if not opcoes.modelo:
        return
    if not os.environ.get("FEATHERLESS_API_KEY", "").strip():
        print("\nSem FEATHERLESS_API_KEY no ambiente: a rodada com modelo não foi feita.")
        return
    from backend.modelos.cliente import ClienteFeatherless

    modelo = os.environ.get("MODELO_INTERPRETACAO", "").strip() or MODELO_INTERPRETACAO_PADRAO
    cliente = ClienteFeatherless(modelo=modelo, max_tokens=1000)
    resultado = avaliar(lambda texto: interpretar_com_modelo(texto, cliente))
    resultado["custo_usd"] = round(cliente.custo_total_usd, 6)
    resultado["modelo"] = modelo
    _imprimir(f"regras + modelo ({modelo})", resultado)


def _rodar_jev() -> None:
    if not os.environ.get(CHAVE_JEV, "").strip():
        print(f"\nSem {CHAVE_JEV} no ambiente: a rodada com o Jev não foi feita.")
        return
    decisor = DecisorJev()
    resultado = avaliar(lambda texto: interpretar_com_jev(texto, decisor))
    resultado["chamadas"] = decisor.chamadas
    resultado["modelo"] = f"{decisor.modelo} ({decisor.tokens_entrada} tokens de entrada)"
    _imprimir("regras + Jev", resultado)


if __name__ == "__main__":
    main()
