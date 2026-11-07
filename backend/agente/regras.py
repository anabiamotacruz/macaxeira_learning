"""Regras determinísticas de critérios, requisitos, contato e decisão. Nenhuma usa modelo de IA."""

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from backend.agente.mandato import Mandato, MandatoInvalido, mandato_valido
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

TERMOS_SENSIVEIS: tuple[tuple[str, ...], ...] = (
    ("cor", "da", "pele"),
    ("estado", "civil"),
    ("etnia",),
    ("etnias",),
    ("genero",),
    ("generos",),
    ("idade",),
    ("idades",),
    ("nascimento",),
    ("orientacao", "sexual"),
    ("raca",),
    ("racas",),
    ("religiao",),
    ("religioes",),
    ("sexo",),
)
"""Sequências de palavras já normalizadas, em ordem alfabética."""

FONTES_VERIFICAVEIS = frozenset({"github", "rede_simulada"})
"""Fontes externas à autodeclaração. Currículo e perfil enviado pela pessoa ficam de fora."""


class StatusRequisito(StrEnum):
    ATENDE = "atende"
    NAO_ATENDE = "nao_atende"
    SEM_DADO = "sem_dado"


class TipoEvidencia(StrEnum):
    INFERIDA = "inferida"
    DECLARADA = "declarada"
    COMPROVADA = "comprovada"


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _palavras(texto: str) -> tuple[str, ...]:
    """Separa em palavras: sem acento e sem caixa, tratando `_` e camelCase como divisão."""
    separado = re.sub(r"([a-z])([A-Z])", r"\1 \2", _sem_acento(texto))
    return tuple(re.findall(r"[^\W_]+", separado.casefold()))


def _contem(palavras: tuple[str, ...], termo: tuple[str, ...]) -> bool:
    tamanho = len(termo)
    return any(palavras[i : i + tamanho] == termo for i in range(len(palavras) - tamanho + 1))


def _termos_sensiveis(*textos: str) -> list[str]:
    achados = {
        " ".join(termo)
        for texto in textos
        for termo in TERMOS_SENSIVEIS
        if _contem(_palavras(texto), termo)
    }
    return sorted(achados)


def validar_criterios(vaga: Vaga) -> list[str]:
    """Lista os critérios com atributo sensível, um problema por critério, em ordem estável.

    Olha requisitos e competências. Título e descrição ficam de fora: são texto livre e
    costumam trazer aviso de não discriminação, que cita esses mesmos termos.
    """
    problemas = []
    for requisito in vaga.requisitos:
        termos = _termos_sensiveis(requisito.descricao, requisito.campo, requisito.valor_esperado)
        if termos:
            problemas.append(f"requisito {requisito.id!r} usa dado sensível: {', '.join(termos)}")
    for competencia in vaga.competencias:
        termos = _termos_sensiveis(competencia.nome)
        if termos:
            problemas.append(
                f"competência {competencia.nome!r} usa dado sensível: {', '.join(termos)}"
            )
    return problemas


def _exigir_mesma_empresa(vaga: Vaga, candidato: Candidato) -> None:
    if vaga.empresa_id != candidato.empresa_id:
        raise ValueError("vaga e candidato pertencem a empresas diferentes")


def _normalizar_valor(texto: str) -> str:
    """Tira acento, caixa e espaços repetidos, mantendo símbolos: `C++` não é `C#`."""
    return " ".join(_sem_acento(texto).casefold().split())


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


def pode_contatar(candidato: Candidato, tentativas: int, vaga: Vaga, hoje: date) -> bool:
    """Diz se o candidato pode receber contato sobre a vaga.

    `tentativas` conta os contatos já feitos.
    """
    _exigir_mesma_empresa(vaga, candidato)
    return autorizacao_ativa(candidato, hoje) and 0 <= tentativas < vaga.max_tentativas_contato


def _trecho_no_perfil(trecho: str, perfil: str) -> bool:
    """Confere o trecho inteiro, palavra a palavra: `Java` não confere com `JavaScript`."""
    alvo = _normalizar_valor(trecho)
    if not _palavras(alvo):
        return False
    return re.search(rf"(?<!\w){re.escape(alvo)}(?!\w)", _normalizar_valor(perfil)) is not None


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


def classificar_faixa(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    mandato: Mandato,
    hoje: date,
    agora: datetime,
) -> Faixa:
    """Aplica a regra da faixa verde: indicar, descartar ou pedir uma pessoa.

    Não usa nome, atributo sensível nem confiança declarada pelo modelo. Levanta
    `MandatoInvalido` se o mandato não vale para a vaga, para o fluxo pausar.
    """
    if not mandato_valido(mandato, vaga, agora):
        raise MandatoInvalido("mandato não vale para esta vaga neste momento")

    politica = mandato.politica
    requisitos = avaliar_requisitos(vaga, candidato)
    evidencias = tuple(
        (e.criterio, classificar_evidencia(e, candidato)) for e in analise.evidencias
    )
    nota = _nota_ponderada(vaga, analise)

    def faixa(tipo: TipoDecisao, regra: str, faltas: tuple[str, ...] = ()) -> Faixa:
        return Faixa(tipo, regra, faltas, nota, requisitos, evidencias)

    if not autorizacao_ativa(candidato, hoje):
        return faixa(TipoDecisao.DESCARTAR, "sem_autorizacao")
    reprovados = sorted(i for i, s in requisitos.items() if s == StatusRequisito.NAO_ATENDE)
    if reprovados:
        faltas = tuple(f"requisito_eliminatorio:{i}" for i in reprovados)
        return faixa(TipoDecisao.DESCARTAR, faltas[0], faltas)

    aceitas = {TipoEvidencia.COMPROVADA}
    if politica.aceitar_declarada:
        aceitas.add(TipoEvidencia.DECLARADA)
    faltas = _faltas_de_evidencia(vaga, analise, evidencias, frozenset(aceitas))
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
    return Decisao(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        tipo=faixa.tipo,
        regra=faixa.regra,
        motivo=", ".join(faixa.faltas) or "dentro da faixa verde do mandato",
        responsavel=f"agente:mandato:{mandato.id}:v{mandato.versao}",
        rastro_id=rastro_id,
        entrada=_entrada(vaga, candidato, mandato, faixa, hoje),
        evidencias=analise.evidencias,
        momento=agora,
    )
