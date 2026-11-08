"""Convite por e-mail com a identidade da CORA, em texto e em HTML (decisão de 8/11).

As duas versões saem do mesmo `ConteudoConvite`, montado pelo código e sem modelo. Todo texto
variável do HTML passa por `html.escape`, e só endereços http(s) ou mailto viram link. O logo vai
como anexo inline (`cid:coral-cora`), para aparecer sem carregar imagem de fora.
"""

from html import escape
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from backend.contato.prompts import AVISO_SIMULACAO, PALAVRA_SAIDA
from backend.contratos.modelos import Analise, Convite

NOTA_MINIMA_DESTAQUE = 0.6
"""Só competência com nota a partir daqui vira destaque no convite."""
CID_LOGO = "coral-cora"
LOGO = Path(__file__).parent / "recursos" / "coral-96.png"
NOME_ANEXO_LOGO = "coral.png"
ROTULO_BOTAO = "Quero conversar sobre a vaga"
BOTAO_SAIDA = "Não quero mais contato"
MARCA = "CORA"
MARCA_EXTENSO = "Conexão de Oportunidade de Recrutamento Ativo"

LARANJA = "#fb3c0d"
PETROLEO = "#0b3038"
VERDE = "#4c8885"
FUNDO = "#f7f8f5"
BORDA = "#dfe7e2"
TEXTO = "#365650"
_ESQUEMAS_DE_LINK = ("https://", "http://", "mailto:")


class ConteudoConvite(BaseModel):
    """O que o convite diz. `lembrete` é a abertura do único lembrete, já com o nome."""

    model_config = ConfigDict(extra="forbid")

    empresa: str
    titulo_vaga: str
    nome: str
    destaques: list[str]
    link: str | None
    descricao_origem: str
    url_origem: str
    data_coleta: str
    simulado: bool
    lembrete: str | None = None


@runtime_checkable
class MensageiroDeEmail(Protocol):
    """Mensageiro que envia o e-mail de verdade: recebe o destinatário e o conteúdo."""

    def enviar(self, convite: Convite) -> bool: ...

    def enviar_email(self, convite: Convite, para: str, conteudo: ConteudoConvite) -> bool: ...


def destaques(analise: Analise | None) -> list[str]:
    """Competências com nota de pelo menos `NOTA_MINIMA_DESTAQUE`, da maior para a menor."""
    if analise is None:
        return []
    notas = sorted(analise.notas.items(), key=lambda item: -item[1])
    return [nome for nome, nota in notas if nota >= NOTA_MINIMA_DESTAQUE]


def assunto_convite(conteudo: ConteudoConvite) -> str:
    inicio = "Lembrete: vaga" if conteudo.lembrete else "Vaga"
    assunto = f"{inicio} de {conteudo.titulo_vaga} na {conteudo.empresa}"
    return f"[SIMULADO] {assunto}" if conteudo.simulado else assunto


def _abertura(conteudo: ConteudoConvite) -> str:
    if conteudo.lembrete:
        return conteudo.lembrete
    inicio = f"Olá, {conteudo.nome}! A {conteudo.empresa} tem uma vaga de {conteudo.titulo_vaga}."
    if conteudo.destaques:
        return f"{inicio} Seu perfil chamou nossa atenção por: {', '.join(conteudo.destaques)}."
    return f"{inicio} Achamos que ela pode interessar a você."


def _por_que(conteudo: ConteudoConvite) -> str:
    return (
        f"a {conteudo.empresa} encontrou este endereço em {conteudo.descricao_origem} "
        f"({conteudo.url_origem}), em {conteudo.data_coleta}, publicado por você. Escrevemos "
        "porque o seu perfil profissional público combina com esta vaga, e guardamos só dados "
        "profissionais públicos para falar sobre ela."
    )


