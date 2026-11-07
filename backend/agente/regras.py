"""Regras determinísticas de critérios, requisitos, contato e decisão. Nenhuma usa modelo de IA."""

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from backend.agente.auditoria import responsavel_do_mandato
from backend.agente.mandato import Mandato, MandatoInvalido, mandato_valido
from backend.agente.neutralizacao import corresponde_ao_original
from backend.contratos.criterios import TERMOS_SENSIVEIS as TERMOS_SENSIVEIS
from backend.contratos.criterios import (
    campo_sensivel,
    frases_restritivas,
    sem_acento,
    termos_sensiveis,
)
from backend.contratos.criterios import contem_termo as contem_termo
from backend.contratos.criterios import separar_palavras as separar_palavras
from backend.contratos.modelos import (
    Analise,
    Candidato,
    Decisao,
    EstadoBanco,
    Evidencia,
    Requisito,
    TipoDecisao,
    Vaga,
)

FONTES_VERIFICAVEIS = frozenset({"github", "rede_simulada"})
"""Fontes externas à autodeclaração. Currículo e perfil enviado pela pessoa ficam de fora."""

FONTE_REGRA = "regra_deterministica"
"""Fonte da evidência criada por código, quando a decisão não tem trecho do perfil para citar."""


PREFIXO_REGRA_FUNIL = "funil:"
PREFIXO_RESPONSAVEL_AGENTE = "agente:"
CORTES_POR_AUTORIZACAO = frozenset(
    {"autorizacao_vencida", "estado_bloqueado", "opt_out", "sem_autorizacao"}
)
"""Quem sai por estes cortes não autorizou o uso do perfil nesta vaga."""

CORTES_QUE_DESCARTAM = CORTES_POR_AUTORIZACAO | {"duplicata", "requisito_nao_atendido"}
"""Fora do limite não descarta: a pessoa é elegível e só não coube nas análises da rodada.
Perfil desatualizado também não: a autorização vale, e uma pessoa confirma o perfil."""

REGRA_PERFIL_DESATUALIZADO = "perfil_desatualizado"


class CorteFunil(Protocol):
    """Saída do funil, sem dados do perfil. A frente de fontes define os valores de `regra`."""

    candidato_id: str
    fonte: str
    origem: str
    regra: str
    motivo: str


class StatusRequisito(StrEnum):
    ATENDE = "atende"
    NAO_ATENDE = "nao_atende"
    SEM_DADO = "sem_dado"


SEM_DADO = StatusRequisito.SEM_DADO


class TipoEvidencia(StrEnum):
    INFERIDA = "inferida"
    DECLARADA = "declarada"
    COMPROVADA = "comprovada"


def _problemas_do_requisito(requisito: Requisito) -> list[str]:
    termos = termos_sensiveis(requisito.descricao, requisito.campo, requisito.valor_esperado)
    if campo_sensivel(requisito.campo) and requisito.campo.strip():
        termos = sorted({*termos, *separar_palavras(requisito.campo)})
    if termos:
        return [f"requisito {requisito.id!r} usa dado sensível: {', '.join(termos)}"]
    if not requisito.valor_esperado.strip() or not requisito.campo.strip():
        return [f"requisito {requisito.id!r} sem atributo ou valor esperado: nunca eliminaria"]
    return []


def validar_requisitos_e_competencias(vaga: Vaga) -> list[str]:
    """Um problema por critério, em ordem estável. Critério não tem exceção para aviso."""
    problemas = [p for requisito in vaga.requisitos for p in _problemas_do_requisito(requisito)]
    for competencia in vaga.competencias:
        termos = termos_sensiveis(competencia.nome)
        if termos:
            problemas.append(
                f"competência {competencia.nome!r} usa dado sensível: {', '.join(termos)}"
            )
    return problemas


def requisitos_sem_valor(vaga: Vaga) -> list[str]:
    """Requisitos que nunca eliminariam ninguém, por não dizerem o atributo ou o valor."""
    return [
        requisito.id
        for requisito in vaga.requisitos
        if not requisito.valor_esperado.strip() or not requisito.campo.strip()
    ]


