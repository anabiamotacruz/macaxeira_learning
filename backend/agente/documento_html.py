"""Dossiê para o recrutador: o documento de ingestão em HTML, com a marca da CORA, pronto para PDF.

É o mesmo `PacoteContexto` do documento em Markdown, sem campo novo. A página é uma folha A4:
na tela aparece com um botão para salvar em PDF, e na impressão sai com rodapé e número de página.

Todo texto vindo da pessoa ou do modelo passa por `html.escape`: aparece, mas não age. A política
de conteúdo vai no próprio documento, para valer onde ele for aberto (aba do painel, arquivo
salvo). O único script é o do botão, fixado pelo hash na política.
"""

import base64
import hashlib
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from functools import cache
from html import escape
from pathlib import Path

from backend.agente.documento import AVISO_DADO
from backend.agente.fluxo import DuvidaConvite
from backend.contratos.modelos import Evidencia, Experiencia, PacoteContexto, Vaga

_LOGO = Path(__file__).parent / "recursos" / "coral.png"
_MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
_SCRIPT = 'document.getElementById("imprimir").addEventListener("click",function(){print()});'
_HASH_SCRIPT = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
_FONTES = (
    "https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700"
    "&family=Geist+Mono:wght@400;500&display=swap"
)

POLITICA_DE_CONTEUDO = (
    "default-src 'none'; img-src data:; "
    "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
    f"script-src 'sha256-{_HASH_SCRIPT}'; base-uri 'none'; form-action 'none'"
)
SELO_SIMULACAO = "pessoa, conversa e entrega fictícias, em ambiente de demonstração."


def _t(texto: object) -> str:
    """Texto de dado: uma linha, escapado. Nunca vira marcação."""
    return escape(" ".join(str(texto).split()), quote=True)


@cache
def _logo() -> str:
    return "data:image/png;base64," + base64.b64encode(_LOGO.read_bytes()).decode()


def _rotulo(criterio: str) -> str:
    """Nome do critério para leitura: sem sublinhado e com a primeira letra maiúscula."""
    texto = " ".join(criterio.replace("_", " ").split())
    return texto[:1].upper() + texto[1:]


def _mes(dia: date | None) -> str:
    return "hoje" if dia is None else f"{_MESES[dia.month - 1]}/{dia.year}"


def _lista(itens: Sequence[str], vazio: str, classe: str) -> str:
    if not itens:
        return f'<p class="vazio">{vazio}</p>'
    return f'<ul class="{classe}">' + "".join(f"<li>{_t(i)}</li>" for i in itens) + "</ul>"


def _citacao(trecho: str, fonte: str) -> str:
    return (
        f'<figure class="citacao"><blockquote>“{_t(trecho)}”</blockquote>'
        f"<figcaption>Fonte: {_t(fonte)}</figcaption></figure>"
    )


def _criterios(motivos: dict[str, str], evidencias: Sequence[Evidencia]) -> str:
    por_criterio: dict[str, list[Evidencia]] = defaultdict(list)
    for evidencia in evidencias:
        por_criterio[evidencia.criterio].append(evidencia)
    nomes = sorted(set(motivos) | set(por_criterio))
    if not nomes:
        return '<p class="vazio">Nenhum critério registrado.</p>'
    cartoes = []
    for nome in nomes:
        motivo = motivos.get(nome)
        provas = por_criterio.get(nome, [])
        repetido = any(_t(motivo) == _t(e.trecho) for e in provas)
        cartoes.append(
            f'<article class="cartao criterio" data-criterio="{_t(nome)}">'
            f"<h3>{_t(_rotulo(nome))}</h3>"
            + (f'<p class="motivo">{_t(motivo)}</p>' if motivo and not repetido else "")
            + "".join(_citacao(e.trecho, e.fonte) for e in provas)
            + ("" if provas else '<p class="vazio">Sem trecho registrado.</p>')
            + "</article>"
        )
    return '<div class="grade-criterios">' + "".join(cartoes) + "</div>"


