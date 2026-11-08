"""Cobertura de canal: quantas pessoas do conjunto o produto conseguiria contatar.

O contato direto só vale por endereço que a própria pessoa publicou para ser
contatada, com a URL de onde ele veio. Quem decide isso em produção é
`_conferir_contato`, em `backend/contato/email_inicial.py`, que exige
`publicado_para_contato` e `url_origem`. Este módulo lê o `Candidato` do
contrato, diz em que situação cada pessoa está diante dessa exigência e agrega a
taxa, para o relatório mostrar o tamanho do gargalo em vez de escondê-lo.

Um atributo `email` sozinho não é canal publicado: sem a URL de origem o portão
recusa, e `tests/avaliacoes/test_canal.py` prova isso chamando a função real.

A medição é por pessoa, não por caso: as duplicatas do gerador são a mesma
pessoa e dobrariam o denominador.
"""

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from enum import StrEnum

from pydantic import NonNegativeInt, model_validator

from avaliacoes.casos import Caso
from avaliacoes.metricas import Taxa, medir_taxa
from backend.contato.email_inicial import CANAL_EMAIL, ContatoPublicado
from backend.contratos.modelos import Candidato, Contrato
from backend.fontes.banco_talentos import ESTADOS_BUSCAVEIS

CHAVE_DE_ENDERECO = "email"
"""Atributo do perfil que guarda o endereço de e-mail."""

CHAVE_DE_URL_DE_ORIGEM = "email_url_origem"
"""Atributo que guardaria a URL pública onde a pessoa publicou o endereço.

Nenhum perfil de `dados/gerador.py` traz esta chave hoje. A métrica existe para
esse vazio virar número em vez de passar despercebido.
"""


class SituacaoCanal(StrEnum):
    """Situação de uma pessoa diante da exigência de contato publicado."""

    PUBLICADO = "publicado"
    """Tem endereço e URL de origem: passaria em `_conferir_contato`."""

    ENDERECO_SEM_ORIGEM = "endereco_sem_origem"
    """Tem endereço, mas não a URL de onde a pessoa o publicou. O portão recusa."""

    SEM_ENDERECO = "sem_endereco"
    """Não há endereço nenhum para contatar."""

    SUPRIMIDO = "suprimido"
    """Opt-out ou autorização inválida: não se chega a perguntar pelo canal."""


def _texto(candidato: Candidato, chave: str) -> str:
    return candidato.atributos.get(chave, "").strip()


def endereco_do_candidato(candidato: Candidato) -> str:
    """Endereço de e-mail declarado no perfil, ou vazio."""
    return _texto(candidato, CHAVE_DE_ENDERECO)


def url_de_origem_do_candidato(candidato: Candidato) -> str:
    """URL onde a pessoa publicou o endereço, ou vazio. Nunca é inferida."""
    return _texto(candidato, CHAVE_DE_URL_DE_ORIGEM)


def _suprimido(candidato: Candidato, *, hoje: date) -> bool:
    """Opt-out, autorização ausente ou vencida, ou estado fora da busca.

    Mesma regra de `backend/fontes/funil.py`, para a métrica não contar como
    "sem canal" quem já estava fora por outro motivo.
    """
    validade = candidato.autorizacao_valida_ate
    return (
        candidato.opt_out
        or not candidato.autorizou_contato
        or validade is None
        or validade < hoje
        or candidato.estado not in ESTADOS_BUSCAVEIS
    )


def contato_do_candidato(candidato: Candidato) -> ContatoPublicado | None:
    """Monta o contato com o que o perfil oferece, sem inventar origem.

    Devolve `None` quando não há endereço. Quando há endereço e não há URL de
    origem, o contato sai com `publicado_para_contato` falso: é o que o perfil
    autoriza, e o portão de produção recusa.
    """
    endereco = endereco_do_candidato(candidato)
    if not endereco:
        return None
    url_origem = url_de_origem_do_candidato(candidato)
    return ContatoPublicado(
        canal=CANAL_EMAIL,
        endereco=endereco,
        url_origem=url_origem,
        descricao_origem=candidato.origem,
        coletado_em=datetime.combine(candidato.atualizado_em, time.min, tzinfo=UTC),
        publicado_para_contato=bool(url_origem),
    )


def situacao_do_candidato(candidato: Candidato, *, hoje: date) -> SituacaoCanal:
    """Classifica a contatabilidade da pessoa. Supressão vem antes do canal."""
    if _suprimido(candidato, hoje=hoje):
        return SituacaoCanal.SUPRIMIDO
    if not endereco_do_candidato(candidato):
        return SituacaoCanal.SEM_ENDERECO
    if not url_de_origem_do_candidato(candidato):
        return SituacaoCanal.ENDERECO_SEM_ORIGEM
    return SituacaoCanal.PUBLICADO


class CoberturaDeCanal(Contrato):
    """Cobertura de canal do conjunto, com o denominador à vista.

    `total` conta pessoas distintas e `casos_lidos` conta os casos de onde elas
    saíram. `considerados` é o denominador da taxa: o total menos quem está
    suprimido, porque para essa pessoa a pergunta sobre canal não se aplica.
    """

    por_situacao: dict[SituacaoCanal, int]
    casos_lidos: NonNegativeInt
    total: NonNegativeInt
    considerados: NonNegativeInt
    taxa_de_canal_publicado: Taxa

    @model_validator(mode="after")
    def _conferir_contagens(self) -> "CoberturaDeCanal":
        if sum(self.por_situacao.values()) != self.total:
            raise ValueError("as situações precisam somar o total de pessoas")
        suprimidos = self.por_situacao.get(SituacaoCanal.SUPRIMIDO, 0)
        if self.considerados != self.total - suprimidos:
            raise ValueError("o denominador é o total menos quem está suprimido")
        if self.taxa_de_canal_publicado.casos != self.considerados:
            raise ValueError("a taxa precisa usar o denominador declarado")
        if self.casos_lidos < self.total:
            raise ValueError("não há mais pessoas distintas do que casos lidos")
        return self


def medir_cobertura(casos: Iterable[Caso], *, hoje: date | None = None) -> CoberturaDeCanal:
    """Agrega a situação de canal das pessoas dos casos.

    Cada pessoa entra uma vez, pelo `grupo` do caso, que já junta duplicatas.
    `hoje` vale para todas; sem ele, cada caso usa a própria data.
    """
    situacoes: dict[str, SituacaoCanal] = {}
    casos_lidos = 0
    for caso in casos:
        casos_lidos += 1
        if caso.grupo in situacoes:
            continue
        situacoes[caso.grupo] = situacao_do_candidato(
            caso.candidato, hoje=hoje if hoje is not None else caso.hoje
        )

    contagem = Counter(situacoes.values())
    por_situacao = {situacao: contagem.get(situacao, 0) for situacao in SituacaoCanal}
    total = len(situacoes)
    considerados = total - por_situacao[SituacaoCanal.SUPRIMIDO]
    return CoberturaDeCanal(
        por_situacao=por_situacao,
        casos_lidos=casos_lidos,
        total=total,
        considerados=considerados,
        taxa_de_canal_publicado=medir_taxa(por_situacao[SituacaoCanal.PUBLICADO], considerados),
    )
