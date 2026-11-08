"""Decisão com destino e score: aprovar, recusar, garden ou revisão humana. Tudo em código.

Convive com `regras.decidir`, que segue valendo no fluxo. Diferenças em relação à faixa verde:

- portão duro é só requisito sem evidência aceita, instrução detectada, trecho inexistente em
  requisito e ressalva grave. Inferência em competência, ressalva leve e outros alertas são sinais:
  só reduzem a nota, em vez de mandar a decisão para uma pessoa;
- nota baixa nunca recusa: vai para uma pessoa, sem prioridade, e pode voltar;
- `SEM_DADO` em requisito nunca aprova, e o contrato `DecisaoFinal` também recusa isso.

Reduções e fatores são ponto de partida, não valores calibrados: por isso o selo `não calibrado`.
"""

import json
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pydantic import ValidationError

from backend.agente.auditoria import PREFIXO_HUMANO, rastreado, responsavel_do_mandato
from backend.agente.mandato import Mandato, MandatoInvalido, mandato_valido
from backend.agente.regras import (
    FONTE_REGRA,
    REGRA_PERFIL_DESATUALIZADO,
    StatusRequisito,
    TipoEvidencia,
    autorizacao_ativa,
    avaliar_requisitos,
    classificar_evidencia,
    corte_de_autorizacao,
    evidencia_da_regra,
    parece_instrucao,
    separar_palavras,
    validar_criterios,
)
from backend.contratos.criterios import termos_proibidos_em_conversa
from backend.contratos.modelos import (
    PREFIXO_RECUSA_REQUISITO,
    REGRA_RECUSA_AUTORIZACAO,
    Analise,
    Candidato,
    Competencia,
    Decisao,
    DecisaoFinal,
    DestinoDecisao,
    EntradaGarden,
    EstadoBanco,
    EstadoGarden,
    Evidencia,
    FaixaScore,
    FatoIndisponibilidade,
    InsightsDaVaga,
    InsightVaga,
    LacunaCriterio,
    MotivoLacuna,
    NivelCriterio,
    NotaCriterio,
    OrigemDecisao,
    Politica,
    PontoExplorar,
    QualidadeDado,
    Requisito,
    ScoreRecrutador,
    SeloCalibracao,
    SinalNota,
    TipoCriterio,
    TipoDecisao,
    TipoPonto,
    TrechoCitado,
    Vaga,
)

logger = logging.getLogger(__name__)

ETAPA_DECISAO_FINAL = "decisao_final"
FATOR_QUALIDADE = {
    QualidadeDado.COMPROVADO: 1.0,
    QualidadeDado.DECLARADO: 1.0,
    QualidadeDado.INFERIDO: 0.5,
    QualidadeDado.SEM_DADO: 0.0,
}
"""Quanto da nota vale. Declarado vale inteiro em competência, como na faixa verde."""

REDUCAO_SINAL_EXTERNO = 0.05
"""Quanto cada ressalva leve ou alerta sem instrução tira da nota geral."""

FAIXA_ALTA_SEM_LIMIAR = 0.8
"""Corte da faixa alta enquanto o mandato não define `limiar_verde`."""

NOTA_DO_NIVEL = {
    NivelCriterio.NEGA: 0.0,
    NivelCriterio.GENERICA: 0.3,
    NivelCriterio.PARCIAL: 0.6,
    NivelCriterio.DIRETA: 0.8,
}
"""Âncoras da escala. Resposta em conversa fica no início de `direta`, pois é só declarada."""

MINIMO_PESSOAS_INSIGHT = 5
"""Abaixo disto o agregado identificaria alguém: o insight não aparece."""

REGRA_APROVACAO = "aprovacao_por_criterios_v1"
REGRA_A_LAPIDAR = "a_lapidar_por_fatos"
REGRA_A_LAPIDAR_NAO_CONFIRMADO = "a_lapidar_nao_confirmado"
REGRA_INDISPONIVEL = "pessoa_indisponivel"
REGRA_NOTA_BAIXA = "nota_baixa_nao_priorizada"
REGRA_PORTAO = "portao_duro"
PORTAO_INSTRUCAO = "instrucao_detectada"
PORTAO_TRECHO_INEXISTENTE = "trecho_inexistente_em_requisito"
PORTAO_PESOS = "pesos_invalidos"
SINAL_RESSALVA = "ressalva_revisor"
SINAL_ALERTA = "alerta"
SINAIS_EXTERNOS = frozenset({SINAL_RESSALVA, SINAL_ALERTA})
RESSALVA_NOTA_SEM_EVIDENCIA = "nota_sem_evidencia"
FONTE_VAGA = "vaga"

_TIPO_ANTIGO = {
    DestinoDecisao.APROVAR: TipoDecisao.INDICAR,
    DestinoDecisao.RECUSAR: TipoDecisao.DESCARTAR,
}
_QUALIDADE_DO_TIPO = {
    TipoEvidencia.COMPROVADA: QualidadeDado.COMPROVADO,
    TipoEvidencia.DECLARADA: QualidadeDado.DECLARADO,
    TipoEvidencia.INFERIDA: QualidadeDado.INFERIDO,
}
_ORDEM_QUALIDADE = (
    QualidadeDado.COMPROVADO,
    QualidadeDado.DECLARADO,
    QualidadeDado.INFERIDO,
)


@dataclass(frozen=True)
class RespostaCriterio:
    """Fato novo sobre um critério, vindo da própria pessoa. Reavalia só este critério."""

    criterio: str
    trecho: str
    fonte: str
    nivel: NivelCriterio | None = None


