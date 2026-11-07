"""Mandato de uma vaga: critérios, limite de gasto e política assinados por uma pessoa.

Modelo local da Frente 1, fora de `backend/contratos`. O mandato guarda o hash da
vaga assinada; qualquer edição posterior da vaga o invalida.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AwareDatetime, ConfigDict, Field, ValidationError, model_validator

from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Contrato, Texto, Vaga

ValidadorCriterios = Callable[[Vaga], list[str]]
"""Recebe a vaga e devolve os problemas encontrados, como critério sensível."""


class MandatoInvalido(ErroContrato):
    """Mandato recusado na assinatura ou que não vale para a vaga atual."""


class ModoEntrega(StrEnum):
    APOS_ACEITE = "apos_aceite"
    NA_DECISAO = "na_decisao"


class Politica(Contrato):
    """Limites dentro dos quais o agente decide sozinho."""

    model_config = ConfigDict(frozen=True)

    limiar_verde: Annotated[float, Field(ge=0, le=1)] | None
    piso_nota: Annotated[float, Field(ge=0, le=1)]
    max_indicacoes: Annotated[int, Field(ge=1)]
    max_ampliacoes: Annotated[int, Field(ge=0)]
    modo_entrega: ModoEntrega = ModoEntrega.APOS_ACEITE

    @model_validator(mode="after")
    def _piso_nao_passa_do_limiar(self) -> Self:
        if self.limiar_verde is not None and self.piso_nota > self.limiar_verde:
            raise ValueError("piso_nota não pode ser maior que limiar_verde")
        return self


class Mandato(Contrato):
    model_config = ConfigDict(frozen=True)

    id: Texto
    versao: Annotated[int, Field(ge=1)]
    empresa_id: Texto
    vaga_id: Texto
    hash_vaga: Texto
    assinante: Texto
    limite_gasto_usd: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
    politica: Politica
    assinado_em: AwareDatetime


def hash_da_vaga(vaga: Vaga) -> str:
    """Resume o conteúdo da vaga, sem `aprovada`, que muda como efeito da própria assinatura."""
    conteudo = vaga.model_dump(mode="json", exclude={"aprovada"})
    canonico = json.dumps(conteudo, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def assinar(
    vaga: Vaga,
    assinante: str,
    limite_gasto_usd: float,
    politica: Politica,
    agora: datetime,
    *,
    validar_criterios: ValidadorCriterios,
    versao: int = 1,
) -> Mandato:
    """Cria o mandato ou levanta `MandatoInvalido`. Não altera a vaga."""
    problemas = validar_criterios(vaga)
    if problemas:
        raise MandatoInvalido(f"vaga com problemas nos critérios: {'; '.join(problemas)}")

    hash_vaga = hash_da_vaga(vaga)
    try:
        return Mandato(
            id=f"mandato-{hash_vaga[:12]}",
            versao=versao,
            empresa_id=vaga.empresa_id,
            vaga_id=vaga.id,
            hash_vaga=hash_vaga,
            assinante=assinante,
            limite_gasto_usd=limite_gasto_usd,
            politica=politica,
            assinado_em=agora,
        )
    except ValidationError as erro:
        campos = sorted({str(detalhe["loc"][0]) for detalhe in erro.errors()})
        raise MandatoInvalido(f"campos recusados: {', '.join(campos)}") from erro


def mandato_valido(mandato: Mandato, vaga: Vaga) -> bool:
    """Diz se o mandato pertence a esta empresa e vaga e se a vaga segue como foi assinada."""
    return (
        mandato.empresa_id == vaga.empresa_id
        and mandato.vaga_id == vaga.id
        and mandato.hash_vaga == hash_da_vaga(vaga)
    )
