"""Coleta no GitHub pela API oficial (T2.5), só de contas com consentimento registrado.

A lista de contas vem da configuração e é vazia por padrão, porque cada conta precisa de
consentimento. A coleta real também começa desligada. Bio, descrição e tópicos são escritos pela
pessoa: viram fato declarado, e instrução neles vira alerta, nunca regra.
"""

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from backend.agente.auditoria import rastreado
from backend.contratos.erros import ErroContrato, FonteIndisponivel
from backend.contratos.modelos import (
    Candidato,
    ContatoColetado,
    FatoColetado,
    PerfilColetado,
    TipoContato,
    TipoFato,
)
from backend.fontes.analisador import INSTRUCAO, normalizar, texto_permitido
from backend.fontes.perfis import candidato_de_perfil, combina_com_consulta

ETAPA_COLETA = "github_coletar_perfil"
FONTE_GITHUB = "github"
API = "https://api.github.com"
VERSAO_DA_API = "2026-03-10"
REPOSITORIOS_POR_CONTA = 10
TEMPO_LIMITE_S = 10.0
ESPERA_MINIMA_S = 60
VARIAVEL_CONTAS = "GITHUB_CONTAS_CONSENTIDAS"
VARIAVEL_COLETA = "GITHUB_COLETA_REAL"

ALERTA_INSTRUCAO_GITHUB = (
    "instrucao_no_github: a bio ou um repositório traz texto dirigido ao avaliador; "
    "ele foi retirado."
)
_ATRIBUTOS_DA_CONTA = {
    "company": "empresa",
    "location": "localizacao",
    "twitter_username": "twitter",
}
_USUARIO_VALIDO = re.compile(r"^[a-z\d](?:[a-z\d-]{0,38})$")
_FIM_DE_FRASE = re.compile(r"(?<=[.!?])\s+|\n+")


class ContaForaDaListaDeConsentimento(ErroContrato):
    """A conta não está na lista explícita de contas com consentimento."""


class ColetaRealDesligada(ErroContrato):
    """A coleta real está desligada na configuração: nada foi pedido à API."""


class ContaNaoEncontrada(FonteIndisponivel):
    """A API não encontrou a conta. Uma conta nessa situação não para a busca das demais."""


@dataclass(frozen=True)
class ConfiguracaoGitHub:
    contas_consentidas: frozenset[str] = frozenset()
    coleta_real: bool = False

    @classmethod
    def do_ambiente(cls) -> "ConfiguracaoGitHub":
        contas = os.environ.get(VARIAVEL_CONTAS, "").split(",")
        return cls(
            contas_consentidas=frozenset(c.strip().casefold() for c in contas if c.strip()),
            coleta_real=os.environ.get(VARIAVEL_COLETA, "").strip() == "1",
        )


def _agora() -> datetime:
    return datetime.now(UTC)


def _hoje() -> date:
    return _agora().date()