def nivel_da_nota(nota: float) -> NivelCriterio:
    """Leva a nota à escala ancorada usada na análise: 0, 0,3, 0,6 e de 0,8 a 1."""
    if nota < 0.15:
        return NivelCriterio.NEGA
    if nota < 0.45:
        return NivelCriterio.GENERICA
    if nota < 0.8:
        return NivelCriterio.PARCIAL
    return NivelCriterio.DIRETA


def _exigir_mesma_execucao(vaga: Vaga, candidato: Candidato, mandato: Mandato) -> None:
    if candidato.empresa_id != vaga.empresa_id or mandato.empresa_id != vaga.empresa_id:
        raise ValueError("candidato e mandato precisam ser da empresa da vaga")
    if mandato.vaga_id != vaga.id:
        raise ValueError("mandato precisa ser da mesma vaga")


def _exigir_mandato_valido(vaga: Vaga, mandato: Mandato, agora: datetime) -> None:
    if not mandato_valido(mandato, vaga, agora):
        raise MandatoInvalido("mandato não vale para esta vaga neste momento")
    problemas = validar_criterios(vaga)
    if problemas:
        raise MandatoInvalido(f"vaga com problemas nos critérios: {'; '.join(problemas)}")


def _trecho_mostravel(evidencia: Evidencia) -> bool:
    """O tipo da evidência conta para a decisão, mas dado sensível não aparece para ninguém."""
    textos = (evidencia.criterio, evidencia.trecho, evidencia.fonte)
    return (
        all(texto.strip() for texto in textos)
        and not termos_proibidos_em_conversa(evidencia.trecho)
        and not parece_instrucao(evidencia.trecho)
    )


def _qualidade(tipos: Iterable[TipoEvidencia]) -> QualidadeDado:
    presentes = {_QUALIDADE_DO_TIPO[tipo] for tipo in tipos}
    for qualidade in _ORDEM_QUALIDADE:
        if qualidade in presentes:
            return qualidade
    return QualidadeDado.SEM_DADO


def _aceita(qualidade: QualidadeDado, politica: Politica) -> bool:
    if qualidade == QualidadeDado.COMPROVADO:
        return True
    return qualidade == QualidadeDado.DECLARADO and politica.aceitar_declarada


def _nota_requisito(
    requisito: Requisito,
    status: StatusRequisito,
    analise: Analise,
    evidencias: Sequence[tuple[Evidencia, TipoEvidencia]],
    politica: Politica,
) -> NotaCriterio:
    citadas = [(e, tipo) for e, tipo in evidencias if e.criterio == requisito.id]
    qualidade = _qualidade(tipo for _, tipo in citadas)
    return NotaCriterio(
        criterio=requisito.id,
        tipo=TipoCriterio.REQUISITO,
        descricao=requisito.descricao,
        peso=0,
        qualidade=qualidade,
        trechos=_trechos(citadas),
        status_requisito=status.value,
        confirmado_na_analise=analise.requisitos_ok.get(requisito.id) is True,
        evidencia_aceita=_aceita(qualidade, politica),
        eliminatorio=not requisito.desenvolvivel,
        desenvolvivel=requisito.desenvolvivel,
    )


def _trechos(citadas: Iterable[tuple[Evidencia, TipoEvidencia]]) -> list[TrechoCitado]:
    return [
        TrechoCitado(trecho=e.trecho, fonte=e.fonte)
        for e, tipo in citadas
        if tipo != TipoEvidencia.INFERIDA and _trecho_mostravel(e)
    ]


def _peso_valido(competencia: Competencia) -> bool:
    return math.isfinite(competencia.peso) and competencia.peso >= 0


def _nota_valida(nota: float | None) -> float | None:
    return nota if nota is not None and math.isfinite(nota) and 0 <= nota <= 1 else None


def _considerada(nota: float | None, qualidade: QualidadeDado) -> float:
    return 0.0 if nota is None else round(nota * FATOR_QUALIDADE[qualidade], 6)


def _nota_competencia(
    competencia: Competencia,
    analise: Analise,
    evidencias: Sequence[tuple[Evidencia, TipoEvidencia]],
) -> NotaCriterio:
    citadas = [(e, tipo) for e, tipo in evidencias if e.criterio == competencia.nome]
    qualidade = _qualidade(tipo for _, tipo in citadas)
    nota = _nota_valida(analise.notas.get(competencia.nome))
    return NotaCriterio(
        criterio=competencia.nome,
        tipo=TipoCriterio.COMPETENCIA,
        descricao=competencia.nome,
        peso=competencia.peso if _peso_valido(competencia) else 0,
        qualidade=qualidade,
        nota=nota,
        nota_considerada=_considerada(nota, qualidade),
        nivel=None if nota is None else nivel_da_nota(nota),
        trechos=_trechos(citadas),
    )


def _sinais_dos_criterios(criterios: Iterable[NotaCriterio], total: float) -> list[SinalNota]:
    sinais = []
    for criterio in criterios:
        if criterio.tipo != TipoCriterio.COMPETENCIA or criterio.peso == 0:
            continue
        if criterio.nota is None:
            sinais.append(SinalNota(codigo="nota_ausente", criterio=criterio.criterio, reducao=0))
            continue
        perda = criterio.nota - (criterio.nota_considerada or 0)
        if perda > 0:
            codigo = (
                "trecho_inexistente_em_competencia"
                if criterio.qualidade == QualidadeDado.INFERIDO
                else "nota_sem_evidencia"
            )
            sinais.append(
                SinalNota(
                    codigo=codigo,
                    criterio=criterio.criterio,
                    reducao=round(perda * criterio.peso / total, 6),
                )
            )
    return sinais


