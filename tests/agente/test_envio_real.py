"""Envio real pelo Resend ligado só por opt-in (decisão de 8/11). Transporte falso, sem rede."""

import logging

from backend.agente.contato_publicado import contato_publicado, mensagem_pelo_contato_publicado
from backend.agente.montagem import montar_servico
from backend.contato.mensageiro import MensageiroSimulado
from backend.contato.prompts import AVISO_SIMULACAO
from backend.contato.resend import MensageiroResend
from backend.contratos.modelos import RespostaCandidato, TipoResposta
from backend.contratos.simulacoes import ClienteNaraSimulado
from backend.contratos.simulacoes import MensageiroSimulado as CaixaSimulada
from backend.fontes.provedores.modelos import CONTATO_NAO_PUBLICADO
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp
from tests.agente.apoio import AnalisadorComEvidencias, candidato_exemplo, vaga_exemplo
from tests.agente.test_fluxo_contato_publicado import EMAIL, ORIGEM, Pecas, externo

CHAVE = "re_valor_falso_de_teste_456"
REMETENTE = "CORA <convites@exemplo.invalid>"
ENVIO_REAL = {"AGENTE_ENVIO_REAL": "1", "RESEND_API_KEY": CHAVE, "EMAIL_FROM": REMETENTE}


class TransporteFalso:
    def __init__(self) -> None:
        self.pedidos: list[PedidoHttp] = []

    def enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        self.pedidos.append(pedido)
        return RespostaHttp(status=200, corpo=b'{"id": "email-1"}')


class PecasReais(Pecas):
    """As peças do fluxo do contato publicado, com o mensageiro do Resend."""

    def __init__(self, tmp_path, candidatos, **campos) -> None:
        super().__init__(tmp_path, candidatos, **campos)
        self.transporte = TransporteFalso()
        self.caixa = CaixaSimulada()
        self.mensageiro = MensageiroResend(
            CHAVE, REMETENTE, transporte=self.transporte, simulado=self.caixa
        )


def _mensageiro(servico):
    return servico._dependencias.mensageiro


def test_sem_as_variaveis_o_mensageiro_e_o_simulado(tmp_path):
    servico = montar_servico(tmp_path / "a.db", ambiente={})

    assert isinstance(_mensageiro(servico), MensageiroSimulado)


def test_faltando_uma_variavel_continua_simulado(tmp_path):
    for falta in ENVIO_REAL:
        ambiente = {k: v for k, v in ENVIO_REAL.items() if k != falta}
        servico = montar_servico(tmp_path / f"{falta}.db", ambiente=ambiente)
        assert isinstance(_mensageiro(servico), MensageiroSimulado), falta


