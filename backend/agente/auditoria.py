"""Auditoria: registro e explicação de decisões. Nada aqui usa modelo de IA."""

import re
from collections import deque
from threading import Lock
from typing import NamedTuple

from pydantic import AwareDatetime, ValidationError

from backend.agente.persistencia import Repositorio
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Contrato, Decisao, Mandato, Texto

PREFIXO_HUMANO = "humano:"
_RESPONSAVEL_AGENTE = re.compile(
    r"agente:mandato:(?P<id>[^:]+):v(?P<versao>[1-9]\d*):assinante:(?P<assinante>\S.*)"
)


class DecisaoIncompleta(ErroContrato):
    """Decisão sem algum dos dados que permitem explicá-la depois."""


class ExplicacaoInexistente(ErroContrato):
    """Nada registrado para o candidato nesta empresa e vaga. Vale também para outra empresa."""


class RegistroRastro(Contrato):
    """Metadados de uma chamada, sem argumentos, retorno ou texto de erro: nada de chaves."""

    rastro_id: Texto
    execucao_id: Texto
    empresa_id: str | None = None
    vaga_id: str | None = None
    candidato_id: str | None = None
    etapa: Texto
    funcao: Texto
    sucesso: bool
    erro_tipo: str | None = None
    duracao_ms: float
    momento: AwareDatetime


class RastroLocal:
    """Rastro em memória, usado com ou sem Langfuse. Não sobrevive a um reinício."""

    def __init__(self, limite: int = 10_000) -> None:
        self._registros: deque[RegistroRastro] = deque(maxlen=limite)
        self._trava = Lock()

    def registrar(self, registro: RegistroRastro) -> None:
        with self._trava:
            self._registros.append(registro)

    def listar(
        self, empresa_id: str, vaga_id: str, candidato_id: str, rastro_ids: set[str]
    ) -> list[RegistroRastro]:
        """Registros do candidato nesta empresa e vaga, ou citados por uma decisão dele."""
        with self._trava:
            registros = list(self._registros)
        return [
            registro
            for registro in registros
            if registro.empresa_id == empresa_id
            and (
                registro.rastro_id in rastro_ids
                or (registro.vaga_id == vaga_id and registro.candidato_id == candidato_id)
            )
        ]


RASTRO_LOCAL = RastroLocal()
"""Rastro local do processo."""


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

    def __init__(self, repositorio: Repositorio, rastro: RastroLocal = RASTRO_LOCAL) -> None:
        self._repositorio = repositorio
        self._rastro = rastro

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

    def explicar_candidato(self, empresa_id: str, candidato_id: str, vaga_id: str) -> dict:
        """Liga decisões, mandato, eventos e rastro, ou levanta `ExplicacaoInexistente`.

        `mandato` é a assinatura mais recente. `mandatos_citados` diz sob qual versão e
        assinante cada decisão foi tomada, mesmo que a vaga tenha sido assinada de novo.
        """
        if not empresa_id.strip():
            raise ValueError("empresa_id é obrigatório")
        decisoes = [
            decisao
            for decisao in self._repositorio.listar_decisoes(empresa_id, vaga_id)
            if decisao.candidato_id == candidato_id
        ]
        rastro_ids = list(dict.fromkeys(decisao.rastro_id for decisao in decisoes))
        rastro = self._rastro.listar(empresa_id, vaga_id, candidato_id, set(rastro_ids))
        eventos = self._repositorio.listar_eventos(empresa_id, vaga_id)
        do_candidato = [evento for evento in eventos if evento.candidato_id == candidato_id]
        if not (decisoes or do_candidato or rastro):
            raise ExplicacaoInexistente("não há registro desse candidato nessa vaga")

        citados = dict.fromkeys(_mandato_citado(decisao.responsavel) for decisao in decisoes)
        mandato = self._repositorio.carregar_mandato(empresa_id, vaga_id)
        return {
            "empresa_id": empresa_id,
            "vaga_id": vaga_id,
            "candidato_id": candidato_id,
            "decisoes": [decisao.model_dump(mode="json") for decisao in decisoes],
            "mandato": (
                Mandato.model_validate_json(mandato).model_dump(mode="json") if mandato else None
            ),
            "mandatos_citados": [citado._asdict() for citado in citados if citado],
            "eventos": [
                evento.model_dump(mode="json")
                for evento in eventos
                if evento.candidato_id in (candidato_id, None)
            ],
            "rastro_ids": rastro_ids,
            "rastro": [registro.model_dump(mode="json") for registro in rastro],
        }
