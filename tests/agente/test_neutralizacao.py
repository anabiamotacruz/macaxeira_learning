"""Regras puras: flexão de gênero e conferência de trecho com marcadores."""

import pytest

from backend.agente.neutralizacao import corresponde_ao_original, neutralizar_genero


@pytest.mark.parametrize(
    ("feminino", "masculino"),
    [
        ("A desenvolvedora liderou", "O desenvolvedor liderou"),
        ("Sou uma engenheira formada", "Sou um engenheiro formado"),
        ("Ela atuou como arquiteta", "Ele atuou como arquiteto"),
        ("Estagiária na área", "Estagiário na área"),
        ("advogada e médica", "advogado e médico"),
    ],
)
def test_feminino_e_masculino_ficam_iguais(feminino, masculino):
    assert neutralizar_genero(feminino) == neutralizar_genero(masculino)


def test_marcador_de_genero_entre_parenteses_sai():
    assert neutralizar_genero("Engenheiro(a) de dados") == "Engenheiro de dados"


@pytest.mark.parametrize(
    "frase",
    [
        "Primeira carreira na área financeira",
        "Formação em Física e Matemática",
        "A transportadora e a seguradora",
        "Atuando na liderança",
    ],
)
def test_palavra_que_nao_e_sobre_a_pessoa_nao_muda(frase):
    assert neutralizar_genero(frase) == frase


def test_trecho_literal_confere():
    assert corresponde_ao_original("Serviços Python", "Fiz serviços python em produção.")


def test_palavra_parcial_nao_confere():
    assert not corresponde_ao_original("Java", "Usei JavaScript.")


def test_marcador_vale_por_texto_retirado():
    original = "Trabalhei na Acme Ltda com Python em 12/03/2019."
    trecho = "Trabalhei na [EMPREGADOR_1] com Python em [ANO_2019]."
    assert corresponde_ao_original(trecho, original)


def test_marcador_nao_faz_trecho_inventado_conferir():
    assert not corresponde_ao_original(
        "Trabalhei na [EMPREGADOR_1] com Rust", "Trabalhei na Acme com Python."
    )


def test_trecho_so_com_marcadores_nao_confere():
    assert not corresponde_ao_original("[PESSOA] [EMAIL_1]", "Maria maria@example.invalid")


def test_trecho_neutro_confere_com_original_flexionado():
    assert corresponde_ao_original("Formado em [INSTITUICAO_1]", "Formada em Unifoo.")


def test_excesso_de_marcadores_nao_confere():
    trecho = " ".join(["[LINK_1] a"] * 40)
    assert not corresponde_ao_original(trecho, "a " * 100)
