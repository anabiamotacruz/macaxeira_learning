"""Regras determinísticas de critérios, requisitos e contato. Nenhuma usa modelo de IA."""

import re
import unicodedata
from datetime import date
from enum import StrEnum

from backend.contratos.modelos import Candidato, EstadoBanco, Evidencia, Requisito, Vaga

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


def pode_contatar(candidato: Candidato, tentativas: int, vaga: Vaga, hoje: date) -> bool:
    """Diz se o candidato pode receber contato sobre a vaga.

    `tentativas` conta os contatos já feitos. A autorização vale até o dia de `valida_ate`.
    """
    _exigir_mesma_empresa(vaga, candidato)
    validade = candidato.autorizacao_valida_ate
    return (
        candidato.estado == EstadoBanco.ATIVO
        and candidato.autorizou_contato
        and not candidato.opt_out
        and validade is not None
        and validade >= hoje
        and 0 <= tentativas < vaga.max_tentativas_contato
    )


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
