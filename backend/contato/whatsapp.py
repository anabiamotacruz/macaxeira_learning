"""WhatsApp simulado e pré-triagem (T3.9; #50, seção 9).

Quem começa a conversa é o candidato, com o código curto do e-mail. O roteiro sai
dos requisitos aprovados da vaga, perguntas sensíveis são bloqueadas em código e o
resultado é validado em código. O modelo só interpreta respostas livres.

O simulador imita o webhook da WhatsApp Cloud API e a janela de 24 horas. `PreTriagem`
e `Pergunta` são tipos locais da frente até o modelo de dados do #50 entrar em
`backend/contratos` (#9).
"""

import logging
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from backend.contato.conversa import contem_instrucao, pede_saida
from backend.contato.email_inicial import EmailConvite, MensageiroEmailSimulado
from backend.contato.pacote import CRITERIOS_SENSIVEIS
from backend.contato.prompts import (
    PALAVRA_SAIDA,
    SISTEMA_INTERPRETACAO,
    montar_pedido_interpretacao,
)
from backend.contato.supressao import ListaSupressao
from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import AgenteRecrutador, ClienteModelo
from backend.contratos.modelos import Vaga

logger = logging.getLogger(__name__)

ETAPA_INTERPRETACAO = "interpretar_resposta"
JANELA = timedelta(hours=24)
PALAVRA_BANCO = "BANCO"
LIMITE_TEXTO = 1000
_CODIGO = re.compile(r"\b[A-Za-z2-7]{6}\b")

_SENSIVEIS = [
    re.compile(rf"\b{p}")
    for p in (
        "idade",
        "anos de idade",
        "nascimento",
        "nasceu",
        "genero",
        "sexo",
        "casad",
        "solteir",
        "divorciad",
        "viuv",
        "estado civil",
        "filho",
        "gravid",
        "gestante",
        "religi",
        "igreja",
        "saude",
        "doenc",
        "deficien",
        "raca",
        "cor da pele",
        "etnia",
        "orientacao sexual",
        "partido",
        "sindica",
    )
]

_PALAVRAS_SIM = {"sim", "claro", "com", "certeza", "tenho", "atendo", "quero", "s", "isso"}
_GATILHO_SIM = {"sim", "claro", "certeza", "s", "isso"}
_PALAVRAS_NAO = {"nao", "n", "tenho", "atendo", "quero", "infelizmente"}
_GATILHO_NAO = {"nao", "n"}

Valor = Literal["sim", "nao", "ambigua"]


