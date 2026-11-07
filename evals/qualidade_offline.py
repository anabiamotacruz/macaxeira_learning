"""Contratos mínimos e adaptadores falsos para avaliações offline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class RespostaInvalida(Exception):
    """Indica que a resposta simulada não atende ao contrato local."""


class ProvedorIndisponivel(Exception):
    """Indica falha recuperável do provedor simulado."""


@dataclass(frozen=True)
class PoliticaRetry:
    max_tentativas: int = 3


@dataclass
class ProvedorFalso:
    respostas: list[str | Exception]
    chamadas: int = 0

    def completar(self) -> str:
        self.chamadas += 1
        if not self.respostas:
            raise ProvedorIndisponivel("provedor simulado sem resposta")
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def obter_com_retry(
    provedor: ProvedorFalso,
    politica: PoliticaRetry | None = None,
) -> str:
    if politica is None:
        politica = PoliticaRetry()

    ultima_falha: Exception | None = None
    for _ in range(politica.max_tentativas):
        try:
            return provedor.completar()
        except (TimeoutError, ProvedorIndisponivel) as erro:
            ultima_falha = erro
    assert ultima_falha is not None
    raise ultima_falha


def validar_rubrica(rubrica: dict[str, Any]) -> None:
    criterios = rubrica.get("criterios")
    if not isinstance(criterios, list) or not 4 <= len(criterios) <= 8:
        raise RespostaInvalida("rubrica deve ter entre 4 e 8 criterios")

    for criterio in criterios:
        if not isinstance(criterio, dict):
            raise RespostaInvalida("criterio deve ser objeto")
        campos = ("id", "dimensao", "eliminatorio", "peso")
        if any(campo not in criterio for campo in campos):
            raise RespostaInvalida("criterio possui campo ausente")
        if not isinstance(criterio["peso"], int) or not 1 <= criterio["peso"] <= 5:
            raise RespostaInvalida("peso deve ser inteiro entre 1 e 5")


def validar_resposta_modelo(texto: str) -> dict[str, Any]:
    try:
        resposta = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise RespostaInvalida("JSON inválido") from erro
    if not isinstance(resposta, dict) or not isinstance(resposta.get("criterios"), list):
        raise RespostaInvalida("resposta deve conter criterios")
    for criterio in resposta["criterios"]:
        if not isinstance(criterio, dict) or not {
            "id",
            "atendido",
            "evidencia",
        }.issubset(criterio):
            raise RespostaInvalida("criterio da resposta possui campo ausente")
    return resposta


def validar_recomendacao(recomendacao: dict[str, Any]) -> None:
    evidencias = recomendacao.get("evidencias")
    if not isinstance(evidencias, list) or not evidencias:
        raise RespostaInvalida("recomendacao exige evidencia")


@dataclass
class DecisaoHumana:
    candidato_id: str
    resultado: str
    justificativa: str


def exigir_decisao_humana(
    candidato_id: str,
    registro: DecisaoHumana | None,
) -> DecisaoHumana:
    if registro is None or registro.candidato_id != candidato_id:
        raise RespostaInvalida("decisão humana registrada é obrigatória")
    return registro


@dataclass
class FluxoFalso:
    convites: list[str] = field(default_factory=list)

    def analisar_e_convidar(self, candidato: dict[str, Any]) -> None:
        if candidato.get("opt_out") is True or candidato.get("autorizacao_contato") is not True:
            return
        self.convites.append(candidato["id"])

