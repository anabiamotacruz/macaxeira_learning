import re

from backend.contato.conversa import mensagem_duvida_encaminhada
from backend.contato.prompts import MARCADOR_NOME, PALAVRA_SAIDA
from backend.contratos.modelos import Competencia, Requisito, Vaga

AVISO_SIMULACAO = "Mensagem simulada, enviada em ambiente de demonstração."


def _vaga() -> Vaga:
    return Vaga(
        id="v1",
        empresa_id="empresa-a",
        titulo="Backend Python",
        descricao="Time de pagamentos. Trabalho remoto, com encontros mensais em Recife.",
        requisitos=[
            Requisito(id="r1", descricao="Python", campo="linguagem", valor_esperado="python")
        ],
        competencias=[Competencia(nome="mensageria", peso=1.0)],
        meta_candidatos=5,
        prazo_dias=7,
        max_tentativas_contato=2,
    )


def test_mensagem_cita_o_titulo_da_vaga():
    assert _vaga().titulo in mensagem_duvida_encaminhada(_vaga())


def test_mensagem_usa_marcador_de_nome_e_palavra_de_saida():
    texto = mensagem_duvida_encaminhada(_vaga())

    assert MARCADOR_NOME in texto
    assert PALAVRA_SAIDA in texto
    assert "Ana" not in texto


def test_mensagem_e_deterministica():
    vaga = _vaga()

    assert mensagem_duvida_encaminhada(vaga) == mensagem_duvida_encaminhada(vaga)


def test_mensagem_nao_tem_digitos_nem_url():
    texto = mensagem_duvida_encaminhada(_vaga())

    assert re.search(r"\d", texto) is None
    assert "http" not in texto.lower()
    assert "www." not in texto.lower()


def test_mensagem_nao_promete_entrevista_aprovacao_nem_contratacao():
    texto = mensagem_duvida_encaminhada(_vaga()).lower()

    for palavra in ("entrevista", "aprovação", "aprovacao", "contratação", "contratacao"):
        assert palavra not in texto


def test_aviso_de_simulacao_e_a_ultima_frase():
    texto = mensagem_duvida_encaminhada(_vaga()).strip()

    assert texto.endswith(AVISO_SIMULACAO)
    assert texto.count(AVISO_SIMULACAO) == 1