class FonteGitHubTeste:
    """Implementa `FonteCandidatos` pela API oficial, dentro dos limites que ela informa."""

    def __init__(
        self,
        configuracao: ConfiguracaoGitHub | None = None,
        *,
        http_client: httpx.Client | None = None,
        hoje: Callable[[], date] = _hoje,
        agora: Callable[[], datetime] = _agora,
    ) -> None:
        self._configuracao = configuracao or ConfiguracaoGitHub()
        self._contas = {conta.strip().casefold() for conta in self._configuracao.contas_consentidas}
        self._http = http_client
        self._hoje = hoje
        self._agora = agora
        self._parado_ate: datetime | None = None

    def _validar_conta(self, usuario: str) -> str:
        conta = usuario.strip().casefold()
        if conta not in self._contas or not _USUARIO_VALIDO.match(conta):
            raise ContaForaDaListaDeConsentimento("Conta fora da lista de consentimento.")
        return conta

    def _cliente(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=TEMPO_LIMITE_S, follow_redirects=False)
        return self._http

    def _anotar_limite(self, resposta: httpx.Response) -> None:
        """Segue a documentação: `retry-after`, depois `x-ratelimit-reset`, depois um minuto."""
        cabecalhos = resposta.headers
        recusado = resposta.status_code in (403, 429)
        esgotado = cabecalhos.get("x-ratelimit-remaining") == "0"
        if not (recusado or esgotado):
            return
        agora = self._agora()
        espera = agora + timedelta(seconds=ESPERA_MINIMA_S)
        if cabecalhos.get("retry-after", "").isdigit():
            espera = agora + timedelta(seconds=int(cabecalhos["retry-after"]))
        elif esgotado and cabecalhos.get("x-ratelimit-reset", "").isdigit():
            espera = datetime.fromtimestamp(int(cabecalhos["x-ratelimit-reset"]), UTC)
        self._parado_ate = espera

    def _pedir(self, caminho: str, parametros: dict[str, Any] | None = None) -> Any:
        if self._parado_ate is not None and self._agora() < self._parado_ate:
            raise FonteIndisponivel("Limite da API do GitHub: aguardando a nova janela.")
        try:
            resposta = self._cliente().get(
                f"{API}{caminho}",
                params=parametros,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": VERSAO_DA_API,
                    "User-Agent": "macaxeira-learning-sourcing",
                },
            )
        except httpx.HTTPError as erro:
            raise FonteIndisponivel("Falha ao consultar a API do GitHub.") from erro
        self._anotar_limite(resposta)
        if resposta.status_code == 404:
            raise ContaNaoEncontrada("A API do GitHub não encontrou a conta.")
        if resposta.status_code != 200:
            raise FonteIndisponivel(f"A API do GitHub respondeu {resposta.status_code}.")
        try:
            return resposta.json()
        except ValueError as erro:
            raise FonteIndisponivel("A API do GitHub respondeu fora do formato.") from erro

    def _candidato_id(self, empresa_id: str, conta: str) -> str:
        """O id vai para rastros e decisões: não pode revelar o usuário nem ligar empresas."""
        return f"gh-{hashlib.sha256(f'{empresa_id}:{conta}'.encode()).hexdigest()[:16]}"

    def perfil_coletado(self, empresa_id: str, usuario: str) -> PerfilColetado:
        """Perfil em JSON, com dois pedidos à API: o usuário e os repositórios próprios."""
        return self._coletar(empresa_id, usuario)[0]

    @rastreado(ETAPA_COLETA)
    def _coletar(self, empresa_id: str, usuario: str) -> tuple[PerfilColetado, dict[str, Any]]:
        conta = self._validar_conta(usuario)
        if not self._configuracao.coleta_real:
            raise ColetaRealDesligada("A coleta real do GitHub está desligada.")
        dados = self._pedir(f"/users/{conta}")
        repositorios = self._pedir(
            f"/users/{conta}/repos",
            {"type": "owner", "sort": "updated", "per_page": REPOSITORIOS_POR_CONTA},
        )
        if self._parado_ate is not None and self._agora() < self._parado_ate:
            raise FonteIndisponivel("Limite da API do GitHub: aguardando a nova janela.")
        return self._montar_perfil(empresa_id, conta, dados, repositorios), dados

    def _montar_perfil(
        self, empresa_id: str, conta: str, dados: dict[str, Any], repositorios: Any
    ) -> PerfilColetado:
        hoje = self._hoje()
        url_perfil = dados.get("html_url") or f"https://github.com/{conta}"
        origem = {"fonte": FONTE_GITHUB, "coletado_em": hoje}
        fatos: list[FatoColetado] = []
        tem_instrucao = False

        def declarar(texto: str, url: str) -> None:
            nonlocal tem_instrucao
            for frase in _FIM_DE_FRASE.split(texto):
                limpa = " ".join(frase.split())
                if not limpa:
                    continue
                if INSTRUCAO.search(normalizar(limpa)):
                    tem_instrucao = True
                elif texto_permitido(limpa):
                    fatos.append(
                        FatoColetado(
                            **origem, url=url, texto=limpa, trecho=limpa, tipo=TipoFato.DECLARADO
                        )
                    )

        declarar(_texto(dados.get("bio")), url_perfil)
        for repositorio in repositorios if isinstance(repositorios, list) else []:
            if repositorio.get("fork") or not _texto(repositorio.get("name")):
                continue
            nome = _texto(repositorio["name"])
            url = repositorio.get("html_url") or f"{url_perfil}/{nome}"
            linguagem = _texto(repositorio.get("language"))
            comprovado = f"Repositório {nome}."
            if linguagem:
                comprovado += f" Linguagem: {linguagem}."
            fatos.append(
                FatoColetado(
                    **origem, url=url, texto=comprovado, trecho=comprovado, tipo=TipoFato.COMPROVADO
                )
            )
            declarar(_texto(repositorio.get("description")), url)
            topicos = ", ".join(t for t in repositorio.get("topics") or [] if isinstance(t, str))
            if topicos:
                declarar(f"Tópicos: {topicos}.", url)
        return PerfilColetado(
            empresa_id=empresa_id,
            candidato_id=self._candidato_id(empresa_id, conta),
            simulado=False,
            coletado_em=hoje,
            nome=_texto(dados.get("name")),
            fatos=fatos,
            contatos=_contatos(dados, url_perfil, origem),
            alertas=[ALERTA_INSTRUCAO_GITHUB] if tem_instrucao else [],
        )

    def coletar_perfil(
        self, empresa_id: str, usuario: str, *, autorizacao_valida_ate: date | None = None
    ) -> Candidato:
        """`Candidato` da conta. Sem validade informada, fica pendente de autorização.

        Empresa, local e rede social ficam em atributos, longe do texto do perfil e do modelo: é
        com eles que a pseudonimização reconhece esses valores na bio.
        """
        perfil, dados = self._coletar(empresa_id, usuario)
        repositorios = [
            f.url.rsplit("/", 1)[-1]
            for f in perfil.fatos
            if f.tipo is TipoFato.COMPROVADO and f.url
        ]
        atributos = {
            "usuario": usuario.strip().casefold(),
            "github": f"https://github.com/{usuario.strip().casefold()}",
        }
        if repositorios:
            atributos["repositorios"] = ", ".join(repositorios)
        for campo, chave in _ATRIBUTOS_DA_CONTA.items():
            if _texto(dados.get(campo)):
                atributos[chave] = _texto(dados[campo]).removeprefix("@")
        return candidato_de_perfil(
            perfil,
            origem=atributos["github"],
            fonte=FONTE_GITHUB,
            autorizacao_valida_ate=autorizacao_valida_ate,
            atributos=atributos,
        )

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        """Limite da API para a busca e chega ao fluxo como fonte fora do ar."""
        if pagina > 1 or not self._configuracao.coleta_real:
            return []
        achados = []
        for conta in sorted(self._contas):
            try:
                candidato = self.coletar_perfil(empresa_id, conta)
            except (ContaNaoEncontrada, ContaForaDaListaDeConsentimento):
                continue
            if combina_com_consulta(candidato, consulta):
                achados.append(candidato)
        return achados


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def _contatos(
    dados: dict[str, Any], url_perfil: str, origem: dict[str, Any]
) -> list[ContatoColetado]:
    """A API só traz o que a pessoa deixou público no perfil."""
    valores = [(TipoContato.PERFIL, url_perfil)]
    if _texto(dados.get("email")):
        valores.append((TipoContato.EMAIL, _texto(dados["email"]).casefold()))
    blog = _texto(dados.get("blog"))
    if blog:
        valores.append((TipoContato.LINK, blog if "://" in blog else f"https://{blog}"))
    return [
        ContatoColetado(
            **origem, url=url_perfil, tipo=tipo, valor=valor, publicado_pela_pessoa=True
        )
        for tipo, valor in valores
    ]
