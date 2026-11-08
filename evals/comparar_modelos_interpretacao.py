"""Compara modelos de decisão e de linguagem da Featherless na interpretação da conversa.

Cada candidato só lê o que as regras deixam como dúvida, como no produto. Mede acertos, erros
perigosos (quem não quer recebe o link), tempo por chamada e custo estimado. A chave vem só de
`FEATHERLESS_API_KEY` no ambiente e nunca é impressa.

    python -m evals.comparar_modelos_interpretacao
"""

from __future__ import annotations

import os
import time

from backend.agente.interpretacao import (
    URL_CLASSIFICADOR_FEATHERLESS,
    DecisorJev,
    interpretar_com_jev,
    interpretar_com_modelo,
    interpretar_mensagem,
)
from backend.contato.conversa import contem_instrucao, pede_saida
from evals.interpretacao_conversa import avaliar, mensagens

CLASSIFICADORES = {
    "featherless-ai/Qwen3.5-4B-classifier": 0.03,
    "featherless-ai/gemma-4-12B-it-classifier": 0.24,
    "featherless-ai/Qwen3.6-35B-A3B-classifier": 0.28,
    "featherless-ai/Qwen3.8-27B-classifier": 0.30,
}
"""Preço de entrada em US$ por milhão de tokens; a saída é grátis (não geram texto)."""

MODELOS_DE_LINGUAGEM = {
    "Qwen/Qwen2.5-14B-Instruct": (0.10775, 0.28),
    "zai-org/GLM-4.7-Flash": (0.0653, 0.4),
    "zai-org/GLM-5.2": (1.4, 4.4),
}
"""Entrada e saída em US$ por milhão de tokens, de `GET /v1/models` em 8/11/2026."""


def _indecisas() -> int:
    """Quantas mensagens as regras deixam para o modelo: é o que cada candidato lê."""
    return sum(
        1
        for m in mensagens()
        if m["texto"].strip()
        and interpretar_mensagem(m["texto"]) is None
        and not contem_instrucao(m["texto"])
        and not pede_saida(m["texto"])
    )


def _linha(nome: str, tipo: str, resultado: dict, chamadas: int, custo: float) -> str:
    tempo = resultado["segundos"] / chamadas if chamadas else 0.0
    return (
        f"| {nome} | {tipo} | {resultado['acertos']}/{resultado['casos']} "
        f"({resultado['precisao']:.0%}) | {len(resultado['perigosos'])} | {chamadas} "
        f"| {tempo * 1000:.0f} ms | US$ {custo:.6f} |"
    )


def main() -> None:
    chave = os.environ.get("FEATHERLESS_API_KEY", "").strip()
    if not chave:
        print("Sem FEATHERLESS_API_KEY no ambiente: nada foi comparado.")
        return
    from backend.modelos.cliente import ClienteFeatherless

    linhas = [
        "| modelo | tipo | acertos | perigosos | chamadas | tempo/chamada | custo |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    erros_por_modelo: dict[str, list[dict]] = {}
    for modelo, preco in CLASSIFICADORES.items():
        decisor = DecisorJev(chave, url=URL_CLASSIFICADOR_FEATHERLESS, modelo=modelo)
        try:
            resultado = avaliar(lambda texto, d=decisor: interpretar_com_jev(texto, d))
        except Exception as erro:  # um candidato fora do ar não derruba a comparação
            linhas.append(f"| {modelo} | classificador | falhou: {type(erro).__name__} | | | | |")
            continue
        custo = decisor.tokens_entrada * preco / 1_000_000
        linhas.append(_linha(modelo, "classificador", resultado, decisor.chamadas, custo))
        erros_por_modelo[modelo] = resultado["erros"]
    for modelo in MODELOS_DE_LINGUAGEM:
        cliente = ClienteFeatherless(modelo=modelo, max_tokens=1000)
        inicio = time.perf_counter()
        try:
            resultado = avaliar(lambda texto, c=cliente: interpretar_com_modelo(texto, c))
        except Exception as erro:
            linhas.append(f"| {modelo} | linguagem | falhou: {type(erro).__name__} | | | | |")
            continue
        resultado["segundos"] = round(time.perf_counter() - inicio, 2)
        chamadas = _indecisas()
        linhas.append(
            _linha(modelo, "linguagem", resultado, chamadas, float(cliente.custo_total_usd))
        )
        erros_por_modelo[modelo] = resultado["erros"]
    print("\n".join(linhas))
    for modelo, erros in erros_por_modelo.items():
        if erros:
            print(f"\n{modelo}:")
            for erro in erros:
                print(f"  - esperado {erro['esperado']}, veio {erro['obtido']}: {erro['texto']}")


if __name__ == "__main__":
    main()
