"""Aprendizado (T1.5): o resultado da Nara sugere ajuste; só uma pessoa aprova; dá para reverter."""

import pytest

from backend.agente.aprendizado import (
    AjusteNaoAprovado,
    aplicar,
    aprovar,
    propor_ajuste,
    reverter,
)
from backend.agente.fluxo import ResponsavelInvalido
from backend.contratos.modelos import Competencia, ResultadoEntrevista
from tests.agente.apoio import vaga_exemplo


def _vaga():
    return vaga_exemplo(
        competencias=[Competencia(nome="backend", peso=1.0), Competencia(nome="cloud", peso=1.0)]
    )


def _resultado(candidato: str, **notas: float) -> ResultadoEntrevista:
    vaga = _vaga()
    return ResultadoEntrevista(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato,
        notas=notas,
        aprovado=min(notas.values()) >= 0.5,
    )


def _reprovados_em_cloud(quantidade: int = 4) -> list[ResultadoEntrevista]:
    return [_resultado(f"c{i}", backend=0.8, cloud=0.2) for i in range(quantidade)]


def test_detecta_criterio_com_reprovacao_repetida():
    vaga = _vaga()

    proposta = propor_ajuste(vaga, _reprovados_em_cloud())

    assert proposta is not None
    assert proposta.vaga_id == vaga.id
    assert proposta.aprovada is False
    assert proposta.antes == vaga
    pesos = {c.nome: c.peso for c in proposta.depois.competencias}
    assert pesos["cloud"] > 1.0
    assert pesos["backend"] == 1.0
    assert "cloud" in proposta.motivo
    assert proposta.resultado_avaliacao["reprovacoes"] == 4
    assert proposta.resultado_avaliacao["entrevistas"] == 4


def test_poucas_entrevistas_nao_geram_proposta():
    assert propor_ajuste(_vaga(), _reprovados_em_cloud(2)) is None


def test_reprovacao_espalhada_nao_gera_proposta():
    resultados = [
        _resultado("c0", backend=0.2, cloud=0.8),
        _resultado("c1", backend=0.8, cloud=0.2),
        _resultado("c2", backend=0.8, cloud=0.8),
        _resultado("c3", backend=0.8, cloud=0.8),
    ]

    assert propor_ajuste(_vaga(), resultados) is None


def test_resultado_de_outra_vaga_ou_empresa_e_ignorado():
    outros = [r.model_copy(update={"empresa_id": "outra-empresa"}) for r in _reprovados_em_cloud()]

    assert propor_ajuste(_vaga(), outros) is None


def test_nao_aplica_sem_aprovacao():
    proposta = propor_ajuste(_vaga(), _reprovados_em_cloud())

    with pytest.raises(AjusteNaoAprovado):
        aplicar(proposta)


def test_aprovacao_exige_uma_pessoa():
    proposta = propor_ajuste(_vaga(), _reprovados_em_cloud())

    with pytest.raises(ResponsavelInvalido):
        aprovar(proposta, "agente automático")


def test_aplica_depois_da_aprovacao():
    proposta = aprovar(propor_ajuste(_vaga(), _reprovados_em_cloud()), "Ana do RH (fictícia)")

    nova = aplicar(proposta)

    assert nova == proposta.depois
    assert nova.aprovada is False


def test_permite_reverter():
    vaga = _vaga()
    proposta = aprovar(propor_ajuste(vaga, _reprovados_em_cloud()), "Ana do RH (fictícia)")
    aplicar(proposta)

    assert reverter(proposta) == vaga
    assert reverter(proposta) == vaga


def test_nao_propoe_criterio_sensivel():
    resultados = [_resultado(f"c{i}", backend=0.8, cloud=0.8, idade=0.1) for i in range(5)]

    assert propor_ajuste(_vaga(), resultados) is None


def test_criterio_fora_da_vaga_nao_e_proposto():
    resultados = [_resultado(f"c{i}", backend=0.8, cloud=0.8, kotlin=0.1) for i in range(5)]

    assert propor_ajuste(_vaga(), resultados) is None
