"""Pré-triagem: roteiro em código, extração validada e validação final, também em código.

O modelo só lê a mensagem da pessoa e devolve dados: ele não conduz, não decide e não vê o nome.
Extração inválida vai para uma pessoa, nunca vira aprovação. A pré-triagem não substitui a
entrevista, e o agente não agenda: quem passa recebe o link do agente de destino, se houver um.

Este módulo não fala com o canal: quem envia e recebe mensagens é `backend/contato`.
"""

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from backend.agente.auditoria import PREFIXO_HUMANO, rastreado
from backend.agente.decisao_final import (
    PORTAO_INSTRUCAO,
    RespostaCriterio,
    pontos_a_explorar,
    reavaliar_criterios,
)
from backend.agente.mandato import Mandato
from backend.agente.neutralizacao import corresponde_ao_original
from backend.agente.prompts import SISTEMA_PRE_TRIAGEM, USUARIO_PRE_TRIAGEM, como_dado
from backend.agente.regras import autorizacao_ativa
from backend.contratos.criterios import sem_acento, separar_palavras, termos_proibidos_em_conversa
from backend.contratos.erros import ErroContrato, ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import AgenteRecrutador, BancoTalentos, ClienteModelo
from backend.contratos.modelos import (
    AtualizacaoPerfil,
    Candidato,
    ContextoOnboarding,
    Contrato,
    DadoPreTriagem,
    DecisaoFinal,
    DestinoDecisao,
    FatoColetado,
    FatoIndisponibilidade,
    NivelCriterio,
    NotaCriterio,
    PacoteContexto,
    PerguntaRoteiro,
    QualidadeDado,
    ResultadoPreTriagem,
    RoteiroPreTriagem,
    SituacaoPreTriagem,
    SituacaoResposta,
    TipoCriterio,
    TipoFato,
    TipoPergunta,
    Vaga,
)

logger = logging.getLogger(__name__)

ETAPA_ROTEIRO = "pre_triagem_roteiro"
ETAPA_EXTRACAO = "pre_triagem_extracao"
ETAPA_VALIDACAO = "pre_triagem_validacao"
FONTE_PRE_TRIAGEM = "pre_triagem"
CRITERIO_DISPONIBILIDADE = "disponibilidade"
MAXIMO_PERGUNTAS = 6
"""Conversa curta. Só pergunta sobre competência fica de fora ao passar deste número."""

LIMITE_MENSAGEM = 4000
PORTAO_EXTRACAO_INVALIDA = "extracao_invalida"
PORTAO_DISPONIBILIDADE = "disponibilidade_nao_confirmada"
_SEM_EVIDENCIA = (QualidadeDado.SEM_DADO, QualidadeDado.INFERIDO)
_NEGACOES = frozenset({"jamais", "nao", "nem", "nenhum", "nenhuma", "nunca", "sem"})
_FIM_DE_FRASE = re.compile(r"(?<=[.!?;])\s+|\n+")
_INSTRUCAO_NA_RESPOSTA = re.compile(
    r"\b(ignor[ea]\w*|desconsider\w*|esquec\w*|disregard|forget)\b"
    r".{0,60}\b(regras?|instruc\w+|anteriores|previous|instructions?|prompt|sistema)\b"
    r"|\b(me de|de me|atribua|conceda|give|assign)\b.{0,30}\b(nota|score)\b"
    r"|\b(aprove|indique|selecione|contrate|approve|hire|marque|classifique)\b"
    r".{0,30}\b(este|esta|me|candidat\w+|perfil|pessoa|this|como)\b"
    r"|\b(system prompt|prompt do sistema|voce agora|you are now)\b"
    r"|\b(sistema|system|assistant|assistente)\s*:"
)
"""Sobre o texto sem acento nem caixa. O que escapar daqui, o modelo aponta em `instrucoes`."""