def validar_criterios(vaga: Vaga) -> list[str]:
    """Lista os problemas da vaga: critérios, título e descrição com dado sensível.

    Título e descrição são texto livre e costumam trazer aviso de não discriminação, que cita
    esses mesmos termos: só a frase que restringe quem concorre, como `apenas homens`, é problema.
    """
    problemas = validar_requisitos_e_competencias(vaga)
    if termos_sensiveis(vaga.titulo):
        problemas.append(f"título usa dado sensível: {', '.join(termos_sensiveis(vaga.titulo))}")
    for _, termos in frases_restritivas(vaga.descricao):
        problemas.append(f"descrição restringe por dado sensível: {', '.join(termos)}")
    return problemas


def _exigir_mesma_empresa(vaga: Vaga, candidato: Candidato) -> None:
    if vaga.empresa_id != candidato.empresa_id:
        raise ValueError("vaga e candidato pertencem a empresas diferentes")


def _normalizar_valor(texto: str) -> str:
    """Tira acento, caixa e espaços repetidos, mantendo símbolos: `C++` não é `C#`."""
    return " ".join(sem_acento(texto).casefold().split())


def _status_requisito(requisito: Requisito, candidato: Candidato) -> StatusRequisito:
    esperado = _normalizar_valor(requisito.valor_esperado)
    atual = _normalizar_valor(candidato.atributos.get(requisito.campo, ""))
    if not esperado or not atual:
        return StatusRequisito.SEM_DADO
    return StatusRequisito.ATENDE if atual == esperado else StatusRequisito.NAO_ATENDE


def avaliar_requisitos(vaga: Vaga, candidato: Candidato) -> dict[str, StatusRequisito]:
    """Compara cada requisito com o atributo do candidato. Dado ausente é SEM_DADO."""
    _exigir_mesma_empresa(vaga, candidato)
    return {r.id: _status_requisito(r, candidato) for r in vaga.requisitos}


def verificar_requisitos(vaga: Vaga, candidato: Candidato) -> dict[str, bool]:
    """Diz quais requisitos estão atendidos.

    False junta NAO_ATENDE e SEM_DADO. Para reprovar alguém, use `avaliar_requisitos`.
    """
    return {
        id_requisito: status == StatusRequisito.ATENDE
        for id_requisito, status in avaliar_requisitos(vaga, candidato).items()
    }


def autorizacao_ativa(candidato: Candidato, hoje: date) -> bool:
    """Diz se a pessoa está ativa e autorizou. A autorização vale até o dia de `valida_ate`."""
    validade = candidato.autorizacao_valida_ate
    return (
        candidato.estado == EstadoBanco.ATIVO
        and candidato.autorizou_contato
        and not candidato.opt_out
        and validade is not None
        and validade >= hoje
    )


@dataclass(frozen=True)
class CorteDeAutorizacao:
    """Saída de quem não pode ir ao modelo, para o fluxo sem funil. Sem dados do perfil."""

    candidato_id: str
    fonte: str
    origem: str
    regra: str
    motivo: str


def corte_de_autorizacao(candidato: Candidato, hoje: date) -> CorteDeAutorizacao | None:
    """Diz por que a pessoa não pode ir ao modelo. Mesmas regras do funil, para um só registro."""
    validade = candidato.autorizacao_valida_ate

    def corte(regra: str, motivo: str) -> CorteDeAutorizacao:
        return CorteDeAutorizacao(candidato.id, candidato.fonte, candidato.origem, regra, motivo)

    if candidato.opt_out:
        return corte("opt_out", "a pessoa pediu para não ser contatada")
    if candidato.estado == EstadoBanco.REMOVIDO:
        return corte("estado_bloqueado", "perfil removido")
    if not candidato.autorizou_contato or validade is None:
        return corte("sem_autorizacao", "sem autorização registrada")
    if validade < hoje:
        return corte("autorizacao_vencida", f"autorização vencida em {validade.isoformat()}")
    if candidato.estado in (EstadoBanco.PENDENTE, EstadoBanco.EXPIRADO):
        return corte("estado_bloqueado", f"perfil com estado {candidato.estado}")
    if candidato.estado == EstadoBanco.DESATUALIZADO:
        return corte(
            REGRA_PERFIL_DESATUALIZADO,
            "autorização válida, perfil desatualizado: uma pessoa confirma antes de analisar",
        )
    return None


