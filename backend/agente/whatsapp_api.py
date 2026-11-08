"""Rotas do WhatsApp real: o webhook da Evolution e a leitura das conversas pelo painel.

Só existem com `EVOLUTION_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCIA` e
`EVOLUTION_WEBHOOK_TOKEN`. Sem isso, a API segue igual à demonstração.
"""

import hmac
import logging
import os
from collections.abc import Callable, Mapping

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from fastapi.responses import JSONResponse, Response

from backend.agente.servico import ServicoVagas
from backend.agente.whatsapp import AtendimentoWhatsApp, Conversa, configurar_numero
from backend.contato.evolution import ClienteEvolution, ler_webhook_evolution, numeros_permitidos
from backend.contato.voz import VozIndisponivel, sintetizador_do_ambiente

logger = logging.getLogger(__name__)

rotas_whatsapp = APIRouter(tags=["whatsapp"])


def atendimento_do_ambiente(
    obter_servico: Callable[[], ServicoVagas], ambiente: Mapping[str, str] | None = None
) -> AtendimentoWhatsApp | None:
    ambiente = os.environ if ambiente is None else ambiente
    canal = ClienteEvolution.do_ambiente(ambiente)
    if canal is None or not (ambiente.get("EVOLUTION_WEBHOOK_TOKEN") or "").strip():
        return None
    try:
        voz = sintetizador_do_ambiente(ambiente)
    except VozIndisponivel as erro:
        logger.warning("whatsapp sem voz: %s", erro)
        voz = None
    numero = (ambiente.get("WHATSAPP_NUMERO") or "").strip() or canal.numero_conectado()
    configurar_numero(numero)
    logger.info("whatsapp ligado: instância %s, voz %s", canal.instancia,
                getattr(voz, "provedor", "desligada"))
    return AtendimentoWhatsApp(obter_servico, canal, voz)


def _atendimento(request: Request) -> AtendimentoWhatsApp | None:
    return getattr(request.app.state, "whatsapp", None)


def _desligado() -> JSONResponse:
    return JSONResponse(
        {"erro": {"codigo": "whatsapp_desligado",
                  "mensagem": "O WhatsApp não está configurado nesta API."}},
        status_code=404,
    )


@rotas_whatsapp.post("/whatsapp/webhook", include_in_schema=False)
async def receber_webhook(
    request: Request,
    tarefas: BackgroundTasks,
    x_webhook_token: str = Header(default=""),
) -> Response:
    """Recebe o `messages.upsert` da Evolution e responde depois de devolver 200."""
    atendimento = _atendimento(request)
    if atendimento is None:
        return _desligado()
    esperado = os.environ.get("EVOLUTION_WEBHOOK_TOKEN", "")
    if not esperado or not hmac.compare_digest(x_webhook_token, esperado):
        return JSONResponse({"erro": {"codigo": "nao_autorizado", "mensagem": "Token inválido."}},
                            status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": False}, status_code=400)
    mensagens = ler_webhook_evolution(payload, numeros_permitidos(os.environ))
    for mensagem in mensagens:
        tarefas.add_task(atendimento.atender, mensagem)
    return JSONResponse({"ok": True, "mensagens": len(mensagens)})


def _empresa(x_empresa_id: str = Header(default="")) -> str:
    return x_empresa_id.strip()


@rotas_whatsapp.get("/vagas/{id}/whatsapp", response_model=list[Conversa], include_in_schema=False)
def conversas_da_vaga(id: str, request: Request, empresa: str = Depends(_empresa)):
    """As conversas de WhatsApp dos convites desta vaga, com o número mascarado."""
    atendimento = _atendimento(request)
    if atendimento is None or not empresa:
        return []
    return atendimento.conversas(empresa, id)


@rotas_whatsapp.get("/vagas/{id}/whatsapp/audio/{audio_id}", include_in_schema=False)
def audio_da_conversa(
    id: str, audio_id: str, request: Request, empresa: str = Depends(_empresa)
) -> Response:
    """O MP3 de uma resposta, só para a empresa e a vaga da conversa."""
    atendimento = _atendimento(request)
    if atendimento is None:
        return _desligado()
    da_vaga = any(
        m.audio_id == audio_id
        for c in atendimento.conversas(empresa, id)
        for m in c.mensagens
    )
    audio = atendimento.audio(audio_id) if da_vaga else None
    if audio is None:
        erro = {"codigo": "nao_encontrado", "mensagem": "Áudio não encontrado."}
        return JSONResponse({"erro": erro}, status_code=404)
    return Response(audio, media_type="audio/mpeg")


@rotas_whatsapp.get("/whatsapp/status", include_in_schema=False)
def status(request: Request) -> dict:
    atendimento = _atendimento(request)
    return {"ligado": atendimento is not None,
            "voz": getattr(getattr(atendimento, "sintetizador", None), "provedor", None)}