class _Local(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pergunta(_Local):
    id: str
    texto: str
    requisito_id: str | None
    eliminatoria: bool


class ResultadoPreTriagem(StrEnum):
    EM_ANDAMENTO = "em_andamento"
    APROVADO = "aprovado"
    REPROVADO = "reprovado"
    HUMANO = "humano"
    SAIU = "saiu"


class PreTriagem(_Local):
    """Estado da pré-triagem. Guarda só o valor de cada resposta (minimização)."""

    codigo: str
    empresa_id: str
    vaga_id: str
    candidato_id: str
    perguntas: list[Pergunta]
    respostas: dict[str, Valor] = {}
    resultado: ResultadoPreTriagem = ResultadoPreTriagem.EM_ANDAMENTO
    link_agendamento: str | None = None
    quer_banco: bool = False
    repeticoes: int = 0

    def proxima(self) -> Pergunta | None:
        return next((p for p in self.perguntas if p.id not in self.respostas), None)


class RespostaPergunta(BaseModel):
    """Saída esperada do modelo na etapa `interpretar_resposta`."""

    valor: Valor


class MensagemWhatsApp(_Local):
    numero: str
    texto: str
    momento: AwareDatetime
    direcao: Literal["entrada", "saida"]
    simulado: bool = True


class JanelaFechada(Exception):
    """Mensagem iniciada pela empresa fora da janela de 24h aberta pelo candidato."""


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


# Roteiro


def pergunta_sensivel(texto: str) -> bool:
    """Pergunta sobre idade, gênero, estado civil, religião, saúde e afins."""
    normalizado = _normalizar(texto)
    return any(p.search(normalizado) for p in _SENSIVEIS)


def montar_roteiro(vaga: Vaga, extras: list[str] | None = None) -> list[Pergunta]:
    """Roteiro fixo: interesse, um requisito por pergunta e extras aprovados pela empresa.

    Lança `ValueError` se alguma pergunta ou requisito for sensível.
    """
    perguntas = [
        Pergunta(
            id="interesse",
            texto=f"Você tem interesse em seguir no processo da vaga {vaga.titulo}? "
            "Responda sim ou não.",
            requisito_id=None,
            eliminatoria=True,
        )
    ]
    for requisito in vaga.requisitos:
        if _normalizar(requisito.campo) in CRITERIOS_SENSIVEIS:
            raise ValueError(f"requisito sensível no roteiro: {requisito.id}")
        perguntas.append(
            Pergunta(
                id=requisito.id,
                texto=f"A vaga pede: {requisito.descricao}. Você atende a esse requisito? "
                "Responda sim ou não.",
                requisito_id=requisito.id,
                eliminatoria=True,
            )
        )
    for indice, texto in enumerate(extras or [], start=1):
        perguntas.append(
            Pergunta(id=f"extra-{indice}", texto=texto, requisito_id=None, eliminatoria=False)
        )
    for pergunta in perguntas:
        if pergunta_sensivel(pergunta.texto):
            raise ValueError(f"pergunta sensível no roteiro: {pergunta.id}")
    return perguntas


# Interpretação e validação


def _decidir_sem_modelo(texto: str) -> Valor | None:
    palavras = set(re.sub(r"[^\w ]", " ", _normalizar(texto)).split())
    if not palavras or len(palavras) > 4:
        return None
    if palavras & _GATILHO_SIM and palavras <= _PALAVRAS_SIM:
        return "sim"
    if palavras & _GATILHO_NAO and palavras <= _PALAVRAS_NAO:
        return "nao"
    return None


def interpretar_resposta(texto: str, cliente_modelo: ClienteModelo, pergunta: str = "") -> Valor:
    """Sim, não ou ambígua. Respostas curtas e claras não passam pelo modelo."""
    if contem_instrucao(texto):
        logger.warning("alerta: instrução no texto da pré-triagem, tratada como ambígua")
        return "ambigua"
    decidido = _decidir_sem_modelo(texto)
    if decidido:
        return decidido
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_INTERPRETACAO,
            montar_pedido_interpretacao(pergunta, texto[:LIMITE_TEXTO]),
            RespostaPergunta,
            ETAPA_INTERPRETACAO,
        )
        return RespostaPergunta.model_validate(resposta.model_dump()).valor
    except (ModeloIndisponivel, RespostaInvalida) as erro:
        logger.warning("resposta da pré-triagem tratada como ambígua: %s", erro)
        return "ambigua"


def validar(pre: PreTriagem) -> ResultadoPreTriagem:
    """Resultado decidido em código a partir das respostas."""
    for pergunta in pre.perguntas:
        if pergunta.eliminatoria and pre.respostas.get(pergunta.id) == "nao":
            return ResultadoPreTriagem.REPROVADO
    if pre.proxima() is not None:
        return ResultadoPreTriagem.EM_ANDAMENTO
    if any(valor == "ambigua" for valor in pre.respostas.values()):
        return ResultadoPreTriagem.HUMANO
    return ResultadoPreTriagem.APROVADO


# Canal simulado


