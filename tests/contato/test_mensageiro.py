import pytest

from backend.contato.mensageiro import (
    AVISO_SIMULACAO,
    MensageiroSimulado,
    PreferenciasContato,
    chave_convite,
    criar_convite,
)
from backend.contratos.erros import ModeloIndisponivel
from backend.contratos.interfaces import Mensageiro
from backend.contratos.modelos import (
    Analise,
    Competencia,
    Evidencia,
    Requisito,
    TipoConvite,
    Vaga,
)
from backend.contratos.simulacoes import ClienteModeloSimulado, candidato_simulado

LINK = "https://agenda.simulada.local/v1/c1"


def _vaga(**extra) -> Vaga:
    dados = {
        "id": "v1",
        "empresa_id": "empresa-a",
        "titulo": "Backend Python",
        "descricao": "Time de pagamentos, trabalho remoto.",
        "requisitos": [
            Requisito(id="r1", descricao="Python", campo="linguagem", valor_esperado="python")
        ],
        "competencias": [Competencia(nome="mensageria", peso=1.0)],
        "meta_candidatos": 5,
        "prazo_dias": 7,
        "max_tentativas_contato": 2,
    }
    dados.update(extra)
    return Vaga(**dados)


def _candidato(**extra):
    campos = {
        "nome": "Ana Souza",
        "perfil_texto": "Ana Souza liderou a migração para Kafka.",
        "atributos": {"genero": "feminino"},
    }
    campos.update(extra)
    return candidato_simulado("c1", "empresa-a", **campos)


def _analise(**extra) -> Analise:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "requisitos_ok": {"r1": True},
        "notas": {"mensageria": 0.9},
        "evidencias": [
            Evidencia(
                criterio="mensageria",
                trecho="Ana Souza liderou a migração para Kafka.",
                fonte="banco",
            )
        ],
        "lacunas": [],
        "pontos_a_aprofundar": [],
        "alertas": [],
    }
    dados.update(extra)
    return Analise(**dados)


def _redacao(mensagem: str | None = None, criterios: list[str] | None = None) -> dict:
    texto = mensagem or (
        "Oi {nome}! Vi que você liderou a migração para Kafka e achei que combina com a "
        "vaga Backend Python. Se quiser conversar, agende aqui: {link_agendamento}. "
        "Se preferir não receber mais mensagens, responda SAIR."
    )
    return {
        "mensagem": texto,
        "criterios_citados": ["mensageria"] if criterios is None else criterios,
    }


def _modelo(**redacao) -> ClienteModeloSimulado:
    return ClienteModeloSimulado({"redigir_convite": _redacao(**redacao)})


class ModeloForaDoAr:
    def __init__(self) -> None:
        self.chamadas = 0

    def completar(self, sistema, usuario, esquema, etapa):
        self.chamadas += 1
        raise ModeloIndisponivel("fora do ar")


def _convite(**extra):
    args = {
        "vaga": _vaga(),
        "candidato": _candidato(),
        "analise": _analise(),
        "link_agendamento": LINK,
        "cliente_modelo": _modelo(),
    }
    args.update(extra)
    return criar_convite(**args)


@pytest.mark.parametrize("personalizar", [True, False])
def test_convite_contem_vaga_e_link_de_agendamento(personalizar):
    convite = _convite(preferencias=PreferenciasContato(personalizar=personalizar))

    assert "Backend Python" in convite.mensagem
    assert LINK in convite.mensagem
    assert "SAIR" in convite.mensagem
    assert "Ana Souza" in convite.mensagem
    assert "{" not in convite.mensagem
    assert convite.link_agendamento == LINK
    assert convite.tipo == TipoConvite.VAGA
    assert convite.vaga_id == "v1"
    assert convite.empresa_id == "empresa-a"


def test_mensagem_personalizada_usa_o_texto_do_modelo():
    convite = _convite()

    assert "liderou a migração para Kafka" in convite.mensagem
    assert convite.mensagem.startswith("Oi Ana Souza!")


