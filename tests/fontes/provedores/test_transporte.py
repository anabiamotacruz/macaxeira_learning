import logging

import httpx2
import pytest

from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.transporte import PedidoHttp, TransporteHttp
from tests.fontes.provedores.apoio import TOKEN_BRIGHT

URL_API = "https://api.brightdata.com/request"


def transporte_com(tratar) -> TransporteHttp:
    return TransporteHttp(httpx2.Client(transport=httpx2.MockTransport(tratar)))


def pedido(**campos) -> PedidoHttp:
    return PedidoHttp(**{"metodo": "POST", "url": URL_API, **campos})


def test_envia_corpo_e_cabecalhos_e_devolve_resposta():
    def tratar(requisicao: httpx2.Request) -> httpx2.Response:
        assert requisicao.headers["authorization"] == f"Bearer {TOKEN_BRIGHT}"
        assert b'"zone"' in requisicao.content
        return httpx2.Response(200, headers={"X-Brd-Status-Code": "200"}, content=b"ok")

    resposta = transporte_com(tratar).enviar(
        pedido(cabecalhos={"Authorization": f"Bearer {TOKEN_BRIGHT}"}, corpo_json={"zone": "z"})
    )
    assert (resposta.status, resposta.corpo) == (200, b"ok")
    assert resposta.cabecalhos["x-brd-status-code"] == "200"


def test_recusa_host_fora_da_lista_sem_enviar_a_chave():
    chamado = []
    transporte = transporte_com(lambda r: chamado.append(r) or httpx2.Response(200))
    with pytest.raises(ErroProvedor):
        transporte.enviar(pedido(url="https://outro-host.com.br/request"))
    assert chamado == []


def test_nao_segue_redirecionamento_da_propria_api():
    chamadas = []

    def tratar(requisicao: httpx2.Request) -> httpx2.Response:
        chamadas.append(str(requisicao.url))
        return httpx2.Response(302, headers={"location": "https://interno.com.br/"})

    assert transporte_com(tratar).enviar(pedido()).status == 302
    assert chamadas == [URL_API]


def test_interrompe_resposta_maior_que_o_teto():
    transporte = transporte_com(lambda _: httpx2.Response(200, content=b"x" * 2000))
    with pytest.raises(ErroProvedor) as erro:
        transporte.enviar(pedido(tamanho_maximo=1000))
    assert erro.value.motivo == MotivoTroca.RESPOSTA_GRANDE_DEMAIS


def test_tempo_total_de_leitura_tambem_tem_limite():
    momentos = iter([0.0, 100.0])
    transporte = TransporteHttp(
        httpx2.Client(transport=httpx2.MockTransport(lambda _: httpx2.Response(200, content=b"x"))),
        relogio=lambda: next(momentos),
    )
    with pytest.raises(TimeoutError):
        transporte.enviar(pedido(tempo_limite_s=1.0))


@pytest.mark.parametrize(
    ("falha", "esperado"),
    [
        (httpx2.ReadTimeout(f"tempo Bearer {TOKEN_BRIGHT}"), TimeoutError),
        (httpx2.ConnectError(f"conexão Bearer {TOKEN_BRIGHT}"), ConnectionError),
    ],
)
def test_erros_do_cliente_viram_temporarios_sem_copiar_o_texto(falha, esperado, caplog):
    def tratar(_: httpx2.Request) -> httpx2.Response:
        raise falha

    caplog.set_level(logging.DEBUG)
    with pytest.raises(esperado) as erro:
        transporte_com(tratar).enviar(pedido())
    assert TOKEN_BRIGHT not in str(erro.value)
    assert erro.value.__cause__ is None and erro.value.__suppress_context__
    assert TOKEN_BRIGHT not in caplog.text


def test_repr_do_pedido_nao_expoe_chave_nem_corpo():
    texto = repr(
        pedido(cabecalhos={"X-Api-Key": TOKEN_BRIGHT}, corpo_json={"email": ["p@ficticio.com"]})
    )
    assert TOKEN_BRIGHT not in texto
    assert "ficticio" not in texto


def test_pedido_sem_user_agent_sai_com_o_do_projeto():
    """O firewall da EnvoAPI devolve 403 ao agente de usuário padrão do Python."""
    vistos = []

    def tratar(requisicao: httpx2.Request) -> httpx2.Response:
        vistos.append(requisicao.headers["user-agent"])
        return httpx2.Response(200)

    transporte_com(tratar).enviar(pedido())
    assert vistos == ["macaxeira-learning/0.1"]


def test_user_agent_do_pedido_e_mantido():
    vistos = []

    def tratar(requisicao: httpx2.Request) -> httpx2.Response:
        vistos.append(requisicao.headers["user-agent"])
        return httpx2.Response(200)

    transporte_com(tratar).enviar(pedido(cabecalhos={"user-agent": "outro/1.0"}))
    assert vistos == ["outro/1.0"]