def pode_contatar(candidato: Candidato, tentativas: int, vaga: Vaga, hoje: date) -> bool:
    """Diz se o candidato pode receber contato sobre a vaga.

    `tentativas` conta os contatos já feitos.
    """
    _exigir_mesma_empresa(vaga, candidato)
    return autorizacao_ativa(candidato, hoje) and 0 <= tentativas < vaga.max_tentativas_contato


def _trecho_no_perfil(trecho: str, perfil: str) -> bool:
    """Confere o trecho inteiro, palavra a palavra: `Java` não confere com `JavaScript`.

    Evidência pseudonimizada traz marcadores, e o gênero não conta: o perfil guardado é o original.
    """
    return corresponde_ao_original(trecho, perfil)


def classificar_evidencia(evidencia: Evidencia, candidato: Candidato) -> TipoEvidencia:
    """Dá o tipo da evidência por código, sem confiar no que o modelo afirma.

    Sem o trecho literal no perfil, é INFERIDA. COMPROVADA exige que a fonte citada seja
    verificável e igual à fonte do perfil conferido: citar `github` num currículo não promove.
    """
    if not _trecho_no_perfil(evidencia.trecho, candidato.perfil_texto):
        return TipoEvidencia.INFERIDA
    fonte = _normalizar_valor(evidencia.fonte)
    if fonte in FONTES_VERIFICAVEIS and fonte == _normalizar_valor(candidato.fonte):
        return TipoEvidencia.COMPROVADA
    return TipoEvidencia.DECLARADA


@dataclass(frozen=True)
class Faixa:
    """Resultado da regra da faixa verde, antes de virar `Decisao`."""

    tipo: TipoDecisao
    regra: str
    faltas: tuple[str, ...]
    nota: float | None
    requisitos: dict[str, StatusRequisito]
    evidencias: tuple[tuple[str, TipoEvidencia], ...]


def _nota_ponderada(vaga: Vaga, analise: Analise) -> float | None:
    """Média das notas pelos pesos. Devolve None se algum peso ou nota não servir."""
    pesos = [c.peso for c in vaga.competencias]
    notas = [analise.notas.get(c.nome) for c in vaga.competencias]
    if not all(math.isfinite(peso) and peso >= 0 for peso in pesos) or sum(pesos) <= 0:
        return None
    if not all(nota is not None and 0 <= nota <= 1 for nota in notas):
        return None
    return round(sum(p * n for p, n in zip(pesos, notas, strict=True)) / sum(pesos), 6)


def _faltas_de_evidencia(
    vaga: Vaga,
    analise: Analise,
    evidencias: tuple[tuple[str, TipoEvidencia], ...],
    aceitas: frozenset[TipoEvidencia],
) -> list[str]:
    faltas = [] if vaga.requisitos else ["vaga_sem_requisitos"]
    for requisito in sorted(vaga.requisitos, key=lambda r: r.id):
        if analise.requisitos_ok.get(requisito.id) is not True:
            faltas.append(f"requisito_nao_confirmado:{requisito.id}")
        if not any(c == requisito.id and tipo in aceitas for c, tipo in evidencias):
            faltas.append(f"sem_evidencia_comprovada:{requisito.id}")
    for competencia in vaga.competencias:
        verificada = any(
            c == competencia.nome and tipo != TipoEvidencia.INFERIDA for c, tipo in evidencias
        )
        if competencia.peso > 0 and not verificada:
            faltas.append(f"sem_evidencia_competencia:{competencia.nome}")
    return faltas