def _trajetoria(historico: Sequence[Experiencia]) -> str:
    itens = "".join(
        f'<li><p class="periodo">{_mes(x.inicio)} a {_mes(x.fim)}</p>'
        f'<p class="cargo">{_t(x.cargo)} <span>· {_t(x.empresa)}</span></p>'
        f'<p class="descricao">{_t(x.descricao)}</p></li>'
        for x in historico
    )
    return f'<ol class="linha-do-tempo">{itens}</ol>'


def _roteiro(pacote: PacoteContexto) -> str:
    itens = [f"<li><p>{_t(p)}</p></li>" for p in pacote.pontos_a_aprofundar]
    itens += [
        f"<li><p>{_t(p.descricao)} "
        f'<span class="etiqueta {"ok" if p.verificado else "aberta"}">{_t(p.rotulo)}</span></p>'
        f"{_citacao(p.trecho, p.fonte)}</li>"
        for p in pacote.pontos_a_explorar
    ]
    if not itens:
        return '<p class="vazio">Nada específico.</p>'
    return '<ol class="roteiro">' + "".join(itens) + "</ol>"


def _conversa(pacote: PacoteContexto, duvidas: Sequence[DuvidaConvite]) -> str:
    if not duvidas and not pacote.respostas_pre_triagem:
        return '<p class="vazio">A pessoa não fez perguntas antes de aceitar.</p>'
    blocos = []
    for duvida in duvidas:
        resposta = (
            f'<p class="fala agente"><span>A CORA respondeu</span>“{_t(duvida.resposta)}”</p>'
            if duvida.resposta
            else '<p class="fala pendente"><span>Sem resposta no material da vaga</span>'
            "A dúvida foi encaminhada a uma pessoa.</p>"
        )
        blocos.append(
            f'<div class="cartao troca"><p class="fala pessoa"><span>A pessoa perguntou</span>'
            f"“{_t(duvida.pergunta)}”</p>{resposta}</div>"
        )
    for resposta in pacote.respostas_pre_triagem:
        blocos.append(
            f'<div class="cartao troca"><p class="fala pessoa"><span>Pré-triagem · '
            f"{_t(resposta.criterio)}</span>“{_t(resposta.trecho)}”</p>"
            f'<p class="fonte">Fonte: {_t(resposta.fonte)}, {resposta.coletado_em:%d/%m/%Y}</p>'
            "</div>"
        )
    return "".join(blocos)


def _secao(numero: int, titulo: str, corpo: str, classe: str = "") -> str:
    return (
        f'<section class="secao {classe}"><h2><span class="numero">{numero:02d}</span>'
        f"{titulo}</h2>{corpo}</section>"
    )


def documento_html(
    pacote: PacoteContexto, vaga: Vaga, duvidas: Sequence[DuvidaConvite] = ()
) -> str:
    """O pacote como dossiê HTML. `duvidas` é a conversa da pessoa com o agente, se houver."""
    criterios = len(set(pacote.motivo_por_criterio) | {e.criterio for e in pacote.evidencias})
    roteiro = len(pacote.pontos_a_aprofundar) + len(pacote.pontos_a_explorar)
    selo = (
        f'<aside class="selo"><strong>SIMULAÇÃO</strong>{SELO_SIMULACAO}</aside>'
        if pacote.simulado
        else ""
    )
    secoes = [("Por que segue", _criterios(pacote.motivo_por_criterio, pacote.evidencias), "")]
    if pacote.historico:
        secoes.append(("Trajetória", _trajetoria(pacote.historico), ""))
    secoes += [
        (
            "Lacunas e ressalvas",
            '<div class="duas-colunas">'
            '<div class="cartao alerta"><h3>O que não encontramos</h3>'
            f"{_lista(pacote.lacunas, 'Nenhuma.', 'marcadores')}</div>"
            '<div class="cartao alerta"><h3>Ressalvas do revisor</h3>'
            f"{_lista(pacote.ressalvas_revisor, 'Nenhuma.', 'marcadores')}</div></div>",
            "",
        ),
        ("Roteiro para a entrevista", _roteiro(pacote), ""),
        ("O que a conversa apurou", _conversa(pacote, duvidas), ""),
    ]
    corpo = "".join(_secao(i, titulo, html, c) for i, (titulo, html, c) in enumerate(secoes, 1))
    titulo = _t(vaga.titulo)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{POLITICA_DE_CONTEUDO}">
