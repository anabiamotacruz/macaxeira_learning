"""Convite de quem veio da busca real pelo e-mail que a própria pessoa publicou (decisão de 8/11).

Constituição VII: o contato direto usa só um contato que a pessoa publicou, diz de onde ele veio
e por quê, e traz a forma de não ser mais contatada, que vale para sempre. Contato inferido ou
vindo de provedor (`contato_origem` marcado como não publicado) nunca serve. Nada aqui usa modelo:
o texto e o HTML saem de `backend/contato/convite_html.py`, com o mesmo conteúdo.
"""

import re
import threading
from datetime import UTC, datetime, time
from typing import Protocol

from backend.contato.canal import MotivoSemCanal
from backend.contato.convite_html import ConteudoConvite, destaques, texto_convite
from backend.contato.email_inicial import (
    CANAL_EMAIL,
    TENTATIVA_LEMBRETE,
    ContatoPublicado,
    paragrafo_lembrete,
)
from backend.contato.prompts import MARCADOR_NOME
from backend.contratos.modelos import Analise, Candidato, Vaga
from backend.fontes.provedores.envoapi import email_valido, url_perfil_linkedin, usuario_de

ORIGEM_AUTORIZACAO_PELO_ACEITE = "aceite do convite enviado ao contato publicado"
"""De onde vem a autorização de quem aceitou o convite: fica no evento da vaga."""
CONFIANCA_INFERIDA = "inferido"
_EMAIL = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+")
_URL = re.compile(r"https?://[^\s<>\"']+")
USUARIO_LINKEDIN = "usuario_linkedin"
"""Gravado pela LinkdAPI: é por ele que a EnvoAPI acha o perfil."""
EMAIL_PUBLICADO_ENVO = "email_publicado_envo"
"""Só o fluxo grava este atributo, com o resultado guardado da EnvoAPI. O que vier da fonte cai."""
DESCRICAO_ORIGEM_LINKEDIN = "seu perfil público do LinkedIn"


class BuscadorContato(Protocol):
    """`BuscadorContatoEnvo`, de `backend/fontes/provedores/envoapi.py`."""

    def emails_publicados(self, usuario_ou_url: str) -> list[str]: ...


class ContatoPorEmpresa:
    """Consulta o e-mail publicado uma vez por empresa e pessoa, e guarda o resultado.

    Cada consulta custa um crédito, mesmo vazia. A trava segura a consulta: duas vagas da mesma
    empresa não pagam pela mesma pessoa ao mesmo tempo. Falha também fica guardada, como vazia.
    """

    def __init__(self, buscador: BuscadorContato) -> None:
        self._buscador = buscador
        self._guardados: dict[tuple[str, str], list[str]] = {}
        self._trava = threading.Lock()

    def __repr__(self) -> str:
        return f"ContatoPorEmpresa(guardados={len(self._guardados)})"

    def emails_publicados(self, empresa_id: str, usuario: str) -> list[str]:
        chave = (empresa_id, usuario)
        with self._trava:
            if chave in self._guardados:
                return list(self._guardados[chave])
            self._guardados[chave] = []
            emails = [e for e in self._buscador.emails_publicados(usuario) if email_valido(e)]
            self._guardados[chave] = emails
            return list(emails)


def usuario_para_consulta(candidato: Candidato) -> str | None:
    """O usuário do LinkedIn no formato aceito, ou `None`: sem ele, nada é consultado."""
    return usuario_de(candidato.atributos.get(USUARIO_LINKEDIN, ""))


def _contato_envo(candidato: Candidato) -> tuple[str, str] | None:
    """E-mail que a pessoa publicou no LinkedIn, achado pela EnvoAPI, e a página do perfil."""
    email = email_valido(candidato.atributos.get(EMAIL_PUBLICADO_ENVO, ""))
    usuario = usuario_para_consulta(candidato)
    if email is None or usuario is None:
        return None
    return email, url_perfil_linkedin(usuario)


