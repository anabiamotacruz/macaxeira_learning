"""Relatório JSON da avaliação, para o painel e para o registro da rodada.

O relatório só carrega agregados e os limites da medição. Nome, contato e texto
de perfil nunca entram. Rode com `python -m avaliacoes.relatorio`.
"""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from avaliacoes.auditoria import escrever_trilha
from avaliacoes.canal import medir_cobertura
from avaliacoes.casos import Caso, carregar_casos, hash_do_conjunto, pares_de_vies
from avaliacoes.execucao import Rodada, rodar
from avaliacoes.metricas import TipoAchado
from avaliacoes.modelos_de_prova import MODELOS_DE_PROVA

PASTA_DE_SAIDA = Path("avaliacoes/saida")
CAMINHO_RELATORIO = PASTA_DE_SAIDA / "relatorio.json"

LIMITES = (
    "Dados sintéticos. Nenhum número aqui descreve pessoas ou currículos reais.",
    "Os modelos de prova não imitam a qualidade de um modelo real: a rodada mede o "
    "que o código determinístico faz com uma saída ruim, não o acerto do modelo.",
    "Precisão com modelo real depende de FEATHERLESS_API_KEY e ainda não foi medida.",
    "Os pares de viés cobrem só nome e gênero. Não há eixo racial, de idade ou de "
    "deficiência, e o resultado não se estende a eles.",
    "O par prova invariância da entrada e das etapas determinísticas; invariância de "
    "um modelo real diante do mesmo par é outra medição.",
    "O cenário de cada caso é a intenção editorial do gerador, não rotulagem "
    "independente feita por pessoa de RH.",
    "Taxa sem casos aparece nula, nunca zero. O denominador vai junto de cada taxa.",
    "A cobertura de canal descreve este conjunto sintético, onde ninguém publicou URL "
    "de origem de contato: ela não estima a cobertura de uma base real, e a cobertura "
    "real tende a ser o maior gargalo do produto.",
)
"""O que esta rodada não prova. Entra no relatório para nenhum número viajar sozinho."""


def _descrever_conjunto(casos: Sequence[Caso], pares: int) -> dict[str, Any]:
    return {
        "origem": "dados.gerador",
        "total_de_casos": len(casos),
        "elegiveis": sum(caso.elegivel_esperado for caso in casos),
        "empresas": sorted({caso.candidato.empresa_id for caso in casos}),
        "vagas": sorted({caso.vaga.id for caso in casos}),
        "pares_de_vies": pares,
        "por_cenario": dict(sorted(Counter(caso.cenario for caso in casos).items())),
        "por_particao": dict(
            sorted(Counter(caso.particao.value for caso in casos).items())
        ),
        "cobertura_de_canal": medir_cobertura(casos).model_dump(mode="json"),
        "hash": hash_do_conjunto(list(casos)),
    }


def _descrever_rodada(rodada: Rodada) -> dict[str, Any]:
    contagem = Counter(achado.tipo for achado in rodada.achados)
    return {
        "modelo": rodada.nome_modelo,
        "simulado": rodada.simulado,
        "aprovado": rodada.resumo.aprovado,
        "casos_analisados": rodada.resumo.casos_analisados,
        "total_de_casos": rodada.resumo.total_de_casos,
        "pares_medidos": rodada.pares_medidos,
        "chamadas": len(rodada.trilha),
        "chamadas_falhas": rodada.chamadas_falhas,
        "tokens_entrada_estimados": rodada.tokens_entrada_estimados,
        "tokens_saida_estimados": rodada.tokens_saida_estimados,
        "custo_usd": rodada.custo_usd,
        "evidencias_propostas": rodada.evidencias_propostas,
        "evidencias_aceitas": rodada.evidencias_aceitas,
        "notas_propostas": rodada.notas_propostas,
        "notas_aceitas": rodada.notas_aceitas,
        "achados_por_tipo": {tipo.value: contagem.get(tipo, 0) for tipo in TipoAchado},
        "taxa_de_casos_com_achado": rodada.resumo.taxa_de_casos_com_achado.model_dump(mode="json"),
        "consumo_por_etapa": {
            etapa: {
                "chamadas": consumo.chamadas,
                "falhas": consumo.falhas,
                "tokens_entrada_estimados": consumo.tokens_entrada_estimados,
                "tokens_saida_estimados": consumo.tokens_saida_estimados,
            }
            for etapa, consumo in sorted(rodada.consumo_por_etapa.items())
        },
    }


def gerar_relatorio(casos: Sequence[Caso], rodadas: Sequence[Rodada]) -> dict[str, Any]:
    """Agrega o conjunto e as rodadas num relatório sem dado de pessoa."""
    return {
        "simulado": True,
        "conjunto": _descrever_conjunto(
            casos, pares=max((rodada.pares_medidos for rodada in rodadas), default=0)
        ),
        "modelos": [_descrever_rodada(rodada) for rodada in rodadas],
        "limites": list(LIMITES),
    }


def escrever_relatorio(caminho: Path | str, relatorio: dict[str, Any]) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    """Roda todos os modelos de prova, grava o relatório e a trilha de cada um."""
    casos = carregar_casos()
    pares = pares_de_vies(casos)
    rodadas = [rodar(casos, nome, pares=pares) for nome in MODELOS_DE_PROVA]
    escrever_relatorio(CAMINHO_RELATORIO, gerar_relatorio(casos, rodadas))
    for rodada in rodadas:
        escrever_trilha(PASTA_DE_SAIDA / f"trilha-{rodada.nome_modelo}.jsonl", rodada.trilha)
    print(f"relatório em {CAMINHO_RELATORIO}")
    for rodada in rodadas:
        situacao = "aprovado" if rodada.resumo.aprovado else "REPROVADO"
        observados = sum(
            1 for achado in rodada.achados if achado.tipo in (TipoAchado.DESCARTE_SEM_RASTRO,)
        )
        print(
            f"  {rodada.nome_modelo:20} {situacao:10} "
            f"propostas {rodada.evidencias_propostas:4} evidências / "
            f"{rodada.notas_propostas:4} notas, "
            f"recusadas {rodada.evidencias_recusadas:4} / {rodada.notas_recusadas:4}, "
            f"observações {observados}"
        )


if __name__ == "__main__":
    main()
