"""API do agente recrutador: PROPOSTA enquanto o acordo das frentes não sair.

Rotas, campos e erros ainda podem mudar. As rotas chamam `ServicoVagas`, injetado em `criar_app`;
regra de negócio não fica aqui. O agente não agenda, não entrevista e não decide contratações;
o destino da pessoa é decidido pelo RH.

`empresa_id` vem da sessão, simulada por enquanto pelo cabeçalho `X-Empresa-Id`.

Depois de mudar este arquivo, gere o contrato com:
`uv run python -m backend.agente.gerar_openapi`
"""

import logging
import re
import threading
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import APIKeyHeader
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.agente import exemplos_api as exemplos
from backend.agente.auditoria import DecisoesAutomaticasPausadas
from backend.agente.fluxo import AcaoRecusada, ResponsavelInvalido, TransicaoInvalida
from backend.agente.mandato import MandatoInvalido
from backend.agente.montagem import montar_demo
from backend.agente.servico import (
    AditivoNecessario,
    CandidatoInexistente,
    ChaveReutilizada,
    CriteriosSensiveis,
    ServicoVagas,
    VagaInexistente,
)
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import (
    Candidato,
    Competencia,
    Contrato,
    Decisao,
    DestinoPessoa,
    EstadoVaga,
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

**Simulação.** A sessão é simulada e os dados são sintéticos: toda resposta traz `simulado: true`.
`exemplo_fixo: true` marca o que ainda não vem da lógica: hoje, as métricas sem provedor de medição
e o reinício sem dados para recarregar. Os números dessas respostas são ilustrativos e não medem o
agente. Os exemplos desta documentação também são fictícios.

**Execução.** Assinar o mandato e retomar respondem na hora e seguem em segundo plano: acompanhe por
`GET /vagas/{id}` e `GET /vagas/{id}/eventos`.

**Limites do agente.** O agente não agenda, não entrevista e não decide contratações.
O destino da pessoa é registrado por alguém do RH.

**Sessão.** `empresa_id` vem da sessão, simulada pelo cabeçalho `X-Empresa-Id`, nunca do corpo.
O que é de outra empresa não existe para esta sessão: a resposta é 404.

**Erros.** `{"erro": {"codigo": "...", "mensagem": "..."}, "simulado": true}`.

**Gerar este arquivo.** `uv run python -m backend.agente.gerar_openapi`
"""


class Erro(Contrato):
    codigo: Texto
    mensagem: Texto


class RespostaErro(Contrato):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    erro: Erro
    simulado: Literal[True] = True


class RespostaSimulada(Contrato):
    """Base das respostas de sucesso. A sessão é simulada; `exemplo_fixo` marca dado fixo."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    simulado: Literal[True] = True
    exemplo_fixo: bool = False


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
    """Taxas da vaga. Sem casos, a taxa aparece como não medida: `valor` nulo."""

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
        bool, Field(description="Falso quando não há dados a recarregar: nada foi apagado.")
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
    409: ("transicao_invalida", "A vaga não permite esta ação no estado atual."),
    422: ("dados_invalidos", "Dados inválidos: body.limite_gasto_usd (greater_than)."),
    500: ("erro_interno", "Erro interno."),
}
_DESCRICOES_DE_ERRO = {
    401: "Sessão ausente ou inválida",
    404: "Não existe nesta empresa",
    409: "A ação não vale no estado atual, ou a chave já foi usada em outro pedido",
    422: "Dados inválidos",
    500: "Erro interno, sem detalhes",
}
_ERROS_DE_ROTA_COM_RECURSO = (401, 404, 422)
_ERROS_DE_ACAO = (401, 404, 409, 422)


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


def _servico(request: Request) -> ServicoVagas:
    return request.app.state.obter_servico()


Servico = Annotated[ServicoVagas, Depends(_servico)]


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