<title>CORA · {titulo}</title>
<link rel="stylesheet" href="{escape(_FONTES)}">
<style>{_estilo(pacote.simulado)}</style>
</head>
<body>
<div class="barra-tela">
<p>Dossiê para entrevista · {titulo}</p>
<button id="imprimir" type="button">Salvar em PDF</button>
</div>
<main class="folha">
<header class="capa">
<div class="marca">
<img src="{_logo()}" alt="Coral da CORA" width="44" height="44">
<div><p class="marca-nome">CORA</p>
<p class="marca-sub">Conexão de Oportunidade<br>de Recrutamento Ativo</p></div>
</div>
<p class="tipo">Dossiê para entrevista</p>
<h1>{titulo}</h1>
<p class="linha-fina">O que a CORA reuniu para quem vai conduzir a conversa: por que a pessoa
segue, com trecho e fonte, o que ainda falta saber e o que ela perguntou.</p>
<dl class="ficha">
<div><dt>Pessoa (código)</dt><dd class="mono">{_t(pacote.candidato_id)}</dd></div>
<div><dt>Origem do perfil</dt><dd>{_t(pacote.fonte)}</dd></div>
<div><dt>Autorização de contato</dt><dd>{_t(pacote.autorizacao)}</dd></div>
<div><dt>Rastro</dt><dd class="mono">{_t(pacote.rastro_id)}</dd></div>
</dl>
</header>
{selo}
<p class="aviso">{AVISO_DADO}</p>
<section class="resumo" aria-label="Em resumo">
<div><p class="grande">{criterios}</p><p>critérios com motivo e trecho</p></div>
<div><p class="grande">{len(pacote.lacunas)}</p><p>lacunas declaradas</p></div>
<div><p class="grande">{roteiro}</p><p>pontos para a entrevista</p></div>
</section>
{corpo}
<footer class="rodape">
<p>A CORA explica por que a pessoa segue. Ela não avalia candidatos nem decide contratações:
a conversa e a decisão são de quem entrevista.</p>
<p class="mono">Vaga {_t(pacote.vaga_id)} · rastro {_t(pacote.rastro_id)}</p>
</footer>
</main>
<script>{_SCRIPT}</script>
</body>
</html>
"""


def _estilo(simulado: bool) -> str:
    marca_rodape = '"CORA · Dossiê para entrevista' + (' · SIMULAÇÃO"' if simulado else '"')
    return (
        """
:root {
  --coral: #fb3c0d; --coral-suave: #fff3ef; --coral-linha: #fcc9bb;
  --petroleo: #0b3038; --texto-2: #58716d; --texto-3: #718784;
  --linha: #dfe7e2; --menta: #edf1ee; --fundo: #e8eeea; --papel: #ffffff;
  --ambar: #fff7df; --ambar-linha: #f1d58a; --grafite: #5b5b5b;
  --sans: "Geist", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Arial, sans-serif;
  --mono: "Geist Mono", ui-monospace, "SF Mono", Menlo, monospace;
}
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: var(--fundo); color: var(--petroleo);
  font: 400 14px/1.55 var(--sans); }
p, h1, h2, h3, dl, dd, ol, ul, figure, blockquote { margin: 0; }
.mono { font-family: var(--mono); font-size: 12px; overflow-wrap: anywhere; }

