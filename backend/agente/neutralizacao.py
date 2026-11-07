"""Flexão de gênero e conferência de trecho com marcadores. Regras puras, sem modelo e sem cofre.

Fica no agente porque `regras.py` confere evidência com ela e a pseudonimização a usa para o texto
enviado ao modelo: os dois lados precisam dar o mesmo resultado.
"""

import re
import unicodedata
from bisect import bisect_left
from typing import NamedTuple

from backend.contratos.criterios import sem_genero

MARCADOR = re.compile(r"\[[A-Z]+(?:_[A-Z0-9]+)?\]")
"""Forma dos marcadores da pseudonimização, como `[PESSOA]`, `[EMAIL_1]` e `[ANO_2019]`."""

MAXIMO_DE_MARCADORES_NO_TRECHO = 12
"""Acima disto o trecho não confere: cada marcador multiplica o trabalho da busca."""

MAXIMO_DE_CARACTERES_POR_MARCADOR = 160
"""Um marcador vale por um valor retirado, não por um parágrafo."""

MAXIMO_DE_CARACTERES_NO_TRECHO = 5_000
"""Uma citação, não um documento. Limita o custo de procurar cada pedaço no original."""

MAXIMO_DE_CARACTERES_DO_PERFIL = 200_000
"""O que se lê de um perfil. Passou disso, o resto não vai ao modelo nem pode ser citado."""

_FLEXOES = {
    "advogada": "advogado",
    "advogadas": "advogados",
    "apaixonada": "apaixonado",
    "aprendiza": "aprendiz",
    "aprovada": "aprovado",
    "autonoma": "autônomo",
    "bacharela": "bacharel",
    "biologa": "biólogo",
    "capacitada": "capacitado",
    "certificada": "certificado",
    "comprometida": "comprometido",
    "contratada": "contratado",
    "convidada": "convidado",
    "dedicada": "dedicado",
    "dela": "dele",
    "doutoranda": "doutorando",
    "ela": "ele",
    "elas": "eles",
    "enfermeira": "enfermeiro",
    "enfermeiras": "enfermeiros",
    "engenheira": "engenheiro",
    "engenheiras": "engenheiros",
    "estagiaria": "estagiário",
    "estagiarias": "estagiários",
    "focada": "focado",
    "graduanda": "graduando",
    "habilitada": "habilitado",
    "indicada": "indicado",
    "interessada": "interessado",
    "medica": "médico",
    "mestra": "mestre",
    "mestranda": "mestrando",
    "motivada": "motivado",
    "nela": "nele",
    "organizada": "organizado",
    "premiada": "premiado",
    "proativa": "proativo",
    "promovida": "promovido",
    "psicologa": "psicólogo",
    "reconhecida": "reconhecido",
    "selecionada": "selecionado",
    "senhora": "senhor",
    "socia": "sócio",
    "sra": "sr",
    "dra": "dr",
    "tecnica": "técnico",
    "tecnicas": "técnicos",
    "voluntaria": "voluntário",
}
"""Feminino sem acento, para o masculino. Só o que fala da pessoa: `física` é também disciplina."""

_NAO_FLEXIONAM = frozenset(
    {
        "aceleradora",
        "controladora",
        "distribuidora",
        "incubadora",
        "seguradora",
        "transportadora",
    }
)
"""Terminam em `-dora`, mas nomeiam empresa ou coisa, e não a pessoa."""

_ARTIGOS = {
    "a": "o",
    "aquela": "aquele",
    "as": "os",
    "da": "do",
    "das": "dos",
    "dessa": "desse",
    "desta": "deste",
    "essa": "esse",
    "esta": "este",
    "minha": "meu",
    "na": "no",
    "nas": "nos",
    "nessa": "nesse",
    "nesta": "neste",
    "pela": "pelo",
    "sua": "seu",
    "uma": "um",
    "umas": "uns",
}
"""Só mudam quando vêm logo antes de uma palavra flexionada: `na` sozinho não diz gênero."""

_PALAVRA = re.compile(r"[^\W\d_]+")
_MARCA_DE_GENERO = re.compile(r"(?<=\w)(?:\((?:a|as|o|os)\)|/(?:a|as)\b)")


class Troca(NamedTuple):
    inicio: int
    fim: int
    novo: str


def dobrar(texto: str) -> str:
    """Sem acento e sem caixa, com o mesmo tamanho do texto: cada posição continua valendo."""
    return "".join(_dobrar_caractere(c) for c in texto)


def _dobrar_caractere(caractere: str) -> str:
    return unicodedata.normalize("NFKD", caractere)[0].casefold()[0]


def _com_a_caixa(modelo: str, palavra: str) -> str:
    if modelo.isupper() and len(modelo) > 1:
        return palavra.upper()
    return palavra.capitalize() if modelo[:1].isupper() else palavra