_TEXTO_DISPONIBILIDADE = (
    "Você tem disponibilidade para seguir nesta vaga agora? "
    "Se não, a partir de quando, ou o que precisaria mudar?"
)
_MOTIVO_DISPONIBILIDADE = "Para saber se seguimos agora ou combinamos de voltar a falar."


class RoteiroIndevido(ErroContrato):
    """Pessoa que não pode receber pré-triagem agora: recusada, no garden ou sem liberação."""


class PseudonimizarTexto(Protocol):
    def __call__(self, candidato: Candidato, texto: str) -> str: ...


class SituacaoExtracao(StrEnum):
    VALIDA = "valida"
    INVALIDA = "invalida"
    INSTRUCAO = "instrucao"


class ExtracaoPreTriagem(Contrato):
    """Só `VALIDA` pode mudar o perfil. As outras situações levam a decisão a uma pessoa."""

    situacao: SituacaoExtracao
    respostas: list[DadoPreTriagem] = []


class _RespostaDoModelo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pergunta_id: str
    situacao: SituacaoResposta
    trecho: str
    nivel: NivelCriterio | None = None
    voltar_em: date | None = None
    motivo: str | None = None


class ExtracaoDoModelo(BaseModel):
    """Esquema pedido ao modelo: `respostas` é obrigatório, e campo a mais é recusado."""

    model_config = ConfigDict(extra="forbid")

    respostas: list[_RespostaDoModelo]
    instrucoes_detectadas: list[str] = []


def _falta_perguntar(criterio: NotaCriterio) -> bool:
    if criterio.tipo == TipoCriterio.REQUISITO:
        return criterio.status_requisito == "sem_dado" or criterio.qualidade in _SEM_EVIDENCIA
    if criterio.peso <= 0:
        return False
    return criterio.qualidade in _SEM_EVIDENCIA or criterio.nivel == NivelCriterio.GENERICA


def _pergunta_de_requisito(criterio: NotaCriterio, ordem: int) -> PerguntaRoteiro:
    eliminatorio = criterio.eliminatorio
    return PerguntaRoteiro(
        id=f"p-{criterio.criterio}",
        ordem=ordem,
        tipo=TipoPergunta.REQUISITO,
        criterio=criterio.criterio,
        texto=(
            f"A vaga pede: {criterio.descricao}. Você atende a esse requisito? "
            "Se sim, conte onde usou ou comprovou."
        ),
        motivo=(
            "Este requisito é obrigatório na vaga e ainda não temos essa informação."
            if eliminatorio
            else "A vaga aceita desenvolver este requisito, e queremos saber onde você está."
        ),
        eliminatorio=eliminatorio,
    )


def _pergunta_de_competencia(criterio: NotaCriterio, ordem: int) -> PerguntaRoteiro:
    return PerguntaRoteiro(
        id=f"p-{criterio.criterio}",
        ordem=ordem,
        tipo=TipoPergunta.COMPETENCIA,
        criterio=criterio.criterio,
        texto=f"Pode contar um exemplo concreto do seu trabalho com {criterio.descricao}?",
        motivo="A vaga valoriza esta competência, e falta um exemplo no seu perfil.",
    )


def _ordenar(criterios: Sequence[NotaCriterio]) -> list[NotaCriterio]:
    """Eliminatório primeiro, depois requisito desenvolvível, depois competência por peso."""

    def chave(criterio: NotaCriterio) -> tuple:
        grupo = 0 if criterio.eliminatorio else 1 if criterio.tipo == TipoCriterio.REQUISITO else 2
        return (grupo, -criterio.peso, criterio.criterio)

    return sorted(criterios, key=chave)


def _exigir_liberacao(decisao: DecisaoFinal, liberado_por: str | None) -> None:
    if decisao.destino == DestinoDecisao.APROVAR:
        return
    if decisao.destino != DestinoDecisao.REVISAO_HUMANA:
        raise RoteiroIndevido("recusa e garden não recebem pré-triagem")
    identificacao = (liberado_por or "").removeprefix(PREFIXO_HUMANO)
    if not (liberado_por or "").startswith(PREFIXO_HUMANO) or not identificacao.strip():
        raise RoteiroIndevido("caso ambíguo: nada é enviado antes de uma pessoa liberar")


