"""Avaliação às cegas pela pessoa de RH (T1.13; spec 005, T047 a T049). Sem modelo.

A sessão sorteia casos sintéticos de ajuste e de prova, mais duplicatas, e gera fichas que não
mostram nada do que o agente ou o gerador decidiram: nem faixa, nota, decisão, explicação,
partição ou gabarito, nem nome. A ficha usa um código no lugar da pessoa.

O que liga a ficha ao caso fica em `ItemSessao`, que nunca vai para a pessoa de RH. A
concordância compara a resposta dela com o gabarito do gerador (a ponte entre os dois), por tipo
de caso, com intervalo. A lista de discordâncias só existe para casos de ajuste: da prova saem só
agregados. O resultado vale para uma pessoa, em dados sintéticos; não prova desempenho com
pessoas reais.

`Ficha` e `AvaliacaoHumana` são modelos locais: o plano da spec 005 os propõe como contratos, e
isso exige aviso às quatro frentes antes de entrar em `backend/contratos`.
"""

import random
from collections.abc import Iterable, Sequence
from enum import StrEnum
from math import sqrt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agente.medicao import Z_95, intervalo_wilson
from backend.contratos.modelos import CasoAvaliacao, Contrato, Particao, TipoDecisao

PERGUNTA = "Você encaminharia este perfil para a entrevista com a Nara?"
FICHAS_DE_AJUSTE = 12
FICHAS_DE_PROVA = 18
DUPLICATAS = 4
SEM_TIPO = "sem_tipo"
LIMITE_COMENTARIO = 200

MotivoCodigo = Literal[
    "requisito_atendido",
    "requisito_faltando",
    "evidencia_fraca",
    "perfil_suspeito",
    "dado_ausente",
    "autorizacao",
    "outro",
]


class DecisaoHumana(StrEnum):
    ENCAMINHAR = "encaminhar"
    MAIS_INFORMACAO = "mais_informacao"
    NAO_ENCAMINHAR = "nao_encaminhar"
    NAO_CONSIGO = "nao_consigo_avaliar"


EQUIVALENTE_DO_GABARITO = {
    TipoDecisao.INDICAR: DecisaoHumana.ENCAMINHAR,
    TipoDecisao.PEDIR_HUMANO: DecisaoHumana.MAIS_INFORMACAO,
    TipoDecisao.DESCARTAR: DecisaoHumana.NAO_ENCAMINHAR,
}
CATEGORIAS = tuple(EQUIVALENTE_DO_GABARITO.values())


class RespostaIncompleta(ValueError):
    """Resposta sem campo obrigatório, fora do formato ou de ficha que não está na sessão."""


class Ficha(Contrato):
    """O que a pessoa de RH vê. Nenhum campo do agente ou do gabarito."""

    model_config = ConfigDict(frozen=True)

    codigo: str
    pergunta: str
    vaga_titulo: str
    requisitos: list[str]
    competencias: list[str]
    perfil: str


class ItemSessao(BaseModel):
    """Liga o código ao caso. Fica com quem conduz a sessão; nunca vai para a ficha."""

    model_config = ConfigDict(frozen=True)

    codigo: str
    caso_id: str
    particao: Particao
    gabarito: TipoDecisao
    armadilha: str | None
    duplicata_de: str | None = None


class AvaliacaoHumana(Contrato):
    """A resposta da pessoa de RH a uma ficha (FR-M038)."""

    model_config = ConfigDict(frozen=True)

    codigo: Annotated[str, Field(min_length=1)]
    decisao: DecisaoHumana
    seguranca: Annotated[int, Field(ge=1, le=5)]
    criterio_decisivo: Annotated[str, Field(min_length=1)]
    motivo: MotivoCodigo
    comentario: Annotated[str, Field(max_length=LIMITE_COMENTARIO)] = ""
    tempo_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class Medida(Contrato):
    total: int
    concordancia: float | None
    intervalo: tuple[float, float] | None


class ResultadoConcordancia(Contrato):
    """Agregados da sessão. Caso a caso, só as discordâncias de ajuste, por código."""

    geral: Medida
    kappa: float | None
    kappa_intervalo: tuple[float, float] | None
    por_tipo: dict[str, Medida]
    ajuste: Medida
    prova: Medida
    consistencia: Medida
    excluidas: int
    discordancias_ajuste: list[str]
    limite: str = (
        "Uma pessoa de RH, em dados sintéticos: confere o gerador, não certifica o agente."
    )


