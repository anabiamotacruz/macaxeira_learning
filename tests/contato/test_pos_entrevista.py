import pytest

from backend.contato.pos_entrevista import AVISO_SIMULACAO, mensagem_pos_entrevista
from backend.contato.prompts import MARCADOR_NOME, PALAVRA_SAIDA
from backend.contratos.modelos import Competencia, Requisito, ResultadoEntrevista, Vaga


def _vaga(**extra) -> Vaga:
    dados = {
        "id": "v1",
        "empresa_id": "empresa-a",
        "titulo": "Backend Python",
        "descricao": "Time de pagamentos.",
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


def _resultado(**extra) -> ResultadoEntrevista:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "notas": {"mensageria": 0.87, "comunicacao": 0.42},
        "aprovado": True,
    }
    dados.update(extra)
    return ResultadoEntrevista(**dados)


@pytest.mark.parametrize("aprovado", [True, False])
def test_mensagem_cita_vaga_marcador_de_nome_e_saida(aprovado):
    texto = mensagem_pos_entrevista(_vaga(), _resultado(aprovado=aprovado))

    assert "Backend Python" in texto
    assert MARCADOR_NOME in texto
    assert PALAVRA_SAIDA in texto


@pytest.mark.parametrize("aprovado", [True, False])
def test_mensagem_nao_traz_nota_ranking_nem_outra_pessoa(aprovado):
    texto = mensagem_pos_entrevista(_vaga(), _resultado(aprovado=aprovado))

    assert not any(caractere.isdigit() for caractere in texto)
    for proibido in ("nota", "ranking", "posição", "mensageria", "comunicacao", "c1"):
        assert proibido not in texto.lower()


def test_aprovado_e_reprovado_recebem_mensagens_diferentes():
    assert mensagem_pos_entrevista(_vaga(), _resultado(aprovado=True)) != (
        mensagem_pos_entrevista(_vaga(), _resultado(aprovado=False))
    )


def test_mensagem_nao_promete_contratacao():
    texto = mensagem_pos_entrevista(_vaga(), _resultado(aprovado=True)).lower()

    assert "contratad" not in texto
    assert "aprovad" not in texto


def test_resultado_simulado_traz_aviso_e_real_nao():
    assert AVISO_SIMULACAO in mensagem_pos_entrevista(_vaga(), _resultado(simulado=True))
    assert AVISO_SIMULACAO not in mensagem_pos_entrevista(_vaga(), _resultado(simulado=False))


def test_mensagem_e_deterministica():
    assert mensagem_pos_entrevista(_vaga(), _resultado()) == (
        mensagem_pos_entrevista(_vaga(), _resultado())
    )


@pytest.mark.parametrize(
    "extra", [{"empresa_id": "empresa-b"}, {"vaga_id": "v2"}], ids=["empresa", "vaga"]
)
def test_resultado_de_outra_vaga_ou_empresa_e_recusado(extra):
    with pytest.raises(ValueError):
        mensagem_pos_entrevista(_vaga(), _resultado(**extra))