def _masculino(dobrada: str) -> str | None:
    if dobrada in _FLEXOES:
        return _FLEXOES[dobrada]
    # O sufixo `-eira` de `sem_genero` também pegaria `carreira` e `primeira`: aqui é lista fechada.
    if dobrada in _NAO_FLEXIONAM or dobrada.endswith(("eira", "eiras")):
        return None
    masculina = sem_genero(dobrada)
    return masculina if masculina != dobrada else None


def trocas_de_genero(texto: str) -> list[Troca]:
    """O que muda para o texto não dizer o gênero, com as posições no próprio texto."""
    dobrado = dobrar(texto)
    trocas = [Troca(m.start(), m.end(), "") for m in _MARCA_DE_GENERO.finditer(dobrado)]
    palavras = list(_PALAVRA.finditer(dobrado))
    for indice, palavra in enumerate(palavras):
        masculina = _masculino(palavra.group())
        if masculina is None:
            continue
        trocas.append(
            Troca(palavra.start(), palavra.end(), _com_a_caixa(texto[palavra.start()], masculina))
        )
        anterior = palavras[indice - 1] if indice else None
        if (
            anterior is not None
            and anterior.group() in _ARTIGOS
            and not dobrado[anterior.end() : palavra.start()].strip()
        ):
            artigo = _com_a_caixa(
                texto[anterior.start() : anterior.end()], _ARTIGOS[anterior.group()]
            )
            trocas.append(Troca(anterior.start(), anterior.end(), artigo))
    return sorted(trocas)


def neutralizar_genero(texto: str) -> str:
    partes = []
    posicao = 0
    for inicio, fim, novo in trocas_de_genero(texto):
        partes += [texto[posicao:inicio], novo]
        posicao = fim
    partes.append(texto[posicao:])
    return "".join(partes)


def _comparavel(texto: str) -> str:
    return " ".join(dobrar(neutralizar_genero(texto)).split())


def _ocorrencias(parte: str, texto: str) -> list[int]:
    """Onde a parte começa no texto, inclusive em posições que se sobrepõem."""
    posicoes = []
    posicao = texto.find(parte)
    while posicao != -1:
        posicoes.append(posicao)
        posicao = texto.find(parte, posicao + 1)
    return posicoes


def _ha_entre(ordenadas: list[int], menor: int, maior: int) -> bool:
    indice = bisect_left(ordenadas, menor)
    return indice < len(ordenadas) and ordenadas[indice] <= maior


def _espaco_de(marcadores: int) -> tuple[int, int]:
    """O menor e o maior pedaço do original que esta quantidade de marcadores pode cobrir."""
    return marcadores, marcadores * (MAXIMO_DE_CARACTERES_POR_MARCADOR + 2)


def _partes_em_ordem(partes: list[str], texto: str) -> bool:
    """As partes aparecem em ordem, com um marcador valendo por um pedaço curto entre elas.

    Compara por posições, sem regex com curinga: o custo cresce com o texto, nunca com o número de
    combinações. `partes` vem de separar o trecho nos marcadores, e parte vazia é marcador seguido.
    """
    literais = [(indice, parte) for indice, parte in enumerate(partes) if parte]
    inicios_de_palavra = [m.start() for m in re.finditer(r"(?<!\w)", texto)]
    fins_de_palavra = [m.start() for m in re.finditer(r"(?!\w)", texto)]

    primeiro, parte = literais[0]
    menor, maior = _espaco_de(primeiro)
    alcancados = [
        posicao + len(parte)
        for posicao in _ocorrencias(parte, texto)
        if _ha_entre(inicios_de_palavra, posicao - maior, posicao - menor)
    ]
    anterior = primeiro
    for indice, parte in literais[1:]:
        menor, maior = _espaco_de(indice - anterior)
        alcancados = [
            posicao + len(parte)
            for posicao in _ocorrencias(parte, texto)
            if _ha_entre(alcancados, posicao - maior, posicao - menor)
        ]
        if not alcancados:
            return False
        anterior = indice
    menor, maior = _espaco_de(len(partes) - 1 - anterior)
    return any(_ha_entre(fins_de_palavra, fim + menor, fim + maior) for fim in alcancados)


def corresponde_ao_original(trecho: str, original: str) -> bool:
    """Confere o trecho palavra a palavra. Cada marcador vale por um pedaço curto do original.

    Trecho só com marcadores não confere: ele não mostra nada sobre o que a pessoa fez.
    """
    if len(trecho) > MAXIMO_DE_CARACTERES_NO_TRECHO:
        return False
    partes = [_comparavel(parte) for parte in MARCADOR.split(trecho)]
    if not any(_PALAVRA.search(parte) or any(c.isdigit() for c in parte) for parte in partes):
        return False
    if len(partes) - 1 > MAXIMO_DE_MARCADORES_NO_TRECHO:
        return False
    return _partes_em_ordem(partes, _comparavel(original[:MAXIMO_DE_CARACTERES_DO_PERFIL]))