def webhook_mensagem(numero: str, texto: str, momento: datetime) -> dict:
    """Payload de mensagem recebida no formato do webhook da WhatsApp Cloud API."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "conta-simulada",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "numero-simulado"},
                            "contacts": [{"wa_id": numero}],
                            "messages": [
                                {
                                    "from": numero,
                                    "id": f"wamid.simulado.{numero}.{int(momento.timestamp())}",
                                    "timestamp": str(int(momento.timestamp())),
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _ler_webhook(payload: dict) -> list[tuple[str, str, datetime]]:
    mensagens = []
    for entrada in payload.get("entry", []):
        for mudanca in entrada.get("changes", []):
            for mensagem in mudanca.get("value", {}).get("messages", []):
                if mensagem.get("type") != "text":
                    continue
                momento = datetime.fromtimestamp(int(mensagem["timestamp"]), UTC)
                mensagens.append((mensagem["from"], mensagem["text"]["body"], momento))
    return mensagens


class WhatsAppSimulado:
    """Canal simulado: guarda as mensagens e aplica a janela de 24 horas."""

    def __init__(self) -> None:
        self._mensagens: dict[str, list[MensagemWhatsApp]] = {}
        self._ultima_entrada: dict[str, datetime] = {}

    def registrar_entrada(self, numero: str, texto: str, momento: datetime) -> None:
        self._mensagens.setdefault(numero, []).append(
            MensagemWhatsApp(numero=numero, texto=texto, momento=momento, direcao="entrada")
        )
        self._ultima_entrada[numero] = momento

    def enviar(self, numero: str, texto: str, momento: datetime) -> None:
        ultima = self._ultima_entrada.get(numero)
        if ultima is None or momento - ultima > JANELA:
            raise JanelaFechada("sem janela de 24h aberta pelo candidato")
        self._mensagens.setdefault(numero, []).append(
            MensagemWhatsApp(numero=numero, texto=texto, momento=momento, direcao="saida")
        )

    def mensagens(self, numero: str) -> list[MensagemWhatsApp]:
        return list(self._mensagens.get(numero, []))


# Atendimento


class AtendenteWhatsApp:
    """Conduz a conversa: liga pelo código, faz a pré-triagem e entrega o link.

    `ao_aprovar` recebe a pré-triagem aprovada, para o fluxo montar e entregar o
    pacote ao agente recrutador (T3.3).
    """

    def __init__(
        self,
        canal: WhatsAppSimulado,
        emails: MensageiroEmailSimulado,
        lista: ListaSupressao,
        obter_vaga: Callable[[str, str], Vaga],
        agente: AgenteRecrutador,
        cliente_modelo: ClienteModelo,
        ao_aprovar: Callable[[PreTriagem], None] | None = None,
    ) -> None:
        self.canal = canal
        self.emails = emails
        self.lista = lista
        self.obter_vaga = obter_vaga
        self.agente = agente
        self.cliente_modelo = cliente_modelo
        self.ao_aprovar = ao_aprovar
        self._conversas: dict[str, PreTriagem] = {}
        self._emails_por_numero: dict[str, EmailConvite] = {}

    def pre_triagem(self, numero: str) -> PreTriagem | None:
        return self._conversas.get(numero)

    def atender(self, payload: dict) -> list[str]:
        """Processa um webhook e devolve as mensagens enviadas em resposta."""
        enviadas: list[str] = []
        for numero, texto, momento in _ler_webhook(payload):
            self.canal.registrar_entrada(numero, texto, momento)
            for resposta in self._responder(numero, texto):
                self.canal.enviar(numero, resposta, momento)
                enviadas.append(resposta)
        return enviadas

    def _responder(self, numero: str, texto: str) -> list[str]:
        pre = self._conversas.get(numero)
        if pre is None:
            return self._iniciar(numero, texto)
        if pre.resultado == ResultadoPreTriagem.SAIU:
            return []
        if pede_saida(texto):
            return self._sair(numero, pre)
        if pre.resultado == ResultadoPreTriagem.REPROVADO and _normalizar(texto) == "banco":
            pre.quer_banco = True
            return ["Anotado! A equipe vai te pedir a autorização para o banco de talentos."]
        if pre.resultado != ResultadoPreTriagem.EM_ANDAMENTO:
            return ["Obrigado pela mensagem! Uma pessoa da equipe vai te responder por aqui."]
        return self._registrar_resposta(pre, texto)

    def _iniciar(self, numero: str, texto: str) -> list[str]:
        email = self._achar_email(texto)
        if email is None:
            if pede_saida(texto):
                return ["Pronto, não vamos mais te enviar mensagens por aqui."]
            return [
                "Olá! Não encontrei o código do convite. Confira o e-mail que você recebeu e "
                "mande a mensagem com o código, por exemplo: Vaga ABC234."
            ]
        convite = email.convite
        if self.lista.esta_suprimido(convite.empresa_id, [email.para, numero]):
            return ["Pronto, não vamos mais te enviar mensagens por aqui."]
        vaga = self.obter_vaga(convite.empresa_id, convite.vaga_id or "")
        pre = PreTriagem(
            codigo=email.codigo,
            empresa_id=convite.empresa_id,
            vaga_id=vaga.id,
            candidato_id=convite.candidato_id,
            perguntas=montar_roteiro(vaga),
        )
        self._conversas[numero] = pre
        self._emails_por_numero[numero] = email
        logger.info("pré-triagem iniciada: %s", email.codigo)
        return [
            f"Olá! Aqui é a equipe de recrutamento da vaga {vaga.titulo} (atendimento "
            f"simulado). Vou fazer {len(pre.perguntas)} perguntas rápidas. Para não receber "
            f"mais mensagens, responda {PALAVRA_SAIDA} a qualquer momento.",
            pre.perguntas[0].texto,
        ]

    def _achar_email(self, texto: str) -> EmailConvite | None:
        for candidato in _CODIGO.findall(texto):
            email = self.emails.por_codigo(candidato)
            if email is not None:
                return email
        return None

    def _sair(self, numero: str, pre: PreTriagem) -> list[str]:
        email = self._emails_por_numero[numero]
        self.lista.suprimir(pre.empresa_id, [numero, email.para])
        pre.resultado = ResultadoPreTriagem.SAIU
        logger.info("saída pelo WhatsApp: %s", pre.codigo)
        return ["Pronto, não vamos mais te enviar mensagens. Obrigado pelo seu tempo."]

    def _registrar_resposta(self, pre: PreTriagem, texto: str) -> list[str]:
        pergunta = pre.proxima()
        if pergunta is None:
            return []
        valor = interpretar_resposta(texto, self.cliente_modelo, pergunta.texto)
        if valor == "ambigua" and pre.repeticoes == 0:
            pre.repeticoes = 1
            return [f"Não entendi bem. Pode responder sim ou não? {pergunta.texto}"]
        pre.respostas = {**pre.respostas, pergunta.id: valor}
        pre.repeticoes = 0
        pre.resultado = validar(pre)
        return self._depois_da_resposta(pre)

    def _depois_da_resposta(self, pre: PreTriagem) -> list[str]:
        if pre.resultado == ResultadoPreTriagem.EM_ANDAMENTO:
            return [pre.proxima().texto]
        if pre.resultado == ResultadoPreTriagem.REPROVADO:
            return [
                "Obrigado pelas respostas! Neste momento, seu perfil não segue para esta vaga. "
                "Se quiser ficar no banco de talentos da empresa para outras vagas, responda "
                f"{PALAVRA_BANCO}."
            ]
        if pre.resultado == ResultadoPreTriagem.HUMANO:
            return [
                "Obrigado pelas respostas! Uma pessoa da equipe vai analisar e te responder "
                "por aqui."
            ]
        pre.link_agendamento = self.agente.link_agendamento(pre.vaga_id, pre.candidato_id)
        if self.ao_aprovar is not None:
            self.ao_aprovar(pre)
        if pre.link_agendamento:
            return [
                "Obrigado! Você pode agendar a entrevista com a nossa recrutadora aqui: "
                f"{pre.link_agendamento}"
            ]
        return ["Obrigado! A equipe vai entrar em contato para combinar a entrevista."]
