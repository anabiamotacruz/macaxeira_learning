"""Canal real de WhatsApp pela Evolution API, hospedada pela própria equipe.

A Evolution conecta um número de WhatsApp por QR code e avisa cada mensagem recebida por
webhook (`messages.upsert`). Este módulo só lê o webhook e envia texto e áudio: quem decide o
que responder é o atendimento. O agente nunca começa a conversa; ele só responde a quem escreveu.

O número da pessoa fica em memória e aparece mascarado nos logs. A chave nunca vai para log.
"""

import base64
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

EVENTO_MENSAGEM = "messages.upsert"


class EnvioFalhou(Exception):
    """A Evolution não aceitou o envio."""


@dataclass(frozen=True, slots=True)
class MensagemRecebida:
    numero: str
    """Só dígitos, com DDI. Serve para a lista de permitidos e para o log mascarado."""
    responder_para: str
    """O endereço que a Evolution usa para responder (o `remoteJid` como veio)."""
    texto: str
    tipo: Literal["texto", "audio"]
    momento: datetime
    id: str


def mascarar(numero: str) -> str:
    digitos = "".join(c for c in numero if c.isdigit())
    if len(digitos) < 9:
        return "***"
    return f"{digitos[:5]}****{digitos[-4:]}"


def numeros_permitidos(ambiente: Mapping[str, str]) -> frozenset[str] | None:
    """`WHATSAPP_NUMEROS_PERMITIDOS`, separados por vírgula. Vazio: qualquer número."""
    bruto = (ambiente.get("WHATSAPP_NUMEROS_PERMITIDOS") or "").strip()
    if not bruto:
        return None
    return frozenset("".join(c for c in parte if c.isdigit()) for parte in bruto.split(","))


def _digitos(jid: str) -> str:
    return "".join(c for c in jid.split("@")[0].split(":")[0] if c.isdigit())


def _texto(mensagem: Mapping[str, Any]) -> str | None:
    if isinstance(mensagem.get("conversation"), str):
        return mensagem["conversation"]
    estendida = mensagem.get("extendedTextMessage")
    if isinstance(estendida, Mapping) and isinstance(estendida.get("text"), str):
        return estendida["text"]
    return None


def ler_webhook_evolution(
    payload: Mapping[str, Any], permitidos: frozenset[str] | None = None
) -> list[MensagemRecebida]:
    """Texto ou áudio que uma pessoa mandou. Ignora eco, grupo, status e outros eventos."""
    if payload.get("event") != EVENTO_MENSAGEM:
        return []
    dados = payload.get("data")
    itens = dados if isinstance(dados, list) else [dados]
    mensagens = []
    for item in itens:
        if not isinstance(item, Mapping):
            continue
        chave = item.get("key") or {}
        jid = str(chave.get("remoteJid") or "")
        if not jid or chave.get("fromMe") or jid.endswith(("@g.us", "@broadcast", "@newsletter")):
            continue
        conteudo = item.get("message") or {}
        texto = _texto(conteudo)
        if texto is not None:
            tipo: Literal["texto", "audio"] = "texto"
        elif "audioMessage" in conteudo:
            tipo, texto = "audio", ""
        else:
            continue
        real = jid
        if jid.endswith("@lid"):
            alternativos = (chave.get("senderPn"), item.get("senderPn"), chave.get("remoteJidAlt"))
            real = str(next((a for a in alternativos if a), jid))
        numero = _digitos(real)
        if permitidos is not None and numero not in permitidos:
            logger.info("whatsapp: mensagem de número fora da lista (%s)", mascarar(numero))
            continue
        try:
            momento = datetime.fromtimestamp(int(item.get("messageTimestamp") or 0), UTC)
        except (TypeError, ValueError):
            momento = datetime.now(UTC)
        mensagens.append(
            MensagemRecebida(
                numero=numero, responder_para=jid, texto=texto, tipo=tipo, momento=momento,
                id=str(chave.get("id") or ""),
            )
        )
    return mensagens


class ClienteEvolution:
    """Envia texto e áudio por uma instância da Evolution."""

    def __init__(
        self, url: str, chave: str, instancia: str, *, http: httpx.Client | None = None
    ) -> None:
        self.url = url.rstrip("/")
        self._chave = chave
        self.instancia = instancia
        self._http = http or httpx.Client(timeout=30)

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str]) -> "ClienteEvolution | None":
        valores = [
            (ambiente.get(nome) or "").strip()
            for nome in ("EVOLUTION_URL", "EVOLUTION_API_KEY", "EVOLUTION_INSTANCIA")
        ]
        return cls(*valores) if all(valores) else None

    def _post(self, caminho: str, corpo: dict) -> None:
        try:
            resposta = self._http.post(
                f"{self.url}{caminho}/{self.instancia}", json=corpo, headers={"apikey": self._chave}
            )
        except httpx.HTTPError as erro:
            raise EnvioFalhou(f"Evolution fora do ar ({type(erro).__name__})") from None
        if resposta.status_code >= 300:
            raise EnvioFalhou(f"Evolution recusou o envio: HTTP {resposta.status_code}")

    def enviar_texto(self, para: str, texto: str) -> None:
        self._post("/message/sendText", {"number": para, "text": texto})

    def enviar_audio(self, para: str, mp3: bytes) -> None:
        self._post(
            "/message/sendWhatsAppAudio",
            {"number": para, "audio": base64.b64encode(mp3).decode("ascii")},
        )

    def numero_conectado(self) -> str | None:
        """O número pareado na instância, para montar o link `wa.me` do convite."""
        try:
            resposta = self._http.get(
                f"{self.url}/instance/fetchInstances",
                params={"instanceName": self.instancia}, headers={"apikey": self._chave},
            )
            itens = resposta.json()
        except (httpx.HTTPError, ValueError):
            return None
        for item in itens if isinstance(itens, list) else [itens]:
            dono = (item or {}).get("ownerJid") or ((item or {}).get("instance") or {}).get("owner")
            if dono:
                return _digitos(str(dono))
        return None
