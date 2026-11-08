import re

import pytest

from backend.contratos.modelos import PacoteContexto
from backend.nara_simulada.servico import NaraSimulada

SEGREDO = "trilho secreto da outra empresa"
MENSAGEM_SEM_PACOTE = "não há pacote entregue para este candidato nesta empresa e vaga"


def _pacote(**extra) -> PacoteContexto:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "motivo_por_criterio": {"mensageria": "Kafka"},
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


def _com_pacote(semente: int, **extra) -> NaraSimulada:
    nara = NaraSimulada(semente=semente)
    nara.entregar(_pacote(**extra))
    return nara


def _semente(aprovado: bool) -> int:
    for semente in range(500):
        nara = _com_pacote(semente)
        if nara.resultados("empresa-a", "v1")[0].aprovado is aprovado:
            return semente
    raise AssertionError(f"nenhuma semente com aprovado={aprovado}")


def _frase(nara: NaraSimulada, empresa_id: str = "empresa-a") -> str:
    return nara.resumo_resultado(empresa_id, "v1", "c1")


def test_resumo_e_deterministico_pela_semente():
    def frase(semente: int) -> str:
        return _frase(_com_pacote(semente))

    assert frase(11) == frase(11)
    assert _frase(_com_pacote(11)) == _frase(_com_pacote(11))

    semente_sim = _semente(True)
    semente_nao = _semente(False)
    assert frase(semente_sim) == frase(semente_sim)
    assert frase(semente_nao) == frase(semente_nao)
    assert frase(semente_sim) != frase(semente_nao)

    nara = _com_pacote(semente_sim)
    assert _frase(nara) == _frase(nara)


def test_frase_bate_com_aprovado_avisa_simulacao_e_nao_tem_digitos():
    for esperado in (True, False):
        nara = _com_pacote(_semente(esperado))
        resultado = nara.resultados("empresa-a", "v1")[0]
        texto = _frase(nara)

        assert resultado.aprovado is esperado
        assert texto.endswith(".")
        assert texto.count(".") == 1
        assert "simulada" in texto
        assert re.search(r"\d", texto) is None
        assert "c1" not in texto
        assert "v1" not in texto
        assert "nota" not in texto.casefold()
        assert "ranking" not in texto.casefold()
        if resultado.aprovado:
            assert "seguir" in texto
            assert "não" not in texto
        else:
            assert "não" in texto
            assert "seguir" in texto


def test_resumo_da_empresa_nao_muda_quando_outra_recebe_pacote():
    nara = _com_pacote(3)
    antes = _frase(nara)
    nara.entregar(
        _pacote(
            empresa_id="empresa-b",
            candidato_id="c9",
            motivo_por_criterio={"mensageria": SEGREDO},
            lacunas=[SEGREDO],
            chave_idempotencia="empresa-b:v1:c9:entrega",
        )
    )

    assert _frase(nara) == antes
    with pytest.raises(ValueError, match=MENSAGEM_SEM_PACOTE) as erro:
        _frase(nara, "empresa-b")
    assert SEGREDO not in str(erro.value)
    assert "2027" not in str(erro.value)


def test_candidato_sem_pacote_gera_erro_claro_sem_vazar_outro():
    nara = _com_pacote(0, motivo_por_criterio={"mensageria": SEGREDO}, lacunas=[SEGREDO])

    with pytest.raises(ValueError, match=MENSAGEM_SEM_PACOTE) as sem_vaga:
        nara.resumo_resultado("empresa-a", "v2", "c1")
    with pytest.raises(ValueError, match=MENSAGEM_SEM_PACOTE) as inexistente:
        NaraSimulada().resumo_resultado("empresa-a", "v1", "c1")

    for erro in (sem_vaga, inexistente):
        mensagem = str(erro.value)
        assert SEGREDO not in mensagem
        assert "Kafka" not in mensagem
        assert "2027" not in mensagem


def test_entrega_que_falhou_nao_gera_resumo():
    nara = NaraSimulada(falhas_restantes=1)
    assert nara.entregar(_pacote()) is False
    with pytest.raises(ValueError, match=MENSAGEM_SEM_PACOTE):
        _frase(nara)
