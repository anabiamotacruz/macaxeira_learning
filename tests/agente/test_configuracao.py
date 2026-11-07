import pytest

from backend.agente.configuracao import (
    ETAPA_CONFIGURACAO,
    MAX_TENTATIVAS_CONTATO,
    TAMANHO_MAXIMO_DESCRICAO,
    PerguntaVaga,
    PropostaModelo,
    propor_configuracao,
)
from backend.contratos.modelos import Vaga
from backend.contratos.simulacoes import ClienteModeloSimulado

DESCRICAO = (
    "Procuramos pessoa desenvolvedora Python em João Pessoa, com SQL. "
    "Queremos 5 candidatos em 14 dias."
)


def _resposta(**campos) -> dict:
    dados = {
        "titulo": "Pessoa Desenvolvedora Python",
        "requisitos": [
            {
                "id": "r1",
                "descricao": "Morar em João Pessoa",
                "campo": "cidade",
                "valor_esperado": "João Pessoa",
            }
        ],
        "competencias": [{"nome": "Python", "peso": 0.7}, {"nome": "SQL", "peso": 0.3}],
        "meta_candidatos": 5,
        "prazo_dias": 14,
        "duvidas": [],
    }
    dados.update(campos)
    return dados


def _cliente(**campos) -> ClienteModeloSimulado:
    return ClienteModeloSimulado({ETAPA_CONFIGURACAO: _resposta(**campos)})


def test_propoe_requisitos_competencias_e_meta():
    cliente = _cliente()

    vaga = propor_configuracao(DESCRICAO, "empresa-a", cliente)

    assert isinstance(vaga, Vaga)
    assert vaga.aprovada is False
    assert vaga.empresa_id == "empresa-a"
    assert vaga.titulo == "Pessoa Desenvolvedora Python"
    assert vaga.descricao == DESCRICAO
    assert [r.id for r in vaga.requisitos] == ["r1"]
    assert [c.nome for c in vaga.competencias] == ["Python", "SQL"]
    assert vaga.meta_candidatos == 5
    assert vaga.prazo_dias == 14
    assert [c["etapa"] for c in cliente.chamadas] == ["configuracao"]


def test_empresa_aprovacao_e_limite_de_contato_nao_vem_do_modelo():
    assert not {"id", "empresa_id", "aprovada", "max_tentativas_contato"} & set(
        PropostaModelo.model_fields
    )

    vaga = propor_configuracao(DESCRICAO, "empresa-a", _cliente())

    assert vaga.max_tentativas_contato == MAX_TENTATIVAS_CONTATO


def test_id_da_vaga_e_estavel_e_nao_repete_entre_empresas():
    primeira = propor_configuracao(DESCRICAO, "empresa-a", _cliente())
    repetida = propor_configuracao(DESCRICAO, "empresa-a", _cliente())
    outra_empresa = propor_configuracao(DESCRICAO, "empresa-b", _cliente())

    assert primeira.id == repetida.id
    assert primeira.id != outra_empresa.id


@pytest.mark.parametrize("empresa_id", ["", "  "])
def test_empresa_vazia_e_recusada_sem_chamar_o_modelo(empresa_id):
    cliente = _cliente()

    with pytest.raises(ValueError, match="empresa_id"):
        propor_configuracao(DESCRICAO, empresa_id, cliente)

    assert cliente.chamadas == []


def test_vaga_ambigua_devolve_pergunta():
    resultado = propor_configuracao(
        DESCRICAO, "empresa-a", _cliente(duvidas=["O inglês é eliminatório?"])
    )

    assert isinstance(resultado, PerguntaVaga)
    assert resultado.empresa_id == "empresa-a"
    assert "inglês" in resultado.pergunta


@pytest.mark.parametrize(
    "campos, trecho",
    [
        ({"requisitos": []}, "requisito"),
        ({"competencias": []}, "competência"),
        ({"meta_candidatos": None}, "candidatos"),
        ({"prazo_dias": None}, "prazo"),
        ({"titulo": " "}, "título"),
        ({"duvidas": [" "], "requisitos": []}, "requisito"),
    ],
)
def test_resposta_incompleta_devolve_pergunta_sem_inventar(campos, trecho):
    resultado = propor_configuracao(DESCRICAO, "empresa-a", _cliente(**campos))

    assert isinstance(resultado, PerguntaVaga)
    assert trecho in resultado.pergunta


