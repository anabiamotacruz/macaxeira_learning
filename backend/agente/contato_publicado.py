"""Convite de quem veio da busca real pelo e-mail que a própria pessoa publicou (decisão de 8/11).

Constituição VII: o contato direto usa só um contato que a pessoa publicou, diz de onde ele veio
e por quê, e traz a forma de não ser mais contatada, que vale para sempre. Contato inferido ou
vindo de provedor (`contato_origem` marcado como não publicado) nunca serve. Nada aqui usa modelo:
a abertura é a de `backend/contato/email_inicial.py`, e o resto é texto fixo.
"""

import re
from datetime import UTC, datetime, time

from backend.contato.canal import MotivoSemCanal
from backend.contato.email_inicial import (
    CANAL_EMAIL,
    TENTATIVA_LEMBRETE,
    ContatoPublicado,
    paragrafo_lembrete,
    paragrafo_padrao,
)
from backend.contato.prompts import AVISO_SIMULACAO, MARCADOR_NOME, PALAVRA_SAIDA
from backend.contratos.modelos import Analise, Candidato, Vaga

BOTAO_SAIDA = "Não quero mais contato"
"""O mesmo rótulo do botão da caixa simulada, que registra o opt-out da pessoa."""
CONFIANCA_INFERIDA = "inferido"
_EMAIL = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+")
_URL = re.compile(r"https?://[^\s<>\"']+")


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
    """O e-mail que a pessoa publicou, com a página de origem. `None` se não houver os dois."""
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


def mensagem_pelo_contato_publicado(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise | None,
    contato: ContatoPublicado,
    link: str | None,
    tentativa: int,
) -> str:
    """E-mail com o motivo, a origem do contato e a saída. Sem modelo e sem dado do perfil além do
    nome e dos critérios atendidos que a análise conferiu."""
    empresa = vaga.empresa_id
    if tentativa >= TENTATIVA_LEMBRETE:
        abertura = paragrafo_lembrete(vaga, empresa)
    elif analise is None:
        abertura = f"Olá, {MARCADOR_NOME}! A {empresa} tem uma vaga de {vaga.titulo}."
    else:
        abertura = paragrafo_padrao(vaga, analise, empresa)
    if link:
        proximo = f"Se tiver interesse, agende uma conversa por aqui: {link}"
    else:
        proximo = "Se tiver interesse, responda este e-mail e a equipe combina a conversa."
    data = contato.coletado_em.strftime("%d/%m/%Y")
    return "\n\n".join(
        [
            abertura.replace(MARCADOR_NOME, candidato.nome),
            proximo,
            f"Por que você recebeu este e-mail: a {empresa} encontrou este endereço em "
            f"{contato.descricao_origem} ({contato.url_origem}), em {data}, publicado por você. "
            "Escrevemos porque o seu perfil profissional público combina com esta vaga, e "
            "guardamos só dados profissionais públicos para falar sobre ela.",
            f'Para não receber mais contatos, use o botão "{BOTAO_SAIDA}" ou responda '
            f"{PALAVRA_SAIDA}. O pedido vale para sempre, em todas as vagas da {empresa}.",
            AVISO_SIMULACAO,
        ]
    )