@pytest.mark.parametrize("personalizar", [True, False])
def test_destino_sem_agenda_gera_convite_sem_link(personalizar):
    modelo = _modelo(
        mensagem=(
            "Oi {nome}! Seu trabalho com Kafka combina com a vaga Backend Python. "
            "A equipe vai combinar a entrevista com você. Para não receber mais, responda SAIR."
        )
    )
    convite = _convite(
        link_agendamento=None,
        cliente_modelo=modelo,
        preferencias=PreferenciasContato(personalizar=personalizar),
    )

    assert convite.link_agendamento is None
    assert "http" not in convite.mensagem
    assert "{" not in convite.mensagem
    assert "SAIR" in convite.mensagem


def test_chave_segue_formato_empresa_vaga_candidato_tipo_tentativa():
    assert chave_convite("empresa-a", "v1", "c1", TipoConvite.VAGA, 2) == ("empresa-a:v1:c1:vaga:2")
    convite = _convite(tentativa=2)
    assert convite.chave_idempotencia == "empresa-a:v1:c1:vaga:2"
    assert convite.id == convite.chave_idempotencia


def test_convite_identifica_simulacao():
    convite = _convite()

    assert convite.simulado is True
    assert convite.canal == "simulado"


def test_modelo_nao_recebe_nome_nem_atributos_do_candidato():
    modelo = _modelo()
    _convite(cliente_modelo=modelo)

    (chamada,) = modelo.chamadas
    assert chamada["etapa"] == "redigir_convite"
    enviado = chamada["sistema"] + chamada["usuario"]
    assert "Ana" not in enviado
    assert "Souza" not in enviado
    assert "feminino" not in enviado
    assert "liderou a migração para Kafka" in enviado
    assert "<dados_candidato>" in chamada["usuario"]


def test_trocar_nome_e_genero_so_muda_o_nome():
    modelo_a, modelo_b = _modelo(), _modelo()
    convite_a = _convite(cliente_modelo=modelo_a)
    convite_b = _convite(
        candidato=_candidato(
            nome="Carlos Lima",
            perfil_texto="Carlos Lima liderou a migração para Kafka.",
            atributos={"genero": "masculino"},
        ),
        analise=_analise(
            evidencias=[
                Evidencia(
                    criterio="mensageria",
                    trecho="Carlos Lima liderou a migração para Kafka.",
                    fonte="banco",
                )
            ]
        ),
        cliente_modelo=modelo_b,
    )

    assert modelo_a.chamadas == modelo_b.chamadas
    assert convite_a.mensagem.replace("Ana Souza", "Carlos Lima") == convite_b.mensagem


def test_empresa_pode_desligar_personalizacao():
    modelo = _modelo()
    convite = _convite(cliente_modelo=modelo, preferencias=PreferenciasContato(personalizar=False))

    assert modelo.chamadas == []
    assert "mensageria" in convite.mensagem


def test_mensagem_padrao_e_deterministica():
    preferencias = PreferenciasContato(personalizar=False)
    assert _convite(preferencias=preferencias).mensagem == (
        _convite(preferencias=preferencias).mensagem
    )


@pytest.mark.parametrize(
    "modelo",
    [ModeloForaDoAr(), ClienteModeloSimulado({})],
    ids=["modelo_indisponivel", "resposta_invalida"],
)
def test_falha_do_modelo_usa_mensagem_padrao(modelo):
    padrao = _convite(preferencias=PreferenciasContato(personalizar=False))
    convite = _convite(cliente_modelo=modelo)

    assert convite.mensagem == padrao.mensagem


@pytest.mark.parametrize(
    "mensagem",
    [
        "Oi {nome}, vaga Backend Python. Responda SAIR para sair.",
        "Oi {nome}, vaga Backend Python. Agende: {link_agendamento}.",
        "Oi {nome}, uma vaga legal. Agende: {link_agendamento}. Responda SAIR.",
        "Oi {nome}, vaga Backend Python na {empresa}: {link_agendamento}. Responda SAIR.",
    ],
    ids=["sem_link", "sem_saida", "sem_vaga", "marcador_desconhecido"],
)
def test_mensagem_incompleta_do_modelo_usa_padrao(mensagem):
    padrao = _convite(preferencias=PreferenciasContato(personalizar=False))
    convite = _convite(cliente_modelo=_modelo(mensagem=mensagem))

    assert convite.mensagem == padrao.mensagem