def sortear(
    casos: Sequence[CasoAvaliacao],
    semente: int,
    *,
    ajuste: int = FICHAS_DE_AJUSTE,
    prova: int = FICHAS_DE_PROVA,
    duplicatas: int = DUPLICATAS,
) -> list[ItemSessao]:
    """Sorteio reproduzível pela semente: ajuste e prova pelas partições, duplicatas e ordem."""
    sorteador = random.Random(semente)
    escolhidos: list[CasoAvaliacao] = []
    for particao, quantidade in ((Particao.AJUSTE, ajuste), (Particao.PROVA, prova)):
        disponiveis = sorted((c for c in casos if c.particao == particao), key=lambda c: c.id)
        if len(disponiveis) < quantidade:
            raise ValueError(f"casos de {particao.value} insuficientes para a sessão")
        escolhidos.extend(sorteador.sample(disponiveis, quantidade))
    if duplicatas > len(escolhidos):
        raise ValueError("mais duplicatas que fichas")
    repetidos = sorteador.sample(escolhidos, duplicatas)
    ordem = [(caso, False) for caso in escolhidos] + [(caso, True) for caso in repetidos]
    sorteador.shuffle(ordem)

    codigos: dict[str, str] = {}
    itens: list[ItemSessao] = []
    pendentes: list[tuple[int, CasoAvaliacao]] = []
    for posicao, (caso, repetido) in enumerate(ordem, start=1):
        codigo = f"F{posicao:02d}"
        if repetido:
            pendentes.append((len(itens), caso))
            itens.append(_item(codigo, caso, None))
        else:
            codigos[caso.id] = codigo
            itens.append(_item(codigo, caso, None))
    for indice, caso in pendentes:
        itens[indice] = itens[indice].model_copy(update={"duplicata_de": codigos[caso.id]})
    return itens


def gerar_fichas(casos: Sequence[CasoAvaliacao], semente: int) -> list[Ficha]:
    """As fichas da sessão, na ordem sorteada (FR-M037, FR-M039)."""
    por_id = {caso.id: caso for caso in casos}
    return [_ficha(item.codigo, por_id[item.caso_id]) for item in sortear(casos, semente)]


def importar_avaliacoes(respostas: Iterable[dict]) -> list[AvaliacaoHumana]:
    """Valida cada resposta. Uma resposta incompleta recusa a importação inteira."""
    avaliacoes: list[AvaliacaoHumana] = []
    for posicao, resposta in enumerate(respostas, start=1):
        try:
            avaliacao = AvaliacaoHumana.model_validate(resposta)
        except ValidationError as erro:
            campos = sorted({str(e["loc"][0]) for e in erro.errors() if e["loc"]})
            raise RespostaIncompleta(
                f"resposta {posicao} incompleta ou fora do formato: {', '.join(campos)}"
            ) from None
        if not avaliacao.criterio_decisivo.strip():
            raise RespostaIncompleta(f"resposta {posicao} sem critério decisivo")
        avaliacoes.append(avaliacao)
    codigos = [a.codigo for a in avaliacoes]
    if len(set(codigos)) != len(codigos):
        raise RespostaIncompleta("há mais de uma resposta para a mesma ficha")
    return avaliacoes


