"""Proposta de configuração de uma vaga a partir da descrição.

O modelo só interpreta o texto. Identificador, empresa, aprovação e limite de contato
são definidos por este código, e a vaga proposta ainda precisa de assinatura humana.
Na dúvida, devolve uma pergunta: não inventa requisito nem deixa critério sensível entrar.
"""

import hashlib
import logging
import math
import re
from typing import Annotated, Self

from pydantic import BaseModel, Field, model_validator

from backend.agente import prompts
from backend.agente.auditoria import contexto_rastro, rastreado
from backend.agente.regras import validar_requisitos_e_competencias
from backend.contratos.criterios import (
    frases_com_termo_sensivel,
    separar_palavras,
    termos_sensiveis,
)
from backend.contratos.erros import RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Competencia, Contrato, Requisito, Texto, Vaga

logger = logging.getLogger(__name__)

ETAPA_CONFIGURACAO = "configuracao"

MAX_TENTATIVAS_CONTATO = 2
"""Limite de contato fixado em código: nem a descrição nem o modelo o alteram."""

MAX_META_CANDIDATOS = 100
MAX_PRAZO_DIAS = 180
"""Tetos da proposta. Acima deles, a resposta é inválida e a pessoa recebe uma pergunta."""

TAMANHO_MAXIMO_DESCRICAO = 20_000
TAMANHO_MAXIMO_TRECHO = 200

PERGUNTA_RESPOSTA_INVALIDA = (
    "Não foi possível interpretar a descrição com segurança. "
    "Pode detalhar requisitos, competências, meta e prazo?"
)

PADROES_DE_INSTRUCAO: tuple[re.Pattern[str], ...] = tuple(
    re.compile(padrao)
    for padrao in (
        r"\b(ignor\w*|desconsider\w*|esquec\w*|disregard|forget)\b"
        r".*\b(instruc\w*|regras?|prompt|instructions?|rules?)\b",
        r"\b(system prompt|prompt do sistema)\b",
        r"\b(voce agora|you are now)\b",
    )
)
"""Sobre o texto normalizado. Só geram alerta: a defesa é o texto seguir como dado."""


class PerguntaVaga(Contrato):
    """Dúvida devolvida à pessoa, em vez de uma vaga proposta. Modelo local: não cruza frentes."""

    empresa_id: Texto
    pergunta: Texto
    trecho_ambiguo: str = ""


class PropostaModelo(Contrato):
    """O que o modelo pode propor. Campo fora desta lista torna a resposta inválida."""

    titulo: str = ""
    requisitos: list[Requisito] = Field(default_factory=list)
    competencias: list[Competencia] = Field(default_factory=list)
    meta_candidatos: Annotated[int, Field(ge=1, le=MAX_META_CANDIDATOS)] | None = None
    prazo_dias: Annotated[int, Field(ge=1, le=MAX_PRAZO_DIAS)] | None = None
    duvidas: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _criterios_bem_formados(self) -> Self:
        ids = [requisito.id for requisito in self.requisitos]
        if len(set(ids)) != len(ids):
            raise ValueError("requisitos com id repetido")
        for requisito in self.requisitos:
            if not (requisito.id.strip() and requisito.campo.strip()):
                raise ValueError("requisito sem id ou sem campo")
            if not requisito.valor_esperado.strip():
                raise ValueError("requisito sem valor esperado")
        for competencia in self.competencias:
            if not (math.isfinite(competencia.peso) and competencia.peso > 0):
                raise ValueError("competência com peso que não é positivo e finito")
        return self


def _id_da_vaga(empresa_id: str, descricao: str) -> str:
    resumo = hashlib.sha256(f"{empresa_id}\n{descricao}".encode()).hexdigest()
    return f"vaga-{resumo[:12]}"


def _alertar_instrucao_embutida(descricao: str, empresa_id: str) -> None:
    """Registra o alerta sem copiar o texto, que é dado não confiável."""
    normalizado = " ".join(separar_palavras(descricao))
    if any(padrao.search(normalizado) for padrao in PADROES_DE_INSTRUCAO):
        logger.warning(
            "descrição de vaga com possível instrução embutida: empresa=%s vaga=%s",
            empresa_id,
            _id_da_vaga(empresa_id, descricao),
        )


