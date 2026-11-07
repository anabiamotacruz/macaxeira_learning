"""API do agente recrutador: PROPOSTA enquanto o acordo das frentes não sair.

Rotas, campos e erros ainda podem mudar. Toda resposta é um exemplo fixo e sintético de
`exemplos_api.py`: nada é gravado, e este módulo não chama o fluxo. O agente não agenda,
não entrevista e não decide contratações; o destino da pessoa é decidido pelo RH.

`empresa_id` vem da sessão, simulada por enquanto pelo cabeçalho `X-Empresa-Id`.

Depois de mudar este arquivo, gere o contrato com:
`uv run python -m backend.agente.gerar_openapi`
"""

import logging
import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import APIKeyHeader
from pydantic import AwareDatetime, BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.agente import exemplos_api as exemplos
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import (
    Candidato,
    Competencia,
    Contrato,
    Decisao,
    DestinoPessoa,
    EventoFluxo,
    Mandato,
    Politica,
    Requisito,
    ResumoExecucao,
    SaidaPersonalizada,
    TaxaMedida,
    Texto,
    TipoDecisao,
    TipoErro,
    Vaga,
)

logger = logging.getLogger(__name__)

LIMITE_PADRAO = 20
LIMITE_MAXIMO = 100
"""Maior `limite` aceito nas listas."""

_MAX_ERROS_NA_MENSAGEM = 5
_EMPRESA_VALIDA = re.compile(r"[\w-]{1,64}")

DESCRICAO = """\
**Proposta**, válida enquanto o acordo das frentes não sair: rotas, campos e erros podem mudar.

**Exemplos fixos e sintéticos.** Nada é gravado e nenhuma lógica roda. Toda resposta traz
`simulado: true`, e as de sucesso trazem também `exemplo_fixo: true`. Os números são
ilustrativos e não medem o agente.

**Limites do agente.** O agente não agenda, não entrevista e não decide contratações.
O destino da pessoa é registrado por alguém do RH.

**Sessão.** `empresa_id` vem da sessão, simulada pelo cabeçalho `X-Empresa-Id`, nunca do corpo.
Os recursos de exemplo pertencem a `empresa-exemplo`; para outra empresa, eles não existem.

**Erros.** `{"erro": {"codigo": "...", "mensagem": "..."}, "simulado": true}`.

**Gerar este arquivo.** `uv run python -m backend.agente.gerar_openapi`
"""


class EstadoVaga(StrEnum):
    """Estados da vaga expostos ao painel. Proposta: espelha o `EstadoFluxo` de hoje."""

    RASCUNHO = "rascunho"
    AGUARDANDO_MANDATO = "aguardando_mandato"
    BUSCANDO = "buscando"
    ANALISANDO = "analisando"
    REVISANDO = "revisando"
    DECIDINDO = "decidindo"
    META_EM_RISCO = "meta_em_risco"
    CONVIDANDO = "convidando"
    ENTREGANDO = "entregando"
    PAUSADA = "pausada"
    CONCLUIDA = "concluida"


class Erro(Contrato):
    codigo: Texto
    mensagem: Texto


class RespostaErro(Contrato):
    erro: Erro
    simulado: Literal[True] = True


class RespostaSimulada(Contrato):
    """Base das respostas de sucesso: identifica a simulação e o exemplo fixo."""

    simulado: Literal[True] = True
    exemplo_fixo: Literal[True] = True


class PedidoVaga(Contrato):
    """Dados da vaga. `id` e `empresa_id` não vêm do cliente."""

    titulo: Texto
    descricao: Texto
    requisitos: list[Requisito]
    competencias: list[Competencia]
    meta_candidatos: Annotated[int, Field(ge=1)]
    prazo_dias: Annotated[int, Field(ge=1)]
    max_tentativas_contato: Annotated[int, Field(ge=0)]


class PedidoMandato(Contrato):
    """O que a pessoa assina. Identificador, versão, hash e horário são do servidor."""

    assinante: Texto
    limite_gasto_usd: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
    politica: Politica
    valido_ate: AwareDatetime | None = None


