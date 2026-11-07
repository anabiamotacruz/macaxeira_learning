"""Mandato de uma vaga: critérios, limite de gasto e política assinados por uma pessoa.

O mandato guarda o hash da vaga assinada; qualquer edição posterior da vaga o invalida.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Mandato, ModoEntrega, Politica, Vaga

__all__ = [
    "Mandato",
    "MandatoInvalido",
    "ModoEntrega",
    "Politica",
    "ValidadorCriterios",
    "assinar",
    "hash_da_vaga",
    "mandato_valido",
]

ValidadorCriterios = Callable[[Vaga], list[str]]
"""Recebe a vaga e devolve os problemas encontrados, como critério sensível."""


class MandatoInvalido(ErroContrato):
    """Mandato recusado na assinatura ou que não vale para a vaga atual."""


def hash_da_vaga(vaga: Vaga) -> str:
    """Resume o conteúdo da vaga, sem `aprovada`, que muda como efeito da própria assinatura."""
    conteudo = vaga.model_dump(mode="json", exclude={"aprovada"})
    canonico = json.dumps(conteudo, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _resumo_assinatura(hash_vaga: str, assinante: str, agora: datetime) -> str:
    conteudo = f"{hash_vaga}:{assinante}:{agora.isoformat()}"
    return hashlib.sha256(conteudo.encode("utf-8")).hexdigest()[:12]


def assinar(
    vaga: Vaga,
    assinante: str,
    limite_gasto_usd: float,
    politica: Politica,
    agora: datetime,
    *,
    validar_criterios: ValidadorCriterios,
    versao: int = 1,
    valido_ate: datetime | None = None,
) -> Mandato:
    """Cria o mandato ou levanta `MandatoInvalido`. Não altera a vaga."""
    problemas = validar_criterios(vaga)
    if problemas:
        raise MandatoInvalido(f"vaga com problemas nos critérios: {'; '.join(problemas)}")

    hash_vaga = hash_da_vaga(vaga)
    try:
        return Mandato(
            id=f"mandato-{_resumo_assinatura(hash_vaga, assinante, agora)}",
            versao=versao,
            empresa_id=vaga.empresa_id,
            vaga_id=vaga.id,
            hash_vaga=hash_vaga,
            assinante=assinante,
            limite_gasto_usd=limite_gasto_usd,
            politica=politica,
            assinado_em=agora,
            valido_ate=valido_ate,
        )
    except ValidationError as erro:
        campos = sorted({str(detalhe["loc"][0]) for detalhe in erro.errors()})
        raise MandatoInvalido(f"campos recusados: {', '.join(campos)}") from erro


def mandato_valido(mandato: Mandato, vaga: Vaga, agora: datetime) -> bool:
    """Diz se o mandato vale para esta empresa e vaga, não venceu e a vaga segue igual."""
    return (
        mandato.empresa_id == vaga.empresa_id
        and mandato.vaga_id == vaga.id
        and mandato.hash_vaga == hash_da_vaga(vaga)
        and (mandato.valido_ate is None or agora <= mandato.valido_ate)
    )
