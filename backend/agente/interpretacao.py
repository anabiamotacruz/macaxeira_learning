"""Interpreta a mensagem livre da pessoa, sem modelo: seguir, não seguir ou agora não.

Aceitar conversar não é aceitar a vaga. Em qualquer momento da conversa a pessoa pode recusar
ou dizer que agora não dá, e o agente reconhece isso por regras. Pedido de saída tem prioridade.
Texto com instrução ao agente nunca vira decisão: fica como dúvida, para uma pessoa olhar.
O texto é dado, nunca instrução, e não vai aos eventos.
"""

import re

from backend.contato.conversa import contem_instrucao, pede_saida
from backend.contratos.criterios import sem_acento
from backend.contratos.modelos import TipoResposta

NAO_AGORA = "nao_agora"
"""Recusa que não fecha a porta: vira sugestão de Talent Garden."""

_NAO_AGORA = re.compile(
    r"\b(agora nao|nao agora|no momento nao|neste momento nao|nao posso agora|nao da agora"
    r"|talvez depois|mais (pra|para) frente|daqui a|em breve|outra oportunidade"
    r"|proxim[ao]s? (mes|meses|ano|semestre|vaga|vagas|oportunidade|oportunidades))\b"
)
_NEGATIVO = re.compile(
    r"\b(nao (tenho|tem) (mais )?interesse|sem interesse|nao quero|nao vou (participar|seguir"
    r"|continuar|aceitar)|nao (e|eh) (pra|para) mim|desist\w*|prefiro nao|aceitei outra"
    r"|fechei com outra|vou recusar|recuso|nao topo|nao rola)\b"
)
_POSITIVO = re.compile(
    r"^(sim|quero|topo|bora|claro|pode ser|tenho interesse|aceito|com certeza|vamos)\b"
    r"|\b(quero (participar|seguir|continuar|agendar|marcar|conversar)|tenho interesse"
    r"|aceito o convite|topo (sim|participar|conversar))\b"
)


def _normalizar(texto: str) -> str:
    return " ".join(sem_acento(texto).casefold().split())


def eh_nao_agora(texto: str) -> bool:
    """A pessoa disse que agora não pode, sem fechar a porta."""
    return bool(_NAO_AGORA.search(_normalizar(texto)))


def interpretar_mensagem(texto: str) -> TipoResposta | str | None:
    """Opt-out, `NAO_AGORA`, recusa, aceite ou `None` (dúvida ou nada claro).

    A recusa vem antes do aceite: "não tenho interesse" contém "tenho interesse". Pergunta com
    "sim" continua dúvida, porque a pessoa ainda quer saber algo antes de decidir.
    """
    if not texto.strip():
        return None
    if pede_saida(texto):
        return TipoResposta.OPT_OUT
    if contem_instrucao(texto):
        return None
    normalizado = _normalizar(texto)
    if eh_nao_agora(texto):
        return NAO_AGORA
    if _NEGATIVO.search(normalizado):
        return TipoResposta.RECUSA
    if "?" in texto:
        return None
    if _POSITIVO.search(normalizado):
        return TipoResposta.ACEITE
    return None