def test_resposta_so_com_duvida_e_valida():
    cliente = ClienteModeloSimulado({ETAPA_CONFIGURACAO: {"duvidas": ["Qual é a cidade?"]}})

    resultado = propor_configuracao(DESCRICAO, "empresa-a", cliente)

    assert isinstance(resultado, PerguntaVaga)
    assert resultado.pergunta == "Qual é a cidade?"


@pytest.mark.parametrize(
    "campos",
    [
        {
            "requisitos": [
                {"id": "r1", "descricao": "Idade", "campo": "idade", "valor_esperado": "30"}
            ]
        },
        {"competencias": [{"nome": "Religião", "peso": 1.0}]},
        {
            "requisitos": [
                {"id": "r1", "descricao": "Perfil", "campo": "p", "valor_esperado": "mulheres"}
            ]
        },
        {"competencias": [{"nome": "Ser jovem", "peso": 1.0}]},
    ],
)
def test_proposta_passa_por_validar_criterios(campos):
    resultado = propor_configuracao(DESCRICAO, "empresa-a", _cliente(**campos))

    assert isinstance(resultado, PerguntaVaga)
    assert "sensível" in resultado.pergunta


@pytest.mark.parametrize(
    "descricao",
    [
        "Pessoa desenvolvedora Python. Idade máxima de 30 anos.",
        "Pessoa desenvolvedora Python, sexo masculino.",
        "Backend Python. Vaga exclusiva para homens.",
        "Buscamos pessoa solteira para viagens.",
        "Procuramos dev. Religião católica é necessária.",
        "Não discriminamos por raça, mas a idade precisa ser até 30.",
        "Valorizamos a diversidade. Idade entre 20 e 30 anos.",
        "Sem distinção de gênero, exceto para esta vaga: só homens.",
        "Vaga inclusiva para mulheres.",
    ],
)
def test_criterio_sensivel_na_descricao_vira_pergunta_sem_chamar_o_modelo(descricao):
    cliente = _cliente()

    resultado = propor_configuracao(descricao, "empresa-a", cliente)

    assert isinstance(resultado, PerguntaVaga)
    assert "sensível" in resultado.pergunta
    assert resultado.trecho_ambiguo
    assert resultado.trecho_ambiguo in descricao
    assert cliente.chamadas == []


@pytest.mark.parametrize(
    "titulo",
    [
        "Dev Python, sexo masculino",
        "Desenvolvedora Python jovem",
        "Dev até certa IDADE",
        "Vaga inclusiva para qualquer gênero",
    ],
)
def test_criterio_sensivel_so_no_titulo_vira_pergunta(titulo):
    resultado = propor_configuracao(DESCRICAO, "empresa-a", _cliente(titulo=titulo))

    assert isinstance(resultado, PerguntaVaga)
    assert "sensível" in resultado.pergunta
    assert resultado.trecho_ambiguo == titulo


@pytest.mark.parametrize(
    "aviso",
    [
        "Não discriminamos por raça, gênero, idade, religião ou orientação sexual.",
        "Todas as pessoas são bem-vindas, independentemente de gênero, raça ou estado civil.",
        "Contratamos sem distinção de sexo, etnia ou idade.",
        "Somos uma empresa com igualdade de oportunidades para qualquer gênero.",
        "Incentivamos candidaturas de mulheres e pessoas negras.",
    ],
)
def test_aviso_de_nao_discriminacao_nao_bloqueia_a_proposta(aviso):
    descricao = f"{DESCRICAO}\n{aviso}"

    resultado = propor_configuracao(descricao, "empresa-a", _cliente())

    assert isinstance(resultado, Vaga)
    assert resultado.descricao == descricao


def test_palavra_parecida_nao_e_confundida_com_termo_sensivel():
    descricao = "Dev com capacidade analítica, para corrigir race conditions no sexto andar."

    assert isinstance(propor_configuracao(descricao, "empresa-a", _cliente()), Vaga)


@pytest.mark.parametrize("descricao", ["", "   "])
def test_descricao_vazia_vira_pergunta_sem_chamar_o_modelo(descricao):
    cliente = _cliente()

    resultado = propor_configuracao(descricao, "empresa-a", cliente)

    assert isinstance(resultado, PerguntaVaga)
    assert cliente.chamadas == []


def test_descricao_grande_demais_vira_pergunta_sem_chamar_o_modelo():
    cliente = _cliente()

    resultado = propor_configuracao("x" * (TAMANHO_MAXIMO_DESCRICAO + 1), "empresa-a", cliente)

    assert isinstance(resultado, PerguntaVaga)
    assert cliente.chamadas == []
