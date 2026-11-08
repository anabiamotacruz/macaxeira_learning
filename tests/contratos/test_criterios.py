import pytest

from backend.contratos.criterios import (
    campo_sensivel,
    e_aviso_de_nao_discriminacao,
    frases_com_termo_sensivel,
    frases_restritivas,
    sem_genero,
    tem_termo_sensivel,
    termos_sensiveis,
)


@pytest.mark.parametrize(
    "texto",
    [
        "gender",
        "Gênero",
        "age",
        "sexualidade",
        "nacionalidade",
        "date of birth",
        "apenas homens",
        "Mulheres",
        "até 30 anos",
        "ate 45 anos",
        "abaixo de 35 anos",
        "PCD",
    ],
)
def test_reconhece_termo_sensivel(texto):
    assert tem_termo_sensivel(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "até 5 anos de experiência",
        "até 20 anos de mercado",
        "engenharia de identidade",
        "cor do tema",
        "race conditions",
        "testes de caixa branca",
        "agile",
        "nome da empresa",
    ],
)
def test_nao_confunde_com_termo_sensivel(texto):
    assert not tem_termo_sensivel(texto)


def test_termos_saem_em_ordem_estavel():
    assert termos_sensiveis("Gender e idade", "raça") == ["gender", "idade", "raca"]


@pytest.mark.parametrize(
    ("palavra", "esperado"),
    [
        ("desenvolvedora", "desenvolvedor"),
        ("desenvolvedoras", "desenvolvedores"),
        ("engenheira", "engenheiro"),
        ("gestora", "gestor"),
        ("tecnica", "tecnico"),
        ("banca", "banca"),
        ("fora", "fora"),
    ],
)
def test_sem_genero_usa_lista_fechada_e_sufixos(palavra, esperado):
    assert sem_genero(palavra) == esperado


@pytest.mark.parametrize("campo", ["nome", "Nome", "name", "nome_completo", "sobrenome", "foto"])
def test_campo_que_identifica_a_pessoa_e_sensivel(campo):
    assert campo_sensivel(campo)


@pytest.mark.parametrize("campo", ["python", "cnh", "linguagem", "renome"])
def test_campo_profissional_nao_e_sensivel(campo):
    assert not campo_sensivel(campo)


def test_aviso_nao_serve_de_escudo_para_restricao():
    assert e_aviso_de_nao_discriminacao("Não discriminamos por gênero ou idade")
    assert not e_aviso_de_nao_discriminacao("Sem distinção de gênero, apenas homens")


def test_frases_com_termo_ignoram_so_o_aviso():
    texto = "Não discriminamos por gênero. Buscamos pessoa solteira."

    assert [frase for frase, _ in frases_com_termo_sensivel(texto)] == ["Buscamos pessoa solteira"]


@pytest.mark.parametrize(
    ("texto", "restringe"),
    [
        ("Vaga apenas para homens.", True),
        ("Só mulheres.", True),
        ("Pessoas até 30 anos.", True),
        ("Only male candidates.", True),
        ("Auxílio-creche para filhos.", False),
        ("Licença maternidade estendida.", False),
        ("Não discriminamos por idade.", False),
        ("Até 5 anos de experiência.", False),
    ],
)
def test_frases_restritivas(texto, restringe):
    assert bool(frases_restritivas(texto)) is restringe