def _pergunta_sobre_dado_sensivel(
    onde: str, termos: list[str], trecho: str, empresa_id: str
) -> PerguntaVaga:
    return PerguntaVaga(
        empresa_id=empresa_id,
        pergunta=(
            f"{onde} cita dado sensível ({', '.join(termos)}), que não pode ser critério. "
            "Reescreva o trecho sem restringir quem pode concorrer. "
            "Se for um aviso de não discriminação, deixe isso explícito na frase."
        ),
        trecho_ambiguo=trecho[:TAMANHO_MAXIMO_TRECHO],
    )


def _pergunta_sobre_texto_da_descricao(descricao: str, empresa_id: str) -> PerguntaVaga | None:
    achadas = frases_com_termo_sensivel(descricao)
    if not achadas:
        return None
    frase, termos = achadas[0]
    return _pergunta_sobre_dado_sensivel("A descrição", termos, frase, empresa_id)


def _pergunta_sobre_descricao(descricao: str, empresa_id: str) -> PerguntaVaga | None:
    if not descricao.strip():
        return PerguntaVaga(empresa_id=empresa_id, pergunta="Qual é a descrição da vaga?")
    if len(descricao) > TAMANHO_MAXIMO_DESCRICAO:
        return PerguntaVaga(
            empresa_id=empresa_id,
            pergunta=(
                f"A descrição passa de {TAMANHO_MAXIMO_DESCRICAO} caracteres. Pode resumi-la?"
            ),
        )
    return _pergunta_sobre_texto_da_descricao(descricao, empresa_id)


def _lacuna_da_proposta(proposta: PropostaModelo) -> str | None:
    if not proposta.titulo.strip():
        return "Qual é o título da vaga?"
    if not proposta.requisitos:
        return "Quais são os requisitos eliminatórios da vaga?"
    if not proposta.competencias:
        return "Quais competências devem pesar na análise?"
    if proposta.meta_candidatos is None:
        return "Quantos candidatos a vaga precisa receber?"
    if proposta.prazo_dias is None:
        return "Qual é o prazo da vaga, em dias?"
    return None


def _vaga_ou_pergunta(
    proposta: PropostaModelo, descricao: str, empresa_id: str
) -> Vaga | PerguntaVaga:
    duvidas = [duvida.strip() for duvida in proposta.duvidas if duvida.strip()]
    if duvidas:
        return PerguntaVaga(empresa_id=empresa_id, pergunta=" ".join(duvidas))
    lacuna = _lacuna_da_proposta(proposta)
    if lacuna:
        return PerguntaVaga(empresa_id=empresa_id, pergunta=lacuna)

    vaga = Vaga(
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
    problemas = validar_requisitos_e_competencias(vaga)
    if problemas:
        return PerguntaVaga(
            empresa_id=empresa_id,
            pergunta=f"A proposta foi recusada: {'; '.join(problemas)}. Como reescrever a vaga?",
        )
    termos_no_titulo = termos_sensiveis(vaga.titulo)
    if termos_no_titulo:
        return _pergunta_sobre_dado_sensivel("O título", termos_no_titulo, vaga.titulo, empresa_id)
    return vaga


@rastreado(ETAPA_CONFIGURACAO)
def _pedir_proposta(cliente_modelo: ClienteModelo, descricao: str) -> BaseModel:
    return cliente_modelo.completar(
        prompts.SISTEMA_CONFIGURACAO,
        prompts.USUARIO_CONFIGURACAO.format(descricao=prompts.como_dado(descricao)),
        PropostaModelo,
        ETAPA_CONFIGURACAO,
    )


def propor_configuracao(
    descricao: str, empresa_id: str, cliente_modelo: ClienteModelo
) -> Vaga | PerguntaVaga:
    """Devolve a vaga proposta, sempre com `aprovada=False`, ou uma pergunta à pessoa."""
    if not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório")

    pergunta = _pergunta_sobre_descricao(descricao, empresa_id)
    if pergunta:
        return pergunta

    _alertar_instrucao_embutida(descricao, empresa_id)
    try:
        with contexto_rastro(empresa_id=empresa_id, vaga_id=_id_da_vaga(empresa_id, descricao)):
            proposta = _pedir_proposta(cliente_modelo, descricao)
    except RespostaInvalida:
        return PerguntaVaga(empresa_id=empresa_id, pergunta=PERGUNTA_RESPOSTA_INVALIDA)
    if not isinstance(proposta, PropostaModelo):
        return PerguntaVaga(empresa_id=empresa_id, pergunta=PERGUNTA_RESPOSTA_INVALIDA)
    return _vaga_ou_pergunta(proposta, descricao, empresa_id)
