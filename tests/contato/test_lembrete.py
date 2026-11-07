"""Testes do lembrete único (T3.7)."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.contato.email_inicial import (
    ContatoBloqueado,
    ContatoPublicado,
    MensageiroEmailSimulado,
    Remetente,
    criar_email,
)
from backend.contato.lembrete import (
    INTERVALO_PADRAO,
    AcaoLembrete,
    AgendaLembretes,
    SituacaoContato,
    decidir_lembrete,
)
from backend.contato.supressao import ListaSupressao
from backend.contratos.modelos import Analise, Competencia, Evidencia, Requisito, Vaga
from backend.contratos.simulacoes import ClienteModeloSimulado, candidato_simulado

ENVIO = datetime(2026, 11, 7, 12, tzinfo=UTC)
ENDERECO = "ana.dev@exemplo.com"


def _vaga() -> Vaga:
    return Vaga(
        id="v1",
        empresa_id="empresa-a",
        titulo="Backend Python",
        descricao="Time de pagamentos.",
        requisitos=[Requisito(id="r1", descricao="Python", campo="linguagem", valor_esperado="py")],
        competencias=[Competencia(nome="mensageria", peso=1.0)],
        meta_candidatos=5,
        prazo_dias=7,
        max_tentativas_contato=2,
    )


def _args(lista: ListaSupressao, modelo=None, candidato_id: str = "c1") -> dict:
    return {
        "vaga": _vaga(),
        "candidato": candidato_simulado(candidato_id, "empresa-a", nome="Ana Souza"),
        "analise": Analise(
            empresa_id="empresa-a",
            vaga_id="v1",
            candidato_id=candidato_id,
            requisitos_ok={"r1": True},
            notas={},
            evidencias=[Evidencia(criterio="mensageria", trecho="Usou Kafka.", fonte="site")],
            lacunas=[],
            pontos_a_aprofundar=[],
            alertas=[],
        ),
        "contato": ContatoPublicado(
            canal="email",
            endereco=ENDERECO if candidato_id == "c1" else f"{candidato_id}@exemplo.com",
            url_origem="https://ana.dev.exemplo.com",
            descricao_origem="seu site pessoal",
            coletado_em=ENVIO,
            publicado_para_contato=True,
        ),
        "remetente": Remetente(nome_empresa="Acme Pagamentos", numero_whatsapp="5581900000000"),
        "lista": lista,
        "cliente_modelo": modelo or ClienteModeloSimulado(),
    }


@pytest.fixture
def lista() -> ListaSupressao:
    return ListaSupressao(b"segredo-de-teste-sintetico")


def _situacao(**extra) -> SituacaoContato:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "para": ENDERECO,
        "enviado_em": ENVIO,
    }
    dados.update(extra)
    return SituacaoContato(**dados)


# Decisão


def test_intervalo_padrao_e_de_tres_dias():
    assert INTERVALO_PADRAO == timedelta(days=3)


def test_antes_do_intervalo_espera():
    decisao = decidir_lembrete(_situacao(), ENVIO + timedelta(days=2, hours=23))

    assert decisao.acao == AcaoLembrete.ESPERAR


def test_depois_do_intervalo_envia_lembrete():
    decisao = decidir_lembrete(_situacao(), ENVIO + timedelta(days=3))

    assert decisao.acao == AcaoLembrete.ENVIAR_LEMBRETE
    assert decisao.regra == "intervalo_sem_resposta"


def test_intervalo_e_configuravel():
    decisao = decidir_lembrete(_situacao(), ENVIO + timedelta(days=1), intervalo=timedelta(days=1))

    assert decisao.acao == AcaoLembrete.ENVIAR_LEMBRETE


def test_silencio_depois_do_lembrete_encerra():
    situacao = _situacao(lembrete_em=ENVIO + timedelta(days=3))

    assert decidir_lembrete(situacao, ENVIO + timedelta(days=5)).acao == AcaoLembrete.ESPERAR
    decisao = decidir_lembrete(situacao, ENVIO + timedelta(days=6))
    assert decisao.acao == AcaoLembrete.ENCERRAR_SILENCIO
    assert decisao.regra == "silencio_apos_lembrete"


def test_nunca_ha_segundo_lembrete():
    situacao = _situacao(lembrete_em=ENVIO + timedelta(days=3))

    for dias in range(3, 60):
        acao = decidir_lembrete(situacao, ENVIO + timedelta(days=dias)).acao
        assert acao != AcaoLembrete.ENVIAR_LEMBRETE


@pytest.mark.parametrize(
    ("extra", "regra"),
    [
        ({"respondeu_em": ENVIO + timedelta(days=1)}, "respondeu"),
        ({"suprimido": True}, "lista_supressao"),
        ({"encerrado": True}, "encerrado"),
    ],
)
def test_resposta_supressao_ou_encerramento_cancelam(extra, regra):
    decisao = decidir_lembrete(_situacao(**extra), ENVIO + timedelta(days=10))

    assert decisao.acao == AcaoLembrete.NADA
    assert decisao.regra == regra


def test_decisao_e_deterministica():
    hoje = ENVIO + timedelta(days=4)

    assert decidir_lembrete(_situacao(), hoje) == decidir_lembrete(_situacao(), hoje)


# E-mail de lembrete


def test_lembrete_e_curto_e_tem_os_itens_obrigatorios(lista):
    primeiro = criar_email(**_args(lista))
    lembrete = criar_email(**_args(lista), tentativa=2)

    corpo = lembrete.convite.mensagem
    assert len(corpo) < len(primeiro.convite.mensagem)
    assert "lembrar" in corpo.lower()
    assert "Backend Python" in corpo
    assert "https://ana.dev.exemplo.com" in corpo
    assert lembrete.link_exclusao in corpo
    assert lembrete.link_whatsapp in corpo
    assert lembrete.codigo == primeiro.codigo
    assert lembrete.assunto.startswith("[SIMULADO] Lembrete:")
    assert lembrete.convite.chave_idempotencia.endswith(":vaga:2")


def test_lembrete_nao_chama_o_modelo(lista):
    modelo = ClienteModeloSimulado()

    criar_email(**_args(lista, modelo), tentativa=2)

    assert modelo.chamadas == []


def test_nao_ha_tentativa_tres(lista):
    with pytest.raises(ValueError):
        criar_email(**_args(lista), tentativa=3)


# Agenda


class Cenario:
    def __init__(self, lista: ListaSupressao) -> None:
        self.lista = lista
        self.emails = MensageiroEmailSimulado(lista)
        self.agenda = AgendaLembretes(lista)
        self.primeiro = criar_email(**_args(lista))
        self.emails.enviar(self.primeiro)
        self.agenda.registrar_envio(self.primeiro, ENVIO)

    def processar(self, dias: float, **extra):
        return self.agenda.processar(
            ENVIO + timedelta(days=dias),
            lambda situacao: criar_email(**_args(self.lista), tentativa=2),
            self.emails,
            **extra,
        )


@pytest.fixture
def cenario(lista) -> Cenario:
    return Cenario(lista)


def test_agenda_envia_um_lembrete_e_depois_encerra(cenario):
    assert cenario.processar(1) == []

    decisoes = cenario.processar(3)
    assert [d.acao for d in decisoes] == [AcaoLembrete.ENVIAR_LEMBRETE]
    assert len(cenario.emails.enviados("empresa-a")) == 2

    assert cenario.processar(4) == []
    assert cenario.processar(5) == []

    decisoes = cenario.processar(6)
    assert [d.acao for d in decisoes] == [AcaoLembrete.ENCERRAR_SILENCIO]

    assert cenario.processar(30) == []
    assert len(cenario.emails.enviados("empresa-a")) == 2


def test_processar_duas_vezes_no_mesmo_dia_nao_duplica(cenario):
    cenario.processar(3)
    cenario.processar(3)

    assert len(cenario.emails.enviados("empresa-a")) == 2


def test_resposta_cancela_o_lembrete(cenario):
    cenario.agenda.registrar_resposta("empresa-a", "v1", "c1", ENVIO + timedelta(days=1))

    assert cenario.processar(3) == []
    assert len(cenario.emails.enviados("empresa-a")) == 1


def test_resposta_de_outra_empresa_nao_cancela(cenario):
    cenario.agenda.registrar_resposta("empresa-b", "v1", "c1", ENVIO + timedelta(days=1))

    assert [d.acao for d in cenario.processar(3)] == [AcaoLembrete.ENVIAR_LEMBRETE]


def test_exclusao_cancela_o_lembrete(cenario):
    token = cenario.primeiro.link_exclusao.rsplit("/", 1)[-1]
    cenario.lista.aplicar_exclusao(token)

    assert cenario.processar(3) == []
    assert len(cenario.emails.enviados("empresa-a")) == 1


def test_pode_contatar_falso_bloqueia_o_lembrete(cenario):
    decisoes = cenario.processar(3, pode_contatar=lambda empresa, vaga, candidato: False)

    assert [d.regra for d in decisoes] == ["pode_contatar"]
    assert len(cenario.emails.enviados("empresa-a")) == 1


def test_falha_de_envio_tenta_de_novo_depois(cenario):
    cenario.emails.falhas_restantes = 1

    cenario.processar(3)
    assert len(cenario.emails.enviados("empresa-a")) == 1

    cenario.processar(3.5)
    assert len(cenario.emails.enviados("empresa-a")) == 2


def test_bloqueio_no_envio_encerra_sem_erro(cenario):
    def suprime_e_cria(situacao):
        email = criar_email(**_args(cenario.lista), tentativa=2)
        cenario.lista.suprimir("empresa-a", [ENDERECO])
        return email

    decisoes = cenario.agenda.processar(ENVIO + timedelta(days=3), suprime_e_cria, cenario.emails)

    assert [d.regra for d in decisoes] == ["lista_supressao"]
    assert len(cenario.emails.enviados("empresa-a")) == 1
    assert cenario.processar(10) == []


def test_criar_lembrete_bloqueado_nao_quebra_a_agenda(cenario):
    def bloqueado(situacao):
        raise ContatoBloqueado("contato_nao_publicado")

    decisoes = cenario.agenda.processar(ENVIO + timedelta(days=3), bloqueado, cenario.emails)

    assert [d.regra for d in decisoes] == ["contato_nao_publicado"]
    assert cenario.processar(10) == []


def test_registrar_o_mesmo_envio_duas_vezes_e_idempotente(cenario):
    cenario.agenda.registrar_envio(cenario.primeiro, ENVIO + timedelta(days=2))

    assert [d.acao for d in cenario.processar(3)] == [AcaoLembrete.ENVIAR_LEMBRETE]


def test_lembrete_nao_entra_como_novo_envio(cenario, lista):
    lembrete = criar_email(**_args(lista), tentativa=2)

    with pytest.raises(ValueError):
        cenario.agenda.registrar_envio(lembrete, ENVIO)
