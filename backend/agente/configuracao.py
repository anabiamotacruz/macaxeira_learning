"""Proposta de configuração de uma vaga a partir da descrição.

O modelo só interpreta o texto. Identificador, empresa, aprovação e limite de contato
são definidos por este código, e a vaga proposta ainda precisa de assinatura humana.
"""

import hashlib

from pydantic import Field

from backend.agente import prompts
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Competencia, Contrato, Requisito, Texto, Vaga

ETAPA_CONFIGURACAO = "configuracao"

MAX_TENTATIVAS_CONTATO = 2
"""Limite de contato fixado em código: nem a descrição nem o modelo o alteram."""


class PropostaModelo(Contrato):
    """O que o modelo pode propor. Campo fora desta lista torna a resposta inválida."""

    titulo: Texto
    requisitos: list[Requisito] = Field(default_factory=list)
    competencias: list[Competencia] = Field(default_factory=list)
    meta_candidatos: int
    prazo_dias: int
    duvidas: list[str] = Field(default_factory=list)


def _id_da_vaga(empresa_id: str, descricao: str) -> str:
    resumo = hashlib.sha256(f"{empresa_id}\n{descricao}".encode()).hexdigest()
    return f"vaga-{resumo[:12]}"


def propor_configuracao(descricao: str, empresa_id: str, cliente_modelo: ClienteModelo) -> Vaga:
    """Devolve a vaga proposta, sempre com `aprovada=False`."""
    if not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório")

    proposta = cliente_modelo.completar(
        prompts.SISTEMA_CONFIGURACAO,
        prompts.USUARIO_CONFIGURACAO.format(descricao=descricao),
        PropostaModelo,
        ETAPA_CONFIGURACAO,
    )
    return Vaga(
        id=_id_da_vaga(empresa_id, descricao),
        empresa_id=empresa_id,
        titulo=proposta.titulo,
        descricao=descricao,
        requisitos=proposta.requisitos,
        competencias=proposta.competencias,
        meta_candidatos=proposta.meta_candidatos,
        prazo_dias=proposta.prazo_dias,
        max_tentativas_contato=MAX_TENTATIVAS_CONTATO,
        aprovada=False,
    )