def _faixa(nota: float | None, politica: Politica) -> FaixaScore | None:
    if nota is None:
        return None
    limiar = politica.limiar_verde
    alta = max(FAIXA_ALTA_SEM_LIMIAR, politica.piso_nota) if limiar is None else limiar
    if nota >= alta:
        return FaixaScore.ALTA
    return FaixaScore.BAIXA if nota < politica.piso_nota else FaixaScore.MEDIA


def _selo(politica: Politica, limiar_certificado: float | None) -> SeloCalibracao:
    certificado = limiar_certificado is not None and limiar_certificado == politica.limiar_verde
    return SeloCalibracao.CERTIFICADO if certificado else SeloCalibracao.NAO_CALIBRADO


def _montar_score(
    criterios: Sequence[NotaCriterio],
    externos: Sequence[SinalNota],
    politica: Politica,
    limiar_certificado: float | None,
    pesos_validos: bool,
) -> ScoreRecrutador:
    competencias = [c for c in criterios if c.tipo == TipoCriterio.COMPETENCIA]
    total = sum(c.peso for c in competencias)
    nota = None
    sinais = list(externos)
    if pesos_validos and total > 0:
        base = sum(c.peso * (c.nota_considerada or 0) for c in competencias) / total
        sinais = [*_sinais_dos_criterios(criterios, total), *externos]
        nota = round(max(0.0, base - sum(s.reducao for s in externos)), 6)
    return ScoreRecrutador(
        criterios=list(criterios),
        nota_geral=nota,
        faixa=_faixa(nota, politica),
        sinais=sinais,
        selo=_selo(politica, limiar_certificado),
        qualidade={q: sum(c.qualidade == q for c in criterios) for q in QualidadeDado},
    )


def _alerta_de_instrucao(alerta: str) -> bool:
    return "instrucao" in separar_palavras(alerta) or parece_instrucao(alerta)


def _criterio_da_ressalva(ressalva: str) -> str | None:
    prefixo, separador, resto = ressalva.partition(":")
    if not separador:
        return None
    return resto.strip() if prefixo.strip() == RESSALVA_NOTA_SEM_EVIDENCIA else prefixo.strip()


def _sinais_e_portoes_externos(vaga: Vaga, analise: Analise) -> tuple[list[SinalNota], list[str]]:
    """Separa o que só reduz a nota do que para a decisão. Ressalva que não se entende é grave."""
    competencias = {c.nome for c in vaga.competencias}
    sinais: list[SinalNota] = []
    portoes: list[str] = []
    for ressalva in analise.ressalvas_revisor:
        criterio = _criterio_da_ressalva(ressalva)
        if criterio in competencias:
            sinais.append(
                SinalNota(codigo=SINAL_RESSALVA, criterio=criterio, reducao=REDUCAO_SINAL_EXTERNO)
            )
        else:
            requisitos = {r.id for r in vaga.requisitos}
            portoes.append(f"ressalva_grave:{criterio if criterio in requisitos else 'revisor'}")
    for alerta in analise.alertas:
        if _alerta_de_instrucao(alerta):
            portoes.append(PORTAO_INSTRUCAO)
        else:
            sinais.append(SinalNota(codigo=SINAL_ALERTA, reducao=REDUCAO_SINAL_EXTERNO))
    return sinais, sorted(set(portoes))


def _lacuna_de_requisito(criterio: NotaCriterio) -> MotivoLacuna | None:
    if criterio.status_requisito == StatusRequisito.NAO_ATENDE:
        return MotivoLacuna.NAO_ATENDE
    if criterio.status_requisito == StatusRequisito.SEM_DADO:
        return MotivoLacuna.SEM_DADO
    if not criterio.evidencia_aceita:
        return MotivoLacuna.SEM_EVIDENCIA_ACEITA
    return None if criterio.confirmado_na_analise else MotivoLacuna.NAO_CONFIRMADO


def _lacuna_de(criterio: NotaCriterio) -> LacunaCriterio | None:
    if criterio.tipo == TipoCriterio.REQUISITO:
        motivo = _lacuna_de_requisito(criterio)
    elif criterio.peso > 0 and criterio.qualidade in (
        QualidadeDado.SEM_DADO,
        QualidadeDado.INFERIDO,
    ):
        motivo = MotivoLacuna.SEM_EVIDENCIA
    else:
        motivo = None
    if motivo is None or not criterio.descricao.strip():
        return None
    return LacunaCriterio(
        criterio=criterio.criterio,
        tipo=criterio.tipo,
        descricao=criterio.descricao,
        motivo=motivo,
        peso=criterio.peso,
        eliminatorio=criterio.eliminatorio,
        desenvolvivel=criterio.desenvolvivel,
    )


@dataclass(frozen=True)
class _Pecas:
    vaga: Vaga
    candidato: Candidato
    mandato: Mandato
    criterios: tuple[NotaCriterio, ...]
    integridade: tuple[str, ...]
    externos: tuple[SinalNota, ...]
    evidencias: tuple[Evidencia, ...]
    indisponibilidade: FatoIndisponibilidade | None
    limiar_certificado: float | None
    hoje: date
    agora: datetime
    rastro_id: str
    origem: OrigemDecisao
    reavaliados: tuple[str, ...]


@dataclass(frozen=True)
class _Resolucao:
    destino: DestinoDecisao
    regra: str
    motivo: str
    portoes: tuple[str, ...] = ()
    pendente: bool = False


def _revisao(regra: str, motivo: str, portoes: Sequence[str] = ()) -> _Resolucao:
    return _Resolucao(DestinoDecisao.REVISAO_HUMANA, regra, motivo, tuple(portoes))


