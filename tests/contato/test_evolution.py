"""Canal real de WhatsApp pela Evolution API, sem rede: HTTP falso e números sintéticos."""

import base64
import json

import httpx
import pytest

from backend.contato.evolution import (
    ClienteEvolution,
    EnvioFalhou,
    ler_webhook_evolution,
    mascarar,
    numeros_permitidos,
)

NUMERO = "5585900000001"


def _webhook(message: dict, *, jid: str = f"{NUMERO}@s.whatsapp.net", from_me: bool = False,
             evento: str = "messages.upsert", extra_key: dict | None = None) -> dict:
    return {
        "event": evento,
        "instance": "macaxeira",
        "data": {
            "key": {"remoteJid": jid, "fromMe": from_me, "id": "ABC123", **(extra_key or {})},
            "pushName": "Pessoa de teste",
            "message": message,
            "messageTimestamp": 1794130000,
        },
    }


def test_le_texto_simples_e_texto_estendido():
    [um] = ler_webhook_evolution(_webhook({"conversation": "Vaga ABC234"}))
    [dois] = ler_webhook_evolution(_webhook({"extendedTextMessage": {"text": "oi"}}))

    assert (um.numero, um.texto, um.tipo, um.responder_para) == (
        NUMERO, "Vaga ABC234", "texto", f"{NUMERO}@s.whatsapp.net",
    )
    assert dois.texto == "oi"
    assert um.momento.timestamp() == 1794130000


def test_audio_vira_tipo_audio_sem_texto():
    [audio] = ler_webhook_evolution(_webhook({"audioMessage": {"seconds": 3}}))

    assert audio.tipo == "audio"
    assert audio.texto == ""


@pytest.mark.parametrize(
    "payload",
    [
        _webhook({"conversation": "eco"}, from_me=True),
        _webhook({"conversation": "grupo"}, jid="123456@g.us"),
        _webhook({"conversation": "status"}, jid="status@broadcast"),
        _webhook({"conversation": "outro evento"}, evento="messages.update"),
        _webhook({"imageMessage": {}}),
        {"event": "messages.upsert"},
        {},
    ],
)
def test_ignora_o_que_nao_e_mensagem_de_uma_pessoa(payload):
    assert ler_webhook_evolution(payload) == []


def test_jid_lid_usa_o_numero_quando_a_evolution_informa():
    payload = _webhook(
        {"conversation": "oi"}, jid="99887766@lid",
        extra_key={"senderPn": f"{NUMERO}@s.whatsapp.net"},
    )

    [msg] = ler_webhook_evolution(payload)

    assert msg.numero == NUMERO
    assert msg.responder_para == "99887766@lid"


def test_lista_de_permitidos_filtra_outros_numeros():
    permitidos = numeros_permitidos({"WHATSAPP_NUMEROS_PERMITIDOS": f"+{NUMERO}, 5585900000002"})

    assert ler_webhook_evolution(_webhook({"conversation": "oi"}), permitidos)
    outro = _webhook({"conversation": "oi"}, jid="5511900000009@s.whatsapp.net")
    assert ler_webhook_evolution(outro, permitidos) == []
    assert numeros_permitidos({}) is None


def test_mascara_o_numero_no_log():
    assert mascarar(NUMERO) == "55859****0001"
    assert mascarar("123") == "***"


def _cliente(pedidos: list, status: int = 201) -> ClienteEvolution:
    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(status, json={"key": {"id": "X"}} if status < 300 else {"erro": 1})

    return ClienteEvolution(
        "http://evolution.local:8080", "chave-de-teste", "macaxeira",
        http=httpx.Client(transport=httpx.MockTransport(responder)),
    )


def test_envia_texto_e_audio_pela_instancia():
    pedidos: list = []
    cliente = _cliente(pedidos)

    cliente.enviar_texto(f"{NUMERO}@s.whatsapp.net", "Olá!")
    cliente.enviar_audio(f"{NUMERO}@s.whatsapp.net", b"mp3")

    texto, audio = pedidos
    assert texto.url.path == "/message/sendText/macaxeira"
    assert texto.headers["apikey"] == "chave-de-teste"
    assert json.loads(texto.content) == {"number": f"{NUMERO}@s.whatsapp.net", "text": "Olá!"}
    assert audio.url.path == "/message/sendWhatsAppAudio/macaxeira"
    assert json.loads(audio.content)["audio"] == base64.b64encode(b"mp3").decode()


def test_falha_de_envio_levanta_erro_sem_a_chave():
    cliente = _cliente([], status=500)

    with pytest.raises(EnvioFalhou) as erro:
        cliente.enviar_texto(NUMERO, "Olá!")

    assert "chave-de-teste" not in str(erro.value)


def test_do_ambiente_exige_url_chave_e_instancia():
    assert ClienteEvolution.do_ambiente({}) is None
    cliente = ClienteEvolution.do_ambiente(
        {"EVOLUTION_URL": "http://x:8080", "EVOLUTION_API_KEY": "k", "EVOLUTION_INSTANCIA": "i"}
    )
    assert cliente is not None and cliente.instancia == "i"
