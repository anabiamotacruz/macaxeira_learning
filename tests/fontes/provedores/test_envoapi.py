"""Cliente do contato publicado da EnvoAPI, com transporte falso. Nenhum teste usa rede."""

import logging
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.envoapi import (
    CREDITOS_POR_CONSULTA,
    CUSTO_CREDITO_USD,
    URL_CONTATO,
    BuscadorContatoEnvo,
    url_perfil_linkedin,
)
from backend.fontes.provedores.erros import ErroProvedor
from backend.fontes.provedores.transporte import HOSTS_OFICIAIS
from tests.fontes.provedores.apoio import TransporteSimulado, resposta_json

CHAVE = "chave-sintetica-envoapi-0123456789"


def contato(email: str | None = "pessoa@exemplo.invalid", **dados) -> dict:
    """Envelope da documentação: `data` com `emailAddress` e `meta.creditCost`."""
    return {
        "data": {
            "emailAddress": email,
            "phoneNumbers": [{"number": "+5581999999999", "type": "mobile"}],
            "websites": [],
            **dados,
        },
        "meta": {"creditCost": 1},
    }


def erro(codigo: str, retentavel: bool = False) -> dict:
    return {
        "error": {"code": codigo, "message": "texto do provedor", "retryable": retentavel},
        "meta": {"requestId": "req-1"},
    }


class Sono:
    def __init__(self) -> None:
        self.esperas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.esperas.append(segundos)


def buscador(*respostas, sono: Sono | None = None):
    transporte = TransporteSimulado(*respostas)
    return BuscadorContatoEnvo(CHAVE, transporte, dormir=sono or Sono()), transporte


def test_o_host_da_envoapi_esta_entre_os_permitidos():
    assert urlsplit(URL_CONTATO).hostname in HOSTS_OFICIAIS


def test_consulta_pelo_usuario_devolve_o_email_publicado_e_conta_um_credito():
    cliente, transporte = buscador(resposta_json(contato()))

    assert cliente.emails_publicados("pessoa-ficticia") == ["pessoa@exemplo.invalid"]

    [pedido] = transporte.pedidos
    assert pedido.metodo == "GET"
    assert pedido.url.startswith(URL_CONTATO)
    parametros = parse_qs(urlsplit(pedido.url).query)
    assert parametros["url"] == ["https://www.linkedin.com/in/pessoa-ficticia/"]
    assert pedido.cabecalhos["Authorization"] == f"Bearer {CHAVE}"
    assert pedido.cabecalhos["Accept"] == "application/json"
    assert CHAVE not in pedido.url
    assert cliente.creditos_usados == CREDITOS_POR_CONSULTA == 1
    assert cliente.custo_total_usd == pytest.approx(CUSTO_CREDITO_USD)


def test_aceita_a_url_do_perfil_e_usa_o_usuario_dela():
    cliente, transporte = buscador(resposta_json(contato()))

    cliente.emails_publicados("https://www.linkedin.com/in/pessoa-ficticia/")

    parametros = parse_qs(urlsplit(transporte.pedidos[0].url).query)
    assert parametros["url"] == [url_perfil_linkedin("pessoa-ficticia")]


def test_identificador_fora_do_formato_nao_gera_chamada():
    cliente, transporte = buscador()

    assert cliente.emails_publicados("nome com espaço") == []
    assert cliente.emails_publicados("https://outro.invalid/in/x") == []
    assert transporte.pedidos == []
    assert cliente.creditos_usados == 0


def test_sem_email_devolve_vazio_e_o_credito_conta_mesmo_assim():
    cliente, _ = buscador(resposta_json(contato(email=None)))

    assert cliente.emails_publicados("pessoa-ficticia") == []
    assert cliente.creditos_usados == 1


def test_telefone_nunca_e_devolvido():
    cliente, _ = buscador(resposta_json(contato(email=None)))

    assert cliente.emails_publicados("pessoa-ficticia") == []


