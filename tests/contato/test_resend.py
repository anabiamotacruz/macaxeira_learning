"""Envio real pelo Resend com transporte falso: nenhum teste abre rede."""

import base64
import json
import logging

import pytest

from backend.contato.convite_html import CID_LOGO, LOGO, ROTULO_BOTAO, ConteudoConvite
from backend.contato.mensageiro import MensageiroSimulado
from backend.contato.prompts import AVISO_SIMULACAO
from backend.contato.resend import (
    HOST_RESEND,
    URL_RESEND,
    USER_AGENT,
    MensageiroResend,
    TransporteResend,
)
from backend.contratos.modelos import Convite, TipoConvite
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp

CHAVE = "re_valor_falso_de_teste_123"
REMETENTE = "CORA <convites@exemplo.invalid>"
PARA = "pessoa@exemplo.invalid"


class TransporteFalso:
    def __init__(self, status: int = 200, corpo: bytes = b'{"id": "email-1"}', erro=None):
        self.status = status
        self.corpo = corpo
        self.erro = erro
        self.pedidos: list[PedidoHttp] = []

    def enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        self.pedidos.append(pedido)
        if self.erro is not None:
            raise self.erro
        return RespostaHttp(status=self.status, corpo=self.corpo)


def convite(simulado: bool = False, chave: str = "convite:empresa-a:v1:ext:1") -> Convite:
    return Convite(
        id="convite:v1:ext:1",
        empresa_id="empresa-a",
        tipo=TipoConvite.VAGA,
        canal="email",
        vaga_id="v1",
        candidato_id="ext",
        mensagem="texto do convite",
        chave_idempotencia=chave,
        simulado=simulado,
    )


def conteudo() -> ConteudoConvite:
    return ConteudoConvite(
        empresa="CORA",
        titulo_vaga="Pessoa Desenvolvedora Python",
        nome="Pessoa Exemplo",
        destaques=["Python"],
        link="https://agenda.exemplo.invalid/x",
        descricao_origem="seu perfil público do LinkedIn",
        url_origem="https://www.linkedin.com/in/pessoa-exemplo/",
        data_coleta="08/11/2026",
        simulado=False,
    )


def mensageiro(transporte: TransporteFalso) -> MensageiroResend:
    return MensageiroResend(CHAVE, REMETENTE, transporte=transporte)


def test_pedido_ao_resend_tem_o_corpo_e_os_cabecalhos_certos():
    transporte = TransporteFalso()

    assert mensageiro(transporte).enviar_email(convite(), PARA, conteudo())

    [pedido] = transporte.pedidos
    assert pedido.metodo == "POST"
    assert pedido.url == URL_RESEND
    corpo = pedido.corpo_json
    assert corpo["from"] == REMETENTE
    assert corpo["to"] == [PARA]
    assert "Pessoa Desenvolvedora Python" in corpo["subject"]
    assert f"cid:{CID_LOGO}" in corpo["html"]
    assert "Pessoa Exemplo" in corpo["text"]
    [anexo] = corpo["attachments"]
    assert anexo["content_id"] == CID_LOGO
    assert base64.b64decode(anexo["content"]) == LOGO.read_bytes()
    assert pedido.cabecalhos["Authorization"] == f"Bearer {CHAVE}"
    assert pedido.cabecalhos["User-Agent"] == USER_AGENT
    assert pedido.cabecalhos["Idempotency-Key"] == convite().chave_idempotencia


def test_envio_real_nao_leva_o_aviso_de_simulacao():
    transporte = TransporteFalso()

    mensageiro(transporte).enviar_email(convite(), PARA, conteudo())

    corpo = transporte.pedidos[0].corpo_json
    assert AVISO_SIMULACAO not in corpo["html"]
    assert AVISO_SIMULACAO not in corpo["text"]
    assert "[SIMULADO]" not in corpo["subject"]


def test_o_mesmo_convite_nao_e_enviado_duas_vezes():
    transporte = TransporteFalso()
    envio = mensageiro(transporte)

    assert envio.enviar_email(convite(), PARA, conteudo())
    assert envio.enviar_email(convite(), PARA, conteudo())

    assert len(transporte.pedidos) == 1


@pytest.mark.parametrize("status", [401, 422, 500, 503])
def test_erro_do_resend_vira_falha_registrada_sem_chave_nem_corpo(status, caplog):
    corpo = json.dumps({"message": f"chave {CHAVE} recusada", "segredo": "corpo-cru"}).encode()
    transporte = TransporteFalso(status=status, corpo=corpo)
    envio = mensageiro(transporte)

    with caplog.at_level(logging.DEBUG):
        assert not envio.enviar_email(convite(), PARA, conteudo())

    assert str(status) in caplog.text
    assert CHAVE not in caplog.text
    assert "corpo-cru" not in caplog.text
    assert PARA not in caplog.text


