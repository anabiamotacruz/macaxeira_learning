"""Pseudonimização do perfil antes de qualquer envio ao modelo e aos rastros.

O nome do arquivo segue o pedido da tarefa, mas o nome correto do que ele faz é pseudonimização:
precisamos reidentificar a pessoa depois, então existe um cofre com a correspondência. Pelo art. 13
da LGPD, o resultado continua sendo dado pessoal, sujeito às mesmas regras de autorização e remoção.
Nunca descreva este texto como anônimo em interface ou documento.

O que fica aqui:
- `Pseudonimizador` troca identificadores diretos sempre; a `PoliticaGeneralizacao` escolhe os
  indiretos e `CUSTOS_DA_GENERALIZACAO` diz o que cada um custa para a análise;
- `CofrePseudonimos` guarda a correspondência, isolada por empresa, fora do banco de talentos;
- `PerfilPseudonimizado` confere o trecho citado pelo modelo e o leva até a fonte original;
- `reidentificar_pacote` é o único caminho de volta: depois da decisão e com registro na auditoria.

Detecção por regra erra: nome de terceiro em minúsculas, apelido e identificador em idioma não
previsto passam. Isso reduz a exposição, sem eliminar o risco, e não substitui a revisão jurídica.
"""

import hashlib
import os
import re
import sqlite3
import unicodedata
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Literal, NamedTuple

from backend.agente.auditoria import rastreado
from backend.agente.neutralizacao import MARCADOR, dobrar, trocas_de_genero
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import (
    Candidato,
    Decisao,
    EventoFluxo,
    PacoteContexto,
    TipoDecisao,
    Vaga,
)

ETAPA_REIDENTIFICACAO = "reidentificacao"
FINALIDADE_PACOTE = "pacote_entrega"
MARCA_FORJADA = "(marca removida)"
"""O que entra no lugar de um marcador escrito no próprio texto da pessoa."""


class Categoria(StrEnum):
    PESSOA = "PESSOA"
    EMAIL = "EMAIL"
    TELEFONE = "TELEFONE"
    LINK = "LINK"
    PERFIL = "PERFIL"
    DOCUMENTO = "DOCUMENTO"
    ENDERECO = "ENDERECO"
    EMPREGADOR = "EMPREGADOR"
    INSTITUICAO = "INSTITUICAO"
    PROJETO = "PROJETO"
    DATA = "DATA"
    NOME = "NOME"


CUSTOS_DA_GENERALIZACAO: dict[Categoria, str] = {
    Categoria.EMPREGADOR: (
        "O modelo não vê porte, setor nem reputação do empregador: critério sobre tipo de empresa "
        "precisa vir de atributo confirmado ou virar pergunta à pessoa."
    ),
    Categoria.INSTITUICAO: (
        "O modelo não vê a instituição de ensino: critério sobre formação específica precisa vir "
        "de atributo confirmado. Em troca, o prestígio da instituição não pesa na nota."
    ),
    Categoria.PROJETO: (
        "O modelo não liga o projeto ao repositório nem julga pelo nome: a comprovação fica no "
        "código, pela fonte do fato, e não na leitura do modelo."
    ),
    Categoria.DATA: (
        "Só o ano fica visível: duração em meses e sobreposição entre empregos passam a ser "
        "aproximadas. Regra de tempo mínimo precisa usar atributo, não a leitura do modelo."
    ),
    Categoria.NOME: (
        "Sequência de nomes próprios fora da lista técnica vira marcador: uma tecnologia composta "
        "desconhecida pode sumir do texto e a evidência sobre ela deixa de ser citável."
    ),
}
"""O que cada generalização custa para a análise. Vai em `RelatorioPseudonimizacao.custos`."""

GENERALIZAVEIS = frozenset(CUSTOS_DA_GENERALIZACAO)
"""Só estas categorias podem ficar visíveis, por política ou por critério da vaga."""


@dataclass(frozen=True)
class PoliticaGeneralizacao:
    """Escolhe os identificadores indiretos. Nome, contato, documento e endereço não têm opção."""

    empregador: bool = True
    instituicao: bool = True
    projeto: bool = True
    nomes_proprios: bool = True
    datas: Literal["ano", "marcador", "manter"] = "ano"

    def ativa(self, categoria: Categoria) -> bool:
        return {
            Categoria.EMPREGADOR: self.empregador,
            Categoria.INSTITUICAO: self.instituicao,
            Categoria.PROJETO: self.projeto,
            Categoria.NOME: self.nomes_proprios,
            Categoria.DATA: self.datas != "manter",
        }.get(categoria, True)


@dataclass(frozen=True)
class RelatorioPseudonimizacao:
    """Quanto foi trocado e o que isso custa. Só contagens e textos fixos, nunca valores."""

    contagem: dict[Categoria, int]
    preservados_pela_vaga: int
    custos: dict[Categoria, str]


class ReidentificacaoNegada(ErroContrato):
    """Pedido de reidentificação fora do caso permitido: nada é revelado."""


