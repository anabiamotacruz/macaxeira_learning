"""Feedback à pessoa: só quando ela pede, a partir do registro da decisão. Tudo em código.

Cada motivo liga um critério a um trecho registrado. Motivo sensível, contestação e decisão sem
critério não atendido vão para a pessoa responsável. Quando a decisão veio da entrevista, só sai o
que o agente de destino informou. Nota, faixa, ranking e outros candidatos não têm campo nem
aparecem no texto. Toda geração é registrada antes de sair: sem auditoria, nada é entregue.

Do registro de decisões vem a decisão final guardada nela. Registro sem ela não tem lacuna para
citar: o pedido vai para a pessoa responsável.
"""

import hashlib
import re
from collections.abc import Callable, Sequence
from datetime import datetime

from backend.agente.auditoria import PREFIXO_HUMANO, rastreado
from backend.agente.decisao_final import decisao_final_do_registro
from backend.agente.neutralizacao import MARCADOR, neutralizar_genero
from backend.agente.regras import FONTE_REGRA, REGRA_FUNIL_REQUISITO
from backend.contratos.criterios import sem_acento, termos_proibidos_em_conversa
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import (
    REGRA_RECUSA_AUTORIZACAO,
    Decisao,
    DecisaoFinal,
    DestinoDecisao,
    EventoFluxo,
    Evidencia,
    FeedbackCandidato,
    LacunaCriterio,
    MotivoFeedback,
    MotivoLacuna,
    PedidoFeedback,
    RetornoDestino,
    StatusFeedback,
    TipoCriterio,
    TipoDecisao,
    Vaga,
)

ETAPA_FEEDBACK = "feedback"
ENCAMINHADO_CONTESTACAO = "contestacao"
ENCAMINHADO_SENSIVEL = "motivo_sensivel"
ENCAMINHADO_SEM_TRECHO = "motivo_sem_trecho_registrado"
ENCAMINHADO_SEM_CRITERIO = "sem_criterio_nao_atendido"
ENCAMINHADO_DESTINO_SEM_MOTIVO = "destino_nao_informou"
ENCAMINHADO_DESTINO_FORA = "destino_fora_dos_criterios"
ENCAMINHADO_SEM_DECISAO_FINAL = "decisao_sem_lacunas_registradas"
TEXTO_ENCAMINHADO = "Seu pedido foi encaminhado à pessoa responsável, que vai responder a você."
DADO_RETIRADO = "(dado retirado)"
PREFIXO_ASSINANTE = ":assinante:"

_EVIDENCIA_FALTANTE = {
    MotivoLacuna.NAO_ATENDE: "O registro mostra que este requisito não foi atendido.",
    MotivoLacuna.SEM_DADO: "Não encontramos essa informação no seu perfil nem nas suas respostas.",
    MotivoLacuna.SEM_EVIDENCIA_ACEITA: "Faltou uma comprovação aceita por esta vaga.",
    MotivoLacuna.NAO_CONFIRMADO: "A análise não confirmou este requisito.",
    MotivoLacuna.SEM_EVIDENCIA: "Faltou um trecho do seu perfil que mostre esta competência.",
}
_O_QUE_PODE_MUDAR = {
    MotivoLacuna.NAO_ATENDE: "Atender a este requisito poderia mudar o resultado.",
    MotivoLacuna.SEM_DADO: "Informar este dado, com um exemplo, poderia mudar o resultado.",
    MotivoLacuna.SEM_EVIDENCIA_ACEITA: "Uma comprovação verificável poderia mudar o resultado.",
    MotivoLacuna.NAO_CONFIRMADO: "Um exemplo concreto poderia mudar o resultado.",
    MotivoLacuna.SEM_EVIDENCIA: "Um exemplo concreto no seu perfil poderia mudar o resultado.",
}
_DESENVOLVER = "Desenvolver este requisito poderia mudar o resultado em uma próxima vaga."