def _id_do_roteiro(decisao: DecisaoFinal, perguntas: Sequence[PerguntaRoteiro]) -> str:
    conteudo = json.dumps(
        [decisao.empresa_id, decisao.vaga_id, decisao.candidato_id, [p.id for p in perguntas]],
        ensure_ascii=False,
    )
    return f"roteiro-{hashlib.sha256(conteudo.encode('utf-8')).hexdigest()[:12]}"


def _motivo_do_contato(vaga: Vaga, perguntas: Sequence[PerguntaRoteiro]) -> str:
    return (
        f"Contato sobre a vaga {vaga.titulo}: seu perfil foi considerado para ela, "
        f"e faltam {len(perguntas)} informações para seguir."
    )


@rastreado(ETAPA_ROTEIRO)
def gerar_roteiro(
    decisao: DecisaoFinal,
    vaga: Vaga,
    *,
    liberado_por: str | None = None,
    maximo_perguntas: int = MAXIMO_PERGUNTAS,
) -> RoteiroPreTriagem:
    """Monta as perguntas dos critérios e lacunas da decisão. Sem modelo, nome ou nota.

    Critério que viraria pergunta sensível não é perguntado e fica em `criterios_bloqueados`, para
    uma pessoa olhar. Texto do modelo e lacuna livre nunca viram pergunta.
    """
    if (decisao.empresa_id, decisao.vaga_id) != (vaga.empresa_id, vaga.id):
        raise ValueError("a decisão é de outra empresa ou vaga")
    _exigir_liberacao(decisao, liberado_por)

    bloqueados: list[str] = []
    perguntaveis: list[NotaCriterio] = []
    for criterio in _ordenar([c for c in decisao.score.criterios if _falta_perguntar(c)]):
        if termos_proibidos_em_conversa(criterio.descricao):
            logger.warning("critério sem pergunta, por citar dado sensível: %s", criterio.criterio)
            bloqueados.append(criterio.criterio)
        else:
            perguntaveis.append(criterio)

    perguntas = [
        PerguntaRoteiro(
            id=f"p-{CRITERIO_DISPONIBILIDADE}",
            ordem=1,
            tipo=TipoPergunta.DISPONIBILIDADE,
            criterio=CRITERIO_DISPONIBILIDADE,
            texto=_TEXTO_DISPONIBILIDADE,
            motivo=_MOTIVO_DISPONIBILIDADE,
        )
    ]
    nao_perguntados = []
    for criterio in perguntaveis:
        if len(perguntas) >= maximo_perguntas and not criterio.eliminatorio:
            nao_perguntados.append(criterio.criterio)
            continue
        ordem = len(perguntas) + 1
        monta = (
            _pergunta_de_requisito
            if criterio.tipo == TipoCriterio.REQUISITO
            else _pergunta_de_competencia
        )
        perguntas.append(monta(criterio, ordem))
    return RoteiroPreTriagem(
        id=_id_do_roteiro(decisao, perguntas),
        empresa_id=decisao.empresa_id,
        vaga_id=decisao.vaga_id,
        candidato_id=decisao.candidato_id,
        motivo_contato=_motivo_do_contato(vaga, perguntas),
        perguntas=perguntas,
        criterios_bloqueados=bloqueados,
        nao_perguntados=nao_perguntados,
        liberado_por=liberado_por,
        simulado=decisao.simulado,
    )


def _sem_frases_sensiveis(texto: str) -> str:
    """Sai a frase inteira, sem alerta: citar um dado sensível não muda o caminho de ninguém."""
    frases = [frase.strip() for frase in _FIM_DE_FRASE.split(texto)]
    return " ".join(f for f in frases if f and not termos_proibidos_em_conversa(f))