def _metricas_fixas(vaga_id: str = exemplos.VAGA_EXEMPLO) -> RespostaMetricas:
    return RespostaMetricas(
        vaga_id=vaga_id,
        sem_revisao=exemplos.TAXA_SEM_REVISAO,
        erros_por_tipo=exemplos.ERROS_POR_TIPO,
        exemplo_fixo=True,
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
        dados_recarregados=True,
        mensagem="Dados sintéticos da empresa recarregados.",
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
    pedido: Annotated[PedidoVaga, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_VAGA))],
    empresa: EmpresaDaSessao,
    servico: Servico,
) -> RespostaVaga:
    """Cria a vaga da empresa da sessão, que espera o mandato."""
    fluxo = servico.criar_vaga(empresa, pedido.model_dump())
    return RespostaVaga(vaga=fluxo.vaga, estado=fluxo.estado, mandato=fluxo.mandato)


@rotas.post(
    "/vagas/{id}/mandato",
    tags=["vagas"],
    status_code=201,
    response_model=RespostaMandato,
    responses=_respostas(_resposta_mandato(), status=201, erros=_ERROS_DE_ACAO),
)
def assinar_mandato(
    id: str,
    pedido: Annotated[
        PedidoMandato, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_MANDATO))
    ],
    empresa: EmpresaDaSessao,
    servico: Servico,
    tarefas: BackgroundTasks,
) -> RespostaMandato:
    """Registra o mandato assinado por uma pessoa e segue a vaga em segundo plano.

    Em vaga pausada, vira um aditivo, que só vale depois de `/retomar`.
    """
    mandato, estado = servico.assinar(
        empresa, id, pedido.assinante, pedido.limite_gasto_usd, pedido.politica, pedido.valido_ate
    )
    if estado != EstadoVaga.PAUSADA:
        tarefas.add_task(servico.executar, empresa, id)
    return RespostaMandato(mandato=mandato, estado=estado)


@rotas.get(
    "/vagas/{id}",
    tags=["vagas"],
    response_model=RespostaVaga,
    responses=_respostas(_resposta_vaga()),
)
def consultar_vaga(id: str, empresa: EmpresaDaSessao, servico: Servico) -> RespostaVaga:
    """Devolve a vaga, o estado e o mandato."""
    fluxo = servico.consultar(empresa, id)
    return RespostaVaga(vaga=fluxo.vaga, estado=fluxo.estado, mandato=fluxo.mandato)


@rotas.get(
    "/vagas/{id}/candidatos",
    tags=["vagas"],
    response_model=RespostaCandidatos,
    responses=_respostas(_resposta_candidatos()),
)
def listar_candidatos(
    id: str,
    empresa: EmpresaDaSessao,
    servico: Servico,
    pagina: Pagina = 1,
    limite: Limite = LIMITE_PADRAO,
) -> RespostaCandidatos:
    """Lista os candidatos da vaga, com a decisão do agente e o destino dado pelo RH."""
    itens = [
        ItemCandidato(candidato=candidato, decisao=decisao, destino=destino)
        for candidato, decisao, destino in servico.situacao_candidatos(empresa, id)
    ]
    return RespostaCandidatos(
        pagina=pagina,
        limite=limite,
        total=len(itens),
        itens=_pagina_de(itens, pagina, limite),
    )


@rotas.get(
    "/vagas/{id}/eventos",
    tags=["vagas"],
    response_model=RespostaEventos,
    responses=_respostas(_resposta_eventos()),
)
def listar_eventos(
    id: str,
    empresa: EmpresaDaSessao,
    servico: Servico,
    pagina: Pagina = 1,
    limite: Limite = LIMITE_PADRAO,
) -> RespostaEventos:
    """Lista os eventos da vaga, para o painel consultar periodicamente."""
    eventos = servico.eventos(empresa, id)
    return RespostaEventos(
        pagina=pagina,
        limite=limite,
        total=len(eventos),
        itens=_pagina_de(eventos, pagina, limite),
    )


@rotas.get(
    "/vagas/{id}/entrega",
    tags=["vagas"],
    response_model=RespostaEntrega,
    responses=_respostas(RespostaEntrega(saida=exemplos.SAIDA)),
)
def consultar_entrega(id: str, empresa: EmpresaDaSessao, servico: Servico) -> RespostaEntrega:
    """Devolve a saída personalizada: só o contexto dos indicados, para quem segue o processo."""
    return RespostaEntrega(saida=servico.saida(empresa, id))


