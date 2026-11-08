"""Chamada real à Featherless. Gasta créditos: roda só com `-m eval` e com a chave no ambiente."""

import os

import pytest
from pydantic import BaseModel

from backend.modelos.cliente import ClienteFeatherless

LIMITE_DE_GASTO_USD = 0.05


class PerfilExtraido(BaseModel):
    linguagem: str
    anos_de_experiencia: int


@pytest.mark.eval
@pytest.mark.skipif(
    not (os.environ.get("FEATHERLESS_API_KEY") or "").strip(),
    reason="FEATHERLESS_API_KEY não definida",
)
def test_chamada_real_devolve_esquema():
    cliente = ClienteFeatherless(limite_gasto_usd=LIMITE_DE_GASTO_USD)

    resultado = cliente.completar(
        "Você extrai dados de perfis profissionais.",
        "<dados>Perfil sintético: Pessoa Teste programa em Python há 5 anos.</dados>",
        PerfilExtraido,
        "teste_real",
    )

    metricas = cliente.metricas()["teste_real"]
    assert isinstance(resultado, PerfilExtraido)
    assert metricas.tokens_entrada > 0
    assert metricas.tokens_saida > 0
    print(
        f"\nresultado={resultado.model_dump()} chamadas={metricas.chamadas} "
        f"falhas={metricas.falhas} tokens={metricas.tokens_entrada}+{metricas.tokens_saida} "
        f"custo_usd={metricas.custo_usd:.6f} estimado={metricas.custo_estimado} "
        f"tempo_s={metricas.tempo_s:.1f}"
    )