def _tem_instrucao(texto: str) -> bool:
    normalizado = " ".join(sem_acento(texto).casefold().split())
    return _INSTRUCAO_NA_RESPOSTA.search(normalizado) is not None


def _tem_negacao(trecho: str) -> bool:
    return bool(_NEGACOES & set(separar_palavras(trecho)))


def _situacao_conferida(resposta: _RespostaDoModelo, pergunta: PerguntaRoteiro) -> SituacaoResposta:
    """O que elimina não pode depender só da leitura do modelo: o trecho precisa concordar."""
    situacao = resposta.situacao
    if situacao == SituacaoResposta.INCERTA:
        return situacao
    if (
        pergunta.tipo == TipoPergunta.DISPONIBILIDADE
        and situacao == SituacaoResposta.NEGA
        and resposta.voltar_em is not None
    ):
        return situacao
    if (situacao == SituacaoResposta.NEGA) != _tem_negacao(resposta.trecho):
        return SituacaoResposta.INCERTA
    return situacao


def _motivo_da_pessoa(motivo: str | None, mensagem: str) -> str | None:
    """Motivo só vale se a pessoa o escreveu, e sem dado sensível."""
    texto = (motivo or "").strip()
    if (
        not texto
        or termos_proibidos_em_conversa(texto)
        or not (corresponde_ao_original(texto, mensagem))
    ):
        return None
    return texto


def _dado_conferido(
    resposta: _RespostaDoModelo,
    pergunta: PerguntaRoteiro,
    mensagem: str,
    hoje: date,
) -> DadoPreTriagem | None:
    """Devolve o dado, ou `None` se a extração não se sustenta e precisa ir a uma pessoa."""
    if not corresponde_ao_original(resposta.trecho, mensagem):
        return None
    if resposta.voltar_em is not None and resposta.voltar_em <= hoje:
        return None
    situacao = _situacao_conferida(resposta, pergunta)
    competencia = pergunta.tipo == TipoPergunta.COMPETENCIA
    nivel = None
    if competencia and situacao != SituacaoResposta.INCERTA:
        nivel = NivelCriterio.NEGA if situacao == SituacaoResposta.NEGA else resposta.nivel
    disponibilidade = pergunta.tipo == TipoPergunta.DISPONIBILIDADE
    try:
        return DadoPreTriagem(
            pergunta_id=pergunta.id,
            criterio=pergunta.criterio,
            situacao=situacao,
            trecho=resposta.trecho,
            fonte=FONTE_PRE_TRIAGEM,
            coletado_em=hoje,
            nivel=nivel,
            voltar_em=resposta.voltar_em if disponibilidade else None,
            motivo=_motivo_da_pessoa(resposta.motivo, mensagem) if disponibilidade else None,
        )
    except ValidationError:
        return None


def _descrever_roteiro(roteiro: RoteiroPreTriagem) -> str:
    return "\n".join(f"{p.id} ({p.tipo}): {p.texto}" for p in roteiro.perguntas)


def _chamar_modelo(
    roteiro: RoteiroPreTriagem, texto: str, cliente: ClienteModelo
) -> ExtracaoDoModelo | None:
    usuario = USUARIO_PRE_TRIAGEM.format(
        roteiro=como_dado(_descrever_roteiro(roteiro)), mensagem=como_dado(texto)
    )
    try:
        resposta = cliente.completar(SISTEMA_PRE_TRIAGEM, usuario, ExtracaoDoModelo, ETAPA_EXTRACAO)
        return ExtracaoDoModelo.model_validate(resposta.model_dump())
    except (ModeloIndisponivel, RespostaInvalida, ValidationError) as erro:
        logger.warning("extração da pré-triagem vai para uma pessoa: %s", type(erro).__name__)
        return None


