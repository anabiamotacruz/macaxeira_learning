"""Critérios de equidade usados por todas as frentes: atributos sensíveis e flexão de gênero.

Só uma lista e uma função para cada coisa: critério da vaga, consulta e funil olham o mesmo.
Tudo aqui é determinístico. Nada usa modelo de IA.
"""

import re
import unicodedata

TERMOS_SENSIVEIS: tuple[tuple[str, ...], ...] = tuple(
    tuple(termo.split())
    for termo in (
        "age",
        "aposentada",
        "aposentado",
        "aparencia fisica",
        "asiatica",
        "asiatico",
        "birth date",
        "boa aparencia",
        "branca",
        "brancas",
        "branco",
        "brancos",
        "candomble",
        "casada",
        "casadas",
        "casado",
        "casados",
        "catolica",
        "catolico",
        "cor da pele",
        "date of birth",
        "deficiencia",
        "deficiencias",
        "deficiente",
        "deficientes",
        "disability",
        "disabled",
        "estado civil",
        "ethnicity",
        "etnia",
        "etnias",
        "evangelica",
        "evangelico",
        "female",
        "feminina",
        "feminino",
        "filha",
        "filhas",
        "filho",
        "filhos",
        "gay",
        "gender",
        "genero",
        "generos",
        "gestante",
        "gestantes",
        "gravida",
        "gravidas",
        "gravidez",
        "homem",
        "homens",
        "idade",
        "idades",
        "idosa",
        "idoso",
        "indigena",
        "jovem",
        "jovens",
        "judaica",
        "judeu",
        "lesbica",
        "lgbt",
        "lgbtqia",
        "male",
        "marital status",
        "masculina",
        "masculino",
        "maternidade",
        "men",
        "muculmana",
        "muculmano",
        "mulher",
        "mulheres",
        "nacionalidade",
        "nacionalidades",
        "nascimento",
        "nationality",
        "negra",
        "negras",
        "negro",
        "negros",
        "orientacao sexual",
        "parda",
        "pardo",
        "pcd",
        "pcds",
        "pregnant",
        "race",
        "raca",
        "racas",
        "religiao",
        "religioes",
        "religion",
        "sexo",
        "sexual orientation",
        "sexualidade",
        "sexuality",
        "solteira",
        "solteiras",
        "solteiro",
        "solteiros",
        "trans",
        "transgenero",
        "umbanda",
        "woman",
        "women",
    )
)
"""Sequências de palavras já normalizadas, em ordem alfabética."""

CAMPOS_SENSIVEIS = frozenset({"foto", "name", "nome", "photo", "sobrenome", "surname"})
"""Só valem como nome de atributo: `nome` em texto livre, como `nome da empresa`, é comum."""

EXPRESSOES_TECNICAS: tuple[tuple[str, ...], ...] = (
    ("caixa", "branca"),
    ("race", "condition"),
    ("race", "conditions"),
)
"""Expressões em que um termo sensível é só parte de um nome técnico."""

LIMITE_DE_IDADE = re.compile(
    r"\b(ate|menos de|menor de|abaixo de|maximo|maximo de|entre \d+ e) (1[6-9]|[2-9]\d) anos\b"
    r"(?! de (experiencia|atuacao|mercado|carreira))"
)
"""Sobre o texto normalizado: limite de idade escrito sem a palavra `idade`."""

MARCADORES_DE_AVISO: tuple[tuple[str, ...], ...] = (
    ("bem", "vindas"),
    ("bem", "vindos"),
    ("diversidade",),
    ("encorajamos",),
    ("equal", "opportunity"),
    ("igualdade", "de", "oportunidades"),
    ("incentivamos",),
    ("inclusao",),
    ("inclusiva",),
    ("inclusivo",),
    ("independente", "de"),
    ("independentemente", "de"),
    ("nao", "discrimina"),
    ("nao", "discriminamos"),
    ("nao", "fazemos", "distincao"),
    ("oportunidades", "iguais"),
    ("regardless", "of"),
    ("sem", "discriminacao"),
    ("sem", "distincao"),
)
"""Expressões típicas de aviso de não discriminação."""

