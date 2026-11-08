"""Voz no WhatsApp simulado.

O padrão não chama rede. Deepgram e ElevenLabs só entram com `VOZ_REAL=1` e a
chave correspondente. Sem isso, a transcrição e a fala são simuladas e marcadas.
"""

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

PREFIXO_AUDIO_SIMULADO = b"audio-simulado\n"


class VozIlegivel(Exception):
    """O áudio simulado não trouxe uma transcrição utilizável."""


class VozIndisponivel(Exception):
    """A voz real foi pedida e não há provedor ligado."""


class Transcricao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: str
    provedor: str
    simulado: bool = True


class Fala(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: str
    provedor: str
    simulado: bool = True


class ReconhecedorSimulado:
    """Lê a transcrição gravada no áudio de teste. Não ouve de verdade."""

    provedor = "simulado"

    def transcrever(self, audio: bytes, tipo: str) -> Transcricao:
        del tipo
        if not audio.startswith(PREFIXO_AUDIO_SIMULADO):
            raise VozIlegivel("áudio simulado sem transcrição")
        texto = audio[len(PREFIXO_AUDIO_SIMULADO) :].decode("utf-8").strip()
        if not texto:
            raise VozIlegivel("áudio simulado sem transcrição")
        return Transcricao(texto=texto, provedor=self.provedor, simulado=True)


class SintetizadorSimulado:
    """Marca a resposta como voz simulada, sem gerar áudio de um provedor."""

    provedor = "simulado"

    def __init__(self) -> None:
        self.falas: list[str] = []

    def falar(self, texto: str) -> Fala:
        self.falas.append(texto)
        return Fala(tipo="audio/mpeg", provedor=self.provedor, simulado=True)


def audio_simulado(texto: str) -> bytes:
    return PREFIXO_AUDIO_SIMULADO + texto.encode("utf-8")


def _ligado(ambiente: Mapping[str, str], nome: str) -> bool:
    return (ambiente.get(nome) or "").strip() == "1"


def _presente(ambiente: Mapping[str, str], nome: str) -> bool:
    return bool((ambiente.get(nome) or "").strip())


def reconhecedor_do_ambiente(
    ambiente: Mapping[str, str] | None = None,
) -> ReconhecedorSimulado:
    """Sem `VOZ_REAL=1`, ignora chave e fica no simulado."""
    ambiente = os.environ if ambiente is None else ambiente
    if not _ligado(ambiente, "VOZ_REAL"):
        return ReconhecedorSimulado()
    if not _presente(ambiente, "DEEPGRAM_API_KEY"):
        raise VozIndisponivel("VOZ_REAL=1 sem DEEPGRAM_API_KEY")
    raise VozIndisponivel("reconhecimento real ainda não está ligado")


def sintetizador_do_ambiente(
    ambiente: Mapping[str, str] | None = None,
) -> SintetizadorSimulado | None:
    """`VOZ_SAIDA=1` responde também por voz simulada. A voz real continua desligada."""
    ambiente = os.environ if ambiente is None else ambiente
    if _ligado(ambiente, "VOZ_REAL"):
        if not _presente(ambiente, "ELEVENLABS_API_KEY"):
            raise VozIndisponivel("VOZ_REAL=1 sem ELEVENLABS_API_KEY")
        raise VozIndisponivel("síntese real ainda não está ligada")
    if _ligado(ambiente, "VOZ_SAIDA"):
        return SintetizadorSimulado()
    return None