def _url_de_origem(candidato: Candidato) -> str | None:
    """A página onde a pessoa publicou o contato: a origem do registro ou a URL coletada."""
    for valor in (candidato.origem, candidato.atributos.get("url", "")):
        url = valor.strip()
        if _URL.fullmatch(url):
            return url
    return None


def _email_publicado(candidato: Candidato) -> str | None:
    """Só o e-mail que a pessoa publicou. Qualquer marca de procedência ou inferência o descarta."""
    atributos = candidato.atributos
    if "contato_origem" in atributos or atributos.get("confianca") == CONFIANCA_INFERIDA:
        return None
    email = atributos.get("email", "").strip()
    return email if _EMAIL.fullmatch(email) else None


def _coletado_em(candidato: Candidato) -> datetime:
    texto = candidato.atributos.get("coletado_em", "")
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        momento = None
    if momento is None or momento.tzinfo is None:
        return datetime.combine(candidato.atualizado_em, time(), tzinfo=UTC)
    return momento


def contato_publicado(candidato: Candidato) -> ContatoPublicado | None:
    """O e-mail que a pessoa publicou, com a página de origem. `None` se não houver os dois.

    O e-mail da EnvoAPI vale mesmo com o perfil marcado como inferido: a marca é do perfil, e o
    endpoint de contato devolve só o que a pessoa publicou no LinkedIn.
    """
    envo = _contato_envo(candidato)
    if envo is not None:
        return ContatoPublicado(
            canal=CANAL_EMAIL,
            endereco=envo[0],
            url_origem=envo[1],
            descricao_origem=DESCRICAO_ORIGEM_LINKEDIN,
            coletado_em=_coletado_em(candidato),
            publicado_para_contato=True,
        )
    email = _email_publicado(candidato)
    url = _url_de_origem(candidato)
    if email is None or url is None:
        return None
    return ContatoPublicado(
        canal=CANAL_EMAIL,
        endereco=email,
        url_origem=url,
        descricao_origem=candidato.fonte,
        coletado_em=_coletado_em(candidato),
        publicado_para_contato=True,
    )


def motivo_sem_contato(candidato: Candidato) -> MotivoSemCanal:
    """Por que não há convite: sem e-mail publicado pela pessoa, ou e-mail sem página de origem."""
    if _email_publicado(candidato) is not None and _url_de_origem(candidato) is None:
        return MotivoSemCanal.CONTATO_SEM_ORIGEM
    return MotivoSemCanal.SEM_CONTATO_PUBLICADO


def conteudo_pelo_contato_publicado(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise | None,
    contato: ContatoPublicado,
    link: str | None,
    tentativa: int,
    *,
    simulado: bool = True,
) -> ConteudoConvite:
    """O que o convite diz, para o texto e o HTML. Sem modelo e sem dado do perfil além do nome e
    das competências com nota de pelo menos 0,6 na análise."""
    empresa = vaga.empresa_id
    lembrete = None
    if tentativa >= TENTATIVA_LEMBRETE:
        lembrete = paragrafo_lembrete(vaga, empresa).replace(MARCADOR_NOME, candidato.nome)
    return ConteudoConvite(
        empresa=empresa,
        titulo_vaga=vaga.titulo,
        nome=candidato.nome,
        destaques=destaques(analise),
        link=link,
        descricao_origem=contato.descricao_origem,
        url_origem=contato.url_origem,
        data_coleta=contato.coletado_em.strftime("%d/%m/%Y"),
        simulado=simulado,
        lembrete=lembrete,
    )


def mensagem_pelo_contato_publicado(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise | None,
    contato: ContatoPublicado,
    link: str | None,
    tentativa: int,
    *,
    simulado: bool = True,
) -> str:
    """E-mail com o motivo, a origem do contato e a saída. O aviso de simulação vai só no simulado.

    O texto sai do mesmo conteúdo do HTML (`conteudo_pelo_contato_publicado`).
    """
    conteudo = conteudo_pelo_contato_publicado(
        vaga, candidato, analise, contato, link, tentativa, simulado=simulado
    )
    return texto_convite(conteudo)
