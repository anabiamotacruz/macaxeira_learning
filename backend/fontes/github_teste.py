"""Coleta e aprofundamento em GitHub e sites pessoais/portfólios públicos (T2.5).

Respeita a lista de contas de teste autorizadas do time e a ligação de identidade
(só segue links públicos para os quais o próprio perfil aponta). Trata qualquer instrução
oculta na página ou na bio como alerta de prompt injection, nunca como regra.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from backend.agente.auditoria import rastreado
from backend.contratos.erros import ErroContrato, FonteIndisponivel
from backend.contratos.modelos import Candidato, EstadoBanco, Experiencia
from backend.fontes.analisador import _INSTRUCAO, _normalizar, texto_permitido
from backend.fontes.documentos import extrair_links_e_contatos

CONTAS_GITHUB_TESTE_PADRAO: frozenset[str] = frozenset(
    {
        "jvchaaves",
        "anabiamotacruz",
        "sofiapontes",
        "candidato-demo",
    }
)


class ContaForaDaListaDeTeste(ErroContrato):
    """A conta do GitHub não está na lista explícita de contas de teste autorizadas."""


class FonteGitHubTeste:
    """Implementa `FonteCandidatos` consultando a API oficial do GitHub só para contas de teste."""

    def __init__(
        self,
        contas_permitidas: set[str] | frozenset[str] = CONTAS_GITHUB_TESTE_PADRAO,
        *,
        http_client: httpx.Client | None = None,
        hoje: date = date(2026, 11, 7),
        simulado: bool = True,
    ) -> None:
        self.contas_permitidas = {c.strip().casefold() for c in contas_permitidas if c.strip()}
        self._http = http_client or httpx.Client(timeout=10.0)
        self._hoje = hoje
        self.simulado = simulado

    def _validar_conta(self, usuario: str) -> str:
        limpo = usuario.strip().casefold()
        if limpo not in self.contas_permitidas:
            raise ContaForaDaListaDeTeste(
                f"Conta {usuario!r} fora da lista explícita de contas de teste autorizadas."
            )
        return limpo

    @rastreado("github_coletar_perfil")
    def coletar_perfil(
        self,
        empresa_id: str,
        usuario: str,
        *,
        autorizado: bool = True,
    ) -> Candidato:
        """Busca usuário e repositórios na API oficial do GitHub e monta um `Candidato`."""
        conta = self._validar_conta(usuario)
        cabecalhos = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "macaxeira-learning-sourcing",
        }
        try:
            resp_user = self._http.get(
                f"https://api.github.com/users/{conta}", headers=cabecalhos
            )
            if resp_user.status_code != 200:
                raise FonteIndisponivel(f"GitHub HTTP {resp_user.status_code} para {conta}")
            dados_user: dict[str, Any] = resp_user.json()

            resp_repos = self._http.get(
                f"https://api.github.com/users/{conta}/repos?sort=updated&per_page=10",
                headers=cabecalhos,
            )
            repos: list[dict[str, Any]] = (
                resp_repos.json()
                if resp_repos.status_code == 200 and isinstance(resp_repos.json(), list)
                else []
            )
        except httpx.HTTPError as erro:
            raise FonteIndisponivel("Falha ao consultar API oficial do GitHub") from erro

        bio = (dados_user.get("bio") or "").strip()
        blog = (dados_user.get("blog") or "").strip()
        local = (dados_user.get("location") or "").strip()
        email = (dados_user.get("email") or "").strip()
        nome = (dados_user.get("name") or conta).strip()
        url_perfil = (dados_user.get("html_url") or f"https://github.com/{conta}").strip()

        linguagens: list[str] = []
        experiencias: list[Experiencia] = []
        frases_projetos: list[str] = []

        for repo in repos:
            if repo.get("fork"):
                continue
            nome_repo = (repo.get("name") or "").strip()
            desc_repo = (repo.get("description") or "").strip()
            lang_repo = (repo.get("language") or "").strip()
            topicos = [t for t in (repo.get("topics") or []) if isinstance(t, str)]
            if lang_repo and lang_repo not in linguagens:
                linguagens.append(lang_repo)
            resumo_repo = ". ".join(
                p
                for p in [
                    f"Repositório {nome_repo}",
                    desc_repo,
                    f"Linguagem: {lang_repo}" if lang_repo else "",
                    f"Tópicos: {', '.join(topicos)}" if topicos else "",
                ]
                if p
            )
            if resumo_repo and texto_permitido(resumo_repo):
                frases_projetos.append(resumo_repo)
                experiencias.append(
                    Experiencia(
                        empresa="GitHub",
                        cargo=lang_repo or "Software Developer",
                        inicio=self._hoje - timedelta(days=365),
                        fim=None,
                        descricao=resumo_repo,
                    )
                )

        partes_perfil = [p for p in [bio, *frases_projetos] if p]
        perfil_texto = ". ".join(partes_perfil) or f"Perfil GitHub {conta}."

        atributos: dict[str, str] = {
            "github": url_perfil,
            "linguagens": ", ".join(linguagens),
            "tecnologias": ", ".join(linguagens),
        }
        if blog:
            atributos["portfolio"] = blog if blog.startswith("http") else f"https://{blog}"
        if email:
            atributos["email"] = email.casefold()
        if local:
            atributos["localizacao"] = local

        contatos_bio = extrair_links_e_contatos( f"{bio} {blog}" )
        for k, v in contatos_bio.items():
            atributos.setdefault(k, v)

        return Candidato(
            id=f"gh-{conta}",
            empresa_id=empresa_id,
            nome=nome,
            fonte="github",
            simulado=self.simulado,
            origem=url_perfil,
            atualizado_em=self._hoje,
            autorizacao_valida_ate=(self._hoje + timedelta(days=365)) if autorizado else None,
            estado=EstadoBanco.ATIVO if autorizado else EstadoBanco.PENDENTE,
            perfil_texto=perfil_texto,
            atributos=atributos,
            historico=experiencias,
            autorizou_contato=autorizado,
            opt_out=False,
        )

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        if pagina > 1:
            return []
        termos = set(re.findall(r"\w+", _normalizar(consulta)))
        achados: list[Candidato] = []
        for conta in sorted(self.contas_permitidas):
            try:
                cand = self.coletar_perfil(empresa_id, conta)
            except FonteIndisponivel:
                continue
            texto_busca = _normalizar(
                " ".join([cand.perfil_texto, *cand.atributos.values()])
            )
            palavras_cand = set(re.findall(r"\w+", texto_busca))
            if not termos or termos <= palavras_cand:
                achados.append(cand)
        return achados


@rastreado("ler_pagina_portfolio")
def extrair_de_pagina_html(html: str, url_origem: str) -> dict[str, Any]:
    """Extrai texto profissional, links e contatos de uma página HTML pública (portfólio/site).

    Ignora `<script>`, `<style>` e elementos ocultos (`display:none`, `visibility:hidden`), e
    sinaliza qualquer tentativa de prompt injection encontrada no HTML.
    """
    sopa = BeautifulSoup(html, "html.parser")
    tem_instrucao = False

    # Verifica também texto oculto por CSS antes de removê-lo
    for tag in sopa.find_all(True):
        estilo = (tag.get("style") or "").replace(" ", "").lower()
        if "display:none" in estilo or "visibility:hidden" in estilo or "opacity:0" in estilo:
            oculto = _normalizar(tag.get_text(" ", strip=True))
            if _INSTRUCAO.search(oculto):
                tem_instrucao = True
            tag.decompose()

    for tag in sopa(["script", "style", "noscript", "template"]):
        tag.decompose()

    hrefs = [
        a.get("href", "").strip()
        for a in sopa.find_all("a", href=True)
        if a.get("href", "").strip()
    ]
    texto_visivel = " ".join(sopa.stripped_strings)
    contatos = extrair_links_e_contatos(f"{texto_visivel} {' '.join(hrefs)}")

    for h in hrefs:
        if h.lower().startswith("mailto:") and "email" not in contatos:
            contatos["email"] = h[7:].split("?")[0].strip().casefold()
        elif h.lower().startswith("tel:") and "telefone" not in contatos:
            contatos["telefone"] = h[4:].strip()

    frases_limpas: list[str] = []
    for frase in re.split(r"(?<=[.!?])\s+|\n+", texto_visivel):
        norm = _normalizar(frase)
        if not norm:
            continue
        if _INSTRUCAO.search(norm):
            tem_instrucao = True
        elif texto_permitido(frase):
            frases_limpas.append(frase.strip())

    return {
        "url": url_origem,
        "texto": " ".join(frases_limpas),
        "contatos": contatos,
        "tem_instrucao": tem_instrucao,
    }