MARCADORES_DE_RESTRICAO = frozenset(
    {
        "abaixo",
        "acima",
        "apenas",
        "ate",
        "contudo",
        "entre",
        "exceto",
        "exclusiva",
        "exclusivamente",
        "exclusivo",
        "exige",
        "exigida",
        "exigido",
        "exigimos",
        "maxima",
        "maximo",
        "mas",
        "minima",
        "minimo",
        "necessaria",
        "necessario",
        "obrigatoria",
        "obrigatorio",
        "only",
        "porem",
        "preferencia",
        "preferencialmente",
        "requisito",
        "so",
        "somente",
    }
)
"""Palavras que tiram da frase o caráter de aviso: ela passa a restringir quem pode concorrer."""

MARCADORES_DE_BENEFICIO = frozenset(
    {"auxilio", "beneficio", "beneficios", "bolsa", "creche", "licenca", "plano", "vale"}
)
"""Frase sobre benefício cita filhos ou maternidade sem restringir quem concorre."""

TERMOS_PROIBIDOS_EM_CONVERSA: tuple[tuple[str, ...], ...] = tuple(
    tuple(termo.split())
    for termo in (
        "afrodescendente",
        "biometria",
        "bissexual",
        "cadeirante",
        "cirurgia",
        "dado genetico",
        "dados geneticos",
        "divorciada",
        "divorciado",
        "doenca",
        "doencas",
        "doente",
        "engravidar",
        "filiacao partidaria",
        "filiada",
        "filiado",
        "licenca maternidade",
        "licenca paternidade",
        "mae",
        "medicamento",
        "medicamentos",
        "opiniao politica",
        "pai",
        "partido politico",
        "paternidade",
        "saude",
        "sindicalizada",
        "sindicalizado",
        "sindicato",
        "tratamento medico",
        "viuva",
        "viuvo",
    )
)
"""Além de `TERMOS_SENSIVEIS`, só para conversa com a pessoa: perguntas, respostas e feedback.

Não vale como critério da vaga: `saude` é setor de muita vaga. Numa pergunta, o erro é seguro: ela
não é feita, e o critério fica para uma pessoa."""

_IDADE_EM_CONVERSA = re.compile(
    r"\bquantos anos (voce )?tem\b"
    r"|\btenho \d{1,3} anos\b(?! (de|em|com|no|na|como|atuando|trabalhando))"
)

JULGAMENTOS_PROIBIDOS: tuple[tuple[str, ...], ...] = tuple(
    tuple(termo.split())
    for termo in (
        "carisma",
        "fit",
        "fit cultural",
        "personalidade",
        "perfil comportamental",
        "temperamento",
    )
)
"""Julgamento sobre a pessoa, sem evidência de critério: não entra em ponto a explorar."""

_SUFIXOS_DE_GENERO = (("doras", "dores"), ("dora", "dor"), ("eiras", "eiros"), ("eira", "eiro"))
_MENOR_PALAVRA_COM_SUFIXO = 6
_MASCULINOS_EM_OR = (
    "assessor auditor autor consultor diretor doutor editor gestor inspetor instrutor mentor "
    "professor redator revisor supervisor tutor"
).split()
_MASCULINOS_EM_O = (
    "arquiteto estagiario estagiário especializado formado graduado pleno tecnico técnico"
).split()
_FEMININOS = {
    **{f"{m}a": m for m in _MASCULINOS_EM_OR},
    **{f"{m}as": f"{m}es" for m in _MASCULINOS_EM_OR},
    **{f"{m[:-1]}a": m for m in _MASCULINOS_EM_O},
    **{f"{m[:-1]}as": f"{m}s" for m in _MASCULINOS_EM_O},
}


def sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def separar_palavras(texto: str) -> tuple[str, ...]:
    """Separa em palavras: sem acento e sem caixa, tratando `_` e camelCase como divisão."""
    separado = re.sub(r"([a-z])([A-Z])", r"\1 \2", sem_acento(texto))
    return tuple(re.findall(r"[^\W_]+", separado.casefold()))


def contem_termo(palavras: tuple[str, ...], termo: tuple[str, ...]) -> bool:
    tamanho = len(termo)
    return any(palavras[i : i + tamanho] == termo for i in range(len(palavras) - tamanho + 1))


def sem_genero(palavra: str) -> str:
    """Leva o feminino ao masculino, por lista fechada e pelos sufixos `-dora` e `-eira`.

    Trocar `-a` por `-o` em qualquer palavra não é seguro: misturaria `banco` e `banca`, `for`
    e `fora`. Palavra fora da lista e dos sufixos, como `advogada`, continua diferente.
    """
    if palavra in _FEMININOS:
        return _FEMININOS[palavra]
    if len(palavra) >= _MENOR_PALAVRA_COM_SUFIXO:
        for feminino, masculino in _SUFIXOS_DE_GENERO:
            if palavra.endswith(feminino):
                return palavra.removesuffix(feminino) + masculino
    return palavra