def test_link_inventado_sem_agenda_usa_padrao():
    padrao = _convite(link_agendamento=None, preferencias=PreferenciasContato(personalizar=False))
    convite = _convite(link_agendamento=None, cliente_modelo=_modelo())

    assert convite.mensagem == padrao.mensagem


def test_citar_fit_inexistente_usa_padrao():
    padrao = _convite(preferencias=PreferenciasContato(personalizar=False))
    convite = _convite(cliente_modelo=_modelo(criterios=["mensageria", "lideranca"]))

    assert convite.mensagem == padrao.mensagem


@pytest.mark.parametrize(
    "extra",
    [
        {"candidato": candidato_simulado("c1", "empresa-b")},
        {"analise": _analise(empresa_id="empresa-b")},
        {"analise": _analise(vaga_id="v2")},
        {"analise": _analise(candidato_id="c2")},
    ],
    ids=["candidato_de_outra_empresa", "analise_de_outra_empresa", "outra_vaga", "outro_id"],
)
def test_candidato_ou_analise_de_outra_empresa_e_recusado(extra):
    with pytest.raises(ValueError):
        _convite(**extra)


def test_mensageiro_segue_a_interface():
    assert isinstance(MensageiroSimulado(), Mensageiro)


def test_reenvio_com_mesma_chave_nao_duplica():
    mensageiro = MensageiroSimulado()
    convite = _convite()

    assert mensageiro.enviar(convite) is True
    assert mensageiro.enviar(convite) is True
    assert mensageiro.enviados("empresa-a") == [convite]


def test_falha_de_envio_permite_repetir():
    mensageiro = MensageiroSimulado(falhas_restantes=1)
    convite = _convite()

    assert mensageiro.enviar(convite) is False
    assert mensageiro.enviados("empresa-a") == []
    assert mensageiro.enviar(convite) is True
    assert mensageiro.enviados("empresa-a") == [convite]


def test_falha_apos_envio_e_repeticao_nao_duplicam():
    mensageiro = MensageiroSimulado(falhas_apos_envio=1)
    convite = _convite()

    assert mensageiro.enviar(convite) is False
    assert mensageiro.enviar(convite) is True
    assert mensageiro.enviados("empresa-a") == [convite]


def test_mensageiro_isola_empresas():
    mensageiro = MensageiroSimulado()
    convite = _convite()
    outro = convite.model_copy(
        update={"empresa_id": "empresa-b", "chave_idempotencia": "empresa-b:v1:c1:vaga:1"}
    )

    mensageiro.enviar(convite)
    mensageiro.enviar(outro)

    assert mensageiro.enviados("empresa-a") == [convite]
    assert mensageiro.enviados("empresa-b") == [outro]


def test_mensageiro_recusa_convite_nao_simulado():
    convite = _convite().model_copy(update={"simulado": False})

    with pytest.raises(ValueError):
        MensageiroSimulado().enviar(convite)


def test_mensageiro_exige_empresa():
    with pytest.raises(ValueError):
        MensageiroSimulado().enviados("")


@pytest.mark.parametrize("personalizar", [True, False])
def test_convite_traz_origem_do_contato_e_aviso_de_simulacao(personalizar):
    candidato = _candidato(fonte="rede_simulada", origem="importacao_rede_sintetica")
    convite = _convite(
        candidato=candidato, preferencias=PreferenciasContato(personalizar=personalizar)
    )

    assert "rede_simulada (importacao_rede_sintetica)" in convite.mensagem
    assert convite.mensagem.endswith(AVISO_SIMULACAO)


def test_rodape_do_convite_nao_vai_ao_modelo():
    modelo = _modelo()
    _convite(cliente_modelo=modelo, candidato=_candidato(fonte="rede_simulada"))

    assert all("rede_simulada" not in str(chamada) for chamada in modelo.chamadas)