@rastreado(ETAPA_EXTRACAO)
def extrair_respostas(
    roteiro: RoteiroPreTriagem,
    mensagem: str,
    candidato: Candidato,
    cliente: ClienteModelo,
    pseudonimizar: PseudonimizarTexto,
    hoje: date,
) -> ExtracaoPreTriagem:
    """Transforma a mensagem em dados. A mensagem é dado, e o modelo não vê o nome da pessoa."""
    if (candidato.empresa_id, candidato.id) != (roteiro.empresa_id, roteiro.candidato_id):
        raise ValueError("o roteiro é de outra empresa ou pessoa")
    if not mensagem.strip():
        return ExtracaoPreTriagem(situacao=SituacaoExtracao.INVALIDA)
    texto = mensagem[:LIMITE_MENSAGEM]
    if _tem_instrucao(texto):
        logger.warning("instrução na resposta da pré-triagem do roteiro %s", roteiro.id)
        return ExtracaoPreTriagem(situacao=SituacaoExtracao.INSTRUCAO)
    limpo = _sem_frases_sensiveis(texto)
    if not limpo:
        return ExtracaoPreTriagem(situacao=SituacaoExtracao.VALIDA)
    pseudonimizado = pseudonimizar(candidato, limpo)
    extraido = _chamar_modelo(roteiro, pseudonimizado, cliente)
    if extraido is None:
        return ExtracaoPreTriagem(situacao=SituacaoExtracao.INVALIDA)
    if extraido.instrucoes_detectadas:
        logger.warning("o modelo apontou instrução na resposta do roteiro %s", roteiro.id)
        return ExtracaoPreTriagem(situacao=SituacaoExtracao.INSTRUCAO)
    return _conferir(roteiro, extraido, pseudonimizado, hoje)


def _conferir(
    roteiro: RoteiroPreTriagem, extraido: ExtracaoDoModelo, mensagem: str, hoje: date
) -> ExtracaoPreTriagem:
    invalida = ExtracaoPreTriagem(situacao=SituacaoExtracao.INVALIDA)
    perguntas = {p.id: p for p in roteiro.perguntas}
    identificadores = [r.pergunta_id for r in extraido.respostas]
    if not set(identificadores) <= set(perguntas) or len(set(identificadores)) != len(
        identificadores
    ):
        return invalida
    dados = []
    for resposta in extraido.respostas:
        dado = _dado_conferido(resposta, perguntas[resposta.pergunta_id], mensagem, hoje)
        if dado is None:
            return invalida
        dados.append(dado)
    return ExtracaoPreTriagem(situacao=SituacaoExtracao.VALIDA, respostas=dados)


def _fato_coletado(roteiro_id: str, dado: DadoPreTriagem, hoje: date) -> FatoColetado:
    return FatoColetado(
        fonte=dado.fonte,
        documento=f"pre_triagem:{roteiro_id}",
        coletado_em=hoje,
        texto=f"{dado.criterio}: {dado.situacao}",
        trecho=dado.trecho,
        tipo=TipoFato.DECLARADO,
    )


def atualizar_perfil(
    vaga: Vaga, roteiro_id: str, respostas: Sequence[DadoPreTriagem], hoje: date
) -> AtualizacaoPerfil:
    """O que muda no perfil, com fonte e data. Resposta incerta não muda nada.

    Resposta negativa grava um valor que nunca confere com o esperado, mesmo quando ele é `nao`.
    """
    requisitos = {r.id: r for r in vaga.requisitos}
    competencias = {c.nome for c in vaga.competencias}
    dados: dict[str, str] = {}
    fatos: list[FatoColetado] = []
    afetados: list[str] = []
    for resposta in respostas:
        if resposta.situacao == SituacaoResposta.INCERTA:
            continue
        criterio = resposta.criterio
        requisito = requisitos.get(criterio)
        if requisito is not None:
            confirmou = resposta.situacao == SituacaoResposta.CONFIRMA
            esperado = requisito.valor_esperado
            dados[requisito.campo] = esperado if confirmou else f"nao_atende:{esperado}"
            afetados.append(criterio)
        elif criterio in competencias:
            afetados.append(criterio)
        elif criterio != CRITERIO_DISPONIBILIDADE:
            continue
        dados[f"pre_triagem:{criterio}:fonte"] = resposta.fonte
        dados[f"pre_triagem:{criterio}:data"] = resposta.coletado_em.isoformat()
        fatos.append(_fato_coletado(roteiro_id, resposta, hoje))
    return AtualizacaoPerfil(dados=dados, fatos=fatos, criterios_afetados=sorted(afetados))


