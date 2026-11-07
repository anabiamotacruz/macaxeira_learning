from datetime import UTC, date, datetime

import pytest

from backend.contato.pacote import chave_entrega, montar_pacote
from backend.contratos.modelos import (
    Analise,
    Decisao,
    Evidencia,
    Experiencia,
    TipoDecisao,
    Vaga,
)
from backend.contratos.simulacoes import candidato_simulado

EXPERIENCIA = Experiencia(
    empresa="Empresa Fictícia",
    cargo="Engenheira de software",
    inicio=date(2022, 1, 1),
    fim=None,
    descricao="Pagamentos com Kafka",
)
KAFKA = Evidencia(criterio="mensageria", trecho="liderou a migração para Kafka", fonte="banco")
PYTHON = Evidencia(criterio="r1", trecho="5 anos de Python", fonte="banco")


def _vaga() -> Vaga:
    return Vaga(
        id="v1",
        empresa_id="empresa-a",
        titulo="Backend Python",
        descricao="Vaga sintética",
        requisitos=[],
        competencias=[],
        meta_candidatos=5,
        prazo_dias=7,
        max_tentativas_contato=2,
    )


def _candidato(**extra):
    campos = {"historico": [EXPERIENCIA], "atributos": {"genero": "feminino"}}
    campos.update(extra)
    return candidato_simulado("c1", "empresa-a", **campos)


def _analise(**extra) -> Analise:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "requisitos_ok": {"r1": True},
        "notas": {"mensageria": 0.9},
        "evidencias": [KAFKA, PYTHON],
        "lacunas": ["intervalo sem trabalho em 2021"],
        "pontos_a_aprofundar": ["escala do sistema de pagamentos"],
        "alertas": [],
        "ressalvas_revisor": ["confirmar liderança técnica"],
    }
    dados.update(extra)
    return Analise(**dados)


def _decisao(**extra) -> Decisao:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "tipo": TipoDecisao.INDICAR,
        "regra": "indicar_com_evidencia",
        "motivo": "atende requisitos e competências",
        "responsavel": "agente",
        "rastro_id": "rastro-1",
        "entrada": {},
        "evidencias": [KAFKA],
        "momento": datetime(2026, 11, 7, 12, tzinfo=UTC),
    }
    dados.update(extra)
    return Decisao(**dados)


def _pacote(**extra):
    args = {
        "vaga": _vaga(),
        "candidato": _candidato(),
        "analise": _analise(),
        "decisao": _decisao(),
    }
    args.update(extra)
    return montar_pacote(**args)


def test_pacote_tem_todos_os_campos_decididos():
    pacote = _pacote()

    assert (pacote.empresa_id, pacote.vaga_id, pacote.candidato_id) == ("empresa-a", "v1", "c1")
    assert pacote.motivo_por_criterio == {
        "mensageria": "liderou a migração para Kafka",
        "r1": "5 anos de Python",
    }
    assert pacote.historico == [EXPERIENCIA]
    assert pacote.evidencias == [KAFKA, PYTHON]
    assert pacote.lacunas == ["intervalo sem trabalho em 2021"]
    assert pacote.pontos_a_aprofundar == ["escala do sistema de pagamentos"]
    assert pacote.ressalvas_revisor == ["confirmar liderança técnica"]
    assert "2027-11-07" in pacote.autorizacao
    assert pacote.fonte == "simulada"
    assert pacote.rastro_id == "rastro-1"
    assert pacote.chave_idempotencia == "empresa-a:v1:c1:entrega"
    assert pacote.simulado is True


def test_pacote_so_leva_evidencia_com_trecho():
    vazia = Evidencia(criterio="lideranca", trecho="  ", fonte="banco")
    pacote = _pacote(analise=_analise(evidencias=[KAFKA, vazia]))

    assert pacote.evidencias == [KAFKA]
    assert "lideranca" not in pacote.motivo_por_criterio


def test_pacote_nao_leva_criterio_sensivel():
    idade = Evidencia(criterio="Idade", trecho="32 anos", fonte="banco")
    pacote = _pacote(analise=_analise(evidencias=[KAFKA, idade]))

    assert pacote.evidencias == [KAFKA]
    assert "Idade" not in pacote.motivo_por_criterio
    assert "feminino" not in pacote.model_dump_json()


def test_pacote_junta_trechos_do_mesmo_criterio_sem_repetir():
    outro = Evidencia(criterio="mensageria", trecho="opera RabbitMQ", fonte="github")
    pacote = _pacote(analise=_analise(evidencias=[KAFKA, outro, KAFKA]))

    assert pacote.motivo_por_criterio["mensageria"] == (
        "liderou a migração para Kafka; opera RabbitMQ"
    )
    assert pacote.evidencias == [KAFKA, outro]


@pytest.mark.parametrize("tipo", [TipoDecisao.DESCARTAR, TipoDecisao.PEDIR_HUMANO])
def test_pacote_exige_decisao_de_indicar(tipo):
    with pytest.raises(ValueError):
        _pacote(decisao=_decisao(tipo=tipo))


@pytest.mark.parametrize(
    "extra",
    [
        {"autorizou_contato": False},
        {"opt_out": True},
        {"autorizacao_valida_ate": None},
    ],
    ids=["sem_autorizacao", "opt_out", "sem_validade"],
)
def test_pacote_exige_autorizacao(extra):
    with pytest.raises(ValueError):
        _pacote(candidato=_candidato(**extra))


@pytest.mark.parametrize(
    "extra",
    [
        {"candidato": candidato_simulado("c1", "empresa-b")},
        {"analise": _analise(empresa_id="empresa-b")},
        {"decisao": _decisao(empresa_id="empresa-b")},
        {"analise": _analise(candidato_id="c2")},
        {"decisao": _decisao(vaga_id="v2")},
    ],
    ids=["candidato", "analise", "decisao", "analise_outro_candidato", "decisao_outra_vaga"],
)
def test_pacote_recusa_dados_que_nao_batem(extra):
    with pytest.raises(ValueError):
        _pacote(**extra)


def test_chave_de_entrega_e_estavel():
    assert chave_entrega("empresa-a", "v1", "c1") == "empresa-a:v1:c1:entrega"
    assert _pacote().chave_idempotencia == _pacote().chave_idempotencia