_CONTESTACAO = re.compile(r"\b(contest\w*|discord\w*|injust\w*|recorr\w*|recurso|revis[ae]\w*)\b")
_NOTA_OU_RANKING = re.compile(
    r"\b(notas?|score|pontuacao|pontos|ranking|posicao|colocacao|classificacao)\b"
    r"|\boutr[oa]s? (candidat|pesso)"
    r"|\b\d+\s*(de|/)\s*\d+\b"
)
"""Sobre o texto sem acento nem caixa. O que fala de nota ou compara pessoas não sai."""


class FeedbackNegado(ErroContrato):
    """Pedido de outra pessoa, vaga ou empresa, ou sem registro. Não revela o que existe."""


RegistrarEvento = Callable[[EventoFluxo], None]


def _normalizado(texto: str) -> str:
    return " ".join(sem_acento(texto).casefold().split())


def _bloqueado(*textos: str) -> bool:
    if termos_proibidos_em_conversa(*textos):
        return True
    return any(_NOTA_OU_RANKING.search(_normalizado(texto)) for texto in textos)


def _para_a_pessoa(trecho: str) -> str:
    """O mesmo trecho para qualquer gênero, e sem marcador da pseudonimização."""
    return MARCADOR.sub(DADO_RETIRADO, neutralizar_genero(trecho))


def _responsavel(decisao: DecisaoFinal | Decisao | None) -> str | None:
    if decisao is None:
        return None
    responsavel = decisao.responsavel
    if PREFIXO_ASSINANTE in responsavel:
        return responsavel.rpartition(PREFIXO_ASSINANTE)[2]
    return responsavel.removeprefix(PREFIXO_HUMANO)


def _trecho_registrado(lacuna: LacunaCriterio, evidencias: Sequence[Evidencia]) -> Evidencia | None:
    """Prefere o que a pessoa escreveu. Sem isso, o critério que a regra registrou."""
    citadas = [e for e in evidencias if e.criterio == lacuna.criterio and e.trecho.strip()]
    do_perfil = [e for e in citadas if e.fonte != FONTE_REGRA]
    return next(iter(do_perfil or citadas), None)


def _motivo_da_lacuna(lacuna: LacunaCriterio, evidencia: Evidencia) -> MotivoFeedback:
    desenvolver = lacuna.desenvolvivel and lacuna.tipo == TipoCriterio.REQUISITO
    return MotivoFeedback(
        criterio=lacuna.criterio,
        descricao=lacuna.descricao,
        trecho=_para_a_pessoa(evidencia.trecho),
        fonte=evidencia.fonte,
        evidencia_faltante=_EVIDENCIA_FALTANTE[lacuna.motivo],
        o_que_pode_mudar=_DESENVOLVER if desenvolver else _O_QUE_PODE_MUDAR[lacuna.motivo],
    )


def _ha_criterio_nao_atendido(decisao: DecisaoFinal) -> bool:
    if decisao.regra == REGRA_RECUSA_AUTORIZACAO or decisao.pendente_confirmacao:
        return False
    return decisao.destino in (DestinoDecisao.RECUSAR, DestinoDecisao.GARDEN_A_LAPIDAR)


def _motivos_da_decisao(decisao: DecisaoFinal) -> tuple[list[MotivoFeedback], str | None]:
    if not _ha_criterio_nao_atendido(decisao) or not decisao.lacunas:
        return [], ENCAMINHADO_SEM_CRITERIO
    lacunas = sorted(
        decisao.lacunas, key=lambda lacuna: (lacuna.tipo != TipoCriterio.REQUISITO, lacuna.criterio)
    )
    motivos = []
    sem_trecho = False
    for lacuna in lacunas:
        evidencia = _trecho_registrado(lacuna, decisao.evidencias)
        trecho = "" if evidencia is None else evidencia.trecho
        if _bloqueado(lacuna.criterio, lacuna.descricao, trecho):
            return [], ENCAMINHADO_SENSIVEL
        if evidencia is None:
            sem_trecho = True
        else:
            motivos.append(_motivo_da_lacuna(lacuna, evidencia))
    return ([], ENCAMINHADO_SEM_TRECHO) if sem_trecho else (motivos, None)