.barra-tela { position: sticky; top: 0; z-index: 2; display: flex; align-items: center;
  justify-content: space-between; gap: 16px; padding: 10px 24px; background: var(--grafite);
  color: #fff; font-size: 13px; }
.barra-tela p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #d0d6d5; }
.barra-tela button { flex: none; border: 0; border-radius: 8px; background: var(--coral);
  color: #fff; font: 600 13px var(--sans); padding: 9px 16px; cursor: pointer;
  box-shadow: 0 0 0 2px rgba(255,255,255,.9); }
.barra-tela button:hover { background: #e23306; }

.folha { width: min(210mm, 100% - 32px); margin: 28px auto 56px; padding: 18mm 17mm 14mm;
  background: var(--papel); border-radius: 6px; box-shadow: 0 1px 2px rgba(11,48,56,.08),
  0 12px 40px rgba(11,48,56,.10); }

.capa { position: relative; padding-bottom: 22px; border-bottom: 1px solid var(--linha); }
.capa::before { content: ""; position: absolute; top: -18mm; left: -17mm; right: -17mm;
  height: 6px; background: var(--coral); border-radius: 6px 6px 0 0; }
.marca { display: flex; align-items: flex-start; gap: 10px; }
.marca img { width: 44px; height: 44px; object-fit: contain; }
.marca-nome { font-size: 22px; font-weight: 600; letter-spacing: -.02em; line-height: 1; }
.marca-sub { margin-top: 4px; font-size: 7.5px; font-weight: 500; text-transform: uppercase;
  letter-spacing: .06em; line-height: 1.25; color: var(--texto-3); }
.tipo { margin-top: 34px; font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .12em; color: var(--coral); }
h1 { margin-top: 8px; font-size: 34px; line-height: 1.1; font-weight: 600; letter-spacing: -.025em;
  text-wrap: balance; }
.linha-fina { margin-top: 12px; max-width: 60ch; font-size: 15px; color: var(--texto-2); }
.ficha { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px;
  margin-top: 24px; }
.ficha dt { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em;
  color: var(--texto-3); }
.ficha dd { margin-top: 2px; font-weight: 500; overflow-wrap: anywhere; }

.selo { display: flex; gap: 10px; align-items: baseline; margin-top: 20px; padding: 10px 14px;
  background: var(--ambar); border: 1px solid var(--ambar-linha); border-radius: 8px;
  font-size: 12.5px; color: #6b4e00; }
.selo strong { letter-spacing: .08em; font-size: 11px; }
.aviso { margin-top: 10px; font-size: 11.5px; color: var(--texto-3); }

.resumo { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 22px;
  border: 1px solid var(--linha); border-radius: 10px; background: var(--menta); }
.resumo > div { padding: 14px 16px; }
.resumo > div + div { border-left: 1px solid var(--linha); }
.resumo .grande { font-size: 30px; font-weight: 600; line-height: 1; color: var(--coral);
  letter-spacing: -.02em; }
.resumo p:not(.grande) { margin-top: 6px; font-size: 12px; color: var(--texto-2); }

.secao { margin-top: 30px; }
h2 { display: flex; align-items: baseline; gap: 10px; padding-bottom: 8px; margin-bottom: 14px;
  border-bottom: 2px solid var(--petroleo); font-size: 19px; font-weight: 600;
  letter-spacing: -.01em; break-after: avoid; }
h2 .numero { font-family: var(--mono); font-size: 12px; font-weight: 500; color: var(--coral); }
h3 { font-size: 14.5px; font-weight: 600; }
.vazio { color: var(--texto-3); font-style: italic; }

.cartao { padding: 14px 16px; border: 1px solid var(--linha); border-radius: 10px;
  background: var(--papel); break-inside: avoid; }
.grade-criterios { display: grid; gap: 10px; }
.criterio { border-left: 4px solid var(--coral); }
.motivo { margin-top: 4px; }
.citacao { margin-top: 10px; padding: 8px 12px; background: var(--coral-suave);
  border-radius: 6px; }
.citacao blockquote { font-size: 13px; color: var(--petroleo); }
.citacao figcaption { margin-top: 4px; font-size: 11px; color: var(--texto-3); }

.linha-do-tempo { list-style: none; margin-left: 7px; padding: 0 0 0 18px;
  border-left: 2px solid var(--linha); }
.linha-do-tempo li { position: relative; padding: 0 0 14px 4px; break-inside: avoid; }
.linha-do-tempo li::before { content: ""; position: absolute; left: -25px; top: 5px; width: 10px;
  height: 10px; border-radius: 50%; background: var(--papel); border: 2px solid var(--coral); }
.periodo { font-family: var(--mono); font-size: 11px; color: var(--texto-3); }
.cargo { font-weight: 600; }
.cargo span { font-weight: 400; color: var(--texto-2); }
.descricao { color: var(--texto-2); }

.duas-colunas { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.alerta { background: #fbfcfa; }
.marcadores { margin-top: 8px; padding-left: 18px; }
.marcadores li + li { margin-top: 4px; }
.marcadores li::marker { color: var(--coral); }

.roteiro { list-style: none; counter-reset: passo; padding: 0; display: grid; gap: 8px; }
.roteiro li { counter-increment: passo; position: relative; padding: 12px 14px 12px 50px;
  border: 1px solid var(--linha); border-radius: 10px; break-inside: avoid; }
.roteiro li::before { content: counter(passo); position: absolute; left: 14px; top: 11px;
  width: 24px; height: 24px; border-radius: 50%; background: var(--petroleo); color: #fff;
  font: 600 12px/24px var(--sans); text-align: center; }
.etiqueta { display: inline-block; margin-left: 6px; padding: 1px 8px; border-radius: 99px;
  font-size: 10.5px; font-weight: 600; vertical-align: 1px; }
.etiqueta.ok { background: #e3f1ea; color: #1f6b4a; }
.etiqueta.aberta { background: var(--menta); color: var(--texto-2); }

.troca + .troca { margin-top: 10px; }
.fala span { display: block; font-size: 10.5px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .08em; color: var(--texto-3); }
.fala + .fala { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--linha); }
.fala.agente span { color: var(--coral); }
.fala.pendente { color: var(--texto-2); }
.fonte { margin-top: 6px; font-size: 11px; color: var(--texto-3); }

.rodape { margin-top: 36px; padding-top: 14px; border-top: 1px solid var(--linha);
  font-size: 11.5px; color: var(--texto-3); display: grid; gap: 4px; }

@media (max-width: 640px) {
  .folha { width: 100%; margin: 0; padding: 28px 16px; border-radius: 0; box-shadow: none; }
  .capa::before { top: -28px; left: -16px; right: -16px; border-radius: 0; }
  h1 { font-size: 27px; }
  .ficha, .duas-colunas { grid-template-columns: 1fr; }
  .resumo .grande { font-size: 24px; }
}

@page {
  size: A4;
  margin: 14mm 15mm 16mm;
  @bottom-left { content: MARCA_RODAPE; font: 500 8pt "Geist", system-ui, sans-serif;
    color: #718784; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 500 8pt "Geist",
    system-ui, sans-serif; color: #718784; }
}
@media print {
  body { background: #fff; font-size: 10pt; }
  .barra-tela { display: none; }
  .folha { width: auto; margin: 0; padding: 0; border-radius: 0; box-shadow: none; }
  .capa { padding-top: 14px; }
  .capa::before { top: 0; left: 0; right: 0; height: 4px; border-radius: 0; }
  .secao { break-before: auto; }
  .cartao, .roteiro li, .linha-do-tempo li, .resumo { break-inside: avoid; }
}
"""
    ).replace("MARCA_RODAPE", marca_rodape)
