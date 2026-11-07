"""Rodada de avaliação: análise, revisão, auditoria e métricas.

Cada caso roda isolado, com cache próprio, para um caso não herdar a análise de
outro. O modelo é o mesmo em toda a rodada, porque é dele que a rodada fala.

Os pares de viés rodam separados dos casos e entram como uma unidade medida cada,
não como duas pessoas: eles medem invariância, não ampliam a amostra de precisão.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from avaliacoes.auditoria import ClienteAuditado, RegistroChamada, ResultadoChamada
from avaliacoes.casos import Caso, Particao
from avaliacoes.metricas import (
    Achado,
    Resumo,
    auditar_analise,
    invariancia_de_pares,
    pares_medidos,
    resumir,
)
from avaliacoes.modelos_de_prova import MODELOS_DE_PROVA
from backend.contratos.modelos import Analise, Contrato
from backend.fontes.analisador import Analisador
from backend.fontes.funil import CacheAnalise
from backend.fontes.revisor import Revisor

ETAPA_ANALISE = "analisar_perfil"


class ResultadoCaso(Contrato):
    """O que aconteceu com um caso. `analisado` falso significa barrado antes do modelo."""

    id_caso: str
    cenario: str
    particao: Particao
    analisado: bool
    motivo_nao_analisado: str | None = None
    analise: Analise | None = None
    achados: list[Achado] = []
    evidencias_propostas: int = 0
    notas_propostas: int = 0
    modelo_respondeu: bool = False


@dataclass
class Rodada:
    """Resultado de uma rodada inteira, pronto para virar relatório."""

    nome_modelo: str
    resultados: list[ResultadoCaso]
    trilha: list[RegistroChamada]
    achados: list[Achado]
    resumo: Resumo
    pares_medidos: int = 0
    simulado: bool = True
    custo_usd: float = 0.0
    consumo_por_etapa: dict = field(default_factory=dict)

    @property
    def evidencias_propostas(self) -> int:
        return sum(r.evidencias_propostas for r in self.resultados)

    @property
    def evidencias_aceitas(self) -> int:
        return sum(len(r.analise.evidencias) for r in self.resultados if r.analise)

    @property
    def evidencias_recusadas(self) -> int:
        return self.evidencias_propostas - self.evidencias_aceitas

    @property
    def notas_propostas(self) -> int:
        return sum(r.notas_propostas for r in self.resultados)

    @property
    def notas_aceitas(self) -> int:
        return sum(len(r.analise.notas) for r in self.resultados if r.analise)

    @property
    def notas_recusadas(self) -> int:
        return self.notas_propostas - self.notas_aceitas

    @property
    def chamadas_falhas(self) -> int:
        return sum(r.resultado != ResultadoChamada.OK for r in self.trilha)

    @property
    def tokens_entrada_estimados(self) -> int:
        return sum(r.tokens_entrada_estimados for r in self.trilha)

    @property
    def tokens_saida_estimados(self) -> int:
        return sum(r.tokens_saida_estimados for r in self.trilha)


FabricaDeModelo = str | Callable[[], object]


def _cliente(modelo: FabricaDeModelo) -> tuple[object, str]:
    if isinstance(modelo, str):
        if modelo not in MODELOS_DE_PROVA:
            raise ValueError(f"modelo de prova desconhecido: {modelo!r}")
        return MODELOS_DE_PROVA[modelo](), modelo
    return modelo(), getattr(modelo, "__name__", "injetado")


def _analisar_um(caso: Caso, auditado: ClienteAuditado, com_revisor: bool) -> ResultadoCaso:
    """Roda um caso com cache novo e devolve o que o código deixou sair."""
    comeco = len(auditado.trilha)
    analisador = Analisador(auditado, hoje=caso.hoje, cache=CacheAnalise(hoje=caso.hoje))
    with auditado.no_caso(caso.id_caso):
        try:
            analise = analisador.analisar(caso.vaga, caso.candidato)
        except ValueError as erro:
            return ResultadoCaso(
                id_caso=caso.id_caso,
                cenario=caso.cenario,
                particao=caso.particao,
                analisado=False,
                motivo_nao_analisado=str(erro),
            )
        if com_revisor:
            analise = Revisor(auditado, hoje=caso.hoje).revisar(caso.vaga, caso.candidato, analise)

    do_caso = auditado.trilha[comeco:]
    analises_ok = [
        registro
        for registro in do_caso
        if registro.etapa == ETAPA_ANALISE and registro.resultado == ResultadoChamada.OK
    ]
    ultima = analises_ok[-1] if analises_ok else None
    respondeu = any(registro.resultado == ResultadoChamada.OK for registro in do_caso)
    return ResultadoCaso(
        id_caso=caso.id_caso,
        cenario=caso.cenario,
        particao=caso.particao,
        analisado=True,
        analise=analise,
        evidencias_propostas=ultima.evidencias_propostas if ultima else 0,
        notas_propostas=ultima.notas_propostas if ultima else 0,
        modelo_respondeu=respondeu,
        achados=auditar_analise(
            caso,
            analise,
            modelo_respondeu=respondeu,
            evidencias_propostas=ultima.evidencias_propostas if ultima else 0,
            notas_propostas=ultima.notas_propostas if ultima else 0,
        ),
    )


def rodar(
    casos: Sequence[Caso],
    modelo: FabricaDeModelo,
    *,
    particao: str | None = None,
    pares: Sequence[tuple[Caso, Caso]] = (),
    com_revisor: bool = True,
) -> Rodada:
    """Roda os casos da partição pedida e, se houver, os pares de viés."""
    cliente, nome = _cliente(modelo)
    auditado = ClienteAuditado(cliente, nome_modelo=nome)
    escolhidos = [caso for caso in casos if particao is None or caso.particao == particao]

    resultados = [_analisar_um(caso, auditado, com_revisor) for caso in escolhidos]
    achados = [achado for resultado in resultados for achado in resultado.achados]

    analises_de_pares: dict[tuple[str, str], Analise] = {}
    for par in pares:
        for membro in par:
            resultado = _analisar_um(membro, auditado, com_revisor)
            if resultado.analise is not None:
                chave = (membro.par_vies or membro.id_caso, membro.variacao_vies or "")
                analises_de_pares[chave] = resultado.analise
    medidos = pares_medidos(analises_de_pares)
    achados_de_pares = invariancia_de_pares(analises_de_pares)

    return Rodada(
        nome_modelo=nome,
        resultados=resultados,
        trilha=auditado.trilha,
        achados=achados + achados_de_pares,
        resumo=resumir(
            achados + achados_de_pares,
            total_de_casos=len(resultados) + medidos,
            casos_analisados=sum(resultado.analisado for resultado in resultados),
        ),
        pares_medidos=medidos,
        consumo_por_etapa=auditado.consumo_por_etapa(),
    )
