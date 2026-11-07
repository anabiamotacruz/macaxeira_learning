"""Contrato do conjunto sintético, sem chamadas de rede ou modelo."""

import importlib
import json
import random
from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest

from backend.contratos.modelos import Candidato, EstadoBanco, Vaga

PASTA = Path(__file__).resolve().parents[2] / "dados" / "sinteticos"
HOJE = date(2026, 11, 7)


def gerar(semente=42, quantidade=200):
    # Importação tardia permite observar as falhas de cada teste antes do módulo existir.
    return importlib.import_module("dados.gerador").gerar(semente, quantidade)


def ler(nome):
    return json.loads((PASTA / nome).read_text(encoding="utf-8"))


def test_geracao_reproduzivel_com_mesma_semente():
    assert gerar() == gerar()
    assert gerar(43) != gerar(42)


def test_nao_altera_rng_global_nem_compartilha_objetos():
    estado = random.getstate()
    primeira = gerar()
    assert random.getstate() == estado
    primeira[0].atributos["extra"] = "alterado"
    primeira[0].historico.clear()
    assert "extra" not in gerar()[0].atributos
    assert gerar()[0].historico


@pytest.mark.parametrize("quantidade", [0, 1, 2, 11, 72, 200, 201])
def test_quantidade_exata(quantidade):
    assert len(gerar(42, quantidade)) == quantidade


@pytest.mark.parametrize("semente", [True, 1.5, "42", None])
def test_rejeita_semente_invalida(semente):
    with pytest.raises(TypeError, match="semente"):
        gerar(semente, 10)


@pytest.mark.parametrize("quantidade", [True, 1.5, "10", None])
def test_rejeita_quantidade_invalida(quantidade):
    with pytest.raises(TypeError, match="quantidade"):
        gerar(42, quantidade)


def test_rejeita_quantidade_negativa():
    with pytest.raises(ValueError, match="quantidade"):
        gerar(42, -1)


def test_todos_os_perfis_sao_simulados():
    for perfil in gerar():
        assert perfil.simulado is True
        assert "Fictícia" in perfil.nome
        assert perfil.atributos["email"].endswith("@example.invalid")
        assert Candidato.model_validate_json(perfil.model_dump_json()) == perfil
        assert perfil.atualizado_em <= HOJE
        for experiencia in perfil.historico:
            assert experiencia.inicio <= (experiencia.fim or HOJE)


def test_contem_armadilhas():
    perfis = gerar()
    assert any("Artífice" in p.perfil_texto for p in perfis)
    assert any("Nunca trabalhei" in p.perfil_texto for p in perfis)
    assert any("sem exemplos verificáveis" in p.perfil_texto for p in perfis)
    assert any("Ignore as regras" in p.perfil_texto for p in perfis)
    assert any(p.opt_out for p in perfis)
    # A instrução maliciosa não altera os fatos estruturados do perfil equivalente.
    assert perfis[3].atributos["cloud"] == perfis[0].atributos["cloud"]


def test_curriculo_forte_mantem_falta_explicita_do_requisito():
    perfis = gerar()
    for caso in ler("respostas_certas.json")["casos"]:
        if caso["cenario"] != "sem_requisito":
            continue
        perfil = perfis[caso["indice"]]
        assert "Nunca trabalhei" in perfil.perfil_texto
        assert "testes automatizados e documentação técnica" in perfil.perfil_texto
        assert "certificações avançadas de cloud" in perfil.perfil_texto
        assert "nao" in perfil.atributos.values()
        assert any(r["estado"] == "nao_atende" for r in caso["requisitos"].values())


def test_contem_sujeira():
    perfis = gerar()
    assert any("desenvolvmento" in p.perfil_texto for p in perfis)
    assert any("cloud" not in p.atributos for p in perfis)
    assert any(p.autorizacao_valida_ate and p.autorizacao_valida_ate < HOJE for p in perfis)
    assert any(p.estado == EstadoBanco.DESATUALIZADO for p in perfis)
    assert any(p.estado == EstadoBanco.PENDENTE and not p.autorizou_contato for p in perfis)
    pessoas = defaultdict(list)
    for perfil in perfis:
        pessoas[perfil.empresa_id, perfil.id].append(perfil)
    duplicatas = [grupo for grupo in pessoas.values() if len(grupo) > 1]
    assert duplicatas
    for grupo in duplicatas:
        assert len({p.fonte for p in grupo}) > 1
        assert len({p.nome for p in grupo}) == 1
        assert len({p.atributos["email"] for p in grupo}) == 1


