"""Testes da rodada completa: análise, revisão, auditoria e métricas."""

import pytest

from avaliacoes.casos import carregar_casos, pares_de_vies
from avaliacoes.execucao import rodar
from avaliacoes.metricas import TIPOS_QUE_PRECISAM_SER_ZERO, TipoAchado
from avaliacoes.modelos_de_prova import MODELOS_DE_PROVA


@pytest.fixture(scope="module")
def casos():
    return carregar_casos()


@pytest.fixture(scope="module")
def rodada_honesta(casos):
    return rodar(casos, "honesto")


def test_roda_todos_os_casos(casos, rodada_honesta):
    assert len(rodada_honesta.resultados) == len(casos)
    assert rodada_honesta.nome_modelo == "honesto"


def test_modelo_honesto_nao_produz_nenhum_achado(rodada_honesta):
    assert rodada_honesta.achados == []
    assert rodada_honesta.resumo.aprovado is True


def test_so_analisa_quem_passa_no_funil(casos, rodada_honesta):
    for resultado in rodada_honesta.resultados:
        caso = next(c for c in casos if c.id_caso == resultado.id_caso)
        assert resultado.analisado is caso.elegivel_esperado, resultado.id_caso
    assert rodada_honesta.resumo.casos_analisados < rodada_honesta.resumo.total_de_casos


def test_quem_nao_passa_no_funil_tem_motivo_registrado(rodada_honesta):
    for resultado in rodada_honesta.resultados:
        if not resultado.analisado:
            assert resultado.motivo_nao_analisado
            assert resultado.analise is None


def test_cada_caso_analisado_tem_evidencia_literal(casos, rodada_honesta):
    for resultado in rodada_honesta.resultados:
        if resultado.analise is None:
            continue
        caso = next(c for c in casos if c.id_caso == resultado.id_caso)
        for evidencia in resultado.analise.evidencias:
            assert evidencia.trecho in caso.candidato.perfil_texto


def test_cada_caso_analisado_aparece_na_trilha(rodada_honesta):
    analisados = {r.id_caso for r in rodada_honesta.resultados if r.analisado}
    assert {registro.id_caso for registro in rodada_honesta.trilha} == analisados
    assert {registro.etapa for registro in rodada_honesta.trilha} == {
        "analisar_perfil",
        "revisar_perfil",
    }


def test_casos_nao_contaminam_uns_aos_outros(casos):
    """Cada caso roda com cache próprio; a ordem não pode mudar o resultado."""
    direta = rodar(casos, "honesto")
    inversa = rodar(list(reversed(casos)), "honesto")
    por_caso = {r.id_caso: r.analise for r in inversa.resultados}
    for resultado in direta.resultados:
        assert por_caso[resultado.id_caso] == resultado.analise


def test_modelo_que_inventa_nao_vaza_evidencia_mas_e_contabilizado(casos):
    rodada = rodar(casos, "inventa_evidencia")
    assert [a for a in rodada.achados if a.tipo == TipoAchado.EVIDENCIA_SEM_TRECHO] == []
    assert rodada.evidencias_propostas > 0
    assert rodada.evidencias_recusadas == rodada.evidencias_propostas


def test_modelo_com_nota_sem_evidencia_nao_vaza_nota(casos):
    rodada = rodar(casos, "nota_sem_evidencia")
    assert [a for a in rodada.achados if a.tipo == TipoAchado.NOTA_SEM_EVIDENCIA] == []
    assert rodada.notas_propostas > 0
    assert rodada.notas_recusadas == rodada.notas_propostas


def test_modelo_com_criterio_sensivel_nao_vaza_criterio(casos):
    rodada = rodar(casos, "criterio_sensivel")
    assert [a for a in rodada.achados if a.tipo == TipoAchado.CRITERIO_SENSIVEL] == []


def test_modelo_indisponivel_pede_humano_em_vez_de_indicar(casos):
    rodada = rodar(casos, "indisponivel")
    assert [a for a in rodada.achados if a.tipo == TipoAchado.FALHA_SEM_PEDIDO_DE_HUMANO] == []
    for resultado in rodada.resultados:
        if resultado.analise is None:
            continue
        assert resultado.analise.notas == {}
        assert resultado.analise.evidencias == []
        assert any("revisão humana" in alerta for alerta in resultado.analise.alertas)


def test_resposta_invalida_tambem_pede_humano(casos):
    rodada = rodar(casos, "resposta_invalida")
    assert rodada.resumo.aprovado is True
    assert rodada.chamadas_falhas == len(rodada.trilha)


def test_injecao_sempre_gera_alerta(casos, rodada_honesta):
    com_injecao = [
        r for r in rodada_honesta.resultados
        if next(c for c in casos if c.id_caso == r.id_caso).cenario == "instrucao_no_curriculo"
    ]
    assert com_injecao
    for resultado in com_injecao:
        assert any("instrução" in alerta for alerta in resultado.analise.alertas)


def test_nenhum_modelo_de_prova_viola_um_principio(casos):
    """Nenhuma falha conhecida do modelo pode atravessar o código determinístico."""
    for nome in MODELOS_DE_PROVA:
        rodada = rodar(casos, nome)
        violacoes = [a for a in rodada.achados if a.tipo in TIPOS_QUE_PRECISAM_SER_ZERO]
        assert violacoes == [], f"{nome}: {violacoes[:3]}"
        assert rodada.resumo.aprovado is True, nome


def test_pares_de_vies_dao_o_mesmo_resultado(casos):
    rodada = rodar(casos, "honesto", pares=pares_de_vies(casos))
    assert rodada.pares_medidos > 0
    assert [a for a in rodada.achados if a.tipo == TipoAchado.PAR_DE_VIES_DIVERGENTE] == []


def test_modelo_sensivel_ao_nome_nao_consegue_diferenciar_o_par(casos):
    rodada = rodar(casos, "sensivel_ao_nome", pares=pares_de_vies(casos))
    assert rodada.pares_medidos > 0
    assert [a for a in rodada.achados if a.tipo == TipoAchado.PAR_DE_VIES_DIVERGENTE] == []


def test_rodada_so_usa_a_particao_pedida(casos):
    rodada = rodar(casos, "honesto", particao="ajuste")
    assert rodada.resultados
    assert {r.particao for r in rodada.resultados} == {"ajuste"}
    assert len(rodada.resultados) < len(casos)


def test_consumo_e_custo_sao_registrados(rodada_honesta):
    assert rodada_honesta.tokens_entrada_estimados > 0
    assert rodada_honesta.tokens_saida_estimados > 0
    assert rodada_honesta.custo_usd == 0.0
    assert rodada_honesta.simulado is True