def registrar_no_perfil(
    banco: BancoTalentos, candidato: Candidato, atualizacao: AtualizacaoPerfil
) -> Candidato:
    """Grava no banco da empresa da pessoa. Sem dados novos, nada muda."""
    if not atualizacao.dados:
        return candidato
    return banco.atualizar(candidato.empresa_id, candidato.id, atualizacao.dados)


def _disponibilidade(
    respostas: Sequence[DadoPreTriagem],
) -> tuple[FatoIndisponibilidade | None, list[str]]:
    resposta = next((r for r in respostas if r.criterio == CRITERIO_DISPONIBILIDADE), None)
    if resposta is None or resposta.situacao == SituacaoResposta.INCERTA:
        return None, [PORTAO_DISPONIBILIDADE]
    if resposta.situacao == SituacaoResposta.CONFIRMA:
        return None, []
    try:
        fato = FatoIndisponibilidade(
            trecho=resposta.trecho,
            fonte=resposta.fonte,
            voltar_em=resposta.voltar_em,
            motivo=resposta.motivo,
        )
    except ValidationError:
        return None, [PORTAO_DISPONIBILIDADE]
    return fato, []


def _link_do_destino(
    destino: AgenteRecrutador | None, vaga_id: str, candidato_id: str
) -> tuple[str | None, bool]:
    """Falha no destino não desfaz a validação: o link fica para uma nova tentativa."""
    if destino is None:
        return None, False
    try:
        link = destino.link_agendamento(vaga_id, candidato_id)
    except (ErroContrato, ConnectionError, TimeoutError, OSError) as erro:
        logger.warning("link do destino indisponível: %s", type(erro).__name__)
        return None, True
    if link is None:
        return None, False
    if not link.startswith(("https://", "http://")):
        logger.warning("link do destino recusado na vaga %s", vaga_id)
        return None, True
    return link, False


def _situacao_do_destino(destino: DestinoDecisao) -> SituacaoPreTriagem:
    if destino == DestinoDecisao.APROVAR:
        return SituacaoPreTriagem.PASSOU
    if destino == DestinoDecisao.REVISAO_HUMANA:
        return SituacaoPreTriagem.AMBIGUO
    return SituacaoPreTriagem.NAO_PASSOU


