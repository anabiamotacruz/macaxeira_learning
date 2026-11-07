"""Testes do e-mail inicial do #50 (ajuste da T3.1)."""

from datetime import UTC, datetime

import pytest

from backend.contato.email_inicial import (
    ContatoBloqueado,
    ContatoPublicado,
    MensageiroEmailSimulado,
    Remetente,
    codigo_convite,
    criar_email,
)
from backend.contato.supressao import ListaSupressao
from backend.contratos.erros import ModeloIndisponivel
from backend.contratos.modelos import Analise, Competencia, Evidencia, Requisito, Vaga
from backend.contratos.simulacoes import ClienteModeloSimulado, candidato_simulado

ENDERECO = "ana.dev@exemplo.com"
ORIGEM = "https://github.com/ana-dev"
REMETENTE = Remetente(nome_empresa="Acme Pagamentos", numero_whatsapp="5581900000000")


def _vaga() -> Vaga:
    return Vaga(
        id="v1",
        empresa_id="empresa-a",
        titulo="Backend Python",
        descricao="Time de pagamentos, trabalho remoto.",
        requisitos=[
            Requisito(id="r1", descricao="Python", campo="linguagem", valor_esperado="python")
        ],
        competencias=[Competencia(nome="mensageria", peso=1.0)],
        meta_candidatos=5,
        prazo_dias=7,
        max_tentativas_contato=2,
    )


def _candidato(**extra):
    campos = {
        "nome": "Ana Souza",
        "perfil_texto": "Ana Souza liderou a migração para Kafka.",
        "atributos": {"genero": "feminino"},
    }
    campos.update(extra)
    return candidato_simulado("c1", "empresa-a", **campos)


def _analise() -> Analise:
    return Analise(
        empresa_id="empresa-a",
        vaga_id="v1",
        candidato_id="c1",
        requisitos_ok={"r1": True},
        notas={"mensageria": 0.9},
        evidencias=[
            Evidencia(
                criterio="mensageria",
                trecho="Ana Souza liderou a migração para Kafka.",
                fonte="github",
            )
        ],
        lacunas=[],
        pontos_a_aprofundar=[],
        alertas=[],
    )


def _contato(**extra) -> ContatoPublicado:
    dados = {
        "canal": "email",
        "endereco": ENDERECO,
        "url_origem": ORIGEM,
        "descricao_origem": "seu perfil público no GitHub",
        "coletado_em": datetime(2026, 11, 7, 10, tzinfo=UTC),
        "publicado_para_contato": True,
    }
    dados.update(extra)
    return ContatoPublicado(**dados)


def _modelo(paragrafo: str | None = None, criterios: list[str] | None = None):
    texto = paragrafo or (
        "Oi {nome}! Vi que você liderou a migração para Kafka e lembrei da nossa vaga "
        "de Backend Python."
    )
    return ClienteModeloSimulado(
        {
            "redigir_email": {
                "paragrafo": texto,
                "criterios_citados": ["mensageria"] if criterios is None else criterios,
            }
        }
    )


@pytest.fixture
def lista() -> ListaSupressao:
    return ListaSupressao(b"segredo-de-teste-sintetico")


def _email(lista, **extra):
    args = {
        "vaga": _vaga(),
        "candidato": _candidato(),
        "analise": _analise(),
        "contato": _contato(),
        "remetente": REMETENTE,
        "lista": lista,
        "cliente_modelo": _modelo(),
    }
    args.update(extra)
    return criar_email(**args)


@pytest.mark.parametrize("personalizar", [True, False])
def test_email_tem_todo_o_conteudo_obrigatorio(lista, personalizar):
    email = _email(lista, personalizar=personalizar)
    corpo = email.convite.mensagem

    assert "Acme Pagamentos" in corpo
    assert "Backend Python" in corpo
    assert "Ana Souza" in corpo
    assert ORIGEM in corpo
    assert "perfil público no GitHub" in corpo
    assert email.link_exclusao in corpo
    assert email.link_whatsapp in corpo
    assert "SAIR" in corpo
    assert "{" not in corpo
    assert email.para == ENDERECO


def test_motivo_da_escolha_vem_do_modelo(lista):
    email = _email(lista)

    assert "liderou a migração para Kafka" in email.convite.mensagem


def test_motivo_padrao_cita_criterios_atendidos(lista):
    email = _email(lista, personalizar=False)

    assert "mensageria" in email.convite.mensagem