def _resolver_autorizacao(pecas: _Pecas) -> _Resolucao | None:
    if autorizacao_ativa(pecas.candidato, pecas.hoje):
        return None
    corte = corte_de_autorizacao(pecas.candidato, pecas.hoje)
    if corte is not None and corte.regra == REGRA_PERFIL_DESATUALIZADO:
        return _revisao(REGRA_PERFIL_DESATUALIZADO, corte.motivo)
    motivo = "sem autorização válida" if corte is None else corte.motivo
    return _Resolucao(DestinoDecisao.RECUSAR, REGRA_RECUSA_AUTORIZACAO, motivo)


def _resolver_requisito_reprovado(criterios: Sequence[NotaCriterio]) -> _Resolucao | None:
    """Falha comprovada elimina. Requisito desenvolvível não: a empresa aceita que se aprenda."""
    reprovados = sorted(
        c.criterio
        for c in criterios
        if c.status_requisito == StatusRequisito.NAO_ATENDE and not c.desenvolvivel
    )
    if not reprovados:
        return None
    motivo = f"requisito não atendido: {', '.join(reprovados)}"
    return _Resolucao(DestinoDecisao.RECUSAR, f"{PREFIXO_RECUSA_REQUISITO}{reprovados[0]}", motivo)


def _competencias_com_evidencia(criterios: Iterable[NotaCriterio]) -> bool:
    return all(
        c.qualidade in (QualidadeDado.COMPROVADO, QualidadeDado.DECLARADO)
        for c in criterios
        if c.tipo == TipoCriterio.COMPETENCIA and c.peso > 0
    )


def _resolver_lacunas_de_requisito(
    pecas: _Pecas, score: ScoreRecrutador, lacunas: Sequence[LacunaCriterio]
) -> _Resolucao | None:
    """A falta de evidência em requisito para a aprovação. A lapidar só com todos os fatos."""
    faltando = [lacuna for lacuna in lacunas if lacuna.tipo == TipoCriterio.REQUISITO]
    if not faltando:
        return None
    portoes = [f"requisito_{lacuna.motivo}:{lacuna.criterio}" for lacuna in faltando]
    if (
        all(lacuna.desenvolvivel for lacuna in faltando)
        and score.faixa == FaixaScore.ALTA
        and _competencias_com_evidencia(score.criterios)
    ):
        politica = pecas.mandato.politica
        return _Resolucao(
            DestinoDecisao.GARDEN_A_LAPIDAR,
            REGRA_A_LAPIDAR,
            f"nota alta com lacunas desenvolvíveis: {', '.join(lc.criterio for lc in faltando)}",
            pendente=politica.lapidar_exige_confirmacao,
        )
    return _revisao(REGRA_PORTAO, ", ".join(portoes), portoes)


def _resolver_nota(pecas: _Pecas, score: ScoreRecrutador) -> _Resolucao:
    politica = pecas.mandato.politica
    nota = score.nota_geral
    if politica.limiar_verde is None:
        return _revisao("limiar_nao_definido", "o mandato não define limiar de aprovação")
    if nota >= politica.limiar_verde:
        return _Resolucao(
            DestinoDecisao.APROVAR, REGRA_APROVACAO, "dentro dos critérios do mandato"
        )
    if nota < politica.piso_nota:
        return _revisao(REGRA_NOTA_BAIXA, "nota baixa: sem prioridade, nunca exclui em definitivo")
    return _revisao("faixa_media", "nota entre o piso e o limiar do mandato")


def _resolver(
    pecas: _Pecas, score: ScoreRecrutador, lacunas: Sequence[LacunaCriterio]
) -> _Resolucao:
    objetiva = _resolver_autorizacao(pecas) or _resolver_requisito_reprovado(pecas.criterios)
    if objetiva is not None:
        return objetiva
    if pecas.integridade:
        return _revisao(REGRA_PORTAO, ", ".join(pecas.integridade), pecas.integridade)
    if score.nota_geral is None:
        return _revisao("notas_incompletas", "sem competência com peso válido para calcular a nota")
    if pecas.indisponibilidade is not None:
        if score.faixa in (FaixaScore.ALTA, FaixaScore.MEDIA):
            return _Resolucao(
                DestinoDecisao.GARDEN_INDISPONIVEL,
                REGRA_INDISPONIVEL,
                "a própria pessoa disse que não pode agora",
            )
        return _revisao("indisponivel_com_nota_baixa", "indisponível, com nota baixa")
    return _resolver_lacunas_de_requisito(pecas, score, lacunas) or _resolver_nota(pecas, score)


def _entrada(pecas: _Pecas, score: ScoreRecrutador, resolucao: _Resolucao) -> dict[str, str]:
    """O que sustentou a decisão, sem nome, atributos nem texto do candidato."""
    politica = pecas.mandato.politica
    return {
        "vaga_id": pecas.vaga.id,
        "candidato_id": pecas.candidato.id,
        "hoje": pecas.hoje.isoformat(),
        "mandato_id": pecas.mandato.id,
        "mandato_versao": str(pecas.mandato.versao),
        "hash_vaga": pecas.mandato.hash_vaga,
        "limiar_verde": "nao_calibrado"
        if politica.limiar_verde is None
        else str(politica.limiar_verde),
        "piso_nota": str(politica.piso_nota),
        "aceitar_declarada": str(politica.aceitar_declarada).lower(),
        "lapidar_exige_confirmacao": str(politica.lapidar_exige_confirmacao).lower(),
        "nota_geral": "indefinida" if score.nota_geral is None else str(score.nota_geral),
        "faixa": "indefinida" if score.faixa is None else score.faixa.value,
        "selo": score.selo.value,
        "qualidade": json.dumps({q.value: n for q, n in score.qualidade.items()}, sort_keys=True),
        "portoes": json.dumps(list(resolucao.portoes)),
        "integridade": json.dumps(list(pecas.integridade)),
    }


