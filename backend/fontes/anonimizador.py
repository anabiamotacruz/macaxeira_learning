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
import logging
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
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Literal, NamedTuple

from backend.agente.auditoria import rastreado
from backend.agente.neutralizacao import (
    MARCADOR,
    MAXIMO_DE_CARACTERES_DO_PERFIL,
    dobrar,
    trocas_de_genero,
)
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import (
    Candidato,
    Decisao,
    EventoFluxo,
    PacoteContexto,
    TipoDecisao,
    Vaga,
)

logger = logging.getLogger(__name__)

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
    active airflow anthropic argo atividades babel bitbucket celery certificacoes circleci
    competencias complementares confluence contato crm cursos cypress datadog dbt directory
    educacional erp etl figma functions gunicorn helm hibernate hive istio jest junit keras
    kibana lambda langchain llm logstash looker matplotlib native nestjs nlp notion numpy nuxt
    openai pessoais pipeline pipelines postman premios prisma profissionais prometheus
    publicacoes pydantic pytest referencias remix salesforce sap scipy selenium sequelize
    slack snowflake streaming studio svelte tableau tailwind tecnicas tecnicos teams trino
    uvicorn visual vite webpack architect certified master solutions
    """.split()
)
"""Palavras que não identificam ninguém: numa sequência, não contam como parte de um nome."""

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
_PALAVRAS_COMUNS = frozenset(
    "ao aos as com em na nas no nos os ou para por que um uma "
    "and at by for in of on the to with".split()
)
"""Em texto todo em maiúsculas, estas palavras separam: não fazem parte de um nome."""
_MENOR_PARTE_DE_NOME = 3
_MENOR_VALOR_CONHECIDO = 4
_MAIOR_NOME_EM_PALAVRAS = 6
_MENOR_PALAVRA_EM_CAIXA_ALTA = 4

_FIM_DE_URL = r"[^\s<>\"'()\[\]{}]*"
_SUFIXOS_COMUNS = "ai|app|br|co|com|dev|edu|gg|info|invalid|io|me|net|org|pt|sh|site|tech|xyz"
_TLD = rf"(?:{_SUFIXOS_COMUNS})(?:\.[a-z]{{2}})?"
_ROTULOS = r"[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*"
_URL_COM_ESQUEMA = rf"(?:https?://|ftp://|www\.){_FIM_DE_URL}"
_URL_DE_CONTATO = re.compile(
    rf"{_URL_COM_ESQUEMA}|(?<![\w@.-]){_ROTULOS}\.{_TLD}(?![\w-])(?:/{_FIM_DE_URL})?"
)
"""O que vira contato registrado: só sufixo comum, para não registrar `os.path` como site."""
_URL = re.compile(
    rf"{_URL_COM_ESQUEMA}|(?<![\w@.-]){_ROTULOS}\.(?P<sufixo>[a-z]{{2,24}})(?![\w-])"
    rf"(?:/{_FIM_DE_URL})?"
)
"""O que sai do texto: qualquer sufixo, porque uma lista de domínios deixaria `.ninja` passar."""
_SUFIXOS_RECONHECIDOS = frozenset(_SUFIXOS_COMUNS.split("|"))
_SUFIXOS_DE_CODIGO = frozenset(
    """
    args bat c cfg class conf cpp cs css csv data doc docx dll env exe get gif go gz h html ini
    items jar java join jpeg jpg js json jsx keys kt len lock log main md name npy open path pdf
    php png ppt pptx py rb read rs run self set size so split sql svg tar text this toml ts tsx
    txt type value war write xls xlsx xml yaml yml zip
    """.split()
)
"""Arquivo e atributo de código, e não site: `README.md`, `Node.js` e `os.path` ficam no texto."""
_EMAIL = re.compile(
    r"(?<![a-z0-9._%+-])[a-z0-9._%+-]+"
    r"(?:@|\s*[(\[](?:at|arroba)[)\]]\s*|\s+(?:at|arroba)\s+)"
    r"[a-z0-9-]+"
    r"(?:(?:\.|\s*[(\[](?:dot|ponto)[)\]]\s*|\s+(?:dot|ponto)\s+)[a-z0-9-]+)+"
)
_EMAIL_COM_ESPACOS = re.compile(
    r"(?<![a-z0-9._%+-])[a-z0-9._%+-]+\s*@\s*[a-z0-9-]+"
    r"(?:(?:\.|\s+\.\s+)[a-z0-9-]+)*"
    rf"(?:\.|\s+\.\s+)(?:{_SUFIXOS_COMUNS})(?![\w-])"
)
"""Só sai do texto, e nunca vira contato: `Dev @ Stone.com` não é um endereço da pessoa."""
_APELIDO = re.compile(r"(?<![\w.@/])@[a-z0-9_][a-z0-9_.-]{1,38}(?![\w/])")
_REDES = "github|gitlab|linkedin|twitter|instagram"
_USUARIO = r"@?([a-z0-9_][a-z0-9_.-]{1,38})"
_USUARIO_DECLARADO = re.compile(
    rf"\b(?:{_REDES}|usuario|username|user|handle)\s*[:=]\s*([a-z0-9_][a-z0-9_.-]{{1,38}})"
)
_USUARIO_DITO_NA_FRASE = re.compile(
    rf"\b(?:meu|minha|my)\s+(?:{_REDES}|usuario|username|user|handle)\s+(?:e|eh|is)\s+{_USUARIO}"
)
_USUARIO_APOS_A_REDE = re.compile(
    rf"\b(?:{_REDES})\s+(?:(?:e|eh|is)\s+)?@?"
    r"((?=[a-z0-9_.-]*[a-z])(?=[a-z0-9_.-]*[\d_-])[a-z0-9_][a-z0-9_.-]{3,38})"
)
"""Sem `meu`, só o que tem forma de usuário: `github actions` continua sendo uma ferramenta."""
_NAO_E_USUARIO = frozenset(
    "aberto ativo atualizado completo privado publico active open private public".split()
)
_DOCUMENTO = re.compile(
    r"\b\d{3}[.\s]\d{3}[.\s]\d{3}[-.\s]\d{2}\b"
    r"|\b\d{1,2}\.\d{3}\.\d{3}-[\dx]\b"
    r"|\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}\b"
    r"|\b(?:cpf|cnpj|rg|cnh|pis|pasep|ctps|passaporte|passport|ssn|titulo de eleitor)\b"
    r"\s*(?:n[o.]*\s*)?[:=]?\s*[a-z0-9][a-z0-9./-]{3,}"
)
_TELEFONE = re.compile(
    r"(?<![\d/.-])(?:\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,5}){1,3}"
    r"|\(?\d{2,3}\)?[\s.-]?(?:9[\s.]?)?\d{4}[\s.-]?\d{4}"
    r"|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"
    r"|\d(?:[\s.-]\d){9,12}"
    r"|\d{10,13})(?![\d])"
)
_TELEFONE_LOCAL = re.compile(
    r"\b(?:tel|telefone|fone|celular|cel|whats|whatsapp|contato)\b\s*[:=.]?\s*(\d{4}[\s.-]?\d{4})\b"
)
_TITULO_DE_RUA = r"\b(?:dr|dra|prof|profa|sr|sra|gen|cel|cap|pe|sto|sta)\."
_NOME_DE_RUA = rf"(?:[^\n,;.]|{_TITULO_DE_RUA}){{2,60}}"
_ENDERECO = re.compile(
    rf"\b(?:rua|avenida|av\.|alameda|al\.|travessa|trav\.|rodovia|rod\.|estrada|praca)\s+{_NOME_DE_RUA}"
    r"(?:,\s*(?:n[o.]*\s*)?\d+[a-z]?)?"
    rf"|\br\.\s+(?:(?:das?|dos?|de)\s+{_NOME_DE_RUA}(?:,\s*(?:n[o.]*\s*)?\d+[a-z]?)?"
    rf"|{_NOME_DE_RUA},\s*(?:n[o.]*\s*)?\d+[a-z]?)"
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
    rf"|(?P<g>{_SEQUENCIA})\s*[(\[|,-]\s*(?:19|20)\d{{2}}\s*(?:[-–—]|\ba\b|\bate\b|\bto\b)\s*"
    r"(?:(?:19|20)\d{2}|[Aa]tual|[Hh]oje|[Pp]resente|[Pp]resent|[Cc]urrent)\b"
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
_PALAVRA_DE_NOME = r"[A-ZÀ-Ý](?:[a-zà-ÿ]+|[A-ZÀ-Ý]+)"
_SEQUENCIA_DE_NOMES = re.compile(
    rf"(?<![\w.-]){_PALAVRA_DE_NOME}"
    rf"(?:\s+(?:(?:de|do|da|dos|das|DE|DO|DA|DOS|DAS)\s+)?{_PALAVRA_DE_NOME})+(?![\w-])"
)
_LETRAS_ESPACADAS = re.compile(r"(?<![\w.-])[A-ZÀ-Ý](?:[ \t][A-Za-zÀ-ÿ]){2,}(?![\w-])")
_FIM_DE_VERBO = ("ei", "ou")
_ENTRE_PARTES_DE_NOME = re.compile(r"\s*(?:(?:de|da|do|dos|das|di|del|van|von|[A-ZÀ-Ý]\.?)\s*)*")
_INICIAIS_ANTES = re.compile(r"(?:\b[A-ZÀ-Ý]\.\s*)+(?:(?:de|da|do|dos|das)\s+)?$")
_JANELA_DAS_INICIAIS = 40
"""Só o que vem logo antes do nome: olhar a frase inteira teria custo quadrático."""
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
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SEM_MARCA_VISIVEL = frozenset("\u115f\u1160\u17b4\u17b5\u2800\u3164\uffa0")
"""Letras em branco: não são caracteres de formato, mas também não aparecem na tela."""
_ULTIMO_LATIN_1 = 0xFF
_HOMOGLIFOS = str.maketrans(
    {
        **dict(zip("АВЕКМНОРСТХЅІЈԚԜ", "ABEKMHOPCTXSIJQW", strict=True)),
        **dict(zip("аеорсухѕіјһԁԛԝѵ", "aeopcyxsijhdqwv", strict=True)),
        **dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEZHIKMNOPTYX", strict=True)),
        **dict(zip("αιοντ", "aiovt", strict=True)),
    }
)
"""Cirílico e grego iguais a letras latinas na tela. Só `_palavra_sem_homoglifos` os troca."""
_PALAVRA_QUALQUER = re.compile(r"\w+")


@lru_cache(maxsize=4096)
def _caractere_canonico(caractere: str) -> str:
    """Vazio se não aparece na tela. Largura total e afins viram ASCII: `［` é `[` para o modelo."""
    categoria = unicodedata.category(caractere)
    if categoria == "Cf" or caractere in _SEM_MARCA_VISIVEL:
        return ""
    if categoria in ("Mn", "Me"):
        return caractere
    if ord(caractere) > _ULTIMO_LATIN_1:
        compativel = unicodedata.normalize("NFKC", caractere)
        if compativel.isascii():
            return compativel
    return caractere


def _palavra_sem_homoglifos(achado: re.Match[str]) -> str:
    """Troca só o que disfarça: palavra toda em cirílico de verdade fica como está."""
    palavra = achado.group()
    trocada = palavra.translate(_HOMOGLIFOS)
    if trocada == palavra:
        return palavra
    so_homoglifos = all(c.isascii() or c in "".join(map(chr, _HOMOGLIFOS)) for c in palavra)
    return trocada if so_homoglifos or _tem_letra_latina(palavra) else palavra


def _tem_letra_latina(palavra: str) -> bool:
    return any(c.isascii() and c.isalpha() or "À" <= c <= "ÿ" for c in palavra)


def forma_canonica(texto: str) -> str:
    """Tira o que não aparece na tela e o que se passa por outra letra.

    Disfarce não pode esconder identificador: caracteres de formato e de tag, seletores de variação,
    marcas soltas, largura total e homóglifos saem antes de qualquer procura.
    """
    sem_controle = _CONTROLE.sub("", texto)
    if sem_controle.isascii():
        return sem_controle
    visivel = "".join(map(_caractere_canonico, sem_controle))
    composto = unicodedata.normalize("NFC", visivel)
    sem_marcas = "".join(c for c in composto if unicodedata.category(c) not in ("Mn", "Me"))
    return _PALAVRA_QUALQUER.sub(_palavra_sem_homoglifos, sem_marcas)


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


def _parece_endereco(url: str, sufixo: str | None) -> bool:
    """Decide por forma, sem lista de domínios, e deixa de fora arquivo e atributo de código."""
    if sufixo is None or "/" in url:
        return True
    if dobrar(url) in _DOMINIOS_TECNICOS:
        return False
    if sufixo in _SUFIXOS_RECONHECIDOS:
        return True
    # `fim.Depois` é uma frase sem espaço depois do ponto, não um endereço.
    escrito = url[-len(sufixo) :]
    return sufixo not in _SUFIXOS_DE_CODIGO and not (escrito[0].isupper() and escrito[1:].islower())


def _pedacos_de_endereco(url: str) -> list[str]:
    """Como a pessoa pode citar o próprio site: sem protocolo, pelo nome e pelo usuário."""
    sem_protocolo = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.strip(), flags=re.I).rstrip("/")
    host, _, caminho = sem_protocolo.partition("/")
    pedacos = [sem_protocolo, host]
    if dobrar(host) not in _REDES_DE_PERFIL and "." in host:
        pedacos.append(host.split(".")[0])
    pedacos += [p for p in caminho.split("/") if any(c.isdigit() for c in p)]
    return [p for p in pedacos if p]


def _o_que_atravessa_frases(texto: str) -> list[tuple[int, int, Categoria]]:
    """Endereços e e-mails com espaços, procurados no texto inteiro, em ordem e sem sobreposição."""
    dobrado = dobrar(texto)
    achados: list[tuple[int, int, Categoria]] = []
    for padrao, categoria in (
        (_ENDERECO, Categoria.ENDERECO),
        (_EMAIL_COM_ESPACOS, Categoria.EMAIL),
    ):
        for achado in padrao.finditer(dobrado):
            fim = achado.end()
            while fim > achado.start() and dobrado[fim - 1] in " .":
                fim -= 1
            achados.append((achado.start(), fim, categoria))
    achados.sort(key=lambda achado: achado[:2])
    sem_sobrepor: list[tuple[int, int, Categoria]] = []
    for achado in achados:
        if not sem_sobrepor or achado[0] >= sem_sobrepor[-1][1]:
            sem_sobrepor.append(achado)
    return sem_sobrepor


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
    for achado in _URL_DE_CONTATO.finditer(dobrado):
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
        if len(texto) > MAXIMO_DE_CARACTERES_DO_PERFIL:
            logger.warning("perfil cortado no limite de tamanho: %s", candidato_id)
        self.fonte = forma_canonica(texto[:MAXIMO_DE_CARACTERES_DO_PERFIL])
        self._atravessam_frases = _o_que_atravessa_frases(self.fonte)
        self._preservar_valores = {" ".join(dobrar(p).split()) for p in preservar}
        self._preservar_palavras = {
            palavra for p in self._preservar_valores for palavra in re.findall(r"\w+", p)
        }
        self._preservados = 0
        self._nome_principal = next((n.strip() for n in identificadores.nomes if n.strip()), "")
        self._conhecidos = self._preparar(identificadores)
        self._partes_do_nome, self._partes_curtas, self._nome_espacado = self._preparar_nomes(
            identificadores
        )

    @property
    def preservados(self) -> int:
        return self._preservados

    def _nomes_no_texto(self) -> list[str]:
        return [m.group("nome") for m in _NOME_DECLARADO.finditer(self.fonte)]

    def _preparar_nomes(
        self, identificadores: Identificadores
    ) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None, re.Pattern[str] | None]:
        longas: set[str] = set()
        curtas: set[str] = set()
        for nome in (*identificadores.nomes, *self._nomes_no_texto()):
            for parte in re.findall(r"[^\W\d_]+", forma_canonica(nome)):
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

        espacadas = "|".join(
            r"\s+".join(re.escape(letra) for letra in parte)
            for parte in sorted(longas, key=len, reverse=True)
        )
        espacado = re.compile(rf"(?<!\w)(?:{espacadas})(?!\w)") if espacadas else None
        return regex(longas), regex(curtas), espacado

    def _preparar(
        self, identificadores: Identificadores
    ) -> list[tuple[re.Pattern[str], Categoria, str]]:
        """Valor conhecido e o que deriva dele: usuário da URL e parte local do e-mail."""
        conhecidos: dict[tuple[Categoria, str], str] = {}
        for categoria, valor in identificadores.valores:
            if categoria not in (Categoria.LINK, Categoria.PERFIL):
                conhecidos.setdefault((categoria, dobrar(valor)), valor)
            else:
                for pedaco in _pedacos_de_endereco(valor):
                    conhecidos.setdefault((categoria, dobrar(pedaco)), pedaco)
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

    def _achados(self, frase: str, deslocamento: int = 0) -> list[Achado]:
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
        self._incluir_o_que_atravessa_frases(deslocamento, len(frase), incluir)
        for achado in _EMAIL.finditer(dobrada):
            incluir(achado.start(), achado.end(), Categoria.EMAIL, None)
        for achado in _URL.finditer(dobrada):
            fim = achado.start() + len(achado.group().rstrip(".,;:!?"))
            url = frase[achado.start() : fim]
            if not _parece_endereco(url, achado.group("sufixo")):
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
        for padrao in (_USUARIO_DECLARADO, _USUARIO_DITO_NA_FRASE, _USUARIO_APOS_A_REDE):
            for achado in padrao.finditer(dobrada):
                usuario = achado.group(1).rstrip(".-")
                if usuario not in TERMOS_TECNICOS and usuario not in _NAO_E_USUARIO:
                    incluir(achado.start(1), achado.start(1) + len(usuario), Categoria.PERFIL, None)
        for achado in _APELIDO.finditer(dobrada):
            fim = achado.start() + len(achado.group().rstrip(".-"))
            incluir(achado.start(), fim, Categoria.PERFIL, None)
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
        comeco = len(frase) - len(frase.lstrip())
        for achado in _SEQUENCIA_DE_NOMES.finditer(frase):
            self._incluir_sequencia(achado, comeco, incluir)
        for achado in _LETRAS_ESPACADAS.finditer(frase):
            if self._generalizavel(Categoria.NOME, achado.group()):
                incluir(achado.start(), achado.end(), Categoria.NOME, None)
        for inicio, fim, novo in trocas_de_genero(frase):
            incluir(inicio, fim, None, novo)
        return achados

    def _incluir_o_que_atravessa_frases(
        self, deslocamento: int, tamanho: int, incluir: Callable
    ) -> None:
        """O ponto de `R. das Flores` e de `gmail . com` corta a frase no meio do identificador."""
        fim_da_frase = deslocamento + tamanho
        primeiro = max(0, bisect_left(self._atravessam_frases, (deslocamento,)) - 1)
        for inicio, fim, categoria in self._atravessam_frases[primeiro:]:
            if inicio >= fim_da_frase:
                break
            if fim > deslocamento:
                incluir(
                    max(inicio, deslocamento) - deslocamento,
                    min(fim, fim_da_frase) - deslocamento,
                    categoria,
                    None,
                )

    def _incluir_nomes(self, frase: str, dobrada: str, incluir: Callable) -> None:
        for padrao, texto in (
            (self._partes_do_nome, dobrada),
            (self._partes_curtas, frase),
            (self._nome_espacado, dobrada),
        ):
            if padrao is None:
                continue
            for achado in padrao.finditer(texto):
                inicio = achado.start()
                comeco_da_janela = max(0, inicio - _JANELA_DAS_INICIAIS)
                iniciais = _INICIAIS_ANTES.search(frase, comeco_da_janela, inicio)
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

    def _incluir_sequencia(self, achado: re.Match[str], comeco: int, incluir: Callable) -> None:
        """Cada pedaço da sequência sem palavra técnica é um nome: `Gerente Carlos Souza`."""
        corrida: list[re.Match[str]] = []

        def fechar() -> None:
            while corrida and dobrar(corrida[-1].group()) in _PARTICULAS:
                corrida.pop()
            proprias = [p.group() for p in corrida if dobrar(p.group()) not in _PARTICULAS]
            todas_em_caixa_alta = all(p.isupper() for p in proprias)
            curtas_demais = todas_em_caixa_alta and all(
                len(p) < _MENOR_PALAVRA_EM_CAIXA_ALTA for p in proprias
            )
            if len(proprias) >= 2 and not curtas_demais:
                inicio = achado.start() + corrida[0].start()
                fim = achado.start() + corrida[-1].end()
                valor = achado.string[inicio:fim]
                if self._generalizavel(Categoria.NOME, valor):
                    incluir(inicio, fim, Categoria.NOME, None)
            corrida.clear()

        for palavra in re.finditer(r"\S+", achado.group()):
            dobrada = dobrar(palavra.group())
            # Verbo no início da frase não é nome: `Criei Dashboards` não fala de ninguém.
            verbo = (
                achado.start() == comeco
                and palavra.start() == 0
                and dobrada.endswith(_FIM_DE_VERBO)
            )
            if verbo or dobrada in TERMOS_TECNICOS or dobrada in _PALAVRAS_COMUNS:
                fechar()
            elif corrida or dobrada not in _PARTICULAS:
                corrida.append(palavra)
                if len(corrida) >= _MAIOR_NOME_EM_PALAVRAS:
                    fechar()
        fechar()

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
        achados = self._unir_partes_do_nome(trecho, self._achados(trecho, inicio))
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
