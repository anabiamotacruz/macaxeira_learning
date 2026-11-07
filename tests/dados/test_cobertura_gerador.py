"""Casos rotulados e invariantes do conjunto da T2.1, sem usar o agente."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from backend.contratos.modelos import Candidato, EstadoBanco, Vaga
from backend.fontes.banco_talentos import BancoTalentos
from dados.gerador import gerar

PASTA = Path(__file__).resolve().parents[2] / "dados/sinteticos"
HOJE = date(2026, 11, 7)


@pytest.fixture(scope="module")
def conjunto():
    def ler(nome):
        return json.loads((PASTA / nome).read_text())

    return (
        [Candidato.model_validate(p) for p in ler("candidatos.json")],
        {v["id"]: Vaga.model_validate(v) for v in ler("vagas.json")},
        ler("respostas_certas.json"),
    )


def test_conjunto_tem_250_casos_rotulados(conjunto):
    perfis, _, gabarito = conjunto
    assert len(perfis) == len(gabarito["casos"]) == gabarito["quantidade"] == 250
    assert len({(p.empresa_id, p.id) for p in perfis}) >= 150


@pytest.mark.parametrize("indice", range(250), ids=lambda i: f"caso-{i + 1:03}")
def test_rotulo_corresponde_aos_fatos_e_a_empresa(conjunto, indice):
    perfis, vagas, gabarito = conjunto
    perfil = perfis[indice]
    caso = gabarito["casos"][indice]
    vaga = vagas[caso["vaga_id"]]
    assert caso["indice"] == indice
    assert caso["empresa_id"] == perfil.empresa_id == vaga.empresa_id
    assert caso["candidato_id"] == perfil.id
    assert caso["fonte"] == perfil.fonte
    assert perfil.simulado
    for requisito in vaga.requisitos:
        esperado = caso["requisitos"][requisito.id]
        valor = perfil.atributos.get(requisito.campo)
        if esperado["estado"] == "desconhecido":
            assert valor is None
        elif esperado["estado"] == "atende":
            assert valor == requisito.valor_esperado
            assert esperado["trecho"] in perfil.perfil_texto
        else:
            assert esperado["estado"] == "nao_atende"
            assert valor is not None and valor != requisito.valor_esperado
            assert esperado["trecho"] in perfil.perfil_texto
    bloqueado = (perfil.opt_out or not perfil.autorizou_contato
                 or perfil.autorizacao_valida_ate is None
                 or perfil.autorizacao_valida_ate < HOJE)
    assert (caso["autorizacao_para_vaga"] == "bloqueada") == bloqueado


def test_cada_vaga_tem_todos_os_cenarios_e_duplicatas_nao_vazam_rotulos(conjunto):
    perfis, vagas, gabarito = conjunto
    cenarios = {c["cenario"] for c in gabarito["casos"]}
    assert len(cenarios) == 12
    for vaga_id in vagas:
        assert {c["cenario"] for c in gabarito["casos"] if c["vaga_id"] == vaga_id} == cenarios
    proibidos = {"cenario", "nota", "gabarito", "resultado_esperado", "requisitos_ok"}
    assert all(not proibidos.intersection(p.atributos) for p in perfis)


@pytest.mark.parametrize("semente", [-999, -1, 0, 1, 42, 2026, 2**63])
def test_multiplas_sementes_preservam_cobertura_e_independencia(semente):
    perfis = gerar(semente, 250)
    assert perfis == gerar(semente, 250)
    assert len(perfis) == 250
    assert len({p.empresa_id for p in perfis}) == 2
    assert all(p.simulado for p in perfis)
    assert sum(p.opt_out for p in perfis) > 0
    assert any(not p.historico for p in perfis)
    assert any(not p.autorizou_contato for p in perfis)
    duplicata = next(p for p in perfis if p.fonte == "rede_simulada")
    original = next(p for p in perfis
                    if p.id == duplicata.id and p.empresa_id == duplicata.empresa_id
                    and p.fonte != duplicata.fonte)
    duplicata.atributos.clear()
    duplicata.historico.clear()
    assert original.atributos and original.historico


@pytest.mark.parametrize("quantidade", [7, 8, 12, 35, 36, 37, 71, 72, 73, 249, 250, 251, 1000])
def test_prefixos_e_identidades_nos_limites_dos_blocos(quantidade):
    perfis = gerar(42, quantidade)
    assert len(perfis) == quantidade
    assert perfis == gerar(42, quantidade + 1)[:quantidade]
    grupos = Counter((p.empresa_id, p.id) for p in perfis)
    assert all(contagem in {1, 2} for contagem in grupos.values())


@pytest.mark.parametrize("dias", [-1, 0, 1])
@pytest.mark.parametrize("opt_out", [False, True])
@pytest.mark.parametrize("autorizou", [False, True])
def test_limite_de_autorizacao_com_perfil_gerado(dias, opt_out, autorizou):
    from datetime import timedelta

    perfil = gerar(42, 1)[0]
    perfil.autorizacao_valida_ate = HOJE + timedelta(days=dias)
    perfil.opt_out = opt_out
    perfil.autorizou_contato = autorizou
    banco = BancoTalentos(hoje=HOJE, confiar_autorizacao_sintetica=True)
    try:
        banco.importar(perfil.empresa_id, [perfil.model_dump(mode="json")])
        assert bool(banco.buscar(perfil.empresa_id, "")) == (
            dias >= 0 and autorizou and not opt_out
        )
    finally:
        banco.fechar()


def test_base_completa_importada_respeita_empresa_autorizacao_e_paginacao(conjunto):
    perfis, _, _ = conjunto
    banco = BancoTalentos(hoje=HOJE, confiar_autorizacao_sintetica=True)
    try:
        for empresa in sorted({p.empresa_id for p in perfis}):
            registros = [p for p in perfis if p.empresa_id == empresa]
            banco.importar(empresa, [p.model_dump(mode="json") for p in registros])
            encontrados = []
            for pagina in range(1, len(registros) + 1):
                lote = banco.buscar(empresa, "", pagina=pagina)
                if not lote:
                    break
                assert len(lote) <= 20
                encontrados.extend(lote)
            esperados = {
                p.id for p in registros
                if p.autorizou_contato and not p.opt_out
                and p.autorizacao_valida_ate is not None
                and p.autorizacao_valida_ate >= HOJE
                and p.estado in {EstadoBanco.ATIVO, EstadoBanco.DESATUALIZADO}
            }
            assert {p.id for p in encontrados} == esperados
            assert len(encontrados) == len(esperados)
            assert all(p.empresa_id == empresa for p in encontrados)
    finally:
        banco.fechar()
