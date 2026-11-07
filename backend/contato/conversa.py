"""Conversa com o candidato (T3.2): classificar respostas e responder dúvidas.

Regras de segurança ficam em código, antes e depois do modelo:
- texto vazio é silêncio; pedido de saída é opt-out sem passar pelo modelo;
- classificação inválida ou indisponível vira dúvida, para uma pessoa olhar;
- mensagem com instrução ao agente nunca vira aceite ou recusa automática;
- dúvida só é respondida com trechos que existem no material da vaga.
"""

import logging
import re
import unicodedata

from pydantic import BaseModel

from backend.contato.prompts import (
    SISTEMA_CLASSIFICACAO,
    SISTEMA_DUVIDA,
    montar_pedido_classificacao,
    montar_pedido_duvida,
)
from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import BancoTalentos, ClienteModelo
from backend.contratos.modelos import (
    Candidato,
    Convite,
    RespostaCandidato,
    TipoResposta,
    Vaga,
)

logger = logging.getLogger(__name__)

ETAPA_CLASSIFICACAO = "classificar_resposta"
ETAPA_DUVIDA = "responder_duvida"
LIMITE_TEXTO = 2000

_SAIDA = [
    re.compile(p)
    for p in (
        r"nao quero mais (receber|ser contatad)",
        r"nao quero receber",
        r"remov\w* (os )?meus dados",
        r"apag\w* (os )?meus dados",
        r"nao me (contate|contatem|procure|procurem|mande|mandem|chame|chamem)",
        r"descadastr",
        r"pare(m)? de (me )?(mandar|enviar|contatar|chamar)",
    )
]

_INSTRUCAO = [
    re.compile(p)
    for p in (
        r"ignor\w*\s+(as\s+|todas\s+as\s+|suas\s+|os\s+)?(instruc|regras|comandos|orientac)",
        r"ignore\s+(all\s+|the\s+)?(previous|prior|above)",
        r"voce agora e",
        r"you are now",
        r"\b(sistema|system|assistant|assistente)\s*:",
        r"\b(classifique|classifica|marque|marca|classify|mark)\b.{0,20}\b(como|as)\b",
        r"</?\s*(mensagem_candidato|material_vaga|dados_vaga|dados_candidato)",
    )
]


class ClassificacaoResposta(BaseModel):
    tipo: TipoResposta


class RespostaDuvida(BaseModel):
    respondivel: bool
    resposta: str
    trechos_usados: list[str]


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def pede_saida(texto: str) -> bool:
    """Pedido de saída explícito, decidido sem modelo."""
    if re.search(r"\bSAIR\b", texto):
        return True
    normalizado = _normalizar(texto)
    if re.sub(r"[^\w ]", "", normalizado).strip() == "sair":
        return True
    return any(p.search(normalizado) for p in _SAIDA)


def contem_instrucao(texto: str) -> bool:
    """Sinais de instrução ao agente dentro do texto da pessoa. Gera alerta."""
    normalizado = _normalizar(texto)
    return any(p.search(normalizado) for p in _INSTRUCAO)


def _limitar(texto: str) -> str:
    if len(texto) <= LIMITE_TEXTO:
        return texto
    return texto[:LIMITE_TEXTO] + " [texto truncado]"


def _tipo_pelo_modelo(texto: str, cliente_modelo: ClienteModelo) -> TipoResposta:
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_CLASSIFICACAO,
            montar_pedido_classificacao(_limitar(texto)),
            ClassificacaoResposta,
            ETAPA_CLASSIFICACAO,
        )
        return ClassificacaoResposta.model_validate(resposta.model_dump()).tipo
    except (ModeloIndisponivel, RespostaInvalida) as erro:
        logger.warning("classificação encaminhada a uma pessoa: %s", erro)
        return TipoResposta.DUVIDA


def classificar_resposta(
    texto: str, cliente_modelo: ClienteModelo, *, convite_id: str
) -> RespostaCandidato:
    def resposta(tipo: TipoResposta) -> RespostaCandidato:
        return RespostaCandidato(convite_id=convite_id, tipo=tipo, texto=texto)

    if not texto.strip():
        return resposta(TipoResposta.SILENCIO)
    if pede_saida(texto):
        return resposta(TipoResposta.OPT_OUT)

    tipo = _tipo_pelo_modelo(texto, cliente_modelo)
    if tipo == TipoResposta.SILENCIO:
        tipo = TipoResposta.DUVIDA
    if contem_instrucao(texto) and tipo != TipoResposta.OPT_OUT:
        logger.warning("alerta: instrução na resposta ao convite %s", convite_id)
        tipo = TipoResposta.DUVIDA
    return resposta(tipo)


def registrar_saida(
    banco: BancoTalentos, convite: Convite, resposta: RespostaCandidato
) -> Candidato:
    """Marca opt-out no banco: a pessoa sai da busca de todas as vagas da empresa."""
    if resposta.tipo != TipoResposta.OPT_OUT:
        raise ValueError("só uma resposta de opt-out registra saída")
    if resposta.convite_id != convite.id:
        raise ValueError("a resposta não é deste convite")
    return banco.registrar_opt_out(convite.empresa_id, convite.candidato_id)


def material_da_vaga(vaga: Vaga) -> str:
    requisitos = "; ".join(r.descricao for r in vaga.requisitos)
    competencias = "; ".join(c.nome for c in vaga.competencias)
    return (
        f"título: {vaga.titulo}\n"
        f"descrição: {vaga.descricao}\n"
        f"requisitos: {requisitos}\n"
        f"competências: {competencias}"
    )


def _resposta_fundamentada(duvida: RespostaDuvida, material: str) -> bool:
    if not duvida.respondivel or not duvida.resposta.strip() or not duvida.trechos_usados:
        return False
    if "http" in duvida.resposta.lower() or "www." in duvida.resposta.lower():
        return False
    base = _normalizar(material)
    return all(_normalizar(t) and _normalizar(t) in base for t in duvida.trechos_usados)


def responder_duvida(vaga: Vaga, texto: str, cliente_modelo: ClienteModelo) -> str | None:
    """Resposta baseada só no material da vaga, ou None para uma pessoa responder."""
    if not texto.strip():
        return None
    if contem_instrucao(texto):
        logger.warning("alerta: instrução numa dúvida sobre a vaga %s", vaga.id)
        return None
    material = material_da_vaga(vaga)
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_DUVIDA,
            montar_pedido_duvida(material, _limitar(texto)),
            RespostaDuvida,
            ETAPA_DUVIDA,
        )
        duvida = RespostaDuvida.model_validate(resposta.model_dump())
    except (ModeloIndisponivel, RespostaInvalida) as erro:
        logger.warning("dúvida da vaga %s encaminhada a uma pessoa: %s", vaga.id, erro)
        return None
    if not _resposta_fundamentada(duvida, material):
        return None
    return duvida.resposta.strip()