def test_cabecalhos_de_saida_em_um_clique(lista):
    email = _email(lista)

    assert email.cabecalhos["List-Unsubscribe"] == f"<{email.link_exclusao}>"
    assert email.cabecalhos["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_link_do_whatsapp_leva_o_codigo_curto(lista):
    email = _email(lista)

    assert email.link_whatsapp == (f"https://wa.me/5581900000000?text=Vaga%20{email.codigo}")
    assert len(email.codigo) == 6
    assert email.codigo.isalnum()
    assert email.codigo == codigo_convite("empresa-a", "v1", "c1")


def test_codigo_e_link_nao_expoem_dados(lista):
    email = _email(lista)

    for texto in (email.codigo, email.link_whatsapp, email.link_exclusao):
        assert "ana" not in texto.lower()
        assert "c1" not in texto
        assert "empresa-a" not in texto


def test_email_identifica_simulacao(lista):
    email = _email(lista)

    assert email.assunto.startswith("[SIMULADO]")
    assert "simulad" in email.convite.mensagem.lower()
    assert email.convite.simulado
    assert email.convite.canal == "email"


def test_primeiro_email_nao_leva_link_da_nara(lista):
    email = _email(lista)

    assert email.convite.link_agendamento is None
    assert "nara" not in email.convite.mensagem.lower()


def test_modelo_nao_recebe_nome_nem_contato(lista):
    modelo = _modelo()
    _email(lista, cliente_modelo=modelo)

    pedido = modelo.chamadas[0]["usuario"]
    assert "Ana" not in pedido
    assert "Souza" not in pedido
    assert ENDERECO not in pedido
    assert "feminino" not in pedido


def test_contato_inferido_e_bloqueado(lista):
    with pytest.raises(ContatoBloqueado) as erro:
        _email(lista, contato=_contato(publicado_para_contato=False))

    assert erro.value.regra == "contato_nao_publicado"


def test_contato_que_nao_e_email_e_bloqueado(lista):
    with pytest.raises(ContatoBloqueado) as erro:
        _email(lista, contato=_contato(canal="whatsapp", endereco="+5581999990000"))

    assert erro.value.regra == "canal_nao_e_email"


def test_suprimido_nao_recebe_email(lista):
    lista.suprimir("empresa-a", ["ANA.DEV@exemplo.com"])

    with pytest.raises(ContatoBloqueado) as erro:
        _email(lista)

    assert erro.value.regra == "lista_supressao"


def test_supressao_depois_de_criar_impede_o_envio(lista):
    mensageiro = MensageiroEmailSimulado(lista)
    email = _email(lista)
    lista.suprimir("empresa-a", [ENDERECO])

    with pytest.raises(ContatoBloqueado):
        mensageiro.enviar(email)

    assert mensageiro.enviados("empresa-a") == []


def test_clicar_no_link_do_email_suprime(lista):
    email = _email(lista)
    token = email.link_exclusao.rsplit("/", 1)[-1]

    lista.aplicar_exclusao(token)

    assert lista.esta_suprimido("empresa-a", [ENDERECO])


@pytest.mark.parametrize(
    "paragrafo",
    [
        "Oi {nome}! Você combina com a vaga.",  # sem o título
        "Oi {nome}! Veja a vaga de Backend Python em https://golpe.exemplo.com",
        "Oi {nome}! Escreva para rh@exemplo.com sobre a vaga de Backend Python.",
        "Oi {nome}! A vaga de Backend Python é sua: {link_exclusao}",
    ],
)
def test_redacao_fora_das_regras_usa_motivo_padrao(lista, paragrafo):
    email = _email(lista, cliente_modelo=_modelo(paragrafo=paragrafo))

    corpo = email.convite.mensagem
    assert "golpe" not in corpo
    assert "rh@exemplo.com" not in corpo
    assert "mensageria" in corpo
    assert corpo.count(email.link_exclusao) == 1


def test_citar_criterio_sem_evidencia_usa_padrao(lista):
    email = _email(lista, cliente_modelo=_modelo(criterios=["liderança"]))

    assert "liderou a migração" not in email.convite.mensagem.split("\n\n")[0]


def test_falha_do_modelo_usa_motivo_padrao(lista):
    class ForaDoAr:
        def completar(self, sistema, usuario, esquema, etapa):
            raise ModeloIndisponivel("fora do ar")

    email = _email(lista, cliente_modelo=ForaDoAr())

    assert "Backend Python" in email.convite.mensagem
    assert email.link_exclusao in email.convite.mensagem


def test_trocar_nome_e_genero_so_muda_o_nome(lista):
    um = _email(lista)
    outro = _email(
        lista,
        candidato=_candidato(nome="Bruno Lima", atributos={"genero": "masculino"}),
    )

    assert um.convite.mensagem.replace("Ana Souza", "X") == outro.convite.mensagem.replace(
        "Bruno Lima", "X"
    )


def test_candidato_de_outra_empresa_e_recusado(lista):
    with pytest.raises(ValueError):
        _email(lista, candidato=candidato_simulado("c1", "empresa-b"))


def test_envio_e_idempotente(lista):
    mensageiro = MensageiroEmailSimulado(lista)
    email = _email(lista)

    assert mensageiro.enviar(email)
    assert mensageiro.enviar(email)

    assert len(mensageiro.enviados("empresa-a")) == 1


def test_falha_de_envio_permite_repetir(lista):
    mensageiro = MensageiroEmailSimulado(lista, falhas_restantes=1)
    email = _email(lista)

    assert not mensageiro.enviar(email)
    assert mensageiro.enviar(email)
    assert len(mensageiro.enviados("empresa-a")) == 1


def test_codigo_encontra_o_email_enviado(lista):
    mensageiro = MensageiroEmailSimulado(lista)
    email = _email(lista)
    mensageiro.enviar(email)

    assert mensageiro.por_codigo(email.codigo) == email
    assert mensageiro.por_codigo(email.codigo.lower()) == email
    assert mensageiro.por_codigo("ZZZZZZ") is None


def test_caixas_separadas_por_empresa(lista):
    mensageiro = MensageiroEmailSimulado(lista)
    mensageiro.enviar(_email(lista))

    assert mensageiro.enviados("empresa-b") == []


def test_lembrete_tem_chave_propria_e_o_mesmo_codigo(lista):
    primeiro = _email(lista)
    lembrete = _email(lista, tentativa=2)

    assert primeiro.convite.chave_idempotencia != lembrete.convite.chave_idempotencia
    assert primeiro.codigo == lembrete.codigo


def test_codigos_diferentes_por_candidato_e_vaga():
    assert codigo_convite("empresa-a", "v1", "c1") != codigo_convite("empresa-a", "v1", "c2")
    assert codigo_convite("empresa-a", "v1", "c1") != codigo_convite("empresa-a", "v2", "c1")
