"""Lembrete único para quem não respondeu (T3.7; #50, seção 9; FR-C006 a FR-C008).

A decisão é determinística, recebe `hoje` e não usa modelo. Há no máximo um
lembrete por vaga, depois do intervalo mínimo. Sem resposta depois do lembrete,
o contato é encerrado como silêncio. Resposta, exclusão ou `pode_contatar` falso
cancelam o lembrete.

`SituacaoContato` é um tipo local da frente até o `Contato` do #50 (seção 7)
entrar em `backend/contratos` (#9).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict

from backend.contato.email_inicial import (
    ContatoBloqueado,
    EmailConvite,
    MensageiroEmailSimulado,
)
from backend.contato.supressao import ListaSupressao

logger = logging.getLogger(__name__)

INTERVALO_PADRAO = timedelta(days=3)


class AcaoLembrete(StrEnum):
    ESPERAR = "esperar"
    ENVIAR_LEMBRETE = "enviar_lembrete"
    ENCERRAR_SILENCIO = "encerrar_silencio"
    NADA = "nada"


class SituacaoContato(BaseModel):
    """Estado do contato de uma pessoa numa vaga."""

    model_config = ConfigDict(extra="forbid")

    empresa_id: str
    vaga_id: str
    candidato_id: str
    para: str
    enviado_em: AwareDatetime
    lembrete_em: AwareDatetime | None = None
    respondeu_em: AwareDatetime | None = None
    suprimido: bool = False
    encerrado: bool = False


@dataclass(frozen=True)
class DecisaoLembrete:
    """Decisão registrada com a regra aplicada (FR-014)."""

    empresa_id: str
    vaga_id: str
    candidato_id: str
    acao: AcaoLembrete
    regra: str
    momento: datetime


def decidir_lembrete(
    situacao: SituacaoContato, hoje: datetime, intervalo: timedelta = INTERVALO_PADRAO
) -> DecisaoLembrete:
    """Decide, sem modelo, o que fazer com o contato hoje."""

    def decisao(acao: AcaoLembrete, regra: str) -> DecisaoLembrete:
        return DecisaoLembrete(
            situacao.empresa_id, situacao.vaga_id, situacao.candidato_id, acao, regra, hoje
        )

    if situacao.encerrado:
        return decisao(AcaoLembrete.NADA, "encerrado")
    if situacao.respondeu_em is not None:
        return decisao(AcaoLembrete.NADA, "respondeu")
    if situacao.suprimido:
        return decisao(AcaoLembrete.NADA, "lista_supressao")
    if situacao.lembrete_em is None:
        if hoje - situacao.enviado_em >= intervalo:
            return decisao(AcaoLembrete.ENVIAR_LEMBRETE, "intervalo_sem_resposta")
        return decisao(AcaoLembrete.ESPERAR, "dentro_do_intervalo")
    if hoje - situacao.lembrete_em >= intervalo:
        return decisao(AcaoLembrete.ENCERRAR_SILENCIO, "silencio_apos_lembrete")
    return decisao(AcaoLembrete.ESPERAR, "dentro_do_intervalo")


def _tentativa(email: EmailConvite) -> int:
    return int(email.convite.chave_idempotencia.rsplit(":", 1)[-1])


class AgendaLembretes:
    """Acompanha os e-mails iniciais e envia o lembrete na hora certa.

    Quem chama avisa as respostas (e-mail ou WhatsApp) com `registrar_resposta`.
    A exclusão é lida direto da lista de supressão.
    """

    def __init__(self, lista: ListaSupressao) -> None:
        self.lista = lista
        self._situacoes: dict[tuple[str, str, str], SituacaoContato] = {}

    def registrar_envio(self, email: EmailConvite, momento: datetime) -> None:
        """Registra o e-mail inicial. Repetir o registro não muda nada."""
        if _tentativa(email) != 1:
            raise ValueError("só o e-mail inicial entra na agenda")
        convite = email.convite
        chave = (convite.empresa_id, convite.vaga_id or "", convite.candidato_id)
        if chave in self._situacoes:
            return
        self._situacoes[chave] = SituacaoContato(
            empresa_id=chave[0],
            vaga_id=chave[1],
            candidato_id=chave[2],
            para=email.para,
            enviado_em=momento,
        )

    def registrar_resposta(
        self, empresa_id: str, vaga_id: str, candidato_id: str, momento: datetime
    ) -> None:
        situacao = self._situacoes.get((empresa_id, vaga_id, candidato_id))
        if situacao is not None and situacao.respondeu_em is None:
            situacao.respondeu_em = momento
            logger.info("lembrete cancelado por resposta: vaga=%s", vaga_id)

    def situacao(self, empresa_id: str, vaga_id: str, candidato_id: str) -> SituacaoContato | None:
        return self._situacoes.get((empresa_id, vaga_id, candidato_id))

    def processar(
        self,
        hoje: datetime,
        criar_lembrete: Callable[[SituacaoContato], EmailConvite],
        emails: MensageiroEmailSimulado,
        *,
        intervalo: timedelta = INTERVALO_PADRAO,
        pode_contatar: Callable[[str, str, str], bool] | None = None,
    ) -> list[DecisaoLembrete]:
        """Roda a rodada do dia. Devolve os lembretes enviados, os bloqueios e os encerramentos."""
        decisoes = []
        for situacao in self._situacoes.values():
            situacao.suprimido = situacao.suprimido or self.lista.esta_suprimido(
                situacao.empresa_id, [situacao.para]
            )
            decisao = decidir_lembrete(situacao, hoje, intervalo)
            if decisao.acao == AcaoLembrete.NADA:
                situacao.encerrado = True
            elif decisao.acao == AcaoLembrete.ENCERRAR_SILENCIO:
                situacao.encerrado = True
                decisoes.append(decisao)
            elif decisao.acao == AcaoLembrete.ENVIAR_LEMBRETE:
                resultado = self._enviar(situacao, decisao, criar_lembrete, emails, pode_contatar)
                if resultado is not None:
                    decisoes.append(resultado)
        for decisao in decisoes:
            logger.info(
                "lembrete: vaga=%s candidato=%s acao=%s regra=%s",
                decisao.vaga_id,
                decisao.candidato_id,
                decisao.acao,
                decisao.regra,
            )
        return decisoes

    def _enviar(
        self,
        situacao: SituacaoContato,
        decisao: DecisaoLembrete,
        criar_lembrete: Callable[[SituacaoContato], EmailConvite],
        emails: MensageiroEmailSimulado,
        pode_contatar: Callable[[str, str, str], bool] | None,
    ) -> DecisaoLembrete | None:
        def bloqueio(regra: str) -> DecisaoLembrete:
            situacao.encerrado = True
            return DecisaoLembrete(
                situacao.empresa_id,
                situacao.vaga_id,
                situacao.candidato_id,
                AcaoLembrete.NADA,
                regra,
                decisao.momento,
            )

        if pode_contatar is not None and not pode_contatar(
            situacao.empresa_id, situacao.vaga_id, situacao.candidato_id
        ):
            return bloqueio("pode_contatar")
        try:
            enviado = emails.enviar(criar_lembrete(situacao))
        except ContatoBloqueado as erro:
            return bloqueio(erro.regra)
        if not enviado:
            logger.warning("lembrete não enviado, nova tentativa na próxima rodada")
            return None
        situacao.lembrete_em = decisao.momento
        return decisao
