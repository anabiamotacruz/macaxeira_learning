"""Registros JSONL e cálculo determinístico de custo para avaliações."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from evals.qualidade_offline import RespostaInvalida


@dataclass(frozen=True)
class PrecosModelo:
    entrada_por_mil_tokens: Decimal
    saida_por_mil_tokens: Decimal

    def __post_init__(self) -> None:
        if self.entrada_por_mil_tokens < 0 or self.saida_por_mil_tokens < 0:
            raise ValueError("preços não podem ser negativos")


def validar_decisao_jsonl(registro: dict[str, Any]) -> None:
    campos = {
        "id",
        "candidato_id",
        "vaga_id",
        "quem_decidiu",
        "quando",
        "resultado",
        "justificativa",
        "evidencias",
        "regra_aplicada",
    }
    if not campos.issubset(registro) or not all(registro[campo] for campo in campos):
        raise RespostaInvalida("registro de decisão incompleto")
    if not isinstance(registro["evidencias"], list):
        raise RespostaInvalida("evidencias devem ser uma lista")


def validar_custo_jsonl(registro: dict[str, Any]) -> None:
    campos = {
        "id",
        "candidato_id",
        "execucao_id",
        "modelo",
        "tokens_entrada",
        "tokens_saida",
        "custo_estimado",
        "moeda",
        "etapa",
    }
    if not campos.issubset(registro):
        raise RespostaInvalida("registro de custo incompleto")
    if any(
        not isinstance(registro[campo], int) or registro[campo] < 0
        for campo in ("tokens_entrada", "tokens_saida")
    ):
        raise RespostaInvalida("tokens devem ser inteiros não negativos")
    if not isinstance(registro["custo_estimado"], (int, float, str)):
        raise RespostaInvalida("custo estimado deve ser numérico")


def para_jsonl(registros: Iterable[dict[str, Any]], validador: Any) -> str:
    linhas = []
    for registro in registros:
        validador(registro)
        linhas.append(json.dumps(registro, ensure_ascii=False, sort_keys=True))
    return "\n".join(linhas)


def de_jsonl(texto: str, validador: Any) -> list[dict[str, Any]]:
    registros = []
    for numero, linha in enumerate(texto.splitlines(), start=1):
        if not linha.strip():
            raise RespostaInvalida(f"linha JSONL vazia: {numero}")
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError as erro:
            raise RespostaInvalida(f"JSONL inválido na linha {numero}") from erro
        if not isinstance(registro, dict):
            raise RespostaInvalida(f"objeto esperado na linha {numero}")
        validador(registro)
        registros.append(registro)
    return registros


def calcular_custo(
    tokens_entrada: int,
    tokens_saida: int,
    precos: PrecosModelo,
) -> Decimal:
    if tokens_entrada < 0 or tokens_saida < 0:
        raise ValueError("tokens não podem ser negativos")
    return (
        Decimal(tokens_entrada) * precos.entrada_por_mil_tokens / Decimal(1000)
        + Decimal(tokens_saida) * precos.saida_por_mil_tokens / Decimal(1000)
    )


def somar_custo_por_candidato(
    registros: Iterable[dict[str, Any]],
) -> dict[str, Decimal]:
    totais: dict[str, Decimal] = {}
    for registro in registros:
        validar_custo_jsonl(registro)
        candidato_id = registro["candidato_id"]
        custo = Decimal(str(registro["custo_estimado"]))
        totais[candidato_id] = totais.get(candidato_id, Decimal("0")) + custo
    return totais