def _exigir_mesma_execucao(
    vaga: Vaga, candidato: Candidato, analise: Analise, mandato: Mandato
) -> None:
    _exigir_mesma_empresa(vaga, candidato)
    if analise.empresa_id != vaga.empresa_id or mandato.empresa_id != vaga.empresa_id:
        raise ValueError("análise e mandato precisam ser da empresa da vaga")
    if analise.vaga_id != vaga.id or mandato.vaga_id != vaga.id:
        raise ValueError("análise e mandato precisam ser da mesma vaga")
    if analise.candidato_id != candidato.id:
        raise ValueError("análise precisa ser do mesmo candidato")


def classificar_faixa(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    mandato: Mandato,
    hoje: date,
    agora: datetime,
) -> Faixa:
    """Aplica a regra da faixa verde: indicar, descartar ou pedir uma pessoa.

    Não usa nome, atributo sensível nem confiança declarada pelo modelo. Requisito sem dado nunca
    indica nem descarta: vai para uma pessoa. Levanta `ValueError`
    se as peças são de empresas, vagas ou candidatos diferentes, e `MandatoInvalido` se o
    mandato não vale para a vaga ou se ela usa critério sensível, para o fluxo pausar.
    """
    _exigir_mesma_execucao(vaga, candidato, analise, mandato)
    if not mandato_valido(mandato, vaga, agora):
        raise MandatoInvalido("mandato não vale para esta vaga neste momento")
    problemas = validar_criterios(vaga)
    if problemas:
        raise MandatoInvalido(f"vaga com problemas nos critérios: {'; '.join(problemas)}")

    politica = mandato.politica
    requisitos = avaliar_requisitos(vaga, candidato)
    evidencias = tuple(
        (e.criterio, classificar_evidencia(e, candidato)) for e in analise.evidencias
    )
    nota = _nota_ponderada(vaga, analise)

    def faixa(tipo: TipoDecisao, regra: str, faltas: tuple[str, ...] = ()) -> Faixa:
        return Faixa(tipo, regra, faltas, nota, requisitos, evidencias)

    if not autorizacao_ativa(candidato, hoje):
        corte = corte_de_autorizacao(candidato, hoje)
        if corte is not None and corte.regra == REGRA_PERFIL_DESATUALIZADO:
            return faixa(
                TipoDecisao.PEDIR_HUMANO, REGRA_PERFIL_DESATUALIZADO, (REGRA_PERFIL_DESATUALIZADO,)
            )
        return faixa(TipoDecisao.DESCARTAR, "sem_autorizacao")
    reprovados = sorted(i for i, s in requisitos.items() if s == StatusRequisito.NAO_ATENDE)
    if reprovados:
        faltas = tuple(f"requisito_eliminatorio:{i}" for i in reprovados)
        return faixa(TipoDecisao.DESCARTAR, faltas[0], faltas)

    aceitas = {TipoEvidencia.COMPROVADA}
    if politica.aceitar_declarada:
        aceitas.add(TipoEvidencia.DECLARADA)
    faltas = _faltas_de_evidencia(vaga, analise, evidencias, frozenset(aceitas))
    # Sem dado, nenhum trecho citado substitui a verificação: a decisão fica com uma pessoa.
    faltas += [f"requisito_sem_dado:{i}" for i, s in sorted(requisitos.items()) if s == SEM_DADO]
    if analise.ressalvas_revisor:
        faltas.append("ressalva_do_revisor")
    if analise.alertas:
        faltas.append("alerta")
    if any(tipo == TipoEvidencia.INFERIDA for _, tipo in evidencias):
        faltas.append("inferencia")
    if nota is None:
        faltas.append("notas_incompletas")
    elif politica.limiar_verde is None:
        faltas.append("limiar_nao_definido")
    elif nota < politica.limiar_verde:
        faltas.append("nota_abaixo_do_limiar")

    if not faltas:
        return faixa(TipoDecisao.INDICAR, "faixa_verde_v1")
    if faltas == ["nota_abaixo_do_limiar"] and nota < politica.piso_nota:
        return faixa(TipoDecisao.DESCARTAR, "abaixo_do_piso", tuple(faltas))
    return faixa(TipoDecisao.PEDIR_HUMANO, "fora_da_faixa_verde", tuple(faltas))


