"""Pacote de contexto entregue ao agente recrutador (T3.3).

O pacote só é montado para quem foi indicado e autorizou contato. Leva apenas
evidências com trecho e nunca critério sensível. Quem entrega, e só depois do
aceite, é o fluxo.
"""

import unicodedata

from backend.contratos.modelos import (
    Analise,
    Candidato,
    Decisao,
    Evidencia,
    PacoteContexto,
    TipoDecisao,
    Vaga,
)

# Barreira de defesa: a T1.1 já recusa critérios sensíveis na vaga.
CRITERIOS_SENSIVEIS = frozenset(
    {
        "genero",
        "sexo",
        "idade",
        "data_de_nascimento",
        "raca",
        "cor",
        "etnia",
        "religiao",
        "estado_civil",
        "orientacao_sexual",
        "deficiencia",
        "gravidez",
    }
)


def _normalizar(criterio: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", criterio).encode("ascii", "ignore").decode()
    return "_".join(sem_acento.lower().split())


def chave_entrega(empresa_id: str, vaga_id: str, candidato_id: str) -> str:
    return f"{empresa_id}:{vaga_id}:{candidato_id}:entrega"


def _conferir(vaga: Vaga, candidato: Candidato, analise: Analise, decisao: Decisao) -> None:
    for item in (candidato, analise, decisao):
        if item.empresa_id != vaga.empresa_id:
            raise ValueError("vaga, candidato, análise e decisão precisam ser da mesma empresa")
    for item in (analise, decisao):
        if item.vaga_id != vaga.id or item.candidato_id != candidato.id:
            raise ValueError("análise e decisão precisam ser desta vaga e deste candidato")
    if decisao.tipo != TipoDecisao.INDICAR:
        raise ValueError("só candidato indicado recebe pacote")
    if (
        not candidato.autorizou_contato
        or candidato.opt_out
        or candidato.autorizacao_valida_ate is None
    ):
        raise ValueError("candidato sem autorização válida não recebe pacote")


def _evidencias_validas(analise: Analise, decisao: Decisao) -> list[Evidencia]:
    """Evidências com trecho e critério permitido, sem repetir e na ordem original."""
    validas: list[Evidencia] = []
    for evidencia in [*analise.evidencias, *decisao.evidencias]:
        if not evidencia.trecho.strip():
            continue
        if _normalizar(evidencia.criterio) in CRITERIOS_SENSIVEIS:
            continue
        if evidencia not in validas:
            validas.append(evidencia)
    return validas


def _motivos(evidencias: list[Evidencia]) -> dict[str, str]:
    trechos: dict[str, list[str]] = {}
    for evidencia in evidencias:
        lista = trechos.setdefault(evidencia.criterio, [])
        if evidencia.trecho not in lista:
            lista.append(evidencia.trecho)
    return {criterio: "; ".join(lista) for criterio, lista in trechos.items()}


def montar_pacote(
    vaga: Vaga, candidato: Candidato, analise: Analise, decisao: Decisao
) -> PacoteContexto:
    _conferir(vaga, candidato, analise, decisao)
    evidencias = _evidencias_validas(analise, decisao)
    validade = candidato.autorizacao_valida_ate.isoformat()
    return PacoteContexto(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        motivo_por_criterio=_motivos(evidencias),
        historico=candidato.historico,
        evidencias=evidencias,
        lacunas=analise.lacunas,
        pontos_a_aprofundar=analise.pontos_a_aprofundar,
        ressalvas_revisor=analise.ressalvas_revisor,
        autorizacao=f"contato autorizado, válido até {validade}",
        fonte=candidato.fonte,
        rastro_id=decisao.rastro_id,
        chave_idempotencia=chave_entrega(vaga.empresa_id, vaga.id, candidato.id),
        simulado=candidato.simulado,
    )
