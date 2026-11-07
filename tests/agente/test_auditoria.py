from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.agente.auditoria import (
    Auditoria,
    DecisaoIncompleta,
    responsavel_do_mandato,
)
from backend.agente.mandato import Mandato, Politica
from backend.agente.persistencia import Repositorio
from backend.contratos.modelos import Decisao, Evidencia, TipoDecisao

FUSO_BRASILIA = timezone(timedelta(hours=-3))
MOMENTO = datetime(2026, 11, 7, 12, 0, tzinfo=FUSO_BRASILIA)


def _mandato(**campos) -> Mandato:
    dados = {
        "id": "mandato-1",
        "versao": 2,
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "hash_vaga": "hash",
        "assinante": "Ana Souza",
        "limite_gasto_usd": 5.0,
        "politica": Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=5, max_ampliacoes=1),
        "assinado_em": MOMENTO,
    }
    dados.update(campos)
    return Mandato(**dados)


def _decisao(**campos) -> Decisao:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "candidato_id": "cand-1",
        "tipo": TipoDecisao.INDICAR,
        "regra": "faixa_verde_v1",
        "motivo": "requisitos comprovados",
        "responsavel": responsavel_do_mandato(_mandato()),
        "rastro_id": "exec-1:vaga-1:cand-1",
        "entrada": {"nota": "0.9"},
        "evidencias": [Evidencia(criterio="r1", trecho="Python há 5 anos", fonte="github")],
        "momento": MOMENTO,
    }
    dados.update(campos)
    return Decisao(**dados)


@pytest.fixture
def repo(tmp_path: Path) -> Repositorio:
    repositorio = Repositorio(tmp_path / "agente.db")
    repositorio.salvar_mandato("empresa-a", "vaga-1", _mandato().model_dump_json())
    return repositorio


@pytest.fixture
def auditoria(repo: Repositorio) -> Auditoria:
    return Auditoria(repo)


def test_toda_decisao_tem_entrada_regra_evidencias_e_responsavel(auditoria, repo):
    decisao = _decisao()

    auditoria.registrar_decisao(decisao)

    assert repo.listar_decisoes("empresa-a", "vaga-1") == [decisao]


@pytest.mark.parametrize(
    "campos, faltando",
    [
        ({"entrada": {}}, "entrada"),
        ({"entrada": {"nota": " "}}, "entrada"),
        ({"evidencias": []}, "evidencias"),
        ({"evidencias": [Evidencia(criterio="r1", trecho=" ", fonte="github")]}, "evidencias"),
        ({"evidencias": [Evidencia(criterio="r1", trecho="x", fonte="")]}, "evidencias"),
        ({"evidencias": [Evidencia(criterio="", trecho="x", fonte="f")]}, "evidencias"),
        ({"motivo": " "}, "motivo"),
        ({"rastro_id": ""}, "rastro_id"),
        ({"vaga_id": ""}, "vaga_id"),
        ({"candidato_id": " "}, "candidato_id"),
    ],
)
def test_decisao_incompleta_e_recusada_e_nada_e_salvo(auditoria, repo, campos, faltando):
    with pytest.raises(DecisaoIncompleta, match=faltando):
        auditoria.registrar_decisao(_decisao(**campos))

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


@pytest.mark.parametrize("campo", ["regra", "responsavel", "empresa_id"])
def test_campo_vazio_que_escapou_do_contrato_e_recusado(auditoria, repo, campo):
    with pytest.raises(DecisaoIncompleta, match=campo):
        auditoria.registrar_decisao(_decisao().model_copy(update={campo: " "}))

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


def test_momento_sem_fuso_e_recusado(auditoria, repo):
    sem_fuso = _decisao().model_copy(update={"momento": datetime(2026, 11, 7, 12, 0)})

    with pytest.raises(DecisaoIncompleta, match="momento"):
        auditoria.registrar_decisao(sem_fuso)

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_erro_de_contrato_nao_copia_os_dados_da_decisao(auditoria):
    decisao = _decisao().model_copy(update={"momento": "dado-do-perfil-sintetico"})

    with pytest.raises(DecisaoIncompleta) as erro:
        auditoria.registrar_decisao(decisao)

    assert "dado-do-perfil-sintetico" not in str(erro.value)


def test_responsavel_identifica_assinante_e_versao_do_mandato():
    responsavel = responsavel_do_mandato(_mandato())

    assert "Ana Souza" in responsavel
    assert "v2" in responsavel
    assert "mandato-1" in responsavel


@pytest.mark.parametrize(
    "responsavel",
    [
        "regras",
        "agente",
        "agente:mandato:mandato-1:v2",
        "agente:mandato:mandato-1:assinante:Ana Souza",
        "humano:",
        "rh",
    ],
)
def test_responsavel_sem_identificacao_e_recusado(auditoria, repo, responsavel):
    with pytest.raises(DecisaoIncompleta, match="responsavel"):
        auditoria.registrar_decisao(_decisao(responsavel=responsavel))

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


@pytest.mark.parametrize(
    "mandato_citado",
    [
        _mandato(id="mandato-falso"),
        _mandato(versao=1),
        _mandato(assinante="Outra Pessoa"),
    ],
)
def test_decisao_do_agente_precisa_citar_o_mandato_assinado(auditoria, repo, mandato_citado):
    decisao = _decisao(responsavel=responsavel_do_mandato(mandato_citado))

    with pytest.raises(DecisaoIncompleta, match="mandato"):
        auditoria.registrar_decisao(decisao)

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


def test_mandato_de_outra_empresa_nao_vale(auditoria, repo):
    decisao = _decisao(empresa_id="empresa-b")

    with pytest.raises(DecisaoIncompleta, match="mandato"):
        auditoria.registrar_decisao(decisao)

    assert repo.listar_decisoes("empresa-b", "vaga-1") == []


def test_decisao_humana_identifica_a_pessoa_e_nao_exige_mandato(tmp_path):
    repositorio = Repositorio(tmp_path / "sem_mandato.db")
    decisao = _decisao(tipo=TipoDecisao.DESCARTAR, responsavel="humano:Carla Lima")

    Auditoria(repositorio).registrar_decisao(decisao)

    assert repositorio.listar_decisoes("empresa-a", "vaga-1") == [decisao]