_PARECE_INSTRUCAO = re.compile(
    r"\b(aprov(e|ar|ado|ada)|contrat(e|ar)|desconsider(e|ar)|ignor(e|ar)|indiqu(e|em)|indicar|"
    r"reprov(e|ar))\b"
)


def parece_instrucao(texto: str) -> bool:
    """Texto livre do modelo pode repetir uma instrução do perfil: ela não segue adiante."""
    return _PARECE_INSTRUCAO.search(" ".join(separar_palavras(texto))) is not None


def evidencia_da_regra(regra: str, motivo: str) -> Evidencia:
    """Registra o fato que a regra usou. Não vem do modelo nem é trecho do perfil."""
    return Evidencia(criterio=regra, trecho=motivo, fonte=FONTE_REGRA)


def _evidencia_completa(evidencia: Evidencia) -> bool:
    return all(texto.strip() for texto in (evidencia.criterio, evidencia.trecho, evidencia.fonte))


def _entrada(
    vaga: Vaga, candidato: Candidato, mandato: Mandato, faixa: Faixa, hoje: date
) -> dict[str, str]:
    """O que sustentou a decisão, sem nome, atributos nem texto do candidato."""
    limiar = mandato.politica.limiar_verde
    return {
        "vaga_id": vaga.id,
        "candidato_id": candidato.id,
        "hoje": hoje.isoformat(),
        "mandato_id": mandato.id,
        "mandato_versao": str(mandato.versao),
        "hash_vaga": mandato.hash_vaga,
        "limiar_verde": "nao_calibrado" if limiar is None else str(limiar),
        "piso_nota": str(mandato.politica.piso_nota),
        "aceitar_declarada": str(mandato.politica.aceitar_declarada).lower(),
        "nota": "indefinida" if faixa.nota is None else str(faixa.nota),
        "requisitos": json.dumps(faixa.requisitos, sort_keys=True),
        "tipos_evidencia": json.dumps(sorted(faixa.evidencias)),
        "faltas": json.dumps(faixa.faltas),
    }


def decidir(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    mandato: Mandato,
    hoje: date,
    agora: datetime,
    rastro_id: str,
) -> Decisao:
    """Transforma a faixa em `Decisao`, com regra, entrada, evidências e responsável."""
    faixa = classificar_faixa(vaga, candidato, analise, mandato, hoje, agora)
    motivo = ", ".join(faixa.faltas) or "dentro da faixa verde do mandato"
    evidencias = [e for e in analise.evidencias if _evidencia_completa(e)]
    return Decisao(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        tipo=faixa.tipo,
        regra=faixa.regra,
        motivo=motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=rastro_id,
        entrada=_entrada(vaga, candidato, mandato, faixa, hoje),
        evidencias=evidencias or [evidencia_da_regra(faixa.regra, motivo)],
        momento=agora,
    )


def nao_priorizada(decisao: Decisao, limite: int) -> Decisao:
    """Passa à fila quem ficou na faixa verde além de `max_indicacoes`, sem descartar ninguém."""
    return decisao.model_copy(
        update={
            "tipo": TipoDecisao.PEDIR_HUMANO,
            "regra": "nao_priorizado",
            "motivo": f"dentro da faixa verde, além do limite de {limite} indicações do mandato",
        }
    )


def decisao_sem_analise(
    vaga: Vaga, candidato: Candidato, mandato: Mandato, agora: datetime, rastro_id: str
) -> Decisao:
    """Falha individual: sem análise válida, a decisão fica com uma pessoa."""
    regra, motivo = "analise_invalida", "a análise voltou inválida"
    return Decisao(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        tipo=TipoDecisao.PEDIR_HUMANO,
        regra=regra,
        motivo=motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=rastro_id,
        entrada={
            "vaga_id": vaga.id,
            "candidato_id": candidato.id,
            "mandato_id": mandato.id,
            "mandato_versao": str(mandato.versao),
            "hash_vaga": mandato.hash_vaga,
        },
        evidencias=[evidencia_da_regra(regra, motivo)],
        momento=agora,
    )


