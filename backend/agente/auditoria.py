"""Auditoria: rastro, registro e explicação de decisões. Nada aqui usa modelo de IA."""

import inspect
import logging
import os
import re
import time
import uuid
from collections import deque
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from threading import Lock
from typing import NamedTuple, Protocol

from pydantic import AwareDatetime, ValidationError

from backend.agente.persistencia import Repositorio
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Contrato, Decisao, Mandato, Texto

logger = logging.getLogger(__name__)

PREFIXO_HUMANO = "humano:"
SEM_CONTEXTO = "sem-contexto"
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

    def limpar(self) -> None:
        with self._trava:
            self._registros.clear()

    def listar(
        self,
        empresa_id: str,
        vaga_id: str,
        candidato_id: str | None,
        rastro_ids: Collection[str] = (),
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


class DestinoRastro(Protocol):
    def registrar(self, registro: RegistroRastro) -> None: ...


class RastroLangfuse:
    """Envia os metadados ao Langfuse, agrupados em um trace por `rastro_id`."""

    def __init__(self, cliente) -> None:
        self._cliente = cliente

    def registrar(self, registro: RegistroRastro) -> None:
        self._cliente.create_event(
            trace_context={"trace_id": self._cliente.create_trace_id(seed=registro.rastro_id)},
            name=registro.etapa,
            metadata=registro.model_dump(mode="json"),
            level="DEFAULT" if registro.sucesso else "ERROR",
            status_message=registro.erro_tipo,
        )


def destino_do_ambiente() -> RastroLangfuse | None:
    """Langfuse, se configurado e disponível. Caso contrário, o rastro fica só no local."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import Langfuse

        return RastroLangfuse(Langfuse())
    except Exception as erro:  # rastro nunca derruba o fluxo; a mensagem pode conter chave
        logger.warning("Langfuse indisponível, rastro só local: %s", type(erro).__name__)
        return None


_externo: DestinoRastro | None = None
_externo_resolvido = False
_trava_externo = Lock()


def configurar_destino_externo(destino: DestinoRastro | None) -> None:
    """Define o destino externo, sem consultar o ambiente. `None` deixa o rastro só no local."""
    global _externo, _externo_resolvido
    with _trava_externo:
        _externo = destino
        _externo_resolvido = True


def _destino_externo() -> DestinoRastro | None:
    global _externo, _externo_resolvido
    with _trava_externo:
        if not _externo_resolvido:
            _externo = destino_do_ambiente()
            _externo_resolvido = True
        return _externo


@dataclass(frozen=True)
class ContextoRastro:
    """A quem pertencem as chamadas em andamento. `rastro_id` vai para a `Decisao`."""

    execucao_id: str
    empresa_id: str
    vaga_id: str | None = None
    candidato_id: str | None = None

    @property
    def rastro_id(self) -> str:
        return f"{self.execucao_id}:{self.vaga_id or '-'}:{self.candidato_id or '-'}"


_contexto: ContextVar[ContextoRastro | None] = ContextVar("contexto_rastro", default=None)


def contexto_atual() -> ContextoRastro | None:
    return _contexto.get()


@contextmanager
def contexto_rastro(
    *,
    empresa_id: str | None = None,
    execucao_id: str | None = None,
    vaga_id: str | None = None,
    candidato_id: str | None = None,
) -> Iterator[ContextoRastro]:
    """Define execução, vaga e candidato das chamadas internas, herdando o que não for informado.

    Usa `contextvars`, porque `ClienteModelo.completar` não recebe esses dados. Chegam a
    tarefas `asyncio` e a `asyncio.to_thread`; em `ThreadPoolExecutor`, copie o contexto.
    """
    externo = _contexto.get()
    if externo is not None and empresa_id is not None and empresa_id != externo.empresa_id:
        raise ValueError("contexto de rastro não pode trocar de empresa")
    empresa = empresa_id if externo is None else externo.empresa_id
    if not empresa or not empresa.strip():
        raise ValueError("empresa_id é obrigatório no contexto de rastro")
    contexto = ContextoRastro(
        execucao_id=execucao_id or (externo.execucao_id if externo else uuid.uuid4().hex),
        empresa_id=empresa,
        vaga_id=vaga_id or (externo.vaga_id if externo else None),
        candidato_id=candidato_id or (externo.candidato_id if externo else None),
    )
    marca = _contexto.set(contexto)
    try:
        yield contexto
    finally:
        _contexto.reset(marca)


def _emitir(registro: RegistroRastro) -> None:
    """Grava no local e no destino externo. Falha de rastro é avisada e não sobe ao fluxo."""
    for destino in (RASTRO_LOCAL, _destino_externo()):
        if destino is None:
            continue
        try:
            destino.registrar(registro)
        except Exception as erro:  # a mensagem pode conter chave: só o tipo vai ao log
            logger.warning("falha ao gravar rastro: %s", type(erro).__name__)


@contextmanager
def _medicao(etapa: str, funcao: str) -> Iterator[None]:
    momento = datetime.now(UTC)
    inicio = time.perf_counter()
    erro_tipo = None
    try:
        yield
    except BaseException as erro:
        erro_tipo = type(erro).__name__
        raise
    finally:
        contexto = _contexto.get()
        _emitir(
            RegistroRastro(
                rastro_id=contexto.rastro_id if contexto else SEM_CONTEXTO,
                execucao_id=contexto.execucao_id if contexto else SEM_CONTEXTO,
                empresa_id=contexto.empresa_id if contexto else None,
                vaga_id=contexto.vaga_id if contexto else None,
                candidato_id=contexto.candidato_id if contexto else None,
                etapa=etapa,
                funcao=funcao,
                sucesso=erro_tipo is None,
                erro_tipo=erro_tipo,
                duracao_ms=(time.perf_counter() - inicio) * 1000,
                momento=momento,
            )
        )


def rastreado[**P, R](etapa: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Registra cada chamada da função e relança qualquer falha, sem alterá-la.

    Argumentos, retorno e mensagem de erro nunca são guardados: podem ter chave ou perfil.
    """
    if not etapa.strip():
        raise ValueError("etapa é obrigatória no rastro")

    def decorador(funcao: Callable[P, R]) -> Callable[P, R]:
        nome = f"{funcao.__module__}.{funcao.__qualname__}"
        if inspect.iscoroutinefunction(funcao):

            @wraps(funcao)
            async def assincrona(*args: P.args, **kwargs: P.kwargs):
                with _medicao(etapa, nome):
                    return await funcao(*args, **kwargs)

            return assincrona

        @wraps(funcao)
        def sincrona(*args: P.args, **kwargs: P.kwargs) -> R:
            with _medicao(etapa, nome):
                return funcao(*args, **kwargs)

        return sincrona

    return decorador


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
