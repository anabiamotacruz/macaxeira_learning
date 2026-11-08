"""Diversidade, separação e evidências do corpus editorial, sem classificador."""

import importlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from backend.contratos.modelos import Candidato, Vaga

PASTA = Path(__file__).resolve().parents[2] / "dados" / "avaliacao_v3"


def construir():
    return importlib.import_module("dados.avaliacao_v3").construir()


def test_prova_tem_120_narrativas_indicaveis_sem_contar_pares():
    dados = construir()
    prova = [c for c in dados["gabarito"]["casos"] if c["particao"] == "prova"
             and c["resultado_esperado"] == "indicar" and c["conta_independencia"]]
    assert len(prova) >= 120
    assert len({c["grupo_independencia"] for c in prova}) == len(prova)
    textos = [dados["candidatos"][c["indice"]]["perfil_texto"] for c in prova]
    assert len(set(textos)) == len(textos)
    assert min(len(t.split()) for t in textos) >= 35
    assert len({c["funcao"] for c in prova}) >= 12


def test_particoes_sao_disjuntas_por_familia_profissional():
    grupos = defaultdict(set)
    for caso in construir()["gabarito"]["casos"]:
        grupos[caso["grupo_independencia"]].add(caso["particao"])
    assert all(len(particoes) == 1 for particoes in grupos.values())


def test_pares_vies_so_trocam_nome_e_genero_e_nao_aumentam_amostra():
    dados = construir()
    pares = defaultdict(list)
    for caso in dados["gabarito"]["casos"]:
        if caso["par_vies"]:
            assert not caso["conta_independencia"]
            pares[caso["par_vies"]].append(caso)
    assert len(pares) >= 12
    for par in pares.values():
        assert len(par) == 2
        assert len({c["resultado_esperado"] for c in par}) == 1
        a, b = [json.loads(json.dumps(dados["candidatos"][c["indice"]])) for c in par]
        assert a.pop("nome") != b.pop("nome")
        assert a["atributos"].pop("genero") != b["atributos"].pop("genero")
        for perfil in (a, b):
            perfil["perfil_texto"] = perfil["perfil_texto"].replace(
                " Sou mulher.", ""
            ).replace(" Sou homem.", "")
        assert a == b
        assert len({c["grupo_independencia"] for c in par}) == 1


def test_ambiguos_nao_sao_rotulados_como_negativa_ou_indicacao():
    casos = [c for c in construir()["gabarito"]["casos"] if c["cenario"] == "ambiguo"]
    assert len(casos) >= 24
    assert {c["particao"] for c in casos} == {"ajuste", "prova"}
    assert all(c["resultado_esperado"] == "pedir_humano" for c in casos)
    assert all("desconhecido" in {r["estado"] for r in c["requisitos"].values()}
               for c in casos)


def test_referencias_contratos_e_trechos_conferem():
    dados = construir()
    vagas = {v["id"]: Vaga.model_validate(v) for v in dados["vagas"]}
    assert len(vagas) >= 24
    for indice, caso in enumerate(dados["gabarito"]["casos"]):
        pessoa = Candidato.model_validate(dados["candidatos"][indice])
        assert caso["indice"] == indice
        assert pessoa.id == caso["candidato_id"]
        assert pessoa.empresa_id == caso["empresa_id"] == vagas[caso["vaga_id"]].empresa_id
        assert pessoa.simulado
        assert pessoa.atributos["email"].endswith("@example.invalid")
        assert set(caso["requisitos"]) == {r.id for r in vagas[caso["vaga_id"]].requisitos}
        for requisito in caso["requisitos"].values():
            assert requisito["trecho"] in pessoa.perfil_texto
            assert requisito["trecho"].strip()
        assert not {"par_vies", "resultado_esperado", "particao"} & pessoa.atributos.keys()


def test_negativas_e_autorizacao_tem_causas_distintas():
    dados = construir()
    for caso in dados["gabarito"]["casos"]:
        pessoa = dados["candidatos"][caso["indice"]]
        if caso["cenario"] == "sem_requisito":
            assert caso["resultado_esperado"] == "descartar"
            assert {r["estado"] for r in caso["requisitos"].values()} == {"nao_atende"}
        if caso["cenario"] == "autorizacao_bloqueada":
            assert caso["resultado_esperado"] == "bloquear_contato"
            assert {r["estado"] for r in caso["requisitos"].values()} == {"atende"}
            assert pessoa["opt_out"] or not pessoa["autorizou_contato"] or (
                pessoa["autorizacao_valida_ate"] < "2026-11-07"
            )


def test_manifesto_audita_volume_e_semelhanca():
    dados = construir()
    manifesto = dados["manifesto"]
    assert manifesto["registros"] == len(dados["candidatos"])
    assert manifesto["indicaveis_prova_independentes"] >= 120
    assert manifesto["funcoes"] >= 12
    assert manifesto["textos_profissionais_distintos_sem_pares"] >= 216
    assert manifesto["pares_muito_semelhantes_sem_vies"] == []
    assert len(manifesto["sha256_candidatos"]) == 64
    assert manifesto["validacao_rh"] == "pendente"


def test_exportacao_reproduzivel_e_fixtures_congeladas(tmp_path):
    modulo = importlib.import_module("dados.avaliacao_v3")
    modulo.exportar(tmp_path)
    for nome in ["candidatos", "vagas", "gabarito", "manifesto"]:
        arquivo = "respostas_certas.json" if nome == "gabarito" else f"{nome}.json"
        assert (tmp_path / arquivo).read_bytes() == (PASTA / arquivo).read_bytes()
    assert construir() == construir()


def test_amostra_nao_aumenta_com_duplicacao_de_par():
    casos = construir()["gabarito"]["casos"]
    contagem = Counter(c["cenario"] for c in casos)
    assert contagem["par_vies"] == 24
    assert len(casos) == 240


def test_identidade_nao_revela_rotulo_particao_ou_par():
    for pessoa in construir()["candidatos"]:
        identidade = " ".join([pessoa["id"], pessoa["nome"], pessoa["atributos"]["email"]])
        assert not any(termo in identidade for termo in (
            "positivos", "negativos", "ambiguos", "bloqueados", "prova", "ajuste", "par-"
        ))
        assert pessoa["id"].startswith("pessoa-")
        # Não atribuir todas as competências de uma função sem evidência individual.
        assert "competencias" not in pessoa["atributos"]
        assert "cargo" not in pessoa["atributos"]


def test_prova_cobre_tres_bloqueios_de_autorizacao():
    dados = construir()
    perfis = [dados["candidatos"][c["indice"]] for c in dados["gabarito"]["casos"]
              if c["particao"] == "prova" and c["cenario"] == "autorizacao_bloqueada"]
    assert any(p["opt_out"] for p in perfis)
    assert any(not p["autorizou_contato"] for p in perfis)
    assert any(p["autorizacao_valida_ate"] and p["autorizacao_valida_ate"] < "2026-11-07"
               for p in perfis)