def _evidencias_com_regra(
    pecas: _Pecas, lacunas: Sequence[LacunaCriterio], resolucao: _Resolucao
) -> list[Evidencia]:
    """Lacuna não tem trecho do perfil: fica registrado o critério que a regra usou."""
    evidencias = [
        *pecas.evidencias,
        *(evidencia_da_regra(lacuna.criterio, lacuna.descricao) for lacuna in lacunas),
    ]
    return evidencias or [evidencia_da_regra(resolucao.regra, resolucao.motivo)]


def _concluir(pecas: _Pecas) -> DecisaoFinal:
    score = _montar_score(
        pecas.criterios,
        pecas.externos,
        pecas.mandato.politica,
        pecas.limiar_certificado,
        PORTAO_PESOS not in pecas.integridade,
    )
    lacunas = [lacuna for c in pecas.criterios if (lacuna := _lacuna_de(c)) is not None]
    resolucao = _resolver(pecas, score, lacunas)
    alertas = [p for p in pecas.integridade if p == PORTAO_INSTRUCAO]
    return DecisaoFinal(
        empresa_id=pecas.vaga.empresa_id,
        vaga_id=pecas.vaga.id,
        candidato_id=pecas.candidato.id,
        destino=resolucao.destino,
        regra=resolucao.regra,
        motivo=resolucao.motivo,
        responsavel=responsavel_do_mandato(pecas.mandato),
        rastro_id=pecas.rastro_id,
        score=score,
        entrada=_entrada(pecas, score, resolucao),
        evidencias=_evidencias_com_regra(pecas, lacunas, resolucao),
        simulado=pecas.candidato.simulado,
        momento=pecas.agora,
        origem=pecas.origem,
        portoes=list(resolucao.portoes),
        lacunas=lacunas,
        indisponibilidade=(
            pecas.indisponibilidade
            if resolucao.destino == DestinoDecisao.GARDEN_INDISPONIVEL
            else None
        ),
        pendente_confirmacao=resolucao.pendente,
        reavaliados=list(pecas.reavaliados),
        alertas=alertas,
    )


@rastreado(ETAPA_DECISAO_FINAL)
def classificar_destino(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    mandato: Mandato,
    hoje: date,
    agora: datetime,
    rastro_id: str,
    *,
    indisponibilidade: FatoIndisponibilidade | None = None,
    limiar_certificado: float | None = None,
) -> DecisaoFinal:
    """Decide o destino da pessoa a partir da análise conferida. Só código.

    Levanta `ValueError` se as peças são de empresas, vagas ou pessoas diferentes, e
    `MandatoInvalido` se o mandato não vale ou a vaga usa critério sensível.
    """
    _exigir_mesma_execucao(vaga, candidato, mandato)
    if analise.empresa_id != vaga.empresa_id or analise.vaga_id != vaga.id:
        raise ValueError("análise precisa ser da empresa e da vaga")
    if analise.candidato_id != candidato.id:
        raise ValueError("análise precisa ser do mesmo candidato")
    _exigir_mandato_valido(vaga, mandato, agora)

    politica = mandato.politica
    status = avaliar_requisitos(vaga, candidato)
    classificadas = [(e, classificar_evidencia(e, candidato)) for e in analise.evidencias]
    criterios = (
        *(
            _nota_requisito(r, status[r.id], analise, classificadas, politica)
            for r in vaga.requisitos
        ),
        *(_nota_competencia(c, analise, classificadas) for c in vaga.competencias),
    )
    externos, integridade = _sinais_e_portoes_externos(vaga, analise)
    for requisito in sorted(vaga.requisitos, key=lambda r: r.id):
        if any(
            e.criterio == requisito.id and tipo == TipoEvidencia.INFERIDA
            for e, tipo in classificadas
        ):
            integridade.append(f"{PORTAO_TRECHO_INEXISTENTE}:{requisito.id}")
    if not all(_peso_valido(c) for c in vaga.competencias):
        integridade.append(PORTAO_PESOS)
    return _concluir(
        _Pecas(
            vaga=vaga,
            candidato=candidato,
            mandato=mandato,
            criterios=criterios,
            integridade=tuple(integridade),
            externos=tuple(externos),
            evidencias=tuple(
                e
                for e, tipo in classificadas
                if tipo != TipoEvidencia.INFERIDA and _trecho_mostravel(e)
            ),
            indisponibilidade=indisponibilidade,
            limiar_certificado=limiar_certificado,
            hoje=hoje,
            agora=agora,
            rastro_id=rastro_id,
            origem=OrigemDecisao.ANALISE,
            reavaliados=(),
        )
    )


def _reavaliar_requisito(
    anterior: NotaCriterio,
    resposta: RespostaCriterio,
    status: StatusRequisito,
    politica: Politica,
) -> NotaCriterio:
    qualidade = (
        QualidadeDado.COMPROVADO
        if anterior.qualidade == QualidadeDado.COMPROVADO
        else QualidadeDado.DECLARADO
    )
    trechos = [*anterior.trechos, TrechoCitado(trecho=resposta.trecho, fonte=resposta.fonte)]
    return anterior.model_copy(
        update={
            "qualidade": qualidade,
            "trechos": trechos,
            "status_requisito": status.value,
            "confirmado_na_analise": (
                anterior.confirmado_na_analise or status == StatusRequisito.ATENDE
            ),
            "evidencia_aceita": _aceita(qualidade, politica),
        }
    )