@rastreado(ETAPA_VALIDACAO)
def validar_pre_triagem(
    decisao: DecisaoFinal,
    roteiro: RoteiroPreTriagem,
    extracao: ExtracaoPreTriagem,
    vaga: Vaga,
    candidato: Candidato,
    mandato: Mandato,
    hoje: date,
    agora: datetime,
    rastro_id: str,
    *,
    destino: AgenteRecrutador | None = None,
    limiar_certificado: float | None = None,
) -> ResultadoPreTriagem:
    """Decide em código: passou recebe link, ambíguo vai a uma pessoa, não passou cai em recusa
    ou garden. Só reavalia os critérios respondidos. Não grava nem envia nada.
    """
    if (roteiro.empresa_id, roteiro.vaga_id, roteiro.candidato_id) != (
        decisao.empresa_id,
        decisao.vaga_id,
        decisao.candidato_id,
    ):
        raise ValueError("o roteiro é de outra empresa, vaga ou pessoa")

    if extracao.situacao != SituacaoExtracao.VALIDA:
        portao = (
            PORTAO_INSTRUCAO
            if extracao.situacao == SituacaoExtracao.INSTRUCAO
            else PORTAO_EXTRACAO_INVALIDA
        )
        nova = reavaliar_criterios(
            decisao,
            vaga,
            candidato,
            mandato,
            [],
            hoje,
            agora,
            rastro_id,
            limiar_certificado=limiar_certificado,
            portoes_extras=[portao],
        )
        return ResultadoPreTriagem(situacao=_situacao_do_destino(nova.destino), decisao=nova)

    perguntados = {p.criterio for p in roteiro.perguntas}
    respostas = [r for r in extracao.respostas if r.criterio in perguntados]
    atualizacao = atualizar_perfil(vaga, roteiro.id, respostas, hoje)
    atualizado = candidato.model_copy(
        update={"atributos": {**candidato.atributos, **atualizacao.dados}}
    )
    novos = [
        RespostaCriterio(r.criterio, r.trecho, r.fonte, r.nivel)
        for r in respostas
        if r.criterio in atualizacao.criterios_afetados
    ]
    fato, extras = _disponibilidade(respostas)
    nova = reavaliar_criterios(
        decisao,
        vaga,
        atualizado,
        mandato,
        novos,
        hoje,
        agora,
        rastro_id,
        indisponibilidade=fato,
        limiar_certificado=limiar_certificado,
        portoes_extras=extras,
    )
    situacao = _situacao_do_destino(nova.destino)
    link, indisponivel = (None, False)
    if situacao == SituacaoPreTriagem.PASSOU:
        link, indisponivel = _link_do_destino(destino, vaga.id, candidato.id)
    return ResultadoPreTriagem(
        situacao=situacao,
        decisao=nova,
        atualizacao=atualizacao,
        respostas=respostas,
        link_agendamento=link,
        link_indisponivel=indisponivel,
    )


def montar_contexto_onboarding(
    decisao: DecisaoFinal,
    roteiro: RoteiroPreTriagem,
    vaga: Vaga,
    candidato: Candidato,
    hoje: date,
) -> ContextoOnboarding:
    """O que o canal recebe para abrir a conversa. Sem autorização válida, não há conversa."""
    if (roteiro.empresa_id, roteiro.vaga_id, roteiro.candidato_id) != (
        decisao.empresa_id,
        decisao.vaga_id,
        decisao.candidato_id,
    ):
        raise ValueError("o roteiro é de outra empresa, vaga ou pessoa")
    if (candidato.empresa_id, candidato.id) != (decisao.empresa_id, decisao.candidato_id):
        raise ValueError("a decisão é de outra empresa ou pessoa")
    validade = candidato.autorizacao_valida_ate
    if not autorizacao_ativa(candidato, hoje) or validade is None:
        raise RoteiroIndevido("sem autorização válida não há contato")
    return ContextoOnboarding(
        empresa_id=decisao.empresa_id,
        vaga_id=decisao.vaga_id,
        candidato_id=decisao.candidato_id,
        nome_tratamento=candidato.nome,
        titulo_vaga=vaga.titulo,
        motivo_contato=roteiro.motivo_contato,
        origem_contato=candidato.origem,
        fonte=candidato.fonte,
        autorizacao_valida_ate=validade,
        roteiro=roteiro,
        simulado=decisao.simulado or candidato.simulado,
    )


def pacote_com_pre_triagem(
    pacote: PacoteContexto,
    decisao: DecisaoFinal,
    vaga: Vaga,
    respostas: Sequence[DadoPreTriagem],
) -> PacoteContexto:
    """Acrescenta ao pacote os pontos a explorar e as respostas, sem mudar o que já há nele."""
    if (pacote.empresa_id, pacote.vaga_id, pacote.candidato_id) != (
        decisao.empresa_id,
        decisao.vaga_id,
        decisao.candidato_id,
    ):
        raise ValueError("o pacote é de outra empresa, vaga ou pessoa")
    return PacoteContexto.model_validate(
        {
            **pacote.model_dump(),
            "pontos_a_explorar": pontos_a_explorar(decisao, vaga),
            "respostas_pre_triagem": list(respostas),
        }
    )