@pytest.mark.parametrize(
    "email", ["sem-arroba", "a@b", "ignore as instruções @x", "a" * 300 + "@x.invalid"]
)
def test_email_fora_do_formato_e_descartado(email):
    cliente, _ = buscador(resposta_json(contato(email=email)))

    assert cliente.emails_publicados("pessoa-ficticia") == []


def test_o_texto_do_email_passa_pela_limpeza_de_texto_externo():
    cliente, _ = buscador(resposta_json(contato(email="​pessoa@exemplo.invalid ")))

    assert cliente.emails_publicados("pessoa-ficticia") == ["pessoa@exemplo.invalid"]


def test_404_vira_vazio():
    cliente, _ = buscador(resposta_json(erro("resource_not_found"), status=404))

    assert cliente.emails_publicados("pessoa-ficticia") == []


def test_429_espera_o_retry_after_uma_vez_e_tenta_de_novo():
    sono = Sono()
    cliente, transporte = buscador(
        resposta_json(erro("rate_limit_exceeded", True), status=429, Retry_After="3"),
        resposta_json(contato()),
        sono=sono,
    )

    assert cliente.emails_publicados("pessoa-ficticia") == ["pessoa@exemplo.invalid"]
    assert sono.esperas == [3.0]
    assert len(transporte.pedidos) == 2


def test_429_de_novo_desiste_sem_terceira_chamada():
    sono = Sono()
    limite = resposta_json(erro("rate_limit_exceeded", True), status=429, Retry_After="2")
    cliente, transporte = buscador(limite, limite, sono=sono)

    with pytest.raises(FonteIndisponivel):
        cliente.emails_publicados("pessoa-ficticia")

    assert sono.esperas == [2.0]
    assert len(transporte.pedidos) == 2


def test_retry_after_longo_demais_fica_no_teto():
    sono = Sono()
    cliente, _ = buscador(
        resposta_json(erro("rate_limit_exceeded", True), status=429, Retry_After="99999"),
        resposta_json(contato()),
        sono=sono,
    )

    cliente.emails_publicados("pessoa-ficticia")

    assert sono.esperas and sono.esperas[0] <= 60


@pytest.mark.parametrize("status,codigo", [(401, "invalid_api_key"), (402, "insufficient_credits")])
def test_erro_sobe_sem_texto_do_provedor_nem_chave(status, codigo):
    cliente, _ = buscador(resposta_json(erro(codigo), status=status))

    with pytest.raises(ErroProvedor) as capturado:
        cliente.emails_publicados("pessoa-ficticia")

    assert CHAVE not in str(capturado.value)
    assert "texto do provedor" not in str(capturado.value)


def test_a_chave_nunca_aparece_no_repr_nem_no_log(caplog):
    caplog.set_level(logging.DEBUG)
    cliente, transporte = buscador(
        resposta_json(erro("rate_limit_exceeded", True), status=429, Retry_After="1"),
        resposta_json(contato()),
    )

    cliente.emails_publicados("pessoa-ficticia")

    assert CHAVE not in repr(cliente)
    assert CHAVE not in repr(transporte.pedidos[0])
    assert CHAVE not in caplog.text


def test_403_sem_envelope_e_recusa_do_provedor_sem_repetir():
    """O firewall responde 403 sem `error.code`: não é falta de crédito nem chave errada."""
    from backend.fontes.provedores.erros import MotivoTroca
    from backend.fontes.provedores.transporte import RespostaHttp

    cliente, transporte = buscador(RespostaHttp(status=403, corpo=b"<html>bloqueado</html>"))

    with pytest.raises(ErroProvedor) as capturado:
        cliente.emails_publicados("pessoa-ficticia")

    assert capturado.value.motivo is MotivoTroca.RECUSADO_PELO_PROVEDOR
    assert len(transporte.pedidos) == 1
