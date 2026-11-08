"""Atendimento pelo WhatsApp real, ligado ao fluxo da vaga.

A pessoa recebe o convite com um link `wa.me` e um código. Quando ela escreve para o número da
empresa com esse código, a conversa se liga ao convite. A partir daí:

- "sim", "quero", "tenho interesse" viram aceite: o fluxo entrega o contexto à Nara e a pessoa
  recebe o link de agendamento;
- "não" vira recusa;
- pergunta vira dúvida: o fluxo responde pelo material da vaga ou deixa para uma pessoa;
- "SAIR" vira opt-out, com prioridade sobre tudo.

O agente nunca começa a conversa, nunca agenda e nunca avalia: só registra a resposta no fluxo,
que aplica as regras em código. O texto da pessoa é dado, nunca instrução. Cada resposta sai em
texto e, com a voz ligada, também em áudio.
"""

import logging
import re
import threading
import unicodedata
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.agente.fluxo import EstadoConvite, RegistroConvite
from backend.agente.servico import ServicoVagas
from backend.contato.conversa import pede_saida
from backend.contato.email_inicial import codigo_convite
from backend.contato.evolution import ClienteEvolution, EnvioFalhou, MensagemRecebida, mascarar
from backend.contato.voz import SintetizadorFeatherless, SintetizadorSimulado, VozIndisponivel
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import RespostaCandidato, TipoResposta

logger = logging.getLogger(__name__)

_CODIGO = re.compile(r"\b[A-Za-z2-7]{6}\b")
_NAO = re.compile(r"\b(nao|n|sem interesse|nao tenho interesse|nao quero|dispenso)\b")
_SIM = re.compile(
    r"\b(sim|s|quero|tenho interesse|aceito|topo|bora|vamos|pode ser|claro|com certeza|agendar)\b"
)

MENSAGEM_SEM_CODIGO = (
    "Olá! Aqui é o agente de recrutamento. Para eu achar o seu convite, mande a mensagem com o "
    "código que veio no e-mail, por exemplo: Vaga ABC234."
)
MENSAGEM_SAIDA = "Pronto, você não vai mais receber mensagens nossas. Obrigado pelo seu tempo."
MENSAGEM_AUDIO = "Recebi seu áudio, mas por aqui eu ainda só leio texto. Pode escrever a mensagem?"
MENSAGEM_ENCAMINHADA = (
    "Boa pergunta! Vou passar para uma pessoa da equipe, que te responde por aqui."
)
CONVITE_A_SEGUIR = "Quer seguir com a vaga? Responda SIM para agendar a entrevista."

_INDICE: dict[str, tuple[str, str, str]] = {}
_NUMERO: list[str] = []
_TRAVA_INDICE = threading.Lock()


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^\w? ]", " ", sem_acento.lower()).split())


def configurar_numero(numero: str | None) -> None:
    """O número pareado na Evolution, que vai no link `wa.me` do convite."""
    _NUMERO.clear()
    if numero:
        _NUMERO.append(numero)


def linha_do_convite(empresa_id: str, vaga_id: str, candidato_id: str) -> str:
    """Registra o código do convite e devolve a linha com o link do WhatsApp, se houver número."""
    codigo = codigo_convite(empresa_id, vaga_id, candidato_id)
    with _TRAVA_INDICE:
        _INDICE[codigo] = (empresa_id, vaga_id, candidato_id)
    if not _NUMERO:
        return ""
    link = f"https://wa.me/{_NUMERO[0]}?text=Vaga%20{codigo}"
    return f" Prefere conversar agora? Fale com a gente no WhatsApp: {link} (código {codigo})."


def classificar(texto: str) -> TipoResposta:
    """Aceite, recusa ou dúvida, em código. Pergunta é sempre dúvida."""
    normalizado = _normalizar(texto)
    if "?" in texto:
        return TipoResposta.DUVIDA
    if _NAO.search(normalizado):
        return TipoResposta.RECUSA
    if _SIM.search(normalizado):
        return TipoResposta.ACEITE
    return TipoResposta.DUVIDA