class PedidoControle(Contrato):
    """Parar ou retomar a vaga. Repetir com a mesma chave não muda o resultado."""

    responsavel: Annotated[Texto, Field(description="Pessoa que pediu a ação.")]
    motivo: str = ""
    chave_idempotencia: Texto


class PedidoReversao(Contrato):
    vaga_id: Texto
    motivo: Texto
    responsavel: Annotated[Texto, Field(description="Pessoa que reverteu a decisão.")]
    chave_idempotencia: Texto


class PedidoDestino(Contrato):
    vaga_id: Texto
    destino: DestinoPessoa
    responsavel: Annotated[
        Texto,
        Field(description="Pessoa do RH que decidiu o destino. O agente não decide o destino."),
    ]
    chave_idempotencia: Texto


class RespostaVaga(RespostaSimulada):
    vaga: Vaga
    estado: EstadoVaga
    mandato: Mandato | None


class RespostaMandato(RespostaSimulada):
    mandato: Mandato
    estado: EstadoVaga


class ItemCandidato(Contrato):
    candidato: Candidato
    decisao: TipoDecisao | None
    destino: DestinoPessoa | None


class RespostaPaginada(RespostaSimulada):
    pagina: int
    limite: int
    total: int


class RespostaCandidatos(RespostaPaginada):
    itens: list[ItemCandidato]


class RespostaEventos(RespostaPaginada):
    itens: list[EventoFluxo]


class RespostaEntrega(RespostaSimulada):
    saida: SaidaPersonalizada


class RespostaResumo(RespostaSimulada):
    resumo: ResumoExecucao


class RespostaMetricas(RespostaSimulada):
    """Taxas ilustrativas. Sem casos, a taxa aparece como não medida: `valor` nulo."""

    vaga_id: Texto
    sem_revisao: TaxaMedida
    erros_por_tipo: dict[TipoErro, TaxaMedida]


class RespostaDecisao(RespostaSimulada):
    decisao: Decisao


class RespostaControle(RespostaSimulada):
    vaga_id: Texto
    estado: EstadoVaga
    estado_anterior: EstadoVaga


class RespostaReversao(RespostaSimulada):
    """A reversão acrescenta uma decisão: a original nunca é apagada."""

    decisao_original: Decisao
    decisao_nova: Decisao


class RespostaDestino(RespostaSimulada):
    vaga_id: Texto
    candidato_id: Texto
    destino: DestinoPessoa
    responsavel: Texto


class RespostaReinicio(RespostaSimulada):
    empresa_id: Texto
    dados_recarregados: Annotated[
        bool, Field(description="Falso nos exemplos fixos: nenhum dado é recarregado.")
    ]
    mensagem: Texto


class ErroApi(ErroContrato):
    """Erro previsível que vira resposta no formato padrão."""

    def __init__(self, status: int, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem


def _corpo_erro(codigo: str, mensagem: str) -> dict[str, Any]:
    return RespostaErro(erro=Erro(codigo=codigo, mensagem=mensagem)).model_dump(mode="json")


_EXEMPLOS_DE_ERRO = {
    401: ("sessao_ausente", "Sessão ausente ou inválida."),
    404: ("nao_encontrado", "Recurso não encontrado nesta empresa."),
    422: ("dados_invalidos", "Dados inválidos: body.limite_gasto_usd (greater_than)."),
    500: ("erro_interno", "Erro interno."),
}
_DESCRICOES_DE_ERRO = {
    401: "Sessão ausente ou inválida",
    404: "Não existe nesta empresa",
    422: "Dados inválidos",
    500: "Erro interno, sem detalhes",
}
_ERROS_DE_ROTA_COM_RECURSO = (401, 404, 422)


def _respostas(
    exemplo: BaseModel, status: int = 200, erros: Sequence[int] = _ERROS_DE_ROTA_COM_RECURSO
) -> dict[int | str, dict[str, Any]]:
    """Documenta o exemplo de sucesso e os erros de uma rota no OpenAPI."""
    respostas: dict[int | str, dict[str, Any]] = {
        status: {"content": {"application/json": {"example": exemplo.model_dump(mode="json")}}}
    }
    for codigo in (*erros, 500):
        respostas[codigo] = {
            "model": RespostaErro,
            "description": _DESCRICOES_DE_ERRO[codigo],
            "content": {"application/json": {"example": _corpo_erro(*_EXEMPLOS_DE_ERRO[codigo])}},
        }
    return respostas


def _exemplo_de_pedido(valor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {"exemplo": {"summary": "Exemplo fictício", "value": valor}}


_cabecalho_sessao = APIKeyHeader(
    name="X-Empresa-Id",
    scheme_name="SessaoSimulada",
    description="Sessão simulada: identifica a empresa até a autenticação real chegar.",
    auto_error=False,
)


def empresa_da_sessao(valor: Annotated[str | None, Depends(_cabecalho_sessao)]) -> str:
    """Devolve a empresa da sessão. É a única origem de `empresa_id` na API."""
    empresa = (valor or "").strip()
    if not _EMPRESA_VALIDA.fullmatch(empresa):
        raise ErroApi(401, "sessao_ausente", "Sessão ausente ou inválida.")
    return empresa


EmpresaDaSessao = Annotated[str, Depends(empresa_da_sessao)]
Pagina = Annotated[int, Query(ge=1)]
Limite = Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)]


