"""Trilha de auditoria das chamadas de modelo da rodada de avaliação.

`ClienteAuditado` embrulha qualquer implementação de `ClienteModelo` e registra
uma linha por chamada: caso, etapa, modelo, versão do prompt, consumo estimado,
tempo, resultado e o que o modelo propôs.

A trilha guarda o hash do prompt, nunca o texto enviado, e descreve a falha só
pelo tipo da exceção, porque a mensagem de um provedor real pode repetir a chave
ou o texto da pessoa. Critério citado é nome de requisito ou competência da vaga,
limitado em tamanho; nome, contato e currículo nunca entram.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, NonNegativeFloat, NonNegativeInt

from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Contrato
from backend.fontes.consultas import _normalizar

CARACTERES_POR_TOKEN = 3
"""Estimativa conservadora. A rodada com modelo de prova não tem token de verdade."""

TAMANHO_MAXIMO_DE_CRITERIO = 120

_INSTRUCAO = re.compile(
    r"\b(ignore|desconsidere|revele|obedeca|instrucoes)\b|nota maxima|previous instructions"
)


class ResultadoChamada(StrEnum):
    OK = "ok"
    RESPOSTA_INVALIDA = "resposta_invalida"
    INDISPONIVEL = "indisponivel"
    ERRO_INESPERADO = "erro_inesperado"


class RegistroChamada(Contrato):
    """Uma chamada de modelo, do ponto de vista de quem audita."""

    id_caso: str
    etapa: str
    modelo: str
    versao_prompt: str
    resultado: ResultadoChamada
    tokens_entrada_estimados: NonNegativeInt
    tokens_saida_estimados: NonNegativeInt
    tempo_s: NonNegativeFloat
    instrucao_no_pedido: bool
    criterios_citados: list[str] = []
    evidencias_propostas: NonNegativeInt = 0
    notas_propostas: NonNegativeInt = 0
    problema: str | None = None
    simulado: bool = True


@dataclass
class ConsumoEtapa:
    chamadas: int = 0
    falhas: int = 0
    tokens_entrada_estimados: int = 0
    tokens_saida_estimados: int = 0
    tempo_s: float = 0.0


def versao_prompt(texto: str) -> str:
    """Identifica o prompt sem guardá-lo, para comparar rodadas de versões diferentes."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def _tokens(texto: str) -> int:
    return len(texto) // CARACTERES_POR_TOKEN


def _criterio_seguro(valor: object) -> str:
    return str(valor)[:TAMANHO_MAXIMO_DE_CRITERIO]


def _descrever_saida(resposta: BaseModel) -> tuple[list[str], int, int]:
    """Critérios citados e quantas evidências e notas o modelo propôs."""
    evidencias = list(getattr(resposta, "evidencias", []) or [])
    ressalvas = list(getattr(resposta, "ressalvas", []) or [])
    notas = dict(getattr(resposta, "notas", {}) or {})
    citados = {
        _criterio_seguro(getattr(item, "criterio", ""))
        for item in (*evidencias, *ressalvas)
        if getattr(item, "criterio", "")
    }
    citados |= {_criterio_seguro(criterio) for criterio in notas}
    return sorted(citados), len(evidencias), len(notas)


class ClienteAuditado:
    """Implementa `ClienteModelo` e grava a trilha. Toda chamada precisa de um caso aberto."""

    def __init__(
        self,
        cliente: ClienteModelo,
        *,
        nome_modelo: str,
        simulado: bool = True,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cliente = cliente
        self.nome_modelo = nome_modelo
        self.simulado = simulado
        self._relogio = relogio
        self._id_caso: str | None = None
        self.trilha: list[RegistroChamada] = []

    @contextmanager
    def no_caso(self, id_caso: str) -> Iterator[None]:
        """Abre o caso ao qual as chamadas seguintes pertencem."""
        anterior = self._id_caso
        self._id_caso = id_caso
        try:
            yield
        finally:
            self._id_caso = anterior

    def completar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> BaseModel:
        if self._id_caso is None:
            raise RuntimeError("abra um caso com `no_caso` antes de chamar o modelo")
        inicio = self._relogio()
        base: dict[str, Any] = {
            "id_caso": self._id_caso,
            "etapa": etapa,
            "modelo": self.nome_modelo,
            "versao_prompt": versao_prompt(sistema),
            "tokens_entrada_estimados": _tokens(sistema) + _tokens(usuario),
            "instrucao_no_pedido": bool(_INSTRUCAO.search(_normalizar(usuario))),
            "simulado": self.simulado,
        }
        try:
            resposta = self._cliente.completar(
                sistema=sistema, usuario=usuario, esquema=esquema, etapa=etapa
            )
        except Exception as erro:
            self.trilha.append(
                RegistroChamada(
                    **base,
                    resultado=_classificar(erro),
                    tokens_saida_estimados=0,
                    tempo_s=self._relogio() - inicio,
                    problema=type(erro).__name__,
                )
            )
            raise
        citados, evidencias, notas = _descrever_saida(resposta)
        self.trilha.append(
            RegistroChamada(
                **base,
                resultado=ResultadoChamada.OK,
                tokens_saida_estimados=_tokens(resposta.model_dump_json()),
                tempo_s=self._relogio() - inicio,
                criterios_citados=citados,
                evidencias_propostas=evidencias,
                notas_propostas=notas,
            )
        )
        return resposta

    def consumo_por_etapa(self) -> dict[str, ConsumoEtapa]:
        consumo: dict[str, ConsumoEtapa] = {}
        for registro in self.trilha:
            etapa = consumo.setdefault(registro.etapa, ConsumoEtapa())
            etapa.chamadas += 1
            etapa.falhas += registro.resultado != ResultadoChamada.OK
            etapa.tokens_entrada_estimados += registro.tokens_entrada_estimados
            etapa.tokens_saida_estimados += registro.tokens_saida_estimados
            etapa.tempo_s += registro.tempo_s
        return consumo


def _classificar(erro: Exception) -> ResultadoChamada:
    if isinstance(erro, RespostaInvalida):
        return ResultadoChamada.RESPOSTA_INVALIDA
    if isinstance(erro, ModeloIndisponivel):
        return ResultadoChamada.INDISPONIVEL
    return ResultadoChamada.ERRO_INESPERADO


def escrever_trilha(caminho: Path | str, registros: Iterable[RegistroChamada]) -> None:
    """Grava uma linha JSON por chamada, para a trilha ser lida aos poucos."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as arquivo:
        for registro in registros:
            arquivo.write(registro.model_dump_json() + "\n")


def ler_trilha(caminho: Path | str) -> list[RegistroChamada]:
    linhas = Path(caminho).read_text(encoding="utf-8").splitlines()
    return [RegistroChamada.model_validate(json.loads(linha)) for linha in linhas if linha.strip()]