def test_com_as_variaveis_o_mensageiro_e_o_resend_sem_mostrar_a_chave(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        servico = montar_servico(tmp_path / "a.db", ambiente=ENVIO_REAL)

    assert isinstance(_mensageiro(servico), MensageiroResend)
    assert CHAVE not in repr(_mensageiro(servico))
    assert CHAVE not in caplog.text


def test_contato_publicado_sai_pelo_resend_sem_aviso_de_simulacao(tmp_path):
    pecas = PecasReais(tmp_path, [externo()])

    fluxo = pecas.rodar()

    [pedido] = pecas.transporte.pedidos
    corpo = pedido.corpo_json
    assert corpo["to"] == [EMAIL]
    assert corpo["from"] == REMETENTE
    assert ORIGEM in corpo["html"] and ORIGEM in corpo["text"]
    assert AVISO_SIMULACAO not in corpo["html"]
    assert AVISO_SIMULACAO not in corpo["text"]
    [registro] = [r for r in fluxo.convites() if r.convite.candidato_id == "ext"]
    assert not registro.convite.simulado
    assert AVISO_SIMULACAO not in registro.convite.mensagem
    assert registro.estado == "aguardando"
    assert any(e.mensagem == "convite enviado" for e in fluxo.eventos if e.candidato_id == "ext")


def test_opt_out_impede_o_envio_real(tmp_path):
    pecas = PecasReais(tmp_path, [externo(opt_out=True)])

    pecas.rodar()

    assert pecas.transporte.pedidos == []


def test_contato_nao_publicado_nunca_sai_pelo_resend(tmp_path):
    inferido = externo(
        atributos={"python": "sim", "email": EMAIL, "contato_origem": CONTATO_NAO_PUBLICADO}
    )
    pecas = PecasReais(tmp_path, [inferido])

    pecas.rodar()

    assert pecas.transporte.pedidos == []


def test_candidato_sintetico_continua_simulado_mesmo_com_envio_real(tmp_path):
    pecas = PecasReais(tmp_path, [candidato_exemplo("banco", atributos={"python": "sim"})])

    fluxo = pecas.rodar()

    assert pecas.transporte.pedidos == []
    [convite] = [c for c in pecas.caixa.enviados.values() if c.candidato_id == "banco"]
    assert convite.simulado
    assert all(r.convite.simulado for r in fluxo.convites())


def test_lembrete_real_tambem_nao_leva_o_aviso():
    vaga = vaga_exemplo()
    candidato = externo()
    analise = AnalisadorComEvidencias().analisar(vaga, candidato)

    texto = mensagem_pelo_contato_publicado(
        vaga, candidato, analise, contato_publicado(candidato), None, 2, simulado=False
    )

    assert AVISO_SIMULACAO not in texto
    assert ORIGEM in texto


LINK = "https://wa.me/5500000000000?text=Vaga"


class PecasComLink(PecasReais):
    def __init__(self, tmp_path, candidatos, **campos) -> None:
        super().__init__(tmp_path, candidatos, **campos)
        self.mensageiro = MensageiroResend(
            CHAVE, REMETENTE, transporte=self.transporte, simulado=self.caixa, link_convite=LINK
        )


class NaraComLink(ClienteNaraSimulado):
    """A Nara simulada de sempre, que devolve um link `.local` de agendamento."""

    def link_agendamento(self, vaga_id: str, candidato_id: str) -> str | None:
        return f"https://nara.simulada.local/agenda/{vaga_id}/{candidato_id}"


def test_envio_real_sem_convite_link_nao_leva_o_link_da_nara_simulada(tmp_path):
    pecas = PecasReais(tmp_path, [externo()])
    pecas.destino = NaraComLink()

    fluxo = pecas.rodar()

    corpo = pecas.transporte.pedidos[0].corpo_json
    for parte in (corpo["html"], corpo["text"]):
        assert "nara.simulada" not in parte
        assert ".local" not in parte
    assert "Quero conversar sobre a vaga" not in corpo["html"]
    assert "responda este e-mail" in corpo["text"]
    [registro] = fluxo.convites()
    assert ".local" not in registro.convite.mensagem
    assert registro.convite.link_agendamento is None


def test_envio_real_com_convite_link_o_botao_usa_esse_link(tmp_path):
    pecas = PecasComLink(tmp_path, [externo()])
    pecas.destino = NaraComLink()

    fluxo = pecas.rodar()

    corpo = pecas.transporte.pedidos[0].corpo_json
    assert 'href="https://wa.me/5500000000000?text=Vaga"' in corpo["html"]
    assert LINK in corpo["text"]
    assert ".local" not in corpo["html"] + corpo["text"]
    [registro] = fluxo.convites()
    assert registro.convite.link_agendamento == LINK


def test_envio_real_manda_uma_unica_mensagem_por_pessoa_e_vaga(tmp_path):
    pecas = PecasReais(tmp_path, [externo()])
    fluxo = pecas.rodar()
    [registro] = fluxo.convites()

    fluxo.registrar_resposta(
        RespostaCandidato(convite_id=registro.convite.id, tipo=TipoResposta.SILENCIO)
    )
    pecas.relogio.avancar(days=30)
    fluxo.verificar_prazo()
    fluxo.continuar()

    assert len(pecas.transporte.pedidos) == 1
    assert len([r for r in fluxo.convites() if r.convite.candidato_id == "ext"]) == 1


class TransporteQueRecusa(TransporteFalso):
    def enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        self.pedidos.append(pedido)
        return RespostaHttp(status=409)


def test_409_encerra_o_convite_sem_tentar_de_novo(tmp_path):
    pecas = PecasReais(tmp_path, [externo()])
    pecas.transporte = TransporteQueRecusa()
    pecas.mensageiro = MensageiroResend(
        CHAVE, REMETENTE, transporte=pecas.transporte, simulado=pecas.caixa
    )
    fluxo = pecas.rodar()

    fluxo.verificar_prazo()
    fluxo.continuar()

    assert len(pecas.transporte.pedidos) == 1
    [registro] = fluxo.convites()
    assert registro.estado == "encerrado"
    assert any("recusado" in e.mensagem for e in fluxo.eventos if e.candidato_id == "ext")


def test_convite_link_do_ambiente_so_vale_com_https(tmp_path):
    com_link = montar_servico(tmp_path / "a.db", ambiente={**ENVIO_REAL, "CONVITE_LINK": LINK})
    sem_https = montar_servico(
        tmp_path / "b.db", ambiente={**ENVIO_REAL, "CONVITE_LINK": "http://wa.me/55"}
    )

    assert _mensageiro(com_link).link_convite == LINK
    assert _mensageiro(sem_https).link_convite is None