def _exigir_vaga(vaga_id: str, empresa: str) -> None:
    if empresa != exemplos.EMPRESA_EXEMPLO or vaga_id != exemplos.VAGA_EXEMPLO:
        raise ErroApi(404, "vaga_nao_encontrada", "Vaga não encontrada nesta empresa.")


def _exigir_candidato(candidato_id: str, empresa: str) -> None:
    if empresa != exemplos.EMPRESA_EXEMPLO or candidato_id not in exemplos.DECISOES:
        raise ErroApi(404, "candidato_nao_encontrado", "Candidato não encontrado nesta empresa.")


def _pagina_de[T](itens: Sequence[T], pagina: int, limite: int) -> list[T]:
    inicio = (pagina - 1) * limite
    return list(itens[inicio : inicio + limite])


def _resposta_vaga_nova(empresa: str = exemplos.EMPRESA_EXEMPLO) -> RespostaVaga:
    return RespostaVaga(
        vaga=exemplos.VAGA_NOVA.model_copy(update={"empresa_id": empresa}),
        estado=EstadoVaga.AGUARDANDO_MANDATO,
        mandato=None,
    )


def _resposta_mandato() -> RespostaMandato:
    return RespostaMandato(mandato=exemplos.MANDATO, estado=EstadoVaga.BUSCANDO)


def _resposta_vaga() -> RespostaVaga:
    return RespostaVaga(
        vaga=exemplos.VAGA_COM_MANDATO, estado=EstadoVaga.DECIDINDO, mandato=exemplos.MANDATO
    )


def _resposta_candidatos(pagina: int = 1, limite: int = LIMITE_PADRAO) -> RespostaCandidatos:
    itens = [
        ItemCandidato(
            candidato=candidato, decisao=exemplos.DECISOES[candidato.id].tipo, destino=None
        )
        for candidato in exemplos.CANDIDATOS
    ]
    return RespostaCandidatos(
        pagina=pagina,
        limite=limite,
        total=len(itens),
        itens=_pagina_de(itens, pagina, limite),
    )


def _resposta_eventos(pagina: int = 1, limite: int = LIMITE_PADRAO) -> RespostaEventos:
    return RespostaEventos(
        pagina=pagina,
        limite=limite,
        total=len(exemplos.EVENTOS),
        itens=_pagina_de(exemplos.EVENTOS, pagina, limite),
    )


def _resposta_metricas() -> RespostaMetricas:
    return RespostaMetricas(
        vaga_id=exemplos.VAGA_EXEMPLO,
        sem_revisao=exemplos.TAXA_SEM_REVISAO,
        erros_por_tipo=exemplos.ERROS_POR_TIPO,
    )