def _sem_expressoes_tecnicas(palavras: tuple[str, ...]) -> tuple[str, ...]:
    restantes = list(palavras)
    for expressao in EXPRESSOES_TECNICAS:
        tamanho = len(expressao)
        inicio = 0
        while inicio <= len(restantes) - tamanho:
            if tuple(restantes[inicio : inicio + tamanho]) == expressao:
                del restantes[inicio : inicio + tamanho]
            else:
                inicio += 1
    return tuple(restantes)


def termos_sensiveis(*textos: str) -> list[str]:
    """Os termos sensíveis citados nos textos, como `apenas homens` ou `até 30 anos`."""
    achados: set[str] = set()
    for texto in textos:
        palavras = _sem_expressoes_tecnicas(separar_palavras(texto))
        achados.update(" ".join(t) for t in TERMOS_SENSIVEIS if contem_termo(palavras, t))
        if LIMITE_DE_IDADE.search(" ".join(palavras)):
            achados.add("idade")
    return sorted(achados)


def termos_proibidos_em_conversa(*textos: str) -> list[str]:
    """Os termos sensíveis, inclusive os que só valem em conversa, como `saude` e `mae`."""
    achados = set(termos_sensiveis(*textos))
    for texto in textos:
        palavras = _sem_expressoes_tecnicas(separar_palavras(texto))
        achados.update(
            " ".join(t) for t in TERMOS_PROIBIDOS_EM_CONVERSA if contem_termo(palavras, t)
        )
        if _IDADE_EM_CONVERSA.search(" ".join(palavras)):
            achados.add("idade")
    return sorted(achados)


def julgamentos_proibidos(*textos: str) -> list[str]:
    """Citações de personalidade ou `fit cultural`, que não são critério nem evidência."""
    achados: set[str] = set()
    for texto in textos:
        palavras = separar_palavras(texto)
        achados.update(" ".join(t) for t in JULGAMENTOS_PROIBIDOS if contem_termo(palavras, t))
    return sorted(achados)


def tem_termo_sensivel(texto: str) -> bool:
    """Diz se o texto traz um termo sensível, comparando palavras inteiras, sem acento nem caixa."""
    return bool(termos_sensiveis(texto))


def campo_sensivel(campo: str) -> bool:
    """Diz se o nome do atributo identifica a pessoa: `nome` não pode ser critério."""
    palavras = separar_palavras(campo)
    return any(palavra in CAMPOS_SENSIVEIS for palavra in palavras)


def _restringe_quem_concorre(palavras: tuple[str, ...]) -> bool:
    if any(p in MARCADORES_DE_RESTRICAO or p.isdigit() for p in palavras):
        return True
    return any(contem_termo(palavras, ("para", *termo)) for termo in TERMOS_SENSIVEIS)


def e_aviso_de_nao_discriminacao(frase: str) -> bool:
    """Reconhece o aviso frase a frase: ele não pode servir de escudo para um critério."""
    palavras = separar_palavras(frase)
    if _restringe_quem_concorre(palavras):
        return False
    return any(contem_termo(palavras, marcador) for marcador in MARCADORES_DE_AVISO)


def _frases(texto: str) -> list[str]:
    return re.split(r"[.!?;\n]+", texto)


def frases_com_termo_sensivel(texto: str) -> list[tuple[str, list[str]]]:
    """Frases de um texto livre que citam dado sensível e não são aviso de não discriminação."""
    achadas = []
    for frase in _frases(texto):
        termos = termos_sensiveis(frase)
        if termos and not e_aviso_de_nao_discriminacao(frase):
            achadas.append((frase.strip(), termos))
    return achadas


def frases_restritivas(texto: str) -> list[tuple[str, list[str]]]:
    """Só as frases que restringem quem concorre, como `apenas homens` ou `até 30 anos`.

    Benefício também cita esses termos, como `auxílio-creche para filhos`, e não é critério.
    """
    achadas = []
    for frase, termos in frases_com_termo_sensivel(texto):
        palavras = separar_palavras(frase)
        if LIMITE_DE_IDADE.search(" ".join(palavras)):
            achadas.append((frase, termos))
        elif _restringe_quem_concorre(palavras) and not any(
            palavra in MARCADORES_DE_BENEFICIO for palavra in palavras
        ):
            achadas.append((frase, termos))
    return achadas
