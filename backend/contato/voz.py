"""Voz no WhatsApp.

O padrão não chama rede. Com `VOZ_REAL=1` e `FEATHERLESS_API_KEY`, a fala sai pela
Featherless (`/v1/audio/speech`, modelo Kokoro, voz em pt-BR). A Featherless não transcreve
áudio, então o que a pessoa manda por voz continua sem transcrição real: o atendimento pede
que ela escreva. Sem `VOZ_REAL=1`, a fala é simulada e marcada.
"""

import logging
import os
import re
from collections.abc import Mapping

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

BASE_FEATHERLESS = "https://api.featherless.ai/v1"
MODELO_VOZ_PADRAO = "hexgrad/Kokoro-82M"
VOZ_PADRAO = "pf_dora"
"""Voz feminina em português do Brasil do Kokoro. `pm_alex` é a masculina."""
_URL = re.compile(r"https?://\S+")

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
    audio: bytes | None = None


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


def texto_para_fala(texto: str) -> str:
    """Link não se lê em voz alta: ele fica só na mensagem de texto."""
    return " ".join(_URL.sub("o link está na mensagem de texto", texto).split())


class SintetizadorFeatherless:
    """Fala real pela Featherless. Uma nova tentativa; depois, `VozIndisponivel`."""

    def __init__(
        self,
        chave: str,
        *,
        base_url: str = BASE_FEATHERLESS,
        modelo: str = MODELO_VOZ_PADRAO,
        voz: str = VOZ_PADRAO,
        http: httpx.Client | None = None,
    ) -> None:
        self._chave = chave
        self._url = f"{base_url.rstrip('/')}/audio/speech"
        self.modelo = modelo
        self.voz = voz
        self.provedor = f"featherless:{modelo}"
        self._http = http or httpx.Client(timeout=30)

    def falar(self, texto: str) -> Fala:
        corpo = {
            "model": self.modelo,
            "input": texto_para_fala(texto),
            "voice": self.voz,
            "response_format": "mp3",
        }
        for tentativa in (1, 2):
            try:
                resposta = self._http.post(
                    self._url, json=corpo, headers={"Authorization": f"Bearer {self._chave}"}
                )
                if resposta.status_code == 200 and resposta.content:
                    return Fala(
                        tipo="audio/mpeg", provedor=self.provedor, simulado=False,
                        audio=resposta.content,
                    )
                logger.warning("voz: Featherless respondeu %s (tentativa %s)",
                               resposta.status_code, tentativa)
            except httpx.HTTPError as erro:
                logger.warning("voz: falha de rede na Featherless (%s), tentativa %s",
                               type(erro).__name__, tentativa)
        raise VozIndisponivel("a Featherless não gerou o áudio")


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
) -> SintetizadorSimulado | SintetizadorFeatherless | None:
    """`VOZ_REAL=1` fala pela Featherless; `VOZ_SAIDA=1` fala em voz simulada."""
    ambiente = os.environ if ambiente is None else ambiente
    if _ligado(ambiente, "VOZ_REAL"):
        if not _presente(ambiente, "FEATHERLESS_API_KEY"):
            raise VozIndisponivel("VOZ_REAL=1 sem FEATHERLESS_API_KEY")
        return SintetizadorFeatherless(
            ambiente["FEATHERLESS_API_KEY"].strip(),
            base_url=(ambiente.get("FEATHERLESS_BASE_URL") or BASE_FEATHERLESS).strip(),
            modelo=(ambiente.get("VOZ_MODELO") or MODELO_VOZ_PADRAO).strip(),
            voz=(ambiente.get("VOZ_NOME") or VOZ_PADRAO).strip(),
        )
    if _ligado(ambiente, "VOZ_SAIDA"):
        return SintetizadorSimulado()
    return None