def _resposta_decisao() -> RespostaDecisao:
    return RespostaDecisao(decisao=exemplos.DECISOES[exemplos.CANDIDATOS[0].id])


def _resposta_parada() -> RespostaControle:
    return RespostaControle(
        vaga_id=exemplos.VAGA_EXEMPLO,
        estado=EstadoVaga.PAUSADA,
        estado_anterior=EstadoVaga.DECIDINDO,
    )


def _resposta_retomada() -> RespostaControle:
    return RespostaControle(
        vaga_id=exemplos.VAGA_EXEMPLO,
        estado=EstadoVaga.DECIDINDO,
        estado_anterior=EstadoVaga.PAUSADA,
    )


def _resposta_reversao(candidato_id: str = exemplos.CANDIDATOS[0].id) -> RespostaReversao:
    original = exemplos.DECISOES[candidato_id]
    nova = exemplos.DECISAO_REVERTIDA.model_copy(
        update={"candidato_id": candidato_id, "entrada": {"rastro_revertido": original.rastro_id}}
    )
    return RespostaReversao(decisao_original=original, decisao_nova=nova)


def _resposta_destino(
    candidato_id: str = exemplos.CANDIDATOS[0].id,
    destino: DestinoPessoa = exemplos.DESTINO_EXEMPLO,
    responsavel: str = exemplos.PESSOA_RESPONSAVEL,
) -> RespostaDestino:
    return RespostaDestino(
        vaga_id=exemplos.VAGA_EXEMPLO,
        candidato_id=candidato_id,
        destino=destino,
        responsavel=responsavel,
    )


def _resposta_reinicio(empresa: str = exemplos.EMPRESA_EXEMPLO) -> RespostaReinicio:
    return RespostaReinicio(
        empresa_id=empresa,
        dados_recarregados=False,
        mensagem="Exemplo fixo: nenhum dado foi recarregado.",
    )


rotas = APIRouter()


@rotas.post(
    "/vagas",
    tags=["vagas"],
    status_code=201,
    response_model=RespostaVaga,
    responses=_respostas(_resposta_vaga_nova(), status=201, erros=(401, 422)),
)
def criar_vaga(
    pedido: Annotated[
        PedidoVaga, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_VAGA))
    ],
    empresa: EmpresaDaSessao,
) -> RespostaVaga:
    """Cria a vaga da empresa da sessão, que espera o mandato. Exemplo fixo: nada é gravado."""
    return _resposta_vaga_nova(empresa)


@rotas.post(
    "/vagas/{id}/mandato",
    tags=["vagas"],
    status_code=201,
    response_model=RespostaMandato,
    responses=_respostas(_resposta_mandato(), status=201),
)
def assinar_mandato(
    id: str,
    pedido: Annotated[
        PedidoMandato, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_MANDATO))
    ],
    empresa: EmpresaDaSessao,
) -> RespostaMandato:
    """Registra o mandato assinado por uma pessoa. Exemplo fixo: o fluxo não é iniciado."""
    _exigir_vaga(id, empresa)
    return _resposta_mandato()


@rotas.get(
    "/vagas/{id}",
    tags=["vagas"],
    response_model=RespostaVaga,
    responses=_respostas(_resposta_vaga()),
)
def consultar_vaga(id: str, empresa: EmpresaDaSessao) -> RespostaVaga:
    """Devolve a vaga, o estado e o mandato."""
    _exigir_vaga(id, empresa)
    return _resposta_vaga()


@rotas.get(
    "/vagas/{id}/candidatos",
    tags=["vagas"],
    response_model=RespostaCandidatos,
    responses=_respostas(_resposta_candidatos()),
)
def listar_candidatos(
    id: str,
    empresa: EmpresaDaSessao,
    pagina: Pagina = 1,
    limite: Limite = LIMITE_PADRAO,
) -> RespostaCandidatos:
    """Lista os candidatos da vaga, com a decisão do agente e o destino dado pelo RH."""
    _exigir_vaga(id, empresa)
    return _resposta_candidatos(pagina, limite)


