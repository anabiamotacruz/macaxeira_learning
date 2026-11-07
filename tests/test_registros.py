from decimal import Decimal

import pytest

from evals.qualidade_offline import RespostaInvalida
from evals.registros import (
    PrecosModelo,
    calcular_custo,
    de_jsonl,
    para_jsonl,
    somar_custo_por_candidato,
    validar_custo_jsonl,
    validar_decisao_jsonl,
)


DECISAO = {
    "id": "d-1",
    "candidato_id": "c-1",
    "vaga_id": "v-1",
    "quem_decidiu": "recrutadora-simulada-1",
    "quando": "2026-11-07T12:00:00-03:00",
    "resultado": "aprovar",
    "justificativa": "Atende aos requisitos eliminatórios.",
    "evidencias": [{"criterio": "python", "fonte": "perfil-sintetico"}],
    "regra_aplicada": "rubrica-v1",
}


def custo(candidato_id: str, valor: str) -> dict:
    return {
        "id": f"custo-{candidato_id}-{valor}",
        "candidato_id": candidato_id,
        "execucao_id": "exec-1",
        "modelo": "modelo-falso",
        "tokens_entrada": 100,
        "tokens_saida": 50,
        "custo_estimado": valor,
        "moeda": "USD",
        "etapa": "analise",
    }


def test_decisao_jsonl_exige_responsavel_justificativa_e_evidencias():
    # Protege a auditoria e o princípio de que cada decisão tem dono e fundamento.
    registro = dict(DECISAO)
    registro.pop("quem_decidiu")
    with pytest.raises(RespostaInvalida):
        validar_decisao_jsonl(registro)


def test_jsonl_serializa_e_le_um_registro_por_linha():
    # Protege a reprodutibilidade do histórico sem depender de banco ou rede.
    texto = para_jsonl([DECISAO], validar_decisao_jsonl)
    assert "\n" not in texto
    assert de_jsonl(texto, validar_decisao_jsonl) == [DECISAO]


def test_jsonl_rejeita_linha_invalida():
    # Protege contra perda silenciosa de eventos de auditoria.
    with pytest.raises(RespostaInvalida, match="linha 1"):
        de_jsonl("{", validar_decisao_jsonl)


def test_calcula_custo_com_precos_de_configuracao():
    # Protege o cálculo determinístico e permite trocar preços sem alterar código.
    precos = PrecosModelo(Decimal("0.20"), Decimal("0.40"))
    assert calcular_custo(1000, 500, precos) == Decimal("0.4")


def test_rejeita_tokens_negativos():
    # Protege métricas contra registros impossíveis ou manipulados.
    with pytest.raises(ValueError):
        calcular_custo(-1, 0, PrecosModelo(Decimal("1"), Decimal("1")))


def test_soma_custo_por_candidato():
    # Protege o painel de custo por pessoa analisada, agregando todas as etapas.
    registros = [custo("c-1", "0.10"), custo("c-1", "0.25"), custo("c-2", "0.40")]
    assert somar_custo_por_candidato(registros) == {
        "c-1": Decimal("0.35"),
        "c-2": Decimal("0.40"),
    }


def test_custo_jsonl_exige_tokens_e_modelo():
    # Protege o rastreamento de consumo e a explicação de qual modelo foi usado.
    registro = custo("c-1", "0.10")
    registro.pop("modelo")
    with pytest.raises(RespostaInvalida):
        validar_custo_jsonl(registro)