def texto_convite(conteudo: ConteudoConvite) -> str:
    """Versão em texto: a mesma do convite gravado no fluxo."""
    if conteudo.link:
        proximo = f"Se tiver interesse, agende uma conversa por aqui: {conteudo.link}"
    else:
        proximo = "Se tiver interesse, responda este e-mail e a equipe combina a conversa."
    partes = [
        _abertura(conteudo),
        proximo,
        f"Por que você recebeu este e-mail: {_por_que(conteudo)}",
        f'Para não receber mais contatos, use o botão "{BOTAO_SAIDA}" ou responda '
        f"{PALAVRA_SAIDA}. O pedido vale para sempre, em todas as vagas da {conteudo.empresa}.",
    ]
    if conteudo.simulado:
        partes.append(AVISO_SIMULACAO)
    return "\n\n".join(partes)


def _href(url: str | None) -> str | None:
    """Endereço pronto para atributo, ou `None` se não for http(s) nem mailto."""
    if not url or not url.strip().lower().startswith(_ESQUEMAS_DE_LINK):
        return None
    return escape(url.strip(), quote=True)


def _selo(texto: str) -> str:
    return (
        '<span style="display:inline-block;background:#fff1ee;color:#a43826;'
        "border:1px solid #fbd3c7;border-radius:999px;padding:4px 12px;font-size:13px;"
        f'margin:0 6px 6px 0;">{escape(texto)}</span>'
    )


def _apresentacao(conteudo: ConteudoConvite) -> str:
    paragrafo = 'style="margin:0 0 14px 0;font-size:16px;line-height:1.55;"'
    if conteudo.lembrete:
        return f"<p {paragrafo}>{escape(conteudo.lembrete)}</p>"
    vaga = f'<strong style="color:{PETROLEO};">{escape(conteudo.titulo_vaga)}</strong>'
    inicio = f"Olá, {escape(conteudo.nome)}! A {escape(conteudo.empresa)} tem uma vaga de {vaga}"
    if not conteudo.destaques:
        return f"<p {paragrafo}>{inicio}. Achamos que ela pode interessar a você.</p>"
    selos = "".join(_selo(d) for d in conteudo.destaques)
    return (
        f"<p {paragrafo}>{inicio} e o seu perfil chamou a nossa atenção por:</p>"
        f'<p style="margin:0 0 24px 0;">{selos}</p>'
    )


def _proximo_passo(conteudo: ConteudoConvite) -> str:
    paragrafo = 'style="margin:0 0 20px 0;font-size:16px;line-height:1.55;"'
    link = _href(conteudo.link)
    if link is None:
        return (
            f"<p {paragrafo}>Se tiver interesse, responda este e-mail e a equipe combina a "
            "conversa.</p>"
        )
    if link.startswith("https://wa.me/"):
        chamada = "Se tiver interesse, a próxima conversa é rápida e pelo WhatsApp:"
    else:
        chamada = "Se tiver interesse, agende uma conversa por aqui:"
    return (
        f"<p {paragrafo}>{chamada}</p>"
        '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 28px 0;">'
        f'<tr><td style="background:{LARANJA};border-radius:8px;">'
        f'<a href="{link}" style="display:inline-block;padding:14px 30px;color:#ffffff;'
        'font-size:17px;font-weight:bold;text-decoration:none;border-radius:8px;">'
        f"{ROTULO_BOTAO}</a></td></tr></table>"
    )


def _origem(conteudo: ConteudoConvite) -> str:
    link = _href(conteudo.url_origem)
    url = escape(conteudo.url_origem)
    if link is not None:
        url = f'<a href="{link}" style="color:{VERDE};">{url}</a>'
    return (
        f"a {escape(conteudo.empresa)} encontrou este endereço em "
        f"{escape(conteudo.descricao_origem)} ({url}), em {escape(conteudo.data_coleta)}, "
        "publicado por você. Escrevemos porque o seu perfil profissional público combina com "
        "esta vaga, e guardamos só dados profissionais públicos para falar sobre ela."
    )


