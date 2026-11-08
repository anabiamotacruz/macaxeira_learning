"""Palavras-chave do recrutador: a consulta principal da busca externa.

O que o recrutador escreve é dado, nunca instrução nem operador de busca. A limpeza é
determinística: tira caractere de controle e pontuação que a busca leria como operador (aspas,
`site:`, `-` no começo da palavra), limita quantidade e tamanho e recusa o que pede o LinkedIn,
que a busca não pode pedir. Termo sensível nunca chega à consulta.
"""

import re
import unicodedata
from collections.abc import Iterable

from backend.contratos.criterios import tem_termo_sensivel
from backend.contratos.modelos import Vaga

MAX_PALAVRAS_CHAVE = 10
MAX_CARACTERES_PALAVRA = 40
MAX_TERMOS_NA_CONSULTA = 32
"""Bem abaixo das 75 palavras que a Brave aceita, com folga para o filtro que a fonte acrescenta."""

_FORA_DO_PERMITIDO = re.compile(r"[^\w\s+#./-]")
_PEDE_LINKEDIN = re.compile(r"linkedin|lnkd\.in|licdn", re.IGNORECASE)


def _sem_controle(texto: str) -> str:
    return "".join(" " if unicodedata.category(c).startswith("C") else c for c in texto)


def limpar_palavra_chave(texto: str) -> str:
    """Uma palavra-chave limpa, ou texto vazio quando nada sobra."""
    texto = _FORA_DO_PERMITIDO.sub(" ", _sem_controle(unicodedata.normalize("NFKC", texto)))
    termos = (termo.lstrip("-") for termo in texto.split())
    limpo = " ".join(termo for termo in termos if termo)
    return limpo[:MAX_CARACTERES_PALAVRA].strip()


def limpar_palavras_chave(palavras: Iterable[str]) -> list[str]:
    """Palavras limpas, sem repetir (sem diferença de caixa), na ordem dada e no limite."""
    vistas: set[str] = set()
    resultado: list[str] = []
    for palavra in palavras:
        limpa = limpar_palavra_chave(palavra)
        chave = limpa.casefold()
        if not limpa or chave in vistas or _PEDE_LINKEDIN.search(limpa):
            continue
        vistas.add(chave)
        resultado.append(limpa)
        if len(resultado) == MAX_PALAVRAS_CHAVE:
            break
    return resultado


def consulta_do_recrutador(vaga: Vaga) -> str | None:
    """As palavras-chave da vaga numa só consulta, na ordem do recrutador. Sem elas, `None`."""
    palavras = [p for p in limpar_palavras_chave(vaga.palavras_chave) if not tem_termo_sensivel(p)]
    termos = " ".join(palavras).split()[:MAX_TERMOS_NA_CONSULTA]
    return " ".join(termos) or None