def _motivos_do_corte(registro: Decisao, vaga: Vaga) -> tuple[list[MotivoFeedback], str | None]:
    """Descarte do funil por requisito: o requisito e o valor registrado que o reprovou.

    Outro registro sem decisão final não tem lacuna para citar e vai para a pessoa responsável.
    """
    if registro.tipo != TipoDecisao.DESCARTAR or registro.regra != REGRA_FUNIL_REQUISITO:
        return [], ENCAMINHADO_SEM_DECISAO_FINAL
    requisitos = {r.id: r for r in vaga.requisitos}
    citadas = [
        e
        for e in registro.evidencias
        if e.criterio in requisitos and e.fonte != FONTE_REGRA and e.trecho.strip()
    ]
    if not citadas:
        return [], ENCAMINHADO_SEM_TRECHO
    motivos = []
    for evidencia in citadas:
        requisito = requisitos[evidencia.criterio]
        if _bloqueado(requisito.id, requisito.descricao, evidencia.trecho):
            return [], ENCAMINHADO_SENSIVEL
        motivos.append(
            MotivoFeedback(
                criterio=requisito.id,
                descricao=requisito.descricao,
                trecho=_para_a_pessoa(evidencia.trecho),
                fonte=evidencia.fonte,
                evidencia_faltante=_EVIDENCIA_FALTANTE[MotivoLacuna.NAO_ATENDE],
                o_que_pode_mudar=(
                    _DESENVOLVER
                    if requisito.desenvolvivel
                    else _O_QUE_PODE_MUDAR[MotivoLacuna.NAO_ATENDE]
                ),
            )
        )
    return motivos, None


def _descricoes_dos_criterios(vaga: Vaga) -> dict[str, str]:
    return {
        **{r.id: r.descricao for r in vaga.requisitos},
        **{c.nome: c.nome for c in vaga.competencias},
    }


def _motivos_do_destino(
    retorno: RetornoDestino, vaga: Vaga
) -> tuple[list[MotivoFeedback], str | None]:
    """Só o que o destino disse, palavra por palavra. A análise do agente não entra aqui."""
    if not retorno.motivos:
        return [], ENCAMINHADO_DESTINO_SEM_MOTIVO
    descricoes = _descricoes_dos_criterios(vaga)
    motivos = []
    for motivo in retorno.motivos:
        if _bloqueado(motivo.criterio, motivo.trecho):
            return [], ENCAMINHADO_SENSIVEL
        if motivo.criterio not in descricoes:
            return [], ENCAMINHADO_DESTINO_FORA
        motivos.append(
            MotivoFeedback(
                criterio=motivo.criterio,
                descricao=descricoes[motivo.criterio],
                trecho=_para_a_pessoa(motivo.trecho),
                fonte=retorno.fonte,
                evidencia_faltante="",
                o_que_pode_mudar="",
            )
        )
    return motivos, None


def _texto(vaga: Vaga, motivos: Sequence[MotivoFeedback]) -> str:
    linhas = [f"Sobre a vaga {vaga.titulo}, estes critérios não foram atendidos:"]
    for motivo in motivos:
        complemento = " ".join(
            parte for parte in (motivo.evidencia_faltante, motivo.o_que_pode_mudar) if parte
        )
        linha = f'- {motivo.descricao}. Registro: "{motivo.trecho}".'
        linhas.append(f"{linha} {complemento}".strip())
    return "\n".join(linhas)