class MensagemConversa(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    direcao: Literal["entrada", "saida"]
    texto: str
    momento: datetime
    audio_id: str | None = None
    enviada: bool = True


class Conversa(BaseModel):
    """A conversa de um número com um convite. O número completo nunca sai na API."""

    model_config = ConfigDict(extra="forbid")

    numero_mascarado: str
    empresa_id: str
    vaga_id: str
    candidato_id: str
    codigo: str
    encerrada: bool = False
    mensagens: list[MensagemConversa] = []
    simulado: bool = False
    """O canal e a voz são reais. O perfil do convite é sintético na demonstração."""


class AtendimentoWhatsApp:
    def __init__(
        self,
        obter_servico: Callable[[], ServicoVagas],
        canal: ClienteEvolution,
        sintetizador: SintetizadorFeatherless | SintetizadorSimulado | None = None,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._obter_servico = obter_servico
        self.canal = canal
        self.sintetizador = sintetizador
        self._relogio = relogio
        self._trava = threading.Lock()
        self._conversas: dict[str, Conversa] = {}
        self._enderecos: dict[str, str] = {}
        self._audios: dict[str, bytes] = {}

    # Leitura, para o painel

    def conversas(self, empresa_id: str, vaga_id: str) -> list[Conversa]:
        with self._trava:
            return [
                c.model_copy(deep=True)
                for c in self._conversas.values()
                if c.empresa_id == empresa_id and c.vaga_id == vaga_id
            ]

    def audio(self, audio_id: str) -> bytes | None:
        return self._audios.get(audio_id)

    # Atendimento

    def atender(self, mensagem: MensagemRecebida) -> list[str]:
        with self._trava:
            self._enderecos[mensagem.numero] = mensagem.responder_para
            conversa = self._conversas.get(mensagem.numero)
            if conversa is not None:
                self._anotar(conversa, "entrada", mensagem.texto or "[áudio]")
            respostas = self._responder(mensagem, conversa)
            atual = self._conversas.get(mensagem.numero)
            for resposta in respostas:
                self._enviar(mensagem.numero, atual, resposta)
            return respostas

    def _responder(self, mensagem: MensagemRecebida, conversa: Conversa | None) -> list[str]:
        texto = mensagem.texto.strip()
        if mensagem.tipo == "audio":
            return [MENSAGEM_AUDIO]
        if conversa is not None and conversa.encerrada:
            return []
        if pede_saida(texto):
            if conversa is not None:
                self._registrar(conversa, TipoResposta.OPT_OUT, texto)
                conversa.encerrada = True
            logger.info("whatsapp: saída pedida por %s", mascarar(mensagem.numero))
            return [MENSAGEM_SAIDA]
        nova = self._ligar_por_codigo(mensagem, texto)
        if nova is not None:
            return nova
        if conversa is None:
            return [MENSAGEM_SEM_CODIGO]
        return self._seguir(conversa, texto)

    def _ligar_por_codigo(self, mensagem: MensagemRecebida, texto: str) -> list[str] | None:
        for candidato in _CODIGO.findall(texto):
            with _TRAVA_INDICE:
                alvo = _INDICE.get(candidato.upper())
            if alvo is None:
                continue
            empresa_id, vaga_id, candidato_id = alvo
            conversa = Conversa(
                numero_mascarado=mascarar(mensagem.numero), empresa_id=empresa_id,
                vaga_id=vaga_id, candidato_id=candidato_id, codigo=candidato.upper(),
            )
            self._conversas[mensagem.numero] = conversa
            self._anotar(conversa, "entrada", texto)
            titulo = self._titulo(empresa_id, vaga_id)
            logger.info("whatsapp: conversa ligada ao convite %s", conversa.codigo)
            return [
                f"Olá! Aqui é o agente de recrutamento da vaga de {titulo}. Que bom que você "
                "escreveu! Quer seguir? Responda SIM para agendar a entrevista com a nossa "
                "recrutadora, NÃO se não tiver interesse, ou mande a sua dúvida sobre a vaga. "
                "Para não receber mais mensagens, responda SAIR."
            ]
        return None

    def _titulo(self, empresa_id: str, vaga_id: str) -> str:
        try:
            return self._obter_servico().consultar(empresa_id, vaga_id).vaga.titulo
        except ErroContrato:
            return "que te convidamos"

    def _registro(self, conversa: Conversa) -> RegistroConvite | None:
        registros = [
            r
            for r in self._obter_servico().convites(conversa.empresa_id, conversa.vaga_id)
            if r.convite.candidato_id == conversa.candidato_id
        ]
        return max(registros, key=lambda r: r.tentativa, default=None)

    def _registrar(self, conversa: Conversa, tipo: TipoResposta, texto: str) -> bool:
        registro = self._registro(conversa)
        if registro is None:
            return False
        try:
            self._obter_servico().registrar_resposta(
                conversa.empresa_id,
                conversa.vaga_id,
                RespostaCandidato(convite_id=registro.convite.id, tipo=tipo, texto=texto),
            )
        except ErroContrato:
            logger.warning("whatsapp: o fluxo não aceitou a resposta (%s)", tipo, exc_info=True)
            return False
        return True

    def _seguir(self, conversa: Conversa, texto: str) -> list[str]:
        tipo = classificar(texto)
        if not self._registrar(conversa, tipo, texto):
            return ["Anotei! Uma pessoa da equipe vai te responder por aqui."]
        registro = self._registro(conversa)
        if tipo == TipoResposta.ACEITE:
            if registro is not None and registro.estado == EstadoConvite.ENCERRADO:
                return ["Esse convite já foi encerrado. Uma pessoa da equipe vai te responder."]
            link = None if registro is None else registro.convite.link_agendamento
            if link:
                return [
                    "Ótimo! Você pode agendar a entrevista com a nossa recrutadora, a Nara, "
                    f"aqui: {link}"
                ]
            return ["Ótimo! A equipe vai entrar em contato para combinar a entrevista."]
        if tipo == TipoResposta.RECUSA:
            return ["Tudo bem, obrigado por responder! Se mudar de ideia, é só mandar mensagem."]
        duvida = next(
            (d for d in reversed(registro.duvidas) if d.pergunta == texto), None
        ) if registro is not None else None
        if duvida is None or not duvida.resposta:
            return [MENSAGEM_ENCAMINHADA]
        return [duvida.resposta, CONVITE_A_SEGUIR]

    # Envio

    def _anotar(
        self, conversa: Conversa, direcao: Literal["entrada", "saida"], texto: str,
        audio_id: str | None = None, enviada: bool = True,
    ) -> None:
        conversa.mensagens.append(
            MensagemConversa(
                id=uuid.uuid4().hex, direcao=direcao, texto=texto, momento=self._relogio(),
                audio_id=audio_id, enviada=enviada,
            )
        )

    def _enviar(self, numero: str, conversa: Conversa | None, texto: str) -> None:
        para = self._enderecos.get(numero, numero)
        enviada = True
        try:
            self.canal.enviar_texto(para, texto)
        except EnvioFalhou as erro:
            enviada = False
            logger.warning("whatsapp: texto não saiu para %s: %s", mascarar(numero), erro)
        audio_id = None
        if self.sintetizador is not None and enviada:
            try:
                fala = self.sintetizador.falar(texto)
                if fala.audio:
                    self.canal.enviar_audio(para, fala.audio)
                    audio_id = uuid.uuid4().hex
                    self._audios[audio_id] = fala.audio
            except (VozIndisponivel, EnvioFalhou) as erro:
                logger.warning("whatsapp: áudio não saiu para %s: %s", mascarar(numero), erro)
        if conversa is not None:
            self._anotar(conversa, "saida", texto, audio_id=audio_id, enviada=enviada)
