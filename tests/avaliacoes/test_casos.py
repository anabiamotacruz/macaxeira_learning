"""Testes do conjunto de casos de avaliação."""

import pytest

from avaliacoes.casos import (
    CENARIOS,
    CENARIOS_INELEGIVEIS,
    Particao,
    carregar_casos,
    pares_de_vies,
)
from backend.fontes.analisador import _perfil_seguro


@pytest.fixture(scope="module")
def casos():
    return carregar_casos()


def test_cobre_os_doze_cenarios(casos):
    assert {caso.cenario for caso in casos} == set(CENARIOS)


def test_cada_caso_tem_vaga_da_mesma_empresa(casos):
    assert all(caso.vaga.empresa_id == caso.candidato.empresa_id for caso in casos)


def test_requisito_da_vaga_corresponde_a_profissao_do_perfil(casos):
    for caso in casos:
        campos = {requisito.campo for requisito in caso.vaga.requisitos}
        assert "presencial_sp" in campos
        assert len(campos) == 2, caso.id_caso


def test_carregamento_e_reproduzivel():
    primeiro = carregar_casos()
    segundo = carregar_casos()
    assert [caso.id_caso for caso in primeiro] == [caso.id_caso for caso in segundo]
    assert [caso.particao for caso in primeiro] == [caso.particao for caso in segundo]


def test_ids_de_caso_sao_unicos(casos):
    assert len({caso.id_caso for caso in casos}) == len(casos)


def test_duas_empresas_e_as_duas_particoes(casos):
    assert len({caso.candidato.empresa_id for caso in casos}) == 2
    assert {caso.particao for caso in casos} == set(Particao)


def test_particao_nao_separa_a_mesma_pessoa(casos):
    particoes_por_grupo = {}
    for caso in casos:
        particoes_por_grupo.setdefault(caso.grupo, set()).add(caso.particao)
    assert all(len(particoes) == 1 for particoes in particoes_por_grupo.values())


def test_elegibilidade_esperada_segue_o_cenario(casos):
    for caso in casos:
        esperado = caso.cenario not in CENARIOS_INELEGIVEIS
        assert caso.elegivel_esperado is esperado, caso.id_caso


def test_elegibilidade_esperada_bate_com_o_funil(casos):
    """O gabarito do conjunto não pode discordar da regra determinística."""
    from backend.fontes.funil import priorizar

    for caso in casos:
        no_funil = bool(
            priorizar(caso.vaga, [caso.candidato], limite=1, hoje=caso.hoje)
        )
        assert no_funil is caso.elegivel_esperado, caso.id_caso


def test_todos_os_perfis_sao_simulados(casos):
    assert all(caso.candidato.simulado for caso in casos)


def test_pares_de_vies_mudam_so_nome_e_genero(casos):
    pares = pares_de_vies(casos)
    assert pares
    for um, outro in pares:
        assert um.par_vies == outro.par_vies
        assert um.variacao_vies != outro.variacao_vies
        assert um.candidato.nome != outro.candidato.nome
        assert um.candidato.perfil_texto != outro.candidato.perfil_texto
        assert um.candidato.atributos == outro.candidato.atributos
        assert um.candidato.historico == outro.candidato.historico
        assert um.vaga == outro.vaga


def test_par_de_vies_chega_identico_ao_modelo(casos):
    """A pseudonimização precisa apagar a diferença antes da chamada do modelo."""
    for um, outro in pares_de_vies(casos):
        assert _perfil_seguro(um.candidato)[0] == _perfil_seguro(outro.candidato)[0]


def test_pares_de_vies_so_usam_casos_elegiveis(casos):
    assert all(caso.elegivel_esperado for par in pares_de_vies(casos) for caso in par)


def test_nome_da_pessoa_aparece_no_texto_do_par(casos):
    """Sem o nome no texto, o par não exerce o caminho que o apaga."""
    for um, outro in pares_de_vies(casos):
        assert um.candidato.nome in um.candidato.perfil_texto
        assert outro.candidato.nome in outro.candidato.perfil_texto
