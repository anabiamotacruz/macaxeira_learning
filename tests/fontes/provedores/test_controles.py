import pytest

from backend.fontes.provedores.controles import (
    CacheConsultas,
    MetricasProvedores,
    OrcamentoProvedores,
)
from backend.fontes.provedores.erros import MotivoTroca
from backend.fontes.provedores.modelos import ResultadoCadeia, SituacaoConsulta

RESULTADO = ResultadoCadeia(situacao=SituacaoConsulta.NAO_ENCONTRADO)


def test_orcamento_reserva_ate_o_limite_da_execucao():
    orcamento = OrcamentoProvedores(limite_empresa_usd=10, limite_execucao_usd=1)
    assert orcamento.reservar("e1", "x1", 0.6) is not None
    assert orcamento.reservar("e1", "x1", 0.6) is None
    assert orcamento.reservar("e1", "x2", 0.6) is not None


def test_orcamento_reserva_ate_o_limite_da_empresa_entre_execucoes():
    orcamento = OrcamentoProvedores(limite_empresa_usd=1, limite_execucao_usd=1)
    assert orcamento.reservar("e1", "x1", 0.6) is not None
    assert orcamento.reservar("e1", "x2", 0.6) is None
    assert orcamento.reservar("e2", "x3", 0.6) is not None


def test_mesma_execucao_em_empresas_diferentes_nao_divide_orcamento():
    orcamento = OrcamentoProvedores(limite_empresa_usd=1, limite_execucao_usd=1)
    assert orcamento.reservar("e1", "x", 1) is not None
    assert orcamento.reservar("e2", "x", 1) is not None


def test_liquidar_troca_a_reserva_pelo_custo_real():
    orcamento = OrcamentoProvedores(limite_empresa_usd=1, limite_execucao_usd=1)
    reserva = orcamento.reservar("e1", "x1", 0.9)
    orcamento.liquidar(reserva, 0.1)
    assert orcamento.gasto_empresa("e1") == pytest.approx(0.1)
    assert orcamento.gasto_execucao("e1", "x1") == pytest.approx(0.1)
    assert orcamento.reservar("e1", "x1", 0.9) is not None


def test_liquidar_sem_cobranca_devolve_tudo():
    orcamento = OrcamentoProvedores(limite_empresa_usd=1, limite_execucao_usd=1)
    orcamento.liquidar(orcamento.reservar("e1", "x1", 1), 0)
    assert orcamento.gasto_empresa("e1") == 0
    assert orcamento.reservar("e1", "x1", 1) is not None


@pytest.mark.parametrize("limite", [-1, float("nan"), float("inf")])
def test_limite_invalido_e_recusado(limite):
    with pytest.raises(ValueError):
        OrcamentoProvedores(limite_empresa_usd=limite, limite_execucao_usd=1)
    with pytest.raises(ValueError):
        OrcamentoProvedores(limite_empresa_usd=1, limite_execucao_usd=limite)


def test_limite_zero_nao_deixa_gastar_nada():
    orcamento = OrcamentoProvedores(limite_empresa_usd=0, limite_execucao_usd=0)
    assert orcamento.reservar("e1", "x1", 0.001) is None


def test_cache_isola_empresas_e_expira():
    momento = [0.0]
    cache = CacheConsultas(ttl_s=10, relogio=lambda: momento[0])
    cache.guardar("e1", "k", RESULTADO)
    assert cache.obter("e1", "k") == RESULTADO
    assert cache.obter("e2", "k") is None
    momento[0] = 11.0
    assert cache.obter("e1", "k") is None


def test_cache_respeita_o_tamanho_maximo():
    cache = CacheConsultas(ttl_s=10, maximo=2, relogio=lambda: 0.0)
    for chave in "abc":
        cache.guardar("e1", chave, RESULTADO)
    assert cache.obter("e1", "a") is None
    assert cache.obter("e1", "c") == RESULTADO


def test_cache_esquece_uma_entrada():
    cache = CacheConsultas(ttl_s=10, relogio=lambda: 0.0)
    cache.guardar("e1", "k", RESULTADO)
    cache.esquecer("e1", "k")
    assert cache.obter("e1", "k") is None


def test_metricas_somam_por_provedor():
    metricas = MetricasProvedores()
    metricas.registrar_acerto("p1", 0.5)
    metricas.registrar_nao_encontrado("p1", 0.25)
    metricas.registrar_falha("p2", 0.0)
    metricas.registrar_troca("p1", MotivoTroca.NAO_ENCONTRADO)
    metricas.registrar_troca("p1", MotivoTroca.NAO_ENCONTRADO)
    metricas.registrar_acerto_de_cache()

    foto = metricas.fotografia()
    assert foto["cache_acertos"] == 1
    assert foto["provedores"]["p1"] == {
        "acertos": 1,
        "nao_encontrados": 1,
        "falhas": 0,
        "trocas": {"nao_encontrado": 2},
        "custo_usd": pytest.approx(0.75),
    }
    assert foto["provedores"]["p2"]["falhas"] == 1