def _reavaliar_competencia(anterior: NotaCriterio, resposta: RespostaCriterio) -> NotaCriterio:
    nota = anterior.nota if resposta.nivel is None else NOTA_DO_NIVEL[resposta.nivel]
    nota = NOTA_DO_NIVEL[NivelCriterio.GENERICA] if nota is None else nota
    qualidade = (
        QualidadeDado.COMPROVADO
        if anterior.qualidade == QualidadeDado.COMPROVADO
        else QualidadeDado.DECLARADO
    )
    return anterior.model_copy(
        update={
            "qualidade": qualidade,
            "nota": nota,
            "nota_considerada": _considerada(nota, qualidade),
            "nivel": nivel_da_nota(nota),
            "trechos": [
                *anterior.trechos,
                TrechoCitado(trecho=resposta.trecho, fonte=resposta.fonte),
            ],
        }
    )


@rastreado(ETAPA_DECISAO_FINAL)
def reavaliar_criterios(
    anterior: DecisaoFinal,
    vaga: Vaga,
    candidato: Candidato,
    mandato: Mandato,
    respostas: Sequence[RespostaCriterio],
    hoje: date,
    agora: datetime,
    rastro_id: str,
    *,
    indisponibilidade: FatoIndisponibilidade | None = None,
    limiar_certificado: float | None = None,
    portoes_extras: Sequence[str] = (),
) -> DecisaoFinal:
    """Refaz a decisão mudando só os critérios respondidos. Os demais ficam como estavam.

    Instrução detectada e ressalva grave continuam valendo. Trecho inexistente em requisito cai
    se a própria pessoa respondeu aquele requisito, porque agora há um trecho de verdade.
    """
    _exigir_mesma_execucao(vaga, candidato, mandato)
    if (anterior.empresa_id, anterior.vaga_id, anterior.candidato_id) != (
        vaga.empresa_id,
        vaga.id,
        candidato.id,
    ):
        raise ValueError("a decisão anterior é de outra empresa, vaga ou pessoa")
    _exigir_mandato_valido(vaga, mandato, agora)

    por_criterio = {r.criterio: r for r in respostas}
    conhecidos = {c.criterio for c in anterior.score.criterios}
    if not set(por_criterio) <= conhecidos:
        raise ValueError("resposta sobre critério que a decisão não tem")

    status = avaliar_requisitos(vaga, candidato)
    criterios = []
    for criterio in anterior.score.criterios:
        resposta = por_criterio.get(criterio.criterio)
        if resposta is None:
            criterios.append(criterio)
        elif criterio.tipo == TipoCriterio.REQUISITO:
            situacao = status[criterio.criterio]
            criterios.append(_reavaliar_requisito(criterio, resposta, situacao, mandato.politica))
        else:
            criterios.append(_reavaliar_competencia(criterio, resposta))

    resolvidos = {f"{PORTAO_TRECHO_INEXISTENTE}:{c}" for c in por_criterio}
    integridade = [p for p in _portoes_de_integridade_anteriores(anterior) if p not in resolvidos]
    novas = [Evidencia(criterio=r.criterio, trecho=r.trecho, fonte=r.fonte) for r in respostas]
    return _concluir(
        _Pecas(
            vaga=vaga,
            candidato=candidato,
            mandato=mandato,
            criterios=tuple(criterios),
            integridade=tuple(sorted({*integridade, *portoes_extras})),
            externos=tuple(s for s in anterior.score.sinais if s.codigo in SINAIS_EXTERNOS),
            evidencias=(*_evidencias_do_perfil(anterior), *novas),
            indisponibilidade=indisponibilidade,
            limiar_certificado=limiar_certificado,
            hoje=hoje,
            agora=agora,
            rastro_id=rastro_id,
            origem=OrigemDecisao.PRE_TRIAGEM,
            reavaliados=tuple(sorted(por_criterio)),
        )
    )


def _portoes_de_integridade_anteriores(anterior: DecisaoFinal) -> list[str]:
    """Os portões guardados na entrada valem mesmo quando a decisão saiu por outra regra."""
    return json.loads(anterior.entrada.get("integridade", "[]"))


def _evidencias_do_perfil(anterior: DecisaoFinal) -> list[Evidencia]:
    return [e for e in anterior.evidencias if e.fonte != FONTE_REGRA]


def _revalidada(decisao: DecisaoFinal, **campos: object) -> DecisaoFinal:
    """`model_copy` não valida: a cópia passa de novo pelas invariantes do destino."""
    return DecisaoFinal.model_validate({**decisao.model_dump(), **campos})


def _exigir_pessoa(responsavel: str) -> None:
    identificacao = responsavel.removeprefix(PREFIXO_HUMANO)
    if not responsavel.startswith(PREFIXO_HUMANO) or not identificacao.strip():
        raise ValueError(f"só uma pessoa identificada como `{PREFIXO_HUMANO}...` decide isto")


def confirmar_lapidar(
    decisao: DecisaoFinal, responsavel: str, aceita: bool, agora: datetime
) -> DecisaoFinal:
    """O RH confirma ou nega a proposta. Negar leva a uma pessoa, não recusa ninguém."""
    _exigir_pessoa(responsavel)
    if decisao.destino != DestinoDecisao.GARDEN_A_LAPIDAR or not decisao.pendente_confirmacao:
        raise ValueError("só proposta de garden a lapidar pendente pode ser confirmada")
    campos: dict[str, object] = {
        "responsavel": responsavel,
        "momento": agora,
        "origem": OrigemDecisao.CONFIRMACAO_HUMANA,
        "pendente_confirmacao": False,
    }
    if not aceita:
        campos |= {
            "destino": DestinoDecisao.REVISAO_HUMANA,
            "regra": REGRA_A_LAPIDAR_NAO_CONFIRMADO,
            "motivo": "o RH não confirmou o garden a lapidar",
        }
    return _revalidada(decisao, **campos)


