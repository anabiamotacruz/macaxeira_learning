"""Regras puras: flexão de gênero e conferência de trecho com marcadores."""

import random
import re
import time

import pytest

from backend.agente.neutralizacao import (
    _PALAVRA,
    MARCADOR,
    MAXIMO_DE_CARACTERES_NO_TRECHO,
    MAXIMO_DE_CARACTERES_POR_MARCADOR,
    MAXIMO_DE_MARCADORES_NO_TRECHO,
    _comparavel,
    corresponde_ao_original,
    neutralizar_genero,
)


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


def _conferencia_por_regex(trecho: str, original: str) -> bool:
    """A regra escrita como regex com curinga: lenta, mas clara. Serve de referência ao teste."""
    partes = [_comparavel(parte) for parte in MARCADOR.split(trecho)]
    if not any(_PALAVRA.search(parte) or any(c.isdigit() for c in parte) for parte in partes):
        return False
    coringa = f".{{1,{MAXIMO_DE_CARACTERES_POR_MARCADOR}}}?"
    padrao = rf"\s?{coringa}\s?".join(re.escape(parte) for parte in partes)
    return re.search(rf"(?<!\w){padrao}(?!\w)", _comparavel(original)) is not None


@pytest.mark.parametrize("semente", range(5))
def test_conferencia_por_posicoes_da_o_mesmo_resultado_da_regex(semente):
    sorteio = random.Random(semente)
    palavras = ["Ana", "usou", "Python", "em", "x", "[PESSOA]", "[EMAIL_1]", "1", ".", "Formada"]
    for _ in range(400):
        trecho = " ".join(sorteio.choices(palavras, k=sorteio.randint(1, 5)))
        original = " ".join(
            sorteio.choice(["Ana", "usou", "Python", "em", "x", "1", ".", "Formada", "ana@b.c"])
            for _ in range(sorteio.randint(1, 12))
        )
        assert corresponde_ao_original(trecho, original) == _conferencia_por_regex(
            trecho, original
        ), (trecho, original)


def test_marcador_cobre_no_maximo_um_pedaco_curto_do_original():
    longe = "a" * (MAXIMO_DE_CARACTERES_POR_MARCADOR + 10)
    assert corresponde_ao_original("Fiz [PESSOA] fim", f"Fiz {'a' * 100} fim")
    assert not corresponde_ao_original("Fiz [PESSOA] fim", f"Fiz {longe} fim")


def test_trecho_maior_que_uma_citacao_nao_confere():
    trecho = "a " * MAXIMO_DE_CARACTERES_NO_TRECHO
    assert not corresponde_ao_original(trecho, trecho)


def test_conferencia_nao_explode_em_texto_comum_com_marcadores():
    trecho = " e ".join(["[PESSOA]"] * MAXIMO_DE_MARCADORES_NO_TRECHO) + " fim"
    original = "Maria e " * 300 + "Maria FIM_NAO"
    inicio = time.monotonic()
    assert not corresponde_ao_original(trecho, original)
    assert time.monotonic() - inicio < 2