class CofrePseudonimos:
    """Correspondência entre marcador e valor, por empresa e pessoa, em arquivo próprio.

    Não há listagem: quem lê precisa saber a empresa, a pessoa e o marcador. Remover a pessoa apaga
    as linhas dela. O arquivo não é criptografado: a proteção é a permissão do arquivo e o
    isolamento. Em uso real, ele precisa de criptografia em repouso e cópias com a mesma regra.
    """

    def __init__(self, caminho: str | Path = ":memory:") -> None:
        self._trava = RLock()
        self._conexao = sqlite3.connect(caminho, check_same_thread=False)
        if str(caminho) != ":memory:":
            os.chmod(caminho, 0o600)
        with self._trava, self._conexao:
            self._conexao.execute("PRAGMA secure_delete = ON")
            self._conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS pseudonimos (
                    empresa_id TEXT NOT NULL,
                    candidato_id TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    numero INTEGER NOT NULL,
                    resumo TEXT NOT NULL,
                    valor TEXT NOT NULL,
                    PRIMARY KEY (empresa_id, candidato_id, categoria, numero),
                    UNIQUE (empresa_id, candidato_id, categoria, resumo)
                )
                """
            )

    def fechar(self) -> None:
        with self._trava:
            self._conexao.close()

    def marcador(self, empresa_id: str, candidato_id: str, categoria: Categoria, valor: str) -> str:
        """O marcador do valor. O mesmo valor da mesma pessoa e empresa dá sempre o mesmo."""
        empresa_id = _exigir(empresa_id, "empresa_id")
        candidato_id = _exigir(candidato_id, "candidato_id")
        resumo = hashlib.sha256(_chave_do_valor(categoria, valor).encode()).hexdigest()
        with self._trava, self._conexao:
            linha = self._conexao.execute(
                "SELECT numero FROM pseudonimos "
                "WHERE empresa_id = ? AND candidato_id = ? AND categoria = ? AND resumo = ?",
                (empresa_id, candidato_id, categoria.value, resumo),
            ).fetchone()
            if linha is not None:
                numero = linha[0]
            else:
                ((maior,),) = self._conexao.execute(
                    "SELECT COALESCE(MAX(numero), 0) FROM pseudonimos "
                    "WHERE empresa_id = ? AND candidato_id = ? AND categoria = ?",
                    (empresa_id, candidato_id, categoria.value),
                ).fetchall()
                numero = maior + 1
                self._conexao.execute(
                    "INSERT INTO pseudonimos "
                    "(empresa_id, candidato_id, categoria, numero, resumo, valor) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (empresa_id, candidato_id, categoria.value, numero, resumo, valor),
                )
        return _texto_do_marcador(categoria, numero)

    def revelar(self, empresa_id: str, candidato_id: str, marcador: str) -> str | None:
        """O valor do marcador nesta empresa e pessoa. Use só em `reidentificar_pacote`."""
        categoria, numero = _partes_do_marcador(marcador)
        if categoria is None:
            return None
        with self._trava:
            linha = self._conexao.execute(
                "SELECT valor FROM pseudonimos "
                "WHERE empresa_id = ? AND candidato_id = ? AND categoria = ? AND numero = ?",
                (empresa_id, candidato_id, categoria.value, numero),
            ).fetchone()
        return linha[0] if linha else None

    def apagar_pessoa(self, empresa_id: str, candidato_id: str) -> int:
        """Apaga tudo da pessoa nesta empresa. Devolve quantas linhas saíram."""
        with self._trava, self._conexao:
            cursor = self._conexao.execute(
                "DELETE FROM pseudonimos WHERE empresa_id = ? AND candidato_id = ?",
                (_exigir(empresa_id, "empresa_id"), candidato_id),
            )
            return cursor.rowcount


def _exigir(valor: str, nome: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nome} é obrigatório no cofre")
    return valor.strip()


def _texto_do_marcador(categoria: Categoria, numero: int) -> str:
    return "[PESSOA]" if categoria is Categoria.PESSOA else f"[{categoria.value}_{numero}]"


def _partes_do_marcador(marcador: str) -> tuple[Categoria | None, int]:
    if marcador == "[PESSOA]":
        return Categoria.PESSOA, 1
    achado = re.fullmatch(r"\[([A-Z]+)_(\d+)\]", marcador)
    if achado is None or achado.group(1) not in Categoria.__members__:
        return None, 0
    return Categoria(achado.group(1)), int(achado.group(2))


def _chave_do_valor(categoria: Categoria, valor: str) -> str:
    """Duas escritas do mesmo valor dão a mesma chave. A pessoa tem um só marcador."""
    if categoria is Categoria.PESSOA:
        return "pessoa"
    chave = " ".join(dobrar(valor).split())
    if categoria in (Categoria.LINK, Categoria.PERFIL):
        chave = re.sub(r"^(?:https?://)?(?:www\.)?", "", chave).rstrip("/")
    if categoria is Categoria.TELEFONE:
        chave = re.sub(r"\D", "", chave)
    return chave


TERMOS_TECNICOS = frozenset(
    """
    academica academico brasil jupyter notebook dockerfile makefile agile ai ajax amazon
    analise analista android angular ansible apache
    api apis application arquitetura asp assistente aws azure backend bash big bigquery boot
    bootstrap business carreira cassandra certificacao certificado ciencia ciencias cloud
    cobol code computacao computer computing container coordenador coordenadora core css
    curriculo curso dados dashboard dashboards data database databricks dba delphi
    desenvolvedor desenvolvedora desenvolvimento design designer developer devops diretor
    diretora distribuidos django docker dot dotnet educacao elasticsearch engenharia
    engenheira engenheiro engineer engineering enterprise especialista excel experiencia
    express fastapi flask flutter formacao framework frontend fullstack gcp gerente git github
    gitlab go golang google gradle grafana graphql habilidades hadoop html http https idiomas
    infraestrutura ingles inteligencia intern java javascript jenkins jira jquery junior kafka
    kotlin kubernetes laravel learning lider linguagens linkedin linux lua machine manager
    mariadb maven mba mestrado microsoft microsservicos microservices mobile mongodb mysql neo
    net next nginx node nosql objetivo objetivos oracle pandas perfil php planner platform
    pleno portugues postgres postgresql power powerbi principal product produto profissional
    programador programadora project projeto projetos python pytorch qualidade rabbitmq rails
    react redes redis resumo rest ruby rust sass scala scrum security seguranca senior server
    service services sistema sistemas site software solidity spark spring sql sqlite sre staff
    stack summary swift tech tecnologia tecnologias tensorflow terraform testes times trabalho
    typescript ubuntu unit vue web windows workspace
    """.split()
)
"""Palavras que não identificam ninguém. Sequência com alguma delas não vira `[NOME_n]`."""

_DOMINIOS_TECNICOS = frozenset({"ado.net", "asp.net", "dot.net", "socket.io", "vb.net"})
_REDES_DE_PERFIL = (
    "behance.net",
    "dev.to",
    "dribbble.com",
    "facebook.com",
    "github.com",
    "gitlab.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "stackoverflow.com",
    "twitter.com",
    "x.com",
)
_PARTICULAS = frozenset({"da", "das", "de", "del", "di", "do", "dos", "e", "van", "von"})
_MENOR_PARTE_DE_NOME = 3
_MENOR_VALOR_CONHECIDO = 4

_FIM_DE_URL = r"[^\s<>\"'()\[\]{}]*"
_TLD = (
    r"(?:ai|app|br|co|com|dev|edu|gg|info|invalid|io|me|net|org|pt|sh|site|tech|xyz)"
    r"(?:\.[a-z]{2})?"
)
_URL = re.compile(
    rf"(?:https?://|ftp://|www\.){_FIM_DE_URL}"
    rf"|(?<![\w@.-])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.{_TLD}(?![\w-])(?:/{_FIM_DE_URL})?"
)
_EMAIL = re.compile(
    r"(?<![a-z0-9._%+-])[a-z0-9._%+-]+"
    r"(?:@|\s*[(\[](?:at|arroba)[)\]]\s*|\s+(?:at|arroba)\s+)"
    r"[a-z0-9-]+"
    r"(?:(?:\.|\s*[(\[](?:dot|ponto)[)\]]\s*|\s+(?:dot|ponto)\s+)[a-z0-9-]+)+"
)
_APELIDO = re.compile(r"(?<![\w.@/])@[a-z0-9_][a-z0-9_.-]{1,38}(?![\w/])")
_USUARIO_DECLARADO = re.compile(
    r"\b(?:github|gitlab|linkedin|twitter|instagram|usuario|username|user|handle)\s*[:=]\s*"
    r"([a-z0-9_][a-z0-9_.-]{1,38})"
)
_DOCUMENTO = re.compile(
    r"\b\d{3}[.\s]\d{3}[.\s]\d{3}[-.\s]\d{2}\b"
    r"|\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}\b"
    r"|\b(?:cpf|cnpj|rg|cnh|pis|pasep|ctps|passaporte|passport|ssn|titulo de eleitor)\b"
    r"\s*(?:n[o.]*\s*)?[:=]?\s*[a-z0-9][a-z0-9./-]{3,}"
)
_TELEFONE = re.compile(
    r"(?<![\d/.-])(?:\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,5}){1,3}"
    r"|\(?\d{2,3}\)?[\s.-]?(?:9[\s.]?)?\d{4}[\s.-]?\d{4}"
    r"|\d{10,13})(?![\d])"
)
_TELEFONE_LOCAL = re.compile(
    r"\b(?:tel|telefone|fone|celular|cel|whats|whatsapp|contato)\b\s*[:=.]?\s*(\d{4}[\s.-]?\d{4})\b"
)
_ENDERECO = re.compile(
    r"\b(?:rua|avenida|av\.|alameda|travessa|rodovia)\s+[^\n,;.]{2,60}(?:,\s*(?:n[o.]*\s*)?\d+[a-z]?)?"
    r"|\b\d{1,5}\s+\w+(?:\s+\w+)?\s+(?:street|st\.|avenue|ave\.|road|rd\.|boulevard)"
    r"|\bcep\s*[:=]?\s*\d{5}-?\d{3}\b"
    r"|\b\d{5}-\d{3}\b"
)
_MORADIA = re.compile(
    r"\b(?:moro|moradora?|resido|residente|residindo)\s+(?:em|na|no)\s+"
    r"(?P<lugar>[A-ZÀ-Ý][^\n,;.]{1,50}(?:,\s*[A-ZÀ-Ý][^\n,;.]{0,30})?)"
    r"|\bBairro\s+(?P<bairro>[A-ZÀ-Ý][^\n,;.]{1,40})"
)
_MESES = (
    "janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|"
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|fev|feb|mar|abr|apr|mai|jun|jul|ago|aug|set|sep|out|oct|nov|dez|dec"
)
_DATA = re.compile(
    rf"\b(?:\d{{1,2}}\s+de\s+)?(?:{_MESES})\.?(?:\s+de\s+|\s+|/)(?P<ano_mes>(?:19|20)\d{{2}})\b"
    r"|\b\d{1,2}[/.-]\d{1,2}[/.-](?P<ano_dma>(?:19|20)\d{2})\b"
    r"|\b(?P<ano_iso>(?:19|20)\d{2})-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/(?P<ano_ma>(?:19|20)\d{2})\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2}\b"
)
_MAIUSCULA = r"[A-ZÀ-Ý]"
_PALAVRA_PROPRIA = rf"{_MAIUSCULA}[\w&.+-]*"
_SEQUENCIA = rf"{_PALAVRA_PROPRIA}(?:\s+(?:(?:de|do|da|dos|das)\s+)?{_PALAVRA_PROPRIA}){{0,5}}"
_EMPREGADOR = re.compile(
    r"\b(?:[Tt]rabalh\w+|[Aa]tu(?:o|ei|ou|ando|ava)|[Ee]stagi\w+|[Cc]ontratad\w+|[Ff]uncion[aá]ri\w+"
    r"|[Ff]undador\w*|[Cc]ofundador\w*)\s+"
    r"(?:como\s+[^,.;\n]{1,40}?\s+)?(?:na|no|em|para|pela|pelo)\s+(?:empresa\s+)?"
    rf"(?P<a>{_SEQUENCIA})"
    rf"|\b[Ee]mpresa\s+(?P<b>{_SEQUENCIA})"
    rf"|\b(?:[Ww]ork(?:ed|ing)?|[Ee]ngineer|[Dd]eveloper|[Cc]onsultant)\s+(?:at|for)\s+(?P<c>{_SEQUENCIA})"
    rf"|(?<=\s)@\s+(?P<d>{_SEQUENCIA})"
    rf"|(?P<e>{_PALAVRA_PROPRIA}(?:\s+{_PALAVRA_PROPRIA}){{0,5}}\s+"
    r"(?:Ltda|S\.?A\.?|Inc|LLC|Corp|GmbH|Eireli)\b\.?)"
    rf"|(?<=\s)(?:na|no|pela|pelo)\s+(?:empresa\s+)?(?P<f>{_SEQUENCIA})"
)
_INSTITUICAO = re.compile(
    r"\b(?:Universidade|Faculdade|Instituto|Escola|Col[eé]gio|Centro Universit[aá]rio"
    r"|Funda[cç][aã]o|University|College|Institute|School)\b"
    rf"(?:\s+(?:(?:de|do|da|dos|das|of|the)\s+)*{_PALAVRA_PROPRIA})*"
    r"|\b(?:UF[A-Z]{1,4}|UE[A-Z]{1,4}|UNI[A-Z]{2,6}|USP|PUC(?:-[A-Z]{2,3})?|FGV|ITA|IME|MIT|Unicamp)\b"
)
_PROJETO = re.compile(
    r"\b(?:[Pp]rojeto|[Pp]roject)\s+(?:chamad[oa]\s+|named\s+|called\s+|open[- ]source\s+)?"
    rf"(?P<a>{_SEQUENCIA}|[a-z0-9]+[-_.][\w.-]+)"
    r"|\b(?:[Rr]eposit[oó]rio|[Rr]epo)\s+(?P<b>[\w.-]+)"
    r"|[\"“”`](?P<c>[A-ZÀ-Ý][^\"“”`\n]{1,50})[\"“”`]"
)
_NOME_DECLARADO = re.compile(
    r"(?:\b[Mm]eu nome [eé]|\b[Mm]e chamo|\b[Nn]ome\s*:|\b[Mm]y name is|\b[Nn]ame\s*:)\s+"
    rf"(?P<nome>{_SEQUENCIA})"
)
_SEQUENCIA_DE_NOMES = re.compile(
    r"(?<![\w.-])[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:(?:de|do|da|dos|das)\s+)?[A-ZÀ-Ý][a-zà-ÿ]+)+(?![\w-])"
)
_FIM_DE_VERBO = ("ei", "ou")
_ENTRE_PARTES_DE_NOME = re.compile(r"\s*(?:(?:de|da|do|dos|das|di|del|van|von|[A-ZÀ-Ý]\.?)\s*)*")
_INICIAIS_ANTES = re.compile(r"(?:\b[A-ZÀ-Ý]\.\s*)+(?:(?:de|da|do|dos|das)\s+)?$")
_SEPARADOR_DE_VALORES = re.compile(r"[,;|]")

_CAMPOS_POR_CATEGORIA = {
    Categoria.EMAIL: {"email", "e_mail", "e-mail"},
    Categoria.TELEFONE: {"telefone", "celular", "fone", "whatsapp", "phone"},
    Categoria.LINK: {"links", "link", "site", "blog", "url", "portfolio"},
    Categoria.PERFIL: {
        "github",
        "gitlab",
        "instagram",
        "linkedin",
        "perfis",
        "twitter",
        "usuario",
    },
    Categoria.DOCUMENTO: {"cpf", "rg", "cnh", "cnpj", "passaporte", "documento"},
    Categoria.ENDERECO: {"endereco", "cep", "bairro", "cidade", "localizacao", "local", "location"},
    Categoria.EMPREGADOR: {"empresa", "empresa_atual", "empregador", "company", "organizacao"},
    Categoria.INSTITUICAO: {"instituicao", "universidade", "faculdade", "escola", "university"},
    Categoria.PROJETO: {"projeto", "projetos", "repositorio", "repositorios"},
}
_INVISIVEIS = re.compile(r"[­͏؜᠎​-‏‪-‮⁠-⁯﻿]")


def forma_canonica(texto: str) -> str:
    """Tira caractere invisível e compõe acentos: disfarce não pode esconder identificador."""
    return unicodedata.normalize("NFC", _INVISIVEIS.sub("", texto))


@dataclass(frozen=True)
class Identificadores:
    """Valores conhecidos da pessoa, procurados no texto em qualquer caixa e acentuação."""

    nomes: tuple[str, ...] = ()
    valores: tuple[tuple[Categoria, str], ...] = ()


def identificadores_do_candidato(candidato: Candidato) -> Identificadores:
    valores: list[tuple[Categoria, str]] = []
    for campo, conteudo in candidato.atributos.items():
        nome_do_campo = dobrar(campo).strip()
        for categoria, campos in _CAMPOS_POR_CATEGORIA.items():
            if nome_do_campo in campos:
                valores += [
                    (categoria, parte.strip())
                    for parte in _SEPARADOR_DE_VALORES.split(conteudo)
                    if parte.strip()
                ]
    valores += [
        (Categoria.EMPREGADOR, experiencia.empresa.strip())
        for experiencia in candidato.historico
        if experiencia.empresa.strip()
    ]
    if candidato.origem.startswith(("http://", "https://")):
        valores.append((Categoria.PERFIL, candidato.origem))
    return Identificadores(nomes=(candidato.nome,), valores=tuple(valores))


def _usuario_em_url(url: str) -> str | None:
    """O usuário da URL de uma rede: `github.com/fulana` dá `fulana`."""
    sem_protocolo = re.sub(r"^(?:https?://)?(?:www\.)?", "", dobrar(url)).rstrip("/")
    for rede in _REDES_DE_PERFIL:
        if sem_protocolo.startswith(f"{rede}/"):
            partes = [p for p in sem_protocolo.split("/")[1:] if p and p != "in"]
            return partes[0] if partes else None
    return None


def _regex_de_valor(valor: str) -> re.Pattern[str]:
    partes = [re.escape(parte) for parte in dobrar(valor).split()]
    return re.compile(rf"(?<![\w]){r'\s+'.join(partes)}(?![\w])")


class ContatoEncontrado(NamedTuple):
    categoria: Categoria
    valor: str


def encontrar_contatos(texto: str) -> list[ContatoEncontrado]:
    """E-mails, telefones e URLs do texto, na ordem em que aparecem. Só lê: nada é buscado na rede.

    E-mail disfarçado volta à forma comum. A URL de uma rede conhecida vem como `PERFIL`.
    """
    canonico = forma_canonica(texto)
    dobrado = dobrar(canonico)
    achados: list[tuple[int, int, Categoria, str]] = []
    for achado in _EMAIL.finditer(dobrado):
        valor = re.sub(r"\s*[(\[](?:at|arroba)[)\]]\s*|\s+(?:at|arroba)\s+", "@", achado.group())
        valor = re.sub(r"\s*[(\[](?:dot|ponto)[)\]]\s*|\s+(?:dot|ponto)\s+", ".", valor)
        achados.append((achado.start(), achado.end(), Categoria.EMAIL, valor))
    for achado in _URL.finditer(dobrado):
        fim = achado.start() + len(achado.group().rstrip(".,;:!?"))
        url = canonico[achado.start() : fim]
        if dobrar(url) in _DOMINIOS_TECNICOS or _sobrepoe(achado.start(), fim, achados):
            continue
        categoria = Categoria.PERFIL if _usuario_em_url(url) else Categoria.LINK
        achados.append((achado.start(), fim, categoria, url))
    for achado in _TELEFONE.finditer(dobrado):
        digitos = sum(c.isdigit() for c in achado.group())
        if (digitos >= 10 or achado.group().startswith("+")) and not _sobrepoe(
            achado.start(), achado.end(), achados
        ):
            valor = canonico[achado.start() : achado.end()]
            achados.append((achado.start(), achado.end(), Categoria.TELEFONE, valor))
    return [ContatoEncontrado(categoria, valor) for _, _, categoria, valor in sorted(achados)]


def _sobrepoe(inicio: int, fim: int, achados: Iterable[tuple]) -> bool:
    return any(inicio < achado[1] and fim > achado[0] for achado in achados)


class Achado(NamedTuple):
    inicio: int
    fim: int
    categoria: Categoria | None
    novo: str | None
    valor: str


@dataclass(frozen=True)
class Segmento:
    """Liga um pedaço do texto enviado a um pedaço da fonte. `exato` diz que são o mesmo texto."""

    inicio: int
    fim: int
    inicio_fonte: int
    fim_fonte: int
    exato: bool


@dataclass(frozen=True)
class TrechoNaFonte:
    """Pedaço do texto original. É dado pessoal: nunca vai ao modelo nem aos rastros."""

    inicio: int
    fim: int
    texto: str = field(repr=False)


@dataclass(frozen=True)
class FrasePseudonimizada:
    texto: str
    segmentos: tuple[Segmento, ...] = field(repr=False)
    marcadores: tuple[str, ...]
    contagem: dict[Categoria, int]


@dataclass(frozen=True)
class PerfilPseudonimizado:
    """O texto que pode sair e, sem aparecer em `repr`, o caminho de volta até a fonte."""

    texto: str
    fonte: str = field(repr=False)
    segmentos: tuple[Segmento, ...] = field(repr=False)
    marcadores: tuple[str, ...]
    relatorio: RelatorioPseudonimizacao

    def localizar(self, trecho: str) -> tuple[int, int] | None:
        """Posição do trecho no texto enviado, sem contar caixa, acento e espaços repetidos."""
        alvo = " ".join(dobrar(trecho).split())
        if not alvo:
            return None
        posicoes, dobrado = _dobrado_com_posicoes(self.texto)
        for achado in re.finditer(re.escape(alvo), dobrado):
            antes = dobrado[achado.start() - 1] if achado.start() else " "
            depois = dobrado[achado.end()] if achado.end() < len(dobrado) else " "
            if not (antes.isalnum() and alvo[0].isalnum()) and not (
                depois.isalnum() and alvo[-1].isalnum()
            ):
                return posicoes[achado.start()], posicoes[achado.end() - 1] + 1
        return None

    def na_fonte(self, trecho: str) -> TrechoNaFonte | None:
        """O pedaço original do trecho. Recusa trecho que atravessa o que foi retirado do texto."""
        posicao = self.localizar(trecho)
        if posicao is None:
            return None
        inicio, fim = posicao
        cobertos = [s for s in self.segmentos if s.inicio < fim and s.fim > inicio]
        if not cobertos:
            return None
        for anterior, seguinte in zip(cobertos, cobertos[1:], strict=False):
            if self.fonte[anterior.fim_fonte : seguinte.inicio_fonte].strip():
                return None
        primeiro, ultimo = cobertos[0], cobertos[-1]
        inicio_fonte = primeiro.inicio_fonte
        if primeiro.exato:
            inicio_fonte += inicio - primeiro.inicio
        fim_fonte = ultimo.fim_fonte
        if ultimo.exato:
            fim_fonte -= ultimo.fim - fim
        return TrechoNaFonte(inicio_fonte, fim_fonte, self.fonte[inicio_fonte:fim_fonte])


def _dobrado_com_posicoes(texto: str) -> tuple[list[int], str]:
    posicoes: list[int] = []
    saida: list[str] = []
    for indice, caractere in enumerate(dobrar(texto)):
        if caractere.isspace():
            if saida and saida[-1] != " ":
                saida.append(" ")
                posicoes.append(indice)
        else:
            saida.append(caractere)
            posicoes.append(indice)
    return posicoes, "".join(saida)


class SessaoPseudonimizacao:
    """Pseudonimiza as frases de uma pessoa, com os valores conhecidos dela já preparados."""

    def __init__(
        self,
        cofre: CofrePseudonimos,
        politica: PoliticaGeneralizacao,
        empresa_id: str,
        candidato_id: str,
        texto: str,
        identificadores: Identificadores,
        preservar: Iterable[str],
    ) -> None:
        self._cofre = cofre
        self._politica = politica
        self._empresa_id = empresa_id
        self._candidato_id = candidato_id
        self.fonte = forma_canonica(texto)
        self._preservar_valores = {" ".join(dobrar(p).split()) for p in preservar}
        self._preservar_palavras = {
            palavra for p in self._preservar_valores for palavra in re.findall(r"\w+", p)
        }
        self._preservados = 0
        self._nome_principal = next((n.strip() for n in identificadores.nomes if n.strip()), "")
        self._conhecidos = self._preparar(identificadores)
        self._partes_do_nome, self._partes_curtas = self._preparar_nomes(identificadores)

    @property
    def preservados(self) -> int:
        return self._preservados

    def _nomes_no_texto(self) -> list[str]:
        return [m.group("nome") for m in _NOME_DECLARADO.finditer(self.fonte)]

    def _preparar_nomes(
        self, identificadores: Identificadores
    ) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
        longas: set[str] = set()
        curtas: set[str] = set()
        for nome in (*identificadores.nomes, *self._nomes_no_texto()):
            for parte in re.findall(r"[^\W\d_]+", nome):
                if dobrar(parte) in _PARTICULAS:
                    continue
                if len(parte) >= _MENOR_PARTE_DE_NOME:
                    longas.add(dobrar(parte))
                else:
                    curtas.add(parte)

        def regex(partes: set[str]) -> re.Pattern[str] | None:
            if not partes:
                return None
            opcoes = "|".join(re.escape(p) for p in sorted(partes, key=len, reverse=True))
            return re.compile(rf"(?<!\w)(?:{opcoes})(?!\w)")

        return regex(longas), regex(curtas)

    def _preparar(
        self, identificadores: Identificadores
    ) -> list[tuple[re.Pattern[str], Categoria, str]]:
        """Valor conhecido e o que deriva dele: usuário da URL e parte local do e-mail."""
        conhecidos: dict[tuple[Categoria, str], str] = {}
        for categoria, valor in identificadores.valores:
            if categoria not in (Categoria.LINK, Categoria.PERFIL):
                conhecidos.setdefault((categoria, dobrar(valor)), valor)
            usuario = _usuario_em_url(valor)
            if usuario:
                conhecidos.setdefault((Categoria.PERFIL, usuario), usuario)
            if categoria is Categoria.EMAIL and "@" in valor:
                local = valor.split("@", 1)[0]
                conhecidos.setdefault((Categoria.PERFIL, dobrar(local)), local)
            if categoria is Categoria.PERFIL and "/" not in valor and "." not in valor:
                conhecidos.setdefault((Categoria.PERFIL, dobrar(valor)), valor)
        ordenados = sorted(conhecidos.items(), key=lambda item: -len(item[0][1]))
        return [
            (_regex_de_valor(valor), categoria, valor)
            for (categoria, chave), valor in ordenados
            if len(chave) >= _MENOR_VALOR_CONHECIDO and chave not in TERMOS_TECNICOS
        ]

    def _visivel_pela_vaga(self, valor: str) -> bool:
        dobrado = " ".join(dobrar(valor).split())
        if dobrado in self._preservar_valores:
            return True
        palavras = re.findall(r"\w+", dobrado)
        return bool(palavras) and all(p in self._preservar_palavras for p in palavras)

    def _generalizavel(self, categoria: Categoria, valor: str) -> bool:
        """Diz se o indireto vira marcador. O critério da vaga mantém o que afeta a avaliação."""
        if not self._politica.ativa(categoria):
            return False
        if self._visivel_pela_vaga(valor):
            self._preservados += 1
            return False
        return True

    def _so_termos_tecnicos(self, valor: str) -> bool:
        return all(
            p in TERMOS_TECNICOS or p in _PARTICULAS for p in re.findall(r"\w+", dobrar(valor))
        )

    def _achados(self, frase: str) -> list[Achado]:
        dobrada = dobrar(frase)
        achados: list[Achado] = []

        def incluir(inicio: int, fim: int, categoria: Categoria | None, novo: str | None) -> None:
            # `achados` fica em ordem: basta olhar os vizinhos, mesmo em texto com muitos valores.
            posicao = bisect_left(achados, (inicio,))
            if posicao < len(achados) and achados[posicao].inicio < fim:
                return
            if posicao and achados[posicao - 1].fim > inicio:
                return
            achados.insert(posicao, Achado(inicio, fim, categoria, novo, frase[inicio:fim]))

        for achado in MARCADOR.finditer(frase):
            incluir(achado.start(), achado.end(), None, MARCA_FORJADA)
        for achado in _EMAIL.finditer(dobrada):
            incluir(achado.start(), achado.end(), Categoria.EMAIL, None)
        for achado in _URL.finditer(dobrada):
            fim = achado.start() + len(achado.group().rstrip(".,;:!?"))
            url = frase[achado.start() : fim]
            if dobrar(url) in _DOMINIOS_TECNICOS:
                continue
            categoria = Categoria.PERFIL if _usuario_em_url(url) else Categoria.LINK
            incluir(achado.start(), fim, categoria, None)
        for achado in _DOCUMENTO.finditer(dobrada):
            fim = achado.start() + len(achado.group().rstrip(".,;:/-"))
            incluir(achado.start(), fim, Categoria.DOCUMENTO, None)
        for achado in _TELEFONE.finditer(dobrada):
            digitos = sum(c.isdigit() for c in achado.group())
            if digitos >= 10 or achado.group().startswith("+"):
                incluir(achado.start(), achado.end(), Categoria.TELEFONE, None)
        for achado in _TELEFONE_LOCAL.finditer(dobrada):
            incluir(achado.start(1), achado.end(1), Categoria.TELEFONE, None)
        for achado in _USUARIO_DECLARADO.finditer(dobrada):
            incluir(achado.start(1), achado.end(1), Categoria.PERFIL, None)
        for achado in _APELIDO.finditer(dobrada):
            fim = achado.start() + len(achado.group().rstrip(".-"))
            incluir(achado.start(), fim, Categoria.PERFIL, None)
        for achado in _ENDERECO.finditer(dobrada):
            incluir(
                achado.start(), len(frase[: achado.end()].rstrip(" .")), Categoria.ENDERECO, None
            )
        for achado in _MORADIA.finditer(frase):
            grupo = "lugar" if achado.group("lugar") else "bairro"
            incluir(achado.start(grupo), achado.end(grupo), Categoria.ENDERECO, None)
        self._incluir_nomes(frase, dobrada, incluir)
        for padrao, categoria, _valor in self._conhecidos:
            for achado in padrao.finditer(dobrada):
                if categoria in GENERALIZAVEIS and not self._generalizavel(
                    categoria, achado.group()
                ):
                    continue
                incluir(achado.start(), achado.end(), categoria, None)
        self._incluir_datas(dobrada, incluir)
        for achado in _INSTITUICAO.finditer(frase):
            self._incluir_indireto(
                achado.start(), achado.end(), frase, Categoria.INSTITUICAO, incluir
            )
        for padrao, categoria in (
            (_EMPREGADOR, Categoria.EMPREGADOR),
            (_PROJETO, Categoria.PROJETO),
        ):
            for achado in padrao.finditer(frase):
                grupo = next(g for g, v in achado.groupdict().items() if v)
                self._incluir_indireto(
                    achado.start(grupo), achado.end(grupo), frase, categoria, incluir
                )
        for achado in _SEQUENCIA_DE_NOMES.finditer(frase):
            self._incluir_sequencia(achado, frase, incluir)
        for inicio, fim, novo in trocas_de_genero(frase):
            incluir(inicio, fim, None, novo)
        return achados

    def _incluir_nomes(self, frase: str, dobrada: str, incluir: Callable) -> None:
        for padrao, texto in ((self._partes_do_nome, dobrada), (self._partes_curtas, frase)):
            if padrao is None:
                continue
            for achado in padrao.finditer(texto):
                inicio = achado.start()
                iniciais = _INICIAIS_ANTES.search(frase[:inicio])
                incluir(
                    iniciais.start() if iniciais else inicio, achado.end(), Categoria.PESSOA, None
                )

    def _incluir_datas(self, dobrada: str, incluir: Callable) -> None:
        if self._politica.datas == "manter":
            return
        for achado in _DATA.finditer(dobrada):
            ano = next((v for v in achado.groupdict().values() if v), None)
            if self._politica.datas == "ano" and ano:
                incluir(achado.start(), achado.end(), Categoria.DATA, f"[ANO_{ano}]")
            else:
                incluir(achado.start(), achado.end(), Categoria.DATA, None)

    def _incluir_indireto(
        self, inicio: int, fim: int, frase: str, categoria: Categoria, incluir: Callable
    ) -> None:
        valor = frase[inicio:fim].rstrip(".,;:")
        fim = inicio + len(valor)
        if self._so_termos_tecnicos(valor) or not self._generalizavel(categoria, valor):
            return
        incluir(inicio, fim, categoria, None)

    def _incluir_sequencia(self, achado: re.Match[str], frase: str, incluir: Callable) -> None:
        valor = achado.group()
        inicio = achado.start()
        palavras = valor.split()
        # Verbo no início da frase não é nome: `Criei Dashboards` não fala de ninguém.
        if not frase[:inicio].strip() and dobrar(palavras[0]).endswith(_FIM_DE_VERBO):
            inicio += len(palavras[0]) + 1
            valor = " ".join(palavras[1:])
            palavras = palavras[1:]
        proprias = [p for p in palavras if dobrar(p) not in _PARTICULAS]
        if len(proprias) < 2 or any(dobrar(p) in TERMOS_TECNICOS for p in proprias):
            return
        if self._generalizavel(Categoria.NOME, valor):
            incluir(inicio, inicio + len(valor), Categoria.NOME, None)

    @staticmethod
    def _unir_partes_do_nome(frase: str, achados: list[Achado]) -> list[Achado]:
        """`Maria da Souza` vira um `[PESSOA]` só, e não um para cada parte do nome."""
        unidos: list[Achado] = []
        for achado in achados:
            anterior = unidos[-1] if unidos else None
            if (
                anterior is not None
                and anterior.categoria is Categoria.PESSOA
                and achado.categoria is Categoria.PESSOA
                and _ENTRE_PARTES_DE_NOME.fullmatch(frase[anterior.fim : achado.inicio])
            ):
                unidos[-1] = Achado(
                    anterior.inicio,
                    achado.fim,
                    Categoria.PESSOA,
                    None,
                    frase[anterior.inicio : achado.fim],
                )
            else:
                unidos.append(achado)
        return unidos

    def frase(self, inicio: int, fim: int) -> FrasePseudonimizada:
        """Troca o que identifica em um pedaço de `fonte`, guardando as posições de origem."""
        trecho = self.fonte[inicio:fim]
        achados = self._unir_partes_do_nome(trecho, self._achados(trecho))
        saida: list[str] = []
        segmentos: list[Segmento] = []
        marcadores: list[str] = []
        contagem: Counter[Categoria] = Counter()
        tamanho = 0

        def escrever(texto: str, de: int, ate: int, exato: bool) -> None:
            nonlocal tamanho
            saida.append(texto)
            segmentos.append(
                Segmento(tamanho, tamanho + len(texto), inicio + de, inicio + ate, exato)
            )
            tamanho += len(texto)

        posicao = 0
        for achado in achados:
            if achado.inicio > posicao:
                escrever(trecho[posicao : achado.inicio], posicao, achado.inicio, True)
            novo = self._substituto(achado)
            if achado.categoria is not None:
                contagem[achado.categoria] += 1
                marcadores.append(novo)
            escrever(novo, achado.inicio, achado.fim, False)
            posicao = achado.fim
        if posicao < len(trecho):
            escrever(trecho[posicao:], posicao, len(trecho), True)
        return FrasePseudonimizada(
            "".join(saida), tuple(segmentos), tuple(marcadores), dict(contagem)
        )

    def _substituto(self, achado: Achado) -> str:
        if achado.novo is not None:
            return achado.novo
        categoria = achado.categoria
        valor = achado.valor
        if categoria is Categoria.PESSOA and self._nome_principal:
            valor = self._nome_principal
        return self._cofre.marcador(self._empresa_id, self._candidato_id, categoria, valor)

    def montar(self, frases: Iterable[FrasePseudonimizada]) -> PerfilPseudonimizado:
        """Junta as frases aceitas, separadas por um espaço que não existe na fonte."""
        textos: list[str] = []
        segmentos: list[Segmento] = []
        marcadores: list[str] = []
        contagem: Counter[Categoria] = Counter()
        tamanho = 0
        for frase in frases:
            if textos:
                tamanho += 1
            textos.append(frase.texto)
            segmentos += [
                Segmento(s.inicio + tamanho, s.fim + tamanho, s.inicio_fonte, s.fim_fonte, s.exato)
                for s in frase.segmentos
            ]
            marcadores += frase.marcadores
            contagem.update(frase.contagem)
            tamanho += len(frase.texto)
        return PerfilPseudonimizado(
            texto=" ".join(textos),
            fonte=self.fonte,
            segmentos=tuple(segmentos),
            marcadores=tuple(dict.fromkeys(marcadores)),
            relatorio=RelatorioPseudonimizacao(
                contagem=dict(contagem),
                preservados_pela_vaga=self._preservados,
                custos={
                    categoria: custo
                    for categoria, custo in CUSTOS_DA_GENERALIZACAO.items()
                    if self._politica.ativa(categoria)
                },
            ),
        )


class Pseudonimizador:
    """Sem cofre informado, a correspondência fica em memória e some com o processo."""

    def __init__(
        self,
        cofre: CofrePseudonimos | None = None,
        politica: PoliticaGeneralizacao | None = None,
    ) -> None:
        self.cofre = CofrePseudonimos() if cofre is None else cofre
        self.politica = PoliticaGeneralizacao() if politica is None else politica

    def sessao(self, candidato: Candidato, preservar: Iterable[str] = ()) -> SessaoPseudonimizacao:
        return self.sessao_de_texto(
            candidato.empresa_id,
            candidato.id,
            candidato.perfil_texto,
            identificadores_do_candidato(candidato),
            preservar,
        )

    def sessao_de_texto(
        self,
        empresa_id: str,
        candidato_id: str,
        texto: str,
        identificadores: Identificadores,
        preservar: Iterable[str] = (),
    ) -> SessaoPseudonimizacao:
        return SessaoPseudonimizacao(
            self.cofre, self.politica, empresa_id, candidato_id, texto, identificadores, preservar
        )

    def pseudonimizar(
        self, candidato: Candidato, preservar: Iterable[str] = ()
    ) -> PerfilPseudonimizado:
        """O perfil inteiro. Para ir ao modelo, use `preparar_perfil`, que tira as instruções."""
        sessao = self.sessao(candidato, preservar)
        return sessao.montar([sessao.frase(0, len(sessao.fonte))])

    def pseudonimizar_texto(
        self,
        empresa_id: str,
        candidato_id: str,
        texto: str,
        identificadores: Identificadores,
        preservar: Iterable[str] = (),
    ) -> PerfilPseudonimizado:
        sessao = self.sessao_de_texto(empresa_id, candidato_id, texto, identificadores, preservar)
        return sessao.montar([sessao.frase(0, len(sessao.fonte))])


def termos_preservados_da_vaga(vaga: Vaga) -> list[str]:
    """O que a vaga pede: se ela cita um empregador, ele afeta a avaliação e fica visível."""
    return [
        *(c.nome for c in vaga.competencias),
        *(r.descricao for r in vaga.requisitos),
        *(r.valor_esperado for r in vaga.requisitos),
    ]


def reidentificador_do_cofre(
    pseudonimizador: Pseudonimizador,
    registrar: Callable[[EventoFluxo], None],
    relogio: Callable[[], datetime],
) -> Callable[[PacoteContexto, Candidato, Vaga, Decisao], PacoteContexto]:
    """Liga `reidentificar_pacote` à entrega do fluxo, com a auditoria do repositório."""

    def reidentificador(
        pacote: PacoteContexto, candidato: Candidato, vaga: Vaga, decisao: Decisao
    ) -> PacoteContexto:
        return reidentificar_pacote(
            pacote,
            candidato,
            vaga,
            decisao,
            pseudonimizador=pseudonimizador,
            registrar=registrar,
            momento=relogio(),
        )

    return reidentificador


@rastreado(ETAPA_REIDENTIFICACAO)
def reidentificar_pacote(
    pacote: PacoteContexto,
    candidato: Candidato,
    vaga: Vaga,
    decisao: Decisao,
    *,
    pseudonimizador: Pseudonimizador,
    registrar: Callable[[EventoFluxo], None],
    momento: datetime,
) -> PacoteContexto:
    """Devolve os dados originais ao pacote de entrega. É o único caminho de volta pelo cofre.

    Exige decisão de indicar da mesma empresa, vaga e pessoa. O registro vem antes e só traz
    marcadores: sem auditoria, nada é revelado. O resultado não pode voltar a modelo nem a rastro.
    """
    if (
        decisao.tipo is not TipoDecisao.INDICAR
        or decisao.empresa_id != pacote.empresa_id
        or decisao.vaga_id != pacote.vaga_id
        or decisao.candidato_id != pacote.candidato_id
        or candidato.id != pacote.candidato_id
        or candidato.empresa_id != pacote.empresa_id
    ):
        raise ReidentificacaoNegada("reidentificação só depois da decisão de indicar a pessoa")

    perfil = pseudonimizador.pseudonimizar(candidato, termos_preservados_da_vaga(vaga))
    textos = [
        *pacote.motivo_por_criterio.values(),
        *(e.trecho for e in pacote.evidencias),
        *pacote.lacunas,
        *pacote.pontos_a_aprofundar,
        *pacote.ressalvas_revisor,
    ]
    usados = sorted({m.group() for texto in textos for m in MARCADOR.finditer(texto)})
    registrar(
        EventoFluxo(
            empresa_id=pacote.empresa_id,
            vaga_id=pacote.vaga_id,
            candidato_id=pacote.candidato_id,
            etapa=ETAPA_REIDENTIFICACAO,
            mensagem=(
                f"finalidade={FINALIDADE_PACOTE}; regra={decisao.regra}; "
                f"responsavel={decisao.responsavel}; marcadores={','.join(usados)}"
            ),
            momento=momento,
        )
    )

    def revelar(texto: str) -> str:
        na_fonte = perfil.na_fonte(texto)
        if na_fonte is not None:
            return na_fonte.texto
        return MARCADOR.sub(
            lambda m: (
                pseudonimizador.cofre.revelar(pacote.empresa_id, candidato.id, m.group())
                or m.group()
            ),
            texto,
        )

    return pacote.model_copy(
        update={
            "motivo_por_criterio": {c: revelar(t) for c, t in pacote.motivo_por_criterio.items()},
            "evidencias": [
                e.model_copy(update={"trecho": revelar(e.trecho)}) for e in pacote.evidencias
            ],
            "lacunas": [revelar(t) for t in pacote.lacunas],
            "pontos_a_aprofundar": [revelar(t) for t in pacote.pontos_a_aprofundar],
            "ressalvas_revisor": [revelar(t) for t in pacote.ressalvas_revisor],
        }
    )