@rotas.get(
    "/vagas/{id}/eventos",
    tags=["vagas"],
    response_model=RespostaEventos,
    responses=_respostas(_resposta_eventos()),
)
def listar_eventos(
    id: str,
    empresa: EmpresaDaSessao,
    pagina: Pagina = 1,
    limite: Limite = LIMITE_PADRAO,
) -> RespostaEventos:
    """Lista os eventos da vaga, para o painel consultar periodicamente."""
    _exigir_vaga(id, empresa)
    return _resposta_eventos(pagina, limite)


@rotas.get(
    "/vagas/{id}/entrega",
    tags=["vagas"],
    response_model=RespostaEntrega,
    responses=_respostas(RespostaEntrega(saida=exemplos.SAIDA)),
)
def consultar_entrega(id: str, empresa: EmpresaDaSessao) -> RespostaEntrega:
    """Devolve a saída personalizada: só o contexto dos indicados, para quem segue o processo."""
    _exigir_vaga(id, empresa)
    return RespostaEntrega(saida=exemplos.SAIDA)


@rotas.get(
    "/vagas/{id}/resumo",
    tags=["vagas"],
    response_model=RespostaResumo,
    responses=_respostas(RespostaResumo(resumo=exemplos.RESUMO)),
)
def consultar_resumo(id: str, empresa: EmpresaDaSessao) -> RespostaResumo:
    """Devolve as contagens e o gasto da vaga, para o controle depois da ação."""
    _exigir_vaga(id, empresa)
    return RespostaResumo(resumo=exemplos.RESUMO)


@rotas.get(
    "/vagas/{id}/metricas",
    tags=["vagas"],
    response_model=RespostaMetricas,
    responses=_respostas(_resposta_metricas()),
)
def consultar_metricas(id: str, empresa: EmpresaDaSessao) -> RespostaMetricas:
    """Devolve taxas com casos e intervalo de Wilson. Valores ilustrativos, não medem o agente."""
    _exigir_vaga(id, empresa)
    return _resposta_metricas()


@rotas.post(
    "/vagas/{id}/parar",
    tags=["controle"],
    response_model=RespostaControle,
    responses=_respostas(_resposta_parada()),
)
def parar_vaga(
    id: str,
    pedido: Annotated[
        PedidoControle, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_PARAR))
    ],
    empresa: EmpresaDaSessao,
) -> RespostaControle:
    """Pausa a vaga a pedido de uma pessoa. Exemplo fixo: nada é alterado."""
    _exigir_vaga(id, empresa)
    return _resposta_parada()


@rotas.post(
    "/vagas/{id}/retomar",
    tags=["controle"],
    response_model=RespostaControle,
    responses=_respostas(_resposta_retomada()),
)
def retomar_vaga(
    id: str,
    pedido: Annotated[
        PedidoControle, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_RETOMAR))
    ],
    empresa: EmpresaDaSessao,
) -> RespostaControle:
    """Devolve a vaga ao estado anterior à pausa. Exemplo fixo: nada é alterado."""
    _exigir_vaga(id, empresa)
    return _resposta_retomada()


@rotas.get(
    "/candidatos/{id}/decisao",
    tags=["candidatos"],
    response_model=RespostaDecisao,
    responses=_respostas(_resposta_decisao()),
)
def consultar_decisao(
    id: str,
    empresa: EmpresaDaSessao,
    vaga_id: Annotated[
        str | None, Query(description="Vaga da decisão, pois a pessoa pode estar em mais de uma.")
    ] = None,
) -> RespostaDecisao:
    """Explica a decisão do agente sobre o candidato, com regra, evidências e rastro."""
    _exigir_candidato(id, empresa)
    if vaga_id is not None:
        _exigir_vaga(vaga_id, empresa)
    return RespostaDecisao(decisao=exemplos.DECISOES[id])


@rotas.post(
    "/candidatos/{id}/reverter",
    tags=["controle"],
    response_model=RespostaReversao,
    responses=_respostas(_resposta_reversao()),
)
def reverter_decisao(
    id: str,
    pedido: Annotated[
        PedidoReversao, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_REVERSAO))
    ],
    empresa: EmpresaDaSessao,
) -> RespostaReversao:
    """Mostra a nova decisão ao lado da original, que nunca é apagada. Nada é alterado."""
    _exigir_candidato(id, empresa)
    _exigir_vaga(pedido.vaga_id, empresa)
    return _resposta_reversao(id)


