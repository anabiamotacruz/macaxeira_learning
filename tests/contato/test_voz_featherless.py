"""Voz real pela Featherless (Kokoro), sem rede: o HTTP é falso."""

import json

import httpx
import pytest

from backend.contato.voz import (
    SintetizadorFeatherless,
    VozIndisponivel,
    sintetizador_do_ambiente,
    texto_para_fala,
)

MP3 = b"ID3-falso-mp3"


def _http(pedidos: list, status: int = 200) -> httpx.Client:
    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        if status != 200:
            return httpx.Response(status, json={"error": "falhou"})
        return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})

    return httpx.Client(transport=httpx.MockTransport(responder))


def test_fala_gera_mp3_com_kokoro_em_portugues():
    pedidos: list = []
    voz = SintetizadorFeatherless("chave-de-teste", http=_http(pedidos))

    fala = voz.falar("Olá! Tudo bem?")

    corpo = json.loads(pedidos[0].content)
    assert pedidos[0].url.path.endswith("/audio/speech")
    assert pedidos[0].headers["authorization"] == "Bearer chave-de-teste"
    assert corpo == {
        "model": "hexgrad/Kokoro-82M",
        "input": "Olá! Tudo bem?",
        "voice": "pf_dora",
        "response_format": "mp3",
    }
    assert fala.audio == MP3
    assert fala.simulado is False
    assert fala.provedor == "featherless:hexgrad/Kokoro-82M"


def test_link_nao_e_lido_em_voz_alta():
    assert texto_para_fala("Agende aqui: https://nara.exemplo/agenda?x=1 obrigado") == (
        "Agende aqui: o link está na mensagem de texto obrigado"
    )


def test_falha_do_provedor_vira_voz_indisponivel_sem_vazar_chave():
    pedidos: list = []
    voz = SintetizadorFeatherless("chave-secreta", http=_http(pedidos, status=500))

    with pytest.raises(VozIndisponivel) as erro:
        voz.falar("Olá")

    assert len(pedidos) == 2  # uma nova tentativa
    assert "chave-secreta" not in str(erro.value)


def test_voz_real_liga_a_featherless_pelo_ambiente():
    voz = sintetizador_do_ambiente({"VOZ_REAL": "1", "FEATHERLESS_API_KEY": "chave-de-teste"})

    assert isinstance(voz, SintetizadorFeatherless)


def test_voz_real_sem_chave_nao_liga():
    with pytest.raises(VozIndisponivel, match="FEATHERLESS_API_KEY"):
        sintetizador_do_ambiente({"VOZ_REAL": "1"})