def como_decisao(final: DecisaoFinal) -> Decisao:
    """Leva ao registro de decisões, em que `entrada` guarda a decisão final inteira.

    O tipo antigo não tem garden: fica como pedir uma pessoa, e a regra diz o destino.
    """
    return Decisao(
        empresa_id=final.empresa_id,
        vaga_id=final.vaga_id,
        candidato_id=final.candidato_id,
        tipo=_TIPO_ANTIGO.get(final.destino, TipoDecisao.PEDIR_HUMANO),
        regra=final.regra,
        motivo=final.motivo,
        responsavel=final.responsavel,
        rastro_id=final.rastro_id,
        entrada={
            **final.entrada,
            "destino": final.destino.value,
            "decisao_final": final.model_dump_json(),
        },
        evidencias=final.evidencias,
        momento=final.momento,
    )


def decisao_final_do_registro(decisao: Decisao) -> DecisaoFinal | None:
    """`None` para decisão antiga, sem destino. Registro corrompido também não vira decisão."""
    registro = decisao.entrada.get("decisao_final")
    if registro is None:
        return None
    try:
        return DecisaoFinal.model_validate_json(registro)
    except ValidationError:
        logger.warning("registro de decisão final inválido: %s", decisao.regra)
        return None


def propor_garden(decisao: DecisaoFinal, hoje: date, prazo_dias: int) -> EntradaGarden:
    """Abre a entrada, que só vale depois da autorização da pessoa."""
    if decisao.destino not in (
        DestinoDecisao.GARDEN_INDISPONIVEL,
        DestinoDecisao.GARDEN_A_LAPIDAR,
    ):
        raise ValueError("só decisão de garden abre entrada no garden")
    if decisao.pendente_confirmacao:
        raise ValueError("garden a lapidar espera a confirmação do RH")
    fato = decisao.indisponibilidade
    voltar_em = None if fato is None else fato.voltar_em
    return EntradaGarden(
        empresa_id=decisao.empresa_id,
        vaga_id=decisao.vaga_id,
        candidato_id=decisao.candidato_id,
        destino=decisao.destino,
        regra=decisao.regra,
        estado=EstadoGarden.AGUARDANDO_AUTORIZACAO,
        revisar_em=voltar_em or hoje + timedelta(days=prazo_dias),
        voltar_em=voltar_em,
        motivo_retorno=None if fato is None else fato.motivo,
        lacunas=[lacuna for lacuna in decisao.lacunas if lacuna.tipo == TipoCriterio.REQUISITO],
    )


def _pessoa_saiu(candidato: Candidato) -> bool:
    return candidato.opt_out or candidato.estado == EstadoBanco.REMOVIDO


def autorizar_garden(
    entrada: EntradaGarden,
    candidato: Candidato,
    hoje: date,
    autorizada_ate: date,
    prazo_dias: int,
) -> EntradaGarden:
    """Registra a autorização. O prazo vai até o que a pessoa deu, limitado pela política."""
    if (entrada.empresa_id, entrada.candidato_id) != (candidato.empresa_id, candidato.id):
        raise ValueError("a entrada é de outra empresa ou pessoa")
    if entrada.estado != EstadoGarden.AGUARDANDO_AUTORIZACAO:
        raise ValueError("a entrada não espera autorização")
    if _pessoa_saiu(candidato):
        raise ValueError("quem pediu para sair não entra no garden")
    if autorizada_ate < hoje:
        raise ValueError("autorização já vencida")
    return EntradaGarden.model_validate(
        {
            **entrada.model_dump(),
            "estado": EstadoGarden.ATIVA,
            "autorizada_em": hoje,
            "valida_ate": min(autorizada_ate, hoje + timedelta(days=prazo_dias)),
        }
    )


def _encerrada(entrada: EntradaGarden, motivo: str) -> EntradaGarden:
    return EntradaGarden.model_validate(
        {**entrada.model_dump(), "estado": EstadoGarden.ENCERRADA, "motivo_encerramento": motivo}
    )


def situacao_do_garden(entrada: EntradaGarden, candidato: Candidato, hoje: date) -> EntradaGarden:
    """Estado atual da entrada. Opt-out e remoção tiram a pessoa sempre, com ou sem revisão."""
    if entrada.estado == EstadoGarden.ENCERRADA:
        return entrada
    if _pessoa_saiu(candidato):
        return _encerrada(entrada, "opt_out" if candidato.opt_out else "removido")
    if entrada.estado == EstadoGarden.AGUARDANDO_AUTORIZACAO:
        return entrada
    if entrada.valida_ate is not None and entrada.valida_ate < hoje:
        return _encerrada(entrada, "autorizacao_vencida")
    estado = EstadoGarden.PARA_REVISAO if entrada.revisar_em <= hoje else EstadoGarden.ATIVA
    return entrada.model_copy(update={"estado": estado})


def rever_garden(entrada: EntradaGarden, responsavel: str, revisar_em: date) -> EntradaGarden:
    """Uma pessoa revê a entrada e marca a próxima revisão, dentro da autorização que existe."""
    _exigir_pessoa(responsavel)
    if entrada.estado not in (EstadoGarden.ATIVA, EstadoGarden.PARA_REVISAO):
        raise ValueError("só entrada ativa pode ser revista")
    return entrada.model_copy(update={"estado": EstadoGarden.ATIVA, "revisar_em": revisar_em})


