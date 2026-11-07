import pytest

from backend.agente.configuracao import (
    ETAPA_CONFIGURACAO,
    MAX_TENTATIVAS_CONTATO,
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
