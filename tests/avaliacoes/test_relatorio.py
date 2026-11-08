"""Testes do relatório da avaliação."""

import json

import pytest

from avaliacoes.canal import SituacaoCanal, medir_cobertura
from avaliacoes.casos import carregar_casos, hash_do_conjunto, pares_de_vies
from avaliacoes.execucao import rodar
from avaliacoes.metricas import TipoAchado
from avaliacoes.relatorio import LIMITES, escrever_relatorio, gerar_relatorio


@pytest.fixture(scope="module")
def casos():
    return carregar_casos()


@pytest.fixture(scope="module")
def relatorio(casos):
    rodadas = [rodar(casos, "honesto", pares=pares_de_vies(casos)), rodar(casos, "indisponivel")]
    return gerar_relatorio(casos, rodadas)


def test_hash_do_conjunto_nao_depende_da_ordem(casos):
    assert hash_do_conjunto(casos) == hash_do_conjunto(list(reversed(casos)))
    assert hash_do_conjunto(casos) != hash_do_conjunto(casos[:-1])


def test_relatorio_identifica_dados_sinteticos(relatorio):
    assert relatorio["simulado"] is True
    assert relatorio["conjunto"]["origem"] == "dados.gerador"


def test_relatorio_descreve_o_conjunto(relatorio, casos):
    conjunto = relatorio["conjunto"]
    assert conjunto["total_de_casos"] == len(casos)
    assert conjunto["elegiveis"] == sum(caso.elegivel_esperado for caso in casos)
    assert sum(conjunto["por_cenario"].values()) == len(casos)
    assert sum(conjunto["por_particao"].values()) == len(casos)
    assert conjunto["hash"] == hash_do_conjunto(casos)


def test_relatorio_traz_a_cobertura_de_canal(relatorio, casos):
    cobertura = relatorio["conjunto"]["cobertura_de_canal"]
    assert cobertura == medir_cobertura(casos).model_dump(mode="json")
    assert set(cobertura["por_situacao"]) == {s.value for s in SituacaoCanal}
    assert sum(cobertura["por_situacao"].values()) == cobertura["total"]


def test_cobertura_no_relatorio_nunca_traz_taxa_sem_denominador(relatorio):
    taxa = relatorio["conjunto"]["cobertura_de_canal"]["taxa_de_canal_publicado"]
    assert taxa["casos"] == relatorio["conjunto"]["cobertura_de_canal"]["considerados"]
    assert (taxa["valor"] is None) == (taxa["casos"] == 0)


def test_limites_avisam_que_a_cobertura_sintetica_nao_estima_a_real():
    assert any("cobertura de canal" in limite.lower() for limite in LIMITES)


def test_relatorio_tem_uma_entrada_por_rodada(relatorio):
    assert [modelo["modelo"] for modelo in relatorio["modelos"]] == ["honesto", "indisponivel"]


def test_relatorio_traz_achados_por_tipo_e_consumo(relatorio):
    honesto = relatorio["modelos"][0]
    assert honesto["aprovado"] is True
    assert set(honesto["achados_por_tipo"]) == {tipo.value for tipo in TipoAchado}
    assert honesto["chamadas"] > 0
    assert honesto["tokens_entrada_estimados"] > 0
    assert honesto["custo_usd"] == 0.0
    assert honesto["pares_medidos"] > 0


def test_relatorio_separa_proposto_de_aceito(relatorio):
    honesto = relatorio["modelos"][0]
    assert honesto["evidencias_propostas"] >= honesto["evidencias_aceitas"]
    assert honesto["notas_propostas"] >= honesto["notas_aceitas"]


def test_relatorio_declara_os_limites_da_medicao(relatorio):
    assert relatorio["limites"] == list(LIMITES)
    assert LIMITES


def test_relatorio_e_json_puro(relatorio):
    assert json.loads(json.dumps(relatorio, ensure_ascii=False)) == relatorio


def test_relatorio_nao_contem_nome_nem_contato_de_pessoa(relatorio, casos):
    despejo = json.dumps(relatorio, ensure_ascii=False)
    for caso in casos:
        assert caso.candidato.nome not in despejo
        assert caso.candidato.atributos.get("email", "sem-email") not in despejo


def test_escrever_relatorio_cria_o_arquivo(tmp_path, relatorio):
    caminho = tmp_path / "saida" / "relatorio.json"
    escrever_relatorio(caminho, relatorio)
    assert json.loads(caminho.read_text(encoding="utf-8")) == relatorio
