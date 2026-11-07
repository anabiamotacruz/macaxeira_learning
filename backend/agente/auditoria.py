"""Auditoria: registro de decisões. Nada aqui usa modelo de IA."""

import re
from typing import NamedTuple

from pydantic import ValidationError

from backend.agente.persistencia import Repositorio
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Decisao, Mandato

PREFIXO_HUMANO = "humano:"
_RESPONSAVEL_AGENTE = re.compile(
    r"agente:mandato:(?P<id>[^:]+):v(?P<versao>[1-9]\d*):assinante:(?P<assinante>\S.*)"
)


class DecisaoIncompleta(ErroContrato):
    """Decisão sem algum dos dados que permitem explicá-la depois."""


class MandatoCitado(NamedTuple):
    id: str
    versao: int
    assinante: str


def responsavel_do_mandato(mandato: Mandato) -> str:
    """Responsável de uma decisão do agente: identifica o mandato, a versão e quem assinou."""
    return f"agente:mandato:{mandato.id}:v{mandato.versao}:assinante:{mandato.assinante}"


def _mandato_citado(responsavel: str) -> MandatoCitado | None:
    achado = _RESPONSAVEL_AGENTE.fullmatch(responsavel)
    if achado is None:
        return None
    return MandatoCitado(achado["id"], int(achado["versao"]), achado["assinante"])


def _revalidar(decisao: Decisao) -> Decisao:
    """`model_copy` não valida. O erro cita só os campos, nunca os valores recebidos."""
    try:
        return Decisao.model_validate(decisao.model_dump())
    except ValidationError as erro:
        campos = sorted({str(detalhe["loc"][0]) for detalhe in erro.errors()})
        raise DecisaoIncompleta(f"campos recusados: {', '.join(campos)}") from None


def _campos_faltando(decisao: Decisao) -> list[str]:
    faltando = [
        campo
        for campo in ("vaga_id", "candidato_id", "motivo", "rastro_id")
        if not getattr(decisao, campo).strip()
    ]
    if not decisao.entrada or not all(valor.strip() for valor in decisao.entrada.values()):
        faltando.append("entrada")
    completas = all(
        evidencia.criterio.strip() and evidencia.trecho.strip() and evidencia.fonte.strip()
        for evidencia in decisao.evidencias
    )
    if not decisao.evidencias or not completas:
        faltando.append("evidencias")
    return faltando


class Auditoria:
    """Registra e explica decisões, sempre dentro da empresa informada."""

    def __init__(self, repositorio: Repositorio) -> None:
        self._repositorio = repositorio

    def registrar_decisao(self, decisao: Decisao) -> None:
        """Salva a decisão, ou levanta `DecisaoIncompleta` sem salvar nada."""
        valida = _revalidar(decisao)
        faltando = _campos_faltando(valida)
        if faltando:
            raise DecisaoIncompleta(f"decisão sem: {', '.join(faltando)}")
        self._conferir_responsavel(valida)
        self._repositorio.salvar_decisao(valida)

    def _conferir_responsavel(self, decisao: Decisao) -> None:
        responsavel = decisao.responsavel
        if responsavel.startswith(PREFIXO_HUMANO) and responsavel[len(PREFIXO_HUMANO) :].strip():
            return
        citado = _mandato_citado(responsavel)
        if citado is None:
            raise DecisaoIncompleta(
                "responsavel precisa identificar o mandato assinado ou a pessoa"
            )
        salvo = self._repositorio.carregar_mandato(decisao.empresa_id, decisao.vaga_id)
        if salvo is None:
            raise DecisaoIncompleta("decisão do agente sem mandato assinado para a vaga")
        mandato = Mandato.model_validate_json(salvo)
        if citado != MandatoCitado(mandato.id, mandato.versao, mandato.assinante):
            raise DecisaoIncompleta("decisão do agente não cita o mandato assinado em vigor")