def test_falha_depois_de_erro_permite_tentar_de_novo():
    transporte = TransporteFalso(status=500)
    envio = mensageiro(transporte)

    assert not envio.enviar_email(convite(), PARA, conteudo())
    transporte.status = 200
    assert envio.enviar_email(convite(), PARA, conteudo())
    assert len(transporte.pedidos) == 2


@pytest.mark.parametrize("erro", [TimeoutError("tempo"), ConnectionError("queda"), OSError("x")])
def test_falha_de_rede_vira_falha_sem_excecao_nem_chave(erro, caplog):
    transporte = TransporteFalso(erro=erro)

    with caplog.at_level(logging.DEBUG):
        assert not mensageiro(transporte).enviar_email(convite(), PARA, conteudo())

    assert CHAVE not in caplog.text


def test_a_chave_nao_aparece_no_repr_nem_no_pedido_formatado():
    transporte = TransporteFalso()
    envio = mensageiro(transporte)
    envio.enviar_email(convite(), PARA, conteudo())

    assert CHAVE not in repr(envio)
    assert CHAVE not in str(envio)
    assert CHAVE not in repr(transporte.pedidos[0])


def test_chave_ou_remetente_vazios_sao_recusados_sem_mostrar_a_chave():
    with pytest.raises(ValueError) as erro:
        MensageiroResend(CHAVE, "  ", transporte=TransporteFalso())
    assert CHAVE not in str(erro.value)
    with pytest.raises(ValueError):
        MensageiroResend(" ", REMETENTE, transporte=TransporteFalso())


def test_convite_simulado_fica_na_caixa_simulada_e_nao_sai():
    transporte = TransporteFalso()
    simulado = MensageiroSimulado()
    envio = MensageiroResend(CHAVE, REMETENTE, transporte=transporte, simulado=simulado)

    assert envio.enviar(convite(simulado=True))
    assert envio.enviar_email(convite(simulado=True, chave="outra"), PARA, conteudo())

    assert transporte.pedidos == []
    assert len(simulado.enviados("empresa-a")) == 2


def test_convite_real_sem_destinatario_nao_sai(caplog):
    transporte = TransporteFalso()

    with caplog.at_level(logging.WARNING):
        assert not mensageiro(transporte).enviar(convite())

    assert transporte.pedidos == []
    assert "convite:v1:ext:1" in caplog.text


class ClienteQueNaoPodeSerUsado:
    def post(self, *args, **kwargs):
        raise AssertionError("o transporte tentou abrir rede")


def test_transporte_so_fala_com_o_resend():
    transporte = TransporteResend(ClienteQueNaoPodeSerUsado())

    with pytest.raises(ConnectionError):
        transporte.enviar(PedidoHttp(metodo="POST", url="https://outro.exemplo.invalid/emails"))
    assert HOST_RESEND == "api.resend.com"


def test_o_botao_usa_so_o_link_configurado_e_nunca_o_do_conteudo():
    transporte = TransporteFalso()
    envio = MensageiroResend(
        CHAVE, REMETENTE, transporte=transporte, link_convite="https://wa.me/5500000000000"
    )
    item = conteudo().model_copy(update={"link": "https://nara.simulada.local/agenda"})

    envio.enviar_email(convite(), PARA, item)

    corpo = transporte.pedidos[0].corpo_json
    assert 'href="https://wa.me/5500000000000"' in corpo["html"]
    assert "nara.simulada" not in corpo["html"] + corpo["text"]


def test_sem_link_configurado_o_email_real_vai_sem_botao():
    transporte = TransporteFalso()
    item = conteudo().model_copy(update={"link": "https://nara.simulada.local/agenda"})

    mensageiro(transporte).enviar_email(convite(), PARA, item)

    corpo = transporte.pedidos[0].corpo_json
    assert ROTULO_BOTAO not in corpo["html"]
    assert "responda este e-mail" in corpo["text"]
    assert ".local" not in corpo["html"] + corpo["text"]


@pytest.mark.parametrize("link", ["http://wa.me/55", "javascript:alert(1)", "wa.me/55", "  "])
def test_link_do_convite_aceita_so_https(link):
    with pytest.raises(ValueError):
        MensageiroResend(CHAVE, REMETENTE, transporte=TransporteFalso(), link_convite=link)


def test_409_do_resend_e_falha_final_sem_nova_tentativa():
    transporte = TransporteFalso(status=409)
    envio = mensageiro(transporte)

    assert not envio.enviar_email(convite(), PARA, conteudo())
    assert envio.falha_final(convite().chave_idempotencia)
    transporte.status = 200
    assert not envio.enviar_email(convite(), PARA, conteudo())
    assert len(transporte.pedidos) == 1


def test_erro_comum_nao_e_falha_final():
    envio = mensageiro(TransporteFalso(status=500))

    envio.enviar_email(convite(), PARA, conteudo())

    assert not envio.falha_final(convite().chave_idempotencia)