def medir_concordancia(
    avaliacoes: Sequence[AvaliacaoHumana], sessao: Sequence[ItemSessao]
) -> ResultadoConcordancia:
    """Concordância com o gabarito, kappa com intervalo, por tipo, e consistência nas duplicatas."""
    itens = {item.codigo: item for item in sessao}
    respostas = {a.codigo: a for a in avaliacoes}
    fora = sorted(set(respostas) - set(itens))
    if fora:
        raise RespostaIncompleta(f"{len(fora)} resposta(s) de ficha que não está na sessão")

    pares: list[tuple[ItemSessao, DecisaoHumana]] = []
    excluidas = 0
    for codigo, item in itens.items():
        resposta = respostas.get(codigo)
        if item.duplicata_de is not None:
            continue
        if resposta is None or resposta.decisao == DecisaoHumana.NAO_CONSIGO:
            excluidas += 1
            continue
        pares.append((item, resposta.decisao))

    def acerto(item: ItemSessao, decisao: DecisaoHumana) -> bool:
        return EQUIVALENTE_DO_GABARITO[item.gabarito] == decisao

    por_tipo: dict[str, list[bool]] = {}
    for item, decisao in pares:
        por_tipo.setdefault(item.armadilha or SEM_TIPO, []).append(acerto(item, decisao))
    kappa, kappa_intervalo = _kappa(
        [EQUIVALENTE_DO_GABARITO[item.gabarito] for item, _ in pares],
        [decisao for _, decisao in pares],
    )
    return ResultadoConcordancia(
        geral=_medida([acerto(i, d) for i, d in pares]),
        kappa=kappa,
        kappa_intervalo=kappa_intervalo,
        por_tipo={tipo: _medida(acertos) for tipo, acertos in sorted(por_tipo.items())},
        ajuste=_medida([acerto(i, d) for i, d in pares if i.particao == Particao.AJUSTE]),
        prova=_medida([acerto(i, d) for i, d in pares if i.particao == Particao.PROVA]),
        consistencia=_consistencia(itens, respostas),
        excluidas=excluidas,
        discordancias_ajuste=sorted(
            i.codigo for i, d in pares if i.particao == Particao.AJUSTE and not acerto(i, d)
        ),
    )


def _item(codigo: str, caso: CasoAvaliacao, duplicata_de: str | None) -> ItemSessao:
    return ItemSessao(
        codigo=codigo,
        caso_id=caso.id,
        particao=caso.particao,
        gabarito=caso.gabarito,
        armadilha=caso.armadilha,
        duplicata_de=duplicata_de,
    )


def _ficha(codigo: str, caso: CasoAvaliacao) -> Ficha:
    perfil = caso.perfil.perfil_texto.replace(caso.perfil.nome, "a pessoa")
    return Ficha(
        codigo=codigo,
        pergunta=PERGUNTA,
        vaga_titulo=caso.vaga.titulo,
        requisitos=[r.descricao for r in caso.vaga.requisitos],
        competencias=[c.nome for c in caso.vaga.competencias],
        perfil=perfil,
    )


def _medida(acertos: Sequence[bool]) -> Medida:
    if not acertos:
        return Medida(total=0, concordancia=None, intervalo=None)
    erros = acertos.count(False)
    baixo, alto = intervalo_wilson(erros, len(acertos))
    return Medida(
        total=len(acertos),
        concordancia=round(1 - erros / len(acertos), 6),
        intervalo=(round(1 - alto, 6), round(1 - baixo, 6)),
    )


def _consistencia(itens: dict[str, ItemSessao], respostas: dict[str, AvaliacaoHumana]) -> Medida:
    """Mesma ficha duas vezes: as duas respostas válidas precisam coincidir."""
    acertos = []
    for codigo, item in itens.items():
        if item.duplicata_de is None:
            continue
        primeira, segunda = respostas.get(item.duplicata_de), respostas.get(codigo)
        validas = [r for r in (primeira, segunda) if r and r.decisao != DecisaoHumana.NAO_CONSIGO]
        if len(validas) == 2:
            acertos.append(validas[0].decisao == validas[1].decisao)
    return _medida(acertos)


def _kappa(
    gabarito: Sequence[DecisaoHumana], pessoa: Sequence[DecisaoHumana]
) -> tuple[float | None, tuple[float, float] | None]:
    """Kappa de Cohen, com o erro-padrão aproximado de Fleiss, Cohen e Everitt."""
    total = len(gabarito)
    if total == 0:
        return None, None
    observada = sum(g == p for g, p in zip(gabarito, pessoa, strict=True)) / total
    esperada = sum(
        (gabarito.count(categoria) / total) * (pessoa.count(categoria) / total)
        for categoria in CATEGORIAS
    )
    if esperada >= 1:
        return None, None
    kappa = (observada - esperada) / (1 - esperada)
    erro = sqrt(observada * (1 - observada) / (total * (1 - esperada) ** 2))
    intervalo = (round(max(-1.0, kappa - Z_95 * erro), 6), round(min(1.0, kappa + Z_95 * erro), 6))
    return round(kappa, 6), intervalo