@rotas.post(
    "/candidatos/{id}/destino",
    tags=["controle"],
    response_model=RespostaDestino,
    responses=_respostas(_resposta_destino()),
)
def registrar_destino(
    id: str,
    pedido: Annotated[
        PedidoDestino, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_DESTINO))
    ],
    empresa: EmpresaDaSessao,
) -> RespostaDestino:
    """Registra o destino que uma pessoa do RH decidiu. O agente não decide. Nada é gravado."""
    _exigir_candidato(id, empresa)
    _exigir_vaga(pedido.vaga_id, empresa)
    return _resposta_destino(id, pedido.destino, pedido.responsavel)


@rotas.post(
    "/sessoes/reiniciar",
    tags=["sessoes"],
    response_model=RespostaReinicio,
    responses=_respostas(_resposta_reinicio(), erros=(401,)),
)
def reiniciar_sessao(empresa: EmpresaDaSessao) -> RespostaReinicio:
    """Reinicia os dados sintéticos da empresa da sessão. Exemplo fixo: nada é recarregado."""
    return _resposta_reinicio(empresa)


def _mensagem_de_validacao(erros: Sequence[Any]) -> str:
    """Resume os erros sem repetir valores nem nomes de campo enviados pelo cliente."""
    partes = []
    for erro in erros[:_MAX_ERROS_NA_MENSAGEM]:
        if erro["type"] == "extra_forbidden":
            partes.append("campo não reconhecido")
        elif erro["type"] == "json_invalid":
            partes.append("corpo não é um JSON válido")
        else:
            local = ".".join(str(parte) for parte in erro["loc"])
            partes.append(f"{local} ({erro['type']})")
    return f"Dados inválidos: {'; '.join(partes)}."


async def _tratar_erro_api(_: Request, erro: ErroApi) -> JSONResponse:
    cabecalhos = {"WWW-Authenticate": "APIKey"} if erro.status == 401 else None
    return JSONResponse(
        _corpo_erro(erro.codigo, erro.mensagem), status_code=erro.status, headers=cabecalhos
    )


async def _tratar_validacao(_: Request, erro: RequestValidationError) -> JSONResponse:
    corpo = _corpo_erro("dados_invalidos", _mensagem_de_validacao(erro.errors()))
    return JSONResponse(corpo, status_code=422)


async def _tratar_http(_: Request, erro: StarletteHTTPException) -> JSONResponse:
    codigo, mensagem = {
        404: ("nao_encontrado", "Recurso não encontrado."),
        405: ("metodo_nao_permitido", "Método não permitido."),
    }.get(erro.status_code, ("erro_http", "Não foi possível atender ao pedido."))
    return JSONResponse(
        _corpo_erro(codigo, mensagem), status_code=erro.status_code, headers=erro.headers
    )


async def _tratar_inesperado(request: Request, erro: Exception) -> JSONResponse:
    logger.error("erro interno em %s: %s", request.method, type(erro).__name__)
    return JSONResponse(_corpo_erro("erro_interno", "Erro interno."), status_code=500)


def _id_da_operacao(rota: APIRoute) -> str:
    return rota.name


def criar_app() -> FastAPI:
    aplicacao = FastAPI(
        title="API do agente recrutador (proposta simulada)",
        version="0.1.0-proposta",
        description=DESCRICAO,
        generate_unique_id_function=_id_da_operacao,
    )
    aplicacao.include_router(rotas)
    aplicacao.add_exception_handler(ErroApi, _tratar_erro_api)
    aplicacao.add_exception_handler(RequestValidationError, _tratar_validacao)
    aplicacao.add_exception_handler(StarletteHTTPException, _tratar_http)
    aplicacao.add_exception_handler(Exception, _tratar_inesperado)
    return aplicacao


app = criar_app()