@rotas.get(
    "/vagas/{id}/resumo",
    tags=["vagas"],
    response_model=RespostaResumo,
    responses=_respostas(RespostaResumo(resumo=exemplos.RESUMO)),
)
def consultar_resumo(id: str, empresa: EmpresaDaSessao, servico: Servico) -> RespostaResumo:
    """Devolve as contagens e o gasto da vaga, para o controle depois da ação."""
    return RespostaResumo(resumo=servico.resumo(empresa, id))


@rotas.get(
    "/vagas/{id}/metricas",
    tags=["vagas"],
    response_model=RespostaMetricas,
    responses=_respostas(_metricas_fixas()),
)
def consultar_metricas(id: str, empresa: EmpresaDaSessao, servico: Servico) -> RespostaMetricas:
    """Devolve taxas com casos e intervalo de Wilson.

    Sem provedor de medição, os valores são ilustrativos e vêm com `exemplo_fixo: true`.
    """
    medidas = servico.metricas(empresa, id)
    if medidas is None:
        return _metricas_fixas(id)
    return RespostaMetricas(
        vaga_id=id, sem_revisao=medidas.sem_revisao, erros_por_tipo=dict(medidas.erros_por_tipo)
    )


@rotas.post(
    "/vagas/{id}/parar",
    tags=["controle"],
    response_model=RespostaControle,
    responses=_respostas(_resposta_parada(), erros=_ERROS_DE_ACAO),
)
def parar_vaga(
    id: str,
    pedido: Annotated[
        PedidoControle, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_PARAR))
    ],
    empresa: EmpresaDaSessao,
    servico: Servico,
) -> RespostaControle:
    """Pausa a vaga a pedido de uma pessoa. A execução em curso sai antes do próximo candidato."""
    servico.consultar(empresa, id)

    def acao() -> RespostaControle:
        estado, anterior = servico.parar(empresa, id, pedido.responsavel, pedido.motivo)
        return RespostaControle(vaga_id=id, estado=estado, estado_anterior=anterior)

    return servico.idempotente(
        empresa,
        f"parar:{id}:{pedido.chave_idempotencia}",
        pedido.model_dump_json(),
        RespostaControle,
        acao,
    )


@rotas.post(
    "/vagas/{id}/retomar",
    tags=["controle"],
    response_model=RespostaControle,
    responses=_respostas(_resposta_retomada(), erros=_ERROS_DE_ACAO),
)
def retomar_vaga(
    id: str,
    pedido: Annotated[
        PedidoControle, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_RETOMAR))
    ],
    empresa: EmpresaDaSessao,
    servico: Servico,
    tarefas: BackgroundTasks,
) -> RespostaControle:
    """Devolve a vaga ao estado anterior à pausa e segue em segundo plano."""
    servico.consultar(empresa, id)

    def acao() -> RespostaControle:
        estado, anterior = servico.retomar(empresa, id, pedido.responsavel, pedido.motivo)
        tarefas.add_task(servico.executar, empresa, id)
        return RespostaControle(vaga_id=id, estado=estado, estado_anterior=anterior)

    return servico.idempotente(
        empresa,
        f"retomar:{id}:{pedido.chave_idempotencia}",
        pedido.model_dump_json(),
        RespostaControle,
        acao,
    )


@rotas.get(
    "/candidatos/{id}/decisao",
    tags=["candidatos"],
    response_model=RespostaDecisao,
    responses=_respostas(_resposta_decisao()),
)
def consultar_decisao(
    id: str,
    empresa: EmpresaDaSessao,
    servico: Servico,
    vaga_id: Annotated[
        str | None, Query(description="Vaga da decisão, pois a pessoa pode estar em mais de uma.")
    ] = None,
) -> RespostaDecisao:
    """Explica a decisão vigente sobre o candidato, com regra, evidências e rastro."""
    return RespostaDecisao(decisao=servico.decisao(empresa, id, vaga_id))