def encerrar_garden(entrada: EntradaGarden, responsavel: str, motivo: str) -> EntradaGarden:
    _exigir_pessoa(responsavel)
    if termos_proibidos_em_conversa(motivo):
        raise ValueError("motivo de encerramento não cita dado sensível")
    return _encerrada(entrada, motivo)


def _criterio_contradito(criterio: NotaCriterio) -> bool:
    if criterio.status_requisito == StatusRequisito.ATENDE:
        return not criterio.confirmado_na_analise
    return criterio.status_requisito == StatusRequisito.NAO_ATENDE and (
        criterio.confirmado_na_analise
    )


def _ponto(
    tipo: TipoPonto,
    criterio: str,
    descricao: str,
    trecho: str,
    fonte: str,
    *,
    verificado: bool = False,
    inferencia: bool = False,
) -> PontoExplorar | None:
    """O contrato recusa dado sensível e julgamento: o ponto some, sem mudar a decisão."""
    try:
        return PontoExplorar(
            tipo=tipo,
            criterio=criterio,
            descricao=descricao,
            trecho=trecho,
            fonte=fonte,
            verificado=verificado,
            inferencia=inferencia,
        )
    except ValidationError:
        logger.info("ponto a explorar recusado pelo contrato: %s", tipo)
        return None


def _pontos_do_criterio(criterio: NotaCriterio) -> list[PontoExplorar | None]:
    if not criterio.trechos:
        return []
    citado = criterio.trechos[0]
    comprovado = criterio.qualidade == QualidadeDado.COMPROVADO
    if criterio.tipo == TipoCriterio.REQUISITO:
        if not _criterio_contradito(criterio):
            return []
        return [
            _ponto(
                TipoPonto.CONTRADICAO,
                criterio.criterio,
                f"Registro e análise divergem sobre: {criterio.descricao}",
                citado.trecho,
                citado.fonte,
                verificado=comprovado,
            )
        ]
    if criterio.nivel == NivelCriterio.GENERICA:
        return [
            _ponto(
                TipoPonto.AFIRMACAO_SEM_EXEMPLO,
                criterio.criterio,
                f"Afirmação sem exemplo sobre: {criterio.descricao}",
                citado.trecho,
                citado.fonte,
                verificado=comprovado,
            )
        ]
    if criterio.nivel == NivelCriterio.PARCIAL:
        return [
            _ponto(
                TipoPonto.EXPERIENCIA_PARECIDA,
                criterio.criterio,
                f"Inferência: experiência parecida com {criterio.descricao}",
                citado.trecho,
                citado.fonte,
                inferencia=True,
            )
        ]
    return []


def pontos_a_explorar(decisao: DecisaoFinal, vaga: Vaga) -> list[PontoExplorar]:
    """O que o recrutador e a entrevista podem aprofundar, a partir do registro da decisão."""
    if (decisao.empresa_id, decisao.vaga_id) != (vaga.empresa_id, vaga.id):
        raise ValueError("a decisão é de outra empresa ou vaga")
    pontos: list[PontoExplorar | None] = [
        _ponto(
            TipoPonto.LACUNA,
            lacuna.criterio,
            f"Falta confirmar: {lacuna.descricao}",
            lacuna.descricao,
            f"{FONTE_VAGA}:{vaga.id}",
        )
        for lacuna in decisao.lacunas
    ]
    for criterio in decisao.score.criterios:
        pontos += _pontos_do_criterio(criterio)
    return [ponto for ponto in pontos if ponto is not None]


def _ultima_por_pessoa(decisoes: Iterable[DecisaoFinal]) -> dict[str, DecisaoFinal]:
    ultimas: dict[str, DecisaoFinal] = {}
    for decisao in decisoes:
        atual = ultimas.get(decisao.candidato_id)
        if atual is None or decisao.momento >= atual.momento:
            ultimas[decisao.candidato_id] = decisao
    return ultimas


def insights_da_vaga(
    vaga: Vaga,
    decisoes: Iterable[DecisaoFinal],
    minimo_pessoas: int = MINIMO_PESSOAS_INSIGHT,
) -> InsightsDaVaga:
    """Critérios em que a maioria para. Só contagens: nenhum identificador ou texto de pessoa."""
    lista = list(decisoes)
    if any((d.empresa_id, d.vaga_id) != (vaga.empresa_id, vaga.id) for d in lista):
        raise ValueError("insight só usa decisões da própria vaga")
    ultimas = list(_ultima_por_pessoa(lista).values())
    total = len(ultimas)
    if total < minimo_pessoas:
        return InsightsDaVaga(
            empresa_id=vaga.empresa_id, vaga_id=vaga.id, total=total, suprimido=True, insights=[]
        )
    contagem: dict[str, int] = {}
    descricoes: dict[str, str] = {}
    for decisao in ultimas:
        for lacuna in decisao.lacunas:
            contagem[lacuna.criterio] = contagem.get(lacuna.criterio, 0) + 1
            descricoes[lacuna.criterio] = lacuna.descricao
    insights = [
        InsightVaga(
            criterio=criterio,
            descricao=f"A maioria para neste critério: {pessoas} de {total} pessoas",
            trecho=descricoes[criterio],
            fonte=f"{FONTE_VAGA}:{vaga.id}",
            pessoas=pessoas,
            total=total,
        )
        for criterio, pessoas in sorted(contagem.items(), key=lambda item: (-item[1], item[0]))
        if pessoas * 2 > total
        and pessoas >= minimo_pessoas
        and not termos_proibidos_em_conversa(descricoes[criterio])
    ]
    return InsightsDaVaga(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        total=total,
        suprimido=False,
        insights=insights,
    )