def _exigir_mesma_pessoa(
    pedido: PedidoFeedback,
    vaga: Vaga,
    decisao: DecisaoFinal | None,
    retorno: RetornoDestino | None,
    registro: Decisao | None,
) -> None:
    if decisao is None and retorno is None and registro is None:
        raise FeedbackNegado("não há decisão registrada para este pedido")
    alvo = (pedido.empresa_id, pedido.vaga_id, pedido.candidato_id)
    registros = [r for r in (decisao, retorno, registro) if r is not None]
    if (vaga.empresa_id, vaga.id) != alvo[:2] or any(
        (r.empresa_id, r.vaga_id, r.candidato_id) != alvo for r in registros
    ):
        raise FeedbackNegado("pedido sem registro correspondente")


def _registrar(
    registrar: RegistrarEvento,
    pedido: PedidoFeedback,
    feedback: FeedbackCandidato,
    decisao: DecisaoFinal | Decisao | None,
    retorno: RetornoDestino | None,
    agora: datetime,
) -> None:
    """Só códigos e critérios. Não leva o nome, o texto do pedido nem o motivo bloqueado."""
    resumo = hashlib.sha256(feedback.texto.encode("utf-8")).hexdigest()[:16]
    partes = {
        "status": feedback.status.value,
        "canal": pedido.canal,
        "origem": "destino" if retorno is not None else "decisao",
        "regra": "nao_se_aplica" if decisao is None else decisao.regra,
        "encaminhado_por": feedback.encaminhado_por or "nao_se_aplica",
        "criterios": ",".join(m.criterio for m in feedback.motivos) or "nenhum",
        "responsavel": feedback.responsavel or "nao_informado",
        "texto_sha256": resumo,
    }
    registrar(
        EventoFluxo(
            empresa_id=pedido.empresa_id,
            vaga_id=pedido.vaga_id,
            candidato_id=pedido.candidato_id,
            etapa=ETAPA_FEEDBACK,
            mensagem="; ".join(f"{chave}={valor}" for chave, valor in partes.items()),
            momento=agora,
        )
    )


@rastreado(ETAPA_FEEDBACK)
def responder_pedido_de_feedback(
    pedido: PedidoFeedback,
    vaga: Vaga,
    nome_tratamento: str,
    *,
    registrar: RegistrarEvento,
    agora: datetime,
    decisao: DecisaoFinal | None = None,
    retorno: RetornoDestino | None = None,
    registro: Decisao | None = None,
) -> FeedbackCandidato:
    """Responde ao pedido da pessoa, ou o encaminha. Com `retorno`, a decisão veio da entrevista.

    `registro` é a decisão vigente no registro de decisões, quando não há `decisao` à mão.
    O texto do pedido é dado: só serve para reconhecer contestação e não entra em lugar nenhum.
    """
    _exigir_mesma_pessoa(pedido, vaga, decisao, retorno, registro)
    if decisao is None and registro is not None:
        decisao = decisao_final_do_registro(registro)
    saudacao = f"Olá, {nome_tratamento}."
    motivos: list[MotivoFeedback] = []
    if pedido.contestacao or _CONTESTACAO.search(_normalizado(pedido.texto)):
        encaminhado = ENCAMINHADO_CONTESTACAO
    elif retorno is not None:
        motivos, encaminhado = _motivos_do_destino(retorno, vaga)
    elif decisao is None and registro is not None:
        motivos, encaminhado = _motivos_do_corte(registro, vaga)
    elif decisao is None:
        encaminhado = ENCAMINHADO_SEM_DECISAO_FINAL
    else:
        motivos, encaminhado = _motivos_da_decisao(decisao)
    if encaminhado is not None:
        feedback = FeedbackCandidato(
            status=StatusFeedback.ENCAMINHADO,
            saudacao=saudacao,
            texto=TEXTO_ENCAMINHADO,
            encaminhado_por=encaminhado,
            responsavel=_responsavel(decisao or registro),
        )
    else:
        feedback = FeedbackCandidato(
            status=StatusFeedback.GERADO,
            saudacao=saudacao,
            texto=_texto(vaga, motivos),
            motivos=motivos,
        )
    _registrar(registrar, pedido, feedback, decisao or registro, retorno, agora)
    return feedback