@rotas.post(
    "/candidatos/{id}/reverter",
    tags=["controle"],
    response_model=RespostaReversao,
    responses=_respostas(_resposta_reversao(), erros=_ERROS_DE_ACAO),
)
def reverter_decisao(
    id: str,
    pedido: Annotated[
        PedidoReversao, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_REVERSAO))
    ],
    empresa: EmpresaDaSessao,
    servico: Servico,
) -> RespostaReversao:
    """Devolve a decisão à fila humana. A nova fica ao lado da original, que nunca é apagada."""
    servico.consultar(empresa, pedido.vaga_id)

    def acao() -> RespostaReversao:
        original, nova = servico.reverter(
            empresa, pedido.vaga_id, id, pedido.motivo, pedido.responsavel
        )
        return RespostaReversao(decisao_original=original, decisao_nova=nova)

    return servico.idempotente(
        empresa,
        f"reverter:{pedido.vaga_id}:{id}:{pedido.chave_idempotencia}",
        pedido.model_dump_json(),
        RespostaReversao,
        acao,
    )


@rotas.post(
    "/candidatos/{id}/destino",
    tags=["controle"],
    response_model=RespostaDestino,
    responses=_respostas(_resposta_destino(), erros=_ERROS_DE_ACAO),
)
def registrar_destino(
    id: str,
    pedido: Annotated[
        PedidoDestino, Body(openapi_examples=_exemplo_de_pedido(exemplos.PEDIDO_DESTINO))
    ],
    empresa: EmpresaDaSessao,
    servico: Servico,
) -> RespostaDestino:
    """Registra o destino que uma pessoa do RH decidiu. O agente não decide."""
    servico.consultar(empresa, pedido.vaga_id)

    def acao() -> RespostaDestino:
        servico.registrar_destino(empresa, pedido.vaga_id, id, pedido.destino, pedido.responsavel)
        return RespostaDestino(
            vaga_id=pedido.vaga_id,
            candidato_id=id,
            destino=pedido.destino,
            responsavel=pedido.responsavel,
        )

    return servico.idempotente(
        empresa,
        f"destino:{pedido.vaga_id}:{id}:{pedido.chave_idempotencia}",
        pedido.model_dump_json(),
        RespostaDestino,
        acao,
    )


@rotas.post(
    "/sessoes/reiniciar",
    tags=["sessoes"],
    response_model=RespostaReinicio,
    responses=_respostas(_resposta_reinicio(), erros=(401,)),
)
def reiniciar_sessao(empresa: EmpresaDaSessao, servico: Servico) -> RespostaReinicio:
    """Reinicia os dados sintéticos da empresa da sessão, se houver dados para recarregar.

    Sem eles, nada é apagado, e a resposta traz `exemplo_fixo: true`.
    """
    recarregados = servico.reiniciar(empresa)
    if recarregados:
        return _resposta_reinicio(empresa)
    return RespostaReinicio(
        empresa_id=empresa,
        dados_recarregados=False,
        mensagem="Não há dados sintéticos para recarregar: nada foi alterado.",
        exemplo_fixo=True,
    )


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


_ERROS_DE_DOMINIO: dict[type[ErroContrato], tuple[int, str, str]] = {
    VagaInexistente: (404, "vaga_nao_encontrada", "Vaga não encontrada nesta empresa."),
    CandidatoInexistente: (
        404,
        "candidato_nao_encontrado",
        "Candidato não encontrado nesta empresa.",
    ),
    CriteriosSensiveis: (
        422,
        "criterio_sensivel",
        "A vaga usa dado sensível como critério. Retire-o dos requisitos e das competências.",
    ),
    ResponsavelInvalido: (
        422,
        "responsavel_invalido",
        "Esta ação é de uma pessoa: informe quem é a pessoa responsável.",
    ),
    TransicaoInvalida: (
        409,
        "transicao_invalida",
        "A vaga não permite esta ação no estado atual.",
    ),
    AditivoNecessario: (
        409,
        "aditivo_necessario",
        "Esta pausa só termina com um novo mandato assinado. Assine e retome.",
    ),
    MandatoInvalido: (
        422,
        "mandato_invalido",
        "O mandato enviado não pode ser assinado para esta vaga.",
    ),
    DecisoesAutomaticasPausadas: (
        409,
        "auditoria_pendente",
        "Um erro na amostra auditada segura a vaga: uma pessoa precisa liberar antes de retomar.",
    ),
    ChaveReutilizada: (
        409,
        "chave_reutilizada",
        "Esta chave de idempotência já foi usada em outro pedido. Use outra chave.",
    ),
}