def decisao_de_corte(
    corte: CorteFunil, mandato: Mandato, agora: datetime, rastro_id: str
) -> Decisao:
    """Transforma a saída do funil em decisão. Regra desconhecida fica com uma pessoa."""
    regra = f"{PREFIXO_REGRA_FUNIL}{corte.regra}"
    descarta = str(corte.regra) in CORTES_QUE_DESCARTAM
    return Decisao(
        empresa_id=mandato.empresa_id,
        vaga_id=mandato.vaga_id,
        candidato_id=corte.candidato_id,
        tipo=TipoDecisao.DESCARTAR if descarta else TipoDecisao.PEDIR_HUMANO,
        regra=regra,
        motivo=corte.motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=rastro_id,
        entrada={
            "vaga_id": mandato.vaga_id,
            "candidato_id": corte.candidato_id,
            "mandato_id": mandato.id,
            "mandato_versao": str(mandato.versao),
            "hash_vaga": mandato.hash_vaga,
            "hoje": agora.date().isoformat(),
            "fonte": corte.fonte or "nao_informada",
            "origem": corte.origem or "nao_informada",
        },
        evidencias=[evidencia_da_regra(regra, corte.motivo)],
        momento=agora,
    )


def decisao_por_novos_requisitos(
    vaga: Vaga,
    candidato: Candidato,
    anterior: Decisao,
    mandato: Mandato,
    agora: datetime,
) -> Decisao | None:
    """Reavalia quem estava indicado contra a vaga do aditivo. `None` se a indicação continua.

    Falta comprovada descarta. Dado ausente tira da faixa verde só a decisão automática: a
    pessoa que indicou alguém sem o dado já tomou essa decisão.
    """
    status = avaliar_requisitos(vaga, candidato)
    reprovados = sorted(i for i, s in status.items() if s == StatusRequisito.NAO_ATENDE)
    sem_dado = sorted(i for i, s in status.items() if s == SEM_DADO)
    if reprovados:
        tipo, regra = TipoDecisao.DESCARTAR, f"requisito_eliminatorio:{reprovados[0]}"
        motivo = f"requisito do aditivo não atendido: {', '.join(reprovados)}"
    elif sem_dado and anterior.responsavel.startswith(PREFIXO_RESPONSAVEL_AGENTE):
        tipo, regra = TipoDecisao.PEDIR_HUMANO, "requisito_sem_dado_no_aditivo"
        motivo = f"requisito do aditivo sem dado: {', '.join(sem_dado)}"
    else:
        return None
    return Decisao(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        tipo=tipo,
        regra=regra,
        motivo=motivo,
        responsavel=responsavel_do_mandato(mandato),
        rastro_id=anterior.rastro_id,
        entrada={
            "vaga_id": vaga.id,
            "candidato_id": candidato.id,
            "mandato_id": mandato.id,
            "mandato_versao": str(mandato.versao),
            "hash_vaga": mandato.hash_vaga,
            "regra_anterior": anterior.regra,
            "requisitos": json.dumps(status, sort_keys=True),
        },
        evidencias=[evidencia_da_regra(regra, motivo)],
        momento=agora,
    )


def criterios_sem_evidencia(vaga: Vaga, candidato: Candidato, analise: Analise) -> list[str]:
    """Critérios relevantes sem nenhuma evidência conferida, comprovada ou declarada."""
    conferidos = {
        e.criterio
        for e in analise.evidencias
        if classificar_evidencia(e, candidato) != TipoEvidencia.INFERIDA
    }
    criterios = [r.id for r in vaga.requisitos]
    criterios += [c.nome for c in vaga.competencias if c.peso > 0]
    return [criterio for criterio in criterios if criterio not in conferidos]
