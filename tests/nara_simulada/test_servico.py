import pytest

from backend.contratos.interfaces import AgenteRecrutador
from backend.contratos.modelos import PacoteContexto
from backend.nara_simulada.servico import NaraSimulada


def _pacote(**extra) -> PacoteContexto:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "motivo_por_criterio": {"mensageria": "Kafka", "r1": "Python"},
        "historico": [],
        "evidencias": [],
        "lacunas": [],
        "pontos_a_aprofundar": [],
        "ressalvas_revisor": [],
        "autorizacao": "válida até 2027-11-07",
        "fonte": "simulada",
        "rastro_id": "rastro-1",
        "chave_idempotencia": "empresa-a:v1:c1:entrega",
        "simulado": True,
    }
    dados.update(extra)
    return PacoteContexto(**dados)


def _outro(candidato_id: str, empresa_id: str = "empresa-a") -> PacoteContexto:
    return _pacote(
        empresa_id=empresa_id,
        candidato_id=candidato_id,
        chave_idempotencia=f"{empresa_id}:v1:{candidato_id}:entrega",
    )


def test_segue_a_interface():
    assert isinstance(NaraSimulada(), AgenteRecrutador)


def test_link_e_resultado_identificam_simulacao():
    nara = NaraSimulada()
    nara.entregar(_pacote())

    link = nara.link_agendamento("v1", "c1")
    assert "simulada" in link
    assert link.endswith("/v1/c1")
    (resultado,) = nara.resultados("empresa-a", "v1")
    assert resultado.simulado is True


def test_entrega_repetida_nao_duplica():
    nara = NaraSimulada()

    assert nara.entregar(_pacote()) is True
    assert nara.entregar(_pacote()) is True
    assert len(nara.entregues("empresa-a")) == 1
    assert len(nara.resultados("empresa-a", "v1")) == 1


def test_falha_de_entrega_permite_repetir():
    nara = NaraSimulada(falhas_restantes=1)

    assert nara.entregar(_pacote()) is False
    assert nara.entregues("empresa-a") == []
    assert nara.entregar(_pacote()) is True
    assert len(nara.entregues("empresa-a")) == 1


def test_recusa_pacote_nao_simulado():
    with pytest.raises(ValueError):
        NaraSimulada().entregar(_pacote(simulado=False))


def test_resultados_reproduziveis_alimentam_aprendizado():
    pacotes = [_outro(f"c{i}") for i in range(20)]

    def rodar(semente: int):
        nara = NaraSimulada(semente=semente)
        for pacote in reversed(pacotes):
            nara.entregar(pacote)
        return nara.resultados("empresa-a", "v1")

    resultados = rodar(7)
    assert resultados == rodar(7)
    assert resultados != rodar(8)
    assert [r.candidato_id for r in resultados] == sorted(p.candidato_id for p in pacotes)
    assert all(set(r.notas) == {"mensageria", "r1"} for r in resultados)
    assert all(0 <= n <= 1 for r in resultados for n in r.notas.values())
    assert {r.aprovado for r in resultados} == {True, False}
    for r in resultados:
        assert r.aprovado == (sum(r.notas.values()) / len(r.notas) >= 0.5)


def test_pacote_sem_criterio_recebe_nota_geral():
    nara = NaraSimulada()
    nara.entregar(_pacote(motivo_por_criterio={}))

    (resultado,) = nara.resultados("empresa-a", "v1")
    assert set(resultado.notas) == {"geral"}


def test_resultados_isolam_empresas():
    nara = NaraSimulada()
    nara.entregar(_outro("c1", "empresa-a"))
    nara.entregar(_outro("c2", "empresa-b"))

    assert [r.candidato_id for r in nara.resultados("empresa-a", "v1")] == ["c1"]
    assert [r.candidato_id for r in nara.resultados("empresa-b", "v1")] == ["c2"]
    assert nara.resultados("empresa-a", "v2") == []


def test_resultados_exigem_empresa():
    with pytest.raises(ValueError):
        NaraSimulada().resultados(" ", "v1")