_TABELA = 'role="presentation" cellspacing="0" cellpadding="0"'
_CORPO = (
    f"margin:0;padding:0;background:{FUNDO};font-family:Arial,Helvetica,sans-serif;color:{TEXTO};"
)
_CAIXA = (
    "max-width:600px;width:100%;background:#ffffff;"
    f"border:1px solid {BORDA};border-radius:12px;overflow:hidden;"
)
_LOGO = 'width="40" height="40" alt="Coral da CORA" style="display:block;border:0;"'
_MARCA = "color:#ffffff;font-size:22px;font-weight:bold;line-height:1;"
_EXTENSO = "color:#d3d5d3;font-size:9px;letter-spacing:1px;text-transform:uppercase;margin-top:4px;"
_ROTULO = (
    f"margin:0 0 6px 0;color:{VERDE};font-size:12px;text-transform:uppercase;"
    "letter-spacing:1px;font-weight:bold;"
)
_TITULO = f"margin:0 0 18px 0;color:{PETROLEO};font-size:24px;line-height:1.25;"
_AVISOS = (
    f"border-top:1px solid {BORDA};padding-top:18px;font-size:13px;line-height:1.55;color:#718784;"
)
_RODAPE = (
    f"background:{FUNDO};padding:14px 28px;font-size:11px;color:#81908d;"
    f"border-top:1px solid {BORDA};"
)


def html_convite(conteudo: ConteudoConvite, link_saida: str) -> str:
    """Versão em HTML, com o layout aprovado. `link_saida` é o botão de não ser mais contatado."""
    saida = _href(link_saida) or "#"
    rodape = f"{MARCA} · recrutamento ativo"
    if conteudo.simulado:
        rodape = f"{rodape} — {AVISO_SIMULACAO}"
    rotulo = "Lembrete" if conteudo.lembrete else "Nova oportunidade"
    empresa = escape(conteudo.empresa)
    partes = [
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width">',
        f"<title>{escape(assunto_convite(conteudo))}</title></head>",
        f'<body style="{_CORPO}">',
        f'<table {_TABELA} width="100%" style="background:{FUNDO};padding:24px 12px;">',
        '<tr><td align="center">',
        f'<table {_TABELA} width="600" style="{_CAIXA}">',
        f'<tr><td style="background:{PETROLEO};padding:22px 28px;">',
        f"<table {_TABELA}><tr>",
        f'<td style="padding-right:10px;"><img src="cid:{CID_LOGO}" {_LOGO}></td>',
        f'<td><div style="{_MARCA}">{MARCA}</div>',
        f'<div style="{_EXTENSO}">{MARCA_EXTENSO}</div></td>',
        "</tr></table></td></tr>",
        '<tr><td style="padding:32px 28px 8px 28px;">',
        f'<p style="{_ROTULO}">{rotulo}</p>',
        f'<h1 style="{_TITULO}">{escape(conteudo.titulo_vaga)}</h1>',
        _apresentacao(conteudo),
        _proximo_passo(conteudo),
        "</td></tr>",
        '<tr><td style="padding:0 28px 24px 28px;">',
        f'<div style="{_AVISOS}">',
        f'<p style="margin:0 0 10px 0;"><strong style="color:{TEXTO};">'
        f"Por que você recebeu este e-mail:</strong> {_origem(conteudo)}</p>",
        '<p style="margin:0;">Não quer mais receber contatos? '
        f'<a href="{saida}" style="color:#a43826;font-weight:bold;">{BOTAO_SAIDA}</a> '
        f"ou responda {PALAVRA_SAIDA}. O pedido vale para sempre, em todas as vagas da "
        f"{empresa}.</p>",
        "</div></td></tr>",
        f'<tr><td style="{_RODAPE}">{escape(rodape)}</td></tr>',
        "</table></td></tr></table></body></html>",
    ]
    return "\n".join(partes)