def test_gera_duas_empresas_separadas():
    perfis = gerar(42, 72)
    empresas = {p.empresa_id for p in perfis}
    assert len(empresas) == 2
    # Mesmo identificador local em empresas diferentes força consumidores a usar empresa_id.
    ids = [{p.id for p in perfis if p.empresa_id == e} for e in sorted(empresas)]
    assert ids[0] & ids[1]
    for identificador in ids[0] & ids[1]:
        contatos = {p.atributos["email"] for p in perfis if p.id == identificador}
        assert len(contatos) == 2


def test_fixture_corresponde_ao_gerador_e_vagas_validam():
    assert ler("candidatos.json") == [p.model_dump(mode="json") for p in gerar()]
    vagas = [Vaga.model_validate(v) for v in ler("vagas.json")]
    assert len({v.titulo for v in vagas}) >= 3
    assert {v.empresa_id for v in vagas} == {p.empresa_id for p in gerar()}
    assert all(not v.aprovada for v in vagas)
    assert all("sintétic" in v.descricao.lower() for v in vagas)
    for vaga in vagas:
        assert not {r.campo for r in vaga.requisitos} & {"genero", "raca", "deficiencia"}


def test_gabarito_tem_referencias_e_evidencias_validas():
    gabarito = ler("respostas_certas.json")
    assert gabarito["semente"] == 42
    assert gabarito["quantidade"] == 200
    assert gabarito["data_referencia"] == HOJE.isoformat()
    perfis = gerar()
    vagas = {v["id"]: v for v in ler("vagas.json")}
    assert len(gabarito["casos"]) == len(perfis)
    for caso, perfil in zip(gabarito["casos"], perfis, strict=True):
        assert (caso["empresa_id"], caso["candidato_id"], caso["fonte"]) == (
            perfil.empresa_id,
            perfil.id,
            perfil.fonte,
        )
        vaga = vagas[caso["vaga_id"]]
        assert vaga["empresa_id"] == perfil.empresa_id
        assert set(caso["requisitos"]) == {r["id"] for r in vaga["requisitos"]}
        for resultado in caso["requisitos"].values():
            assert resultado["estado"] in {"atende", "nao_atende", "desconhecido"}
            if resultado["estado"] != "desconhecido":
                assert resultado["trecho"]
                assert resultado["trecho"] in perfil.perfil_texto
        assert not {"caso", "resultado_esperado", "nota", "gabarito"} & perfil.atributos.keys()


def test_gerador_nao_depende_do_gabarito(monkeypatch):
    modulo = importlib.import_module("dados.gerador")

    def impedir_leitura(*args, **kwargs):
        pytest.fail("O gerador não deve ler os arquivos de avaliação")

    monkeypatch.setattr(Path, "read_text", impedir_leitura)
    assert len(modulo.gerar(42, 200)) == 200


def test_experiencia_de_quatro_anos_existe_na_data_da_atualizacao():
    for perfil in gerar():
        if "quatro anos" in perfil.perfil_texto:
            inicio = min(e.inicio for e in perfil.historico)
            assert (perfil.atualizado_em - inicio).days >= 4 * 365


def test_gabarito_separa_autorizacao_de_aderencia():
    casos = ler("respostas_certas.json")["casos"]
    for caso in casos:
        if caso["cenario"] in {"opt_out", "autorizacao_vencida", "sem_autorizacao"}:
            assert caso["autorizacao_para_vaga"] == "bloqueada"
            assert all(r["estado"] == "atende" for r in caso["requisitos"].values())
        if caso["cenario"] == "informacao_ausente":
            assert all(r["estado"] == "desconhecido" for r in caso["requisitos"].values())
        if caso["cenario"] == "sem_requisito":
            assert any(r["estado"] == "nao_atende" for r in caso["requisitos"].values())


def test_cobertura_completa_por_empresa_com_72_registros():
    casos = ler("respostas_certas.json")["casos"][:72]
    for empresa in {c["empresa_id"] for c in casos}:
        grupo = [c for c in casos if c["empresa_id"] == empresa]
        assert len({c["cenario"] for c in grupo}) == 12
        assert len({c["vaga_id"] for c in grupo}) == 3


def test_semente_negativa_e_reproduzivel():
    assert gerar(-42, 72) == gerar(-42, 72)
