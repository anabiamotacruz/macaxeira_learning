"""Modelo local do que os provedores devolvem. Na integração, vira `PerfilColetado`.

Todo campo que veio de fora é dado, nunca instrução: chega limpo e sem marcadores que possam
imitar os delimitadores dos prompts.
"""

import hashlib
import json
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, runtime_checkable

from pydantic import (
    AfterValidator,
    AwareDatetime,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.agente.prompts import como_dado
from backend.contratos.modelos import Contrato, Experiencia, Texto
from backend.fontes.provedores.erros import MotivoTroca, UrlRecusada
from backend.fontes.provedores.url_segura import remover_links_proibidos, validar_forma

CONTATO_NAO_PUBLICADO: Literal["não publicado pela pessoa"] = "não publicado pela pessoa"
TAMANHO_MAXIMO_CONSULTA = 300
TAMANHO_MAXIMO_TEXTO = 20_000
_INVISIVEIS = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_ESPACOS_MANTIDOS = frozenset("\n\t")


def limpar_texto_externo(texto: str) -> str:
    """Tira caracteres invisíveis, marcadores e links proibidos. O sentido do texto fica."""
    sem_controle = "".join(
        c for c in texto if c in _ESPACOS_MANTIDOS or unicodedata.category(c) not in _INVISIVEIS
    )
    return remover_links_proibidos(como_dado(sem_controle)).strip()[:TAMANHO_MAXIMO_TEXTO]


TextoExterno = Annotated[str, AfterValidator(limpar_texto_externo)]


class ConfiancaDado(StrEnum):
    """Dado de provedor nunca é comprovado: quem comprova é a pessoa ou um documento dela."""

    DECLARADO = "declarado"
    INFERIDO = "inferido"


class ContatoColetado(Contrato):
    """Contato vindo de provedor. Não basta para contatar: a autorização continua obrigatória."""

    tipo: Literal["email"]
    valor: Texto
    origem: Literal["não publicado pela pessoa"] = CONTATO_NAO_PUBLICADO


class ItemColetado(Contrato):
    """Um achado, com a procedência completa.

    `descoberta` marca o achado que só aponta uma página a ler, como o resultado da Brave. Ele
    vive em memória durante a execução e nunca vira candidato, evidência nem registro: só o que
    vier da leitura da página fica.
    """

    provedor: Texto
    fonte: Texto
    coletado_em: AwareDatetime
    url: str | None = None
    confianca: ConfiancaDado
    nome: TextoExterno = ""
    texto: TextoExterno = ""
    atributos: dict[str, TextoExterno] = Field(default_factory=dict)
    historico: list[Experiencia] = Field(default_factory=list)
    contatos: list[ContatoColetado] = Field(default_factory=list)
    descoberta: bool = False

    @field_validator("url")
    @classmethod
    def _url_permitida(cls, url: str | None) -> str | None:
        if url is None:
            return None
        try:
            return validar_forma(url)
        except UrlRecusada as erro:  # sem copiar a URL para a mensagem de validação
            raise ValueError(erro.motivo.value) from None

    @property
    def email(self) -> str | None:
        return next((c.valor for c in self.contatos if c.tipo == "email"), None)


def _normalizar_email(email: str) -> str:
    return email.strip().casefold()


def _resumo(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def id_externo_de_url(url: str) -> str:
    return f"ext-{_resumo(f'url:{url.strip().casefold()}')[:32]}"


def id_externo_de_email(email: str) -> str:
    return f"ext-{_resumo(f'email:{_normalizar_email(email)}')[:32]}"


def id_externo(item: ItemColetado) -> str:
    """Identificador estável, sem dado pessoal à mostra. O e-mail vale mais que o endereço."""
    if item.email:
        return id_externo_de_email(item.email)
    if item.url:
        return id_externo_de_url(item.url)
    return f"ext-{_resumo(f'{item.provedor}:{item.nome}:{item.texto}')[:32]}"


class IdentidadeConsulta(Contrato):
    """O que identifica a pessoa numa consulta de enriquecimento."""

    model_config = ConfigDict(frozen=True)

    candidato_id: str | None = None
    email: str | None = None
    nome: str | None = None
    empresa: str | None = None
    local: str | None = None
    perfil: str | None = None


class ConsultaProvedor(Contrato):
    """Uma consulta só: texto livre, uma página pública ou a identidade de alguém."""

    model_config = ConfigDict(frozen=True)

    texto: str | None = Field(default=None, max_length=TAMANHO_MAXIMO_CONSULTA)
    url: str | None = None
    identidade: IdentidadeConsulta | None = None
    pagina: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _um_tipo_so(self) -> Self:
        if self.texto is not None and not self.texto.strip():
            raise ValueError("consulta de texto vazia")
        if sum(valor is not None for valor in (self.texto, self.url, self.identidade)) != 1:
            raise ValueError("informe exatamente um entre texto, url e identidade")
        return self

    def chave(self) -> str:
        """Resumo estável para cache e travas. Nunca expõe o que foi consultado."""
        identidade = self.identidade.model_dump(exclude={"candidato_id"}) if self.identidade else {}
        normalizada = {
            "texto": " ".join((self.texto or "").casefold().split()),
            "url": (self.url or "").strip(),
            "identidade": {
                k: " ".join(v.casefold().split()) for k, v in identidade.items() if v is not None
            },
            "pagina": self.pagina,
        }
        return _resumo(json.dumps(normalizada, sort_keys=True))


class RespostaProvedor(Contrato):
    """O que um provedor devolve. `itens` vazio significa não encontrado."""

    itens: list[ItemColetado] = Field(default_factory=list)
    custo_usd: float = Field(default=0.0, ge=0)


@runtime_checkable
class ProvedorDados(Protocol):
    """Um fornecedor de dados externos, atrás da cadeia.

    Falha temporária sobe como `FonteIndisponivel`, `ConnectionError` ou `TimeoutError`, para
    `com_tentativas` repetir. Falha permanente sobe como `ErroProvedor`.
    """

    nome: str

    def aceita(self, consulta: ConsultaProvedor) -> bool: ...

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        """O máximo que a consulta pode custar, para reservar o orçamento antes de chamar."""
        ...

    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor: ...


class SituacaoConsulta(StrEnum):
    ENCONTRADO = "encontrado"
    NAO_ENCONTRADO = "nao_encontrado"
    NAO_SUPORTADA = "nao_suportada"
    RECUSADA = "recusada"
    SUPRIMIDO = "suprimido"
    SEM_FONTES_EXTERNAS = "sem_fontes_externas"
    SOMENTE_SINTETICOS = "somente_sinteticos"


class Troca(Contrato):
    """Um provedor ficou para trás. `para` é None quando não havia outro."""

    de: Texto
    para: str | None
    motivo: MotivoTroca


class ResultadoCadeia(Contrato):
    """Resposta da cadeia: quem respondeu, por que houve troca e o que custou."""

    situacao: SituacaoConsulta
    provedor: str | None = None
    itens: list[ItemColetado] = Field(default_factory=list)
    trocas: list[Troca] = Field(default_factory=list)
    do_cache: bool = False
    custo_usd: float = 0.0
    suprimidos: int = 0
    cobertura_parcial: bool = False
    motivo_recusa: MotivoTroca | None = None
    descobertas_sem_leitura: int = 0
    """Descobertas cuja página não foi lida. Só a contagem: sem URL e sem texto."""