def mensagem_segura(erro: ErroContrato) -> str:
    """A mesma mensagem que a API daria a este erro, sem detalhes internos."""
    if isinstance(erro, ErroApi):
        return erro.mensagem
    if isinstance(erro, AcaoRecusada):
        return str(erro)
    tipo = next((t for t in type(erro).__mro__ if t in _ERROS_DE_DOMINIO), None)
    return "Erro interno." if tipo is None else _ERROS_DE_DOMINIO[tipo][2]


async def _tratar_erro_de_dominio(_: Request, erro: ErroContrato) -> JSONResponse:
    tipo = next(t for t in type(erro).__mro__ if t in _ERROS_DE_DOMINIO)
    status, codigo, mensagem = _ERROS_DE_DOMINIO[tipo]
    return JSONResponse(_corpo_erro(codigo, mensagem), status_code=status)


async def _tratar_acao_recusada(_: Request, erro: AcaoRecusada) -> JSONResponse:
    return JSONResponse(_corpo_erro("acao_recusada", str(erro)), status_code=409)


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


def _gerar_openapi(aplicacao: FastAPI) -> dict[str, Any]:
    """Gera o OpenAPI e devolve os exemplos completos das rotas.

    O FastAPI remove valores nulos do esquema gerado. Os exemplos precisam deles: `valor: null`
    é como uma taxa não medida aparece, e o painel precisa ver esse formato.
    """
    if aplicacao.openapi_schema:
        return aplicacao.openapi_schema
    esquema = get_openapi(
        title=aplicacao.title,
        version=aplicacao.version,
        description=aplicacao.description,
        routes=aplicacao.routes,
    )
    for rota in rotas.routes:
        for metodo in rota.methods:
            respostas = esquema["paths"][rota.path_format][metodo.lower()]["responses"]
            for status, resposta in rota.responses.items():
                respostas[str(status)]["content"]["application/json"]["example"] = resposta[
                    "content"
                ]["application/json"]["example"]
    aplicacao.openapi_schema = esquema
    return esquema


def criar_app(servico: ServicoVagas | None = None) -> FastAPI:
    """Cria a aplicação com o serviço injetado. Sem ele, monta a demonstração no primeiro pedido."""
    aplicacao = FastAPI(
        title="API do agente recrutador (proposta simulada)",
        version="0.1.0-proposta",
        description=DESCRICAO,
        generate_unique_id_function=_id_da_operacao,
    )
    aplicacao.state.obter_servico = _lazy_demo() if servico is None else (lambda: servico)
    aplicacao.include_router(rotas)
    aplicacao.add_exception_handler(ErroApi, _tratar_erro_api)
    for tipo in _ERROS_DE_DOMINIO:
        aplicacao.add_exception_handler(tipo, _tratar_erro_de_dominio)
    aplicacao.add_exception_handler(AcaoRecusada, _tratar_acao_recusada)
    aplicacao.add_exception_handler(RequestValidationError, _tratar_validacao)
    aplicacao.add_exception_handler(StarletteHTTPException, _tratar_http)
    aplicacao.add_exception_handler(Exception, _tratar_inesperado)
    aplicacao.openapi = lambda: _gerar_openapi(aplicacao)
    return aplicacao


def _lazy_demo() -> Callable[[], ServicoVagas]:
    """Importar a API, como faz o gerador do OpenAPI, não cria banco nenhum."""
    trava = threading.Lock()
    montado: list[ServicoVagas] = []

    def obter() -> ServicoVagas:
        with trava:
            if not montado:
                montado.append(montar_demo())
            return montado[0]

    return obter


app = criar_app()
