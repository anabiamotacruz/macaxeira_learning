"""People Data Labs: Person Enrichment pela API oficial.

Referências: docs.peopledatalabs.com/docs/reference-person-enrichment-api,
/docs/input-parameters-person-enrichment-api, /docs/examples-person-enrichment-api,
/docs/authentication e /docs/errors.

Cobrança: por pessoa encontrada. 200 consome um crédito; 404 significa sem resultado e não cobra.
Os dados de identidade vão no corpo do POST, nunca na URL, que aparece em logs do cliente HTTP.
Só é permitido pedir enriquecimento por identificadores que não sejam do LinkedIn.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.contratos.modelos import Experiencia
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca, UrlRecusada
from backend.fontes.provedores.modelos import (
    ConfiancaDado,
    ConsultaProvedor,
    ContatoColetado,
    IdentidadeConsulta,
    ItemColetado,
    RespostaProvedor,
    limpar_texto_externo,
)
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte
from backend.fontes.provedores.url_segura import validar_forma

NOME = "people_data_labs"
ETAPA_PDL = "provedor_people_data_labs"
URL_ENRIQUECIMENTO = "https://api.peopledatalabs.com/v5/person/enrich"
URL_SANDBOX = "https://sandbox.api.peopledatalabs.com/v5/person/enrich"
"""Dados artificiais e sem consumir créditos: serve para conferir o formato antes de ligar."""
MIN_LIKELIHOOD_PADRAO = 6
PISO_MIN_LIKELIHOOD = 6
"""A documentação recomenda 6 ou mais quando a precisão importa. Abaixo disso, o risco é atribuir
os dados de uma pessoa a outra: a configuração só pode subir este valor."""
MAX_LIKELIHOOD = 10
CUSTO_CREDITO_USD = 0.28
"""Plano Pro inicial: US$ 98 por 350 créditos, o preço mais alto da tabela. Serve de teto."""
CAMPOS_PEDIDOS = (
    "full_name",
    "job_title",
    "job_company_name",
    "location_name",
    "skills",
    "summary",
    "work_email",
    "github_url",
    "experience.company.name",
    "experience.title.name",
    "experience.start_date",
    "experience.end_date",
    "education.school.name",
    "education.degrees",
)
"""Só o necessário para o perfil profissional. Sexo, nascimento, LinkedIn e telefones ficam fora."""
HOSTS_DE_PERFIL = ("github.com",)
TEMPORARIOS = frozenset({429})
_EMAIL = re.compile(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+")


def _texto(valor: Any) -> str:
    return valor if isinstance(valor, str) else ""


def _data_parcial(valor: Any) -> date | None:
    """A API devolve `AAAA` ou `AAAA-MM`. Sem data legível, a experiência não entra no histórico."""
    if not isinstance(valor, str):
        return None
    partes = valor.split("-")
    try:
        ano = int(partes[0])
        mes = int(partes[1]) if len(partes) > 1 else 1
        return date(ano, mes, 1)
    except (ValueError, IndexError):
        return None


def _nome_em(campo: Any) -> str:
    return _texto(campo.get("name")) if isinstance(campo, dict) else ""


def _experiencias(dados: dict[str, Any]) -> tuple[list[Experiencia], list[str]]:
    """Com data vira histórico. Sem data, fica só como texto, pois o contrato exige início."""
    historico: list[Experiencia] = []
    sem_data: list[str] = []
    bruto = dados.get("experience")
    for experiencia in bruto if isinstance(bruto, list) else []:
        if not isinstance(experiencia, dict):
            continue
        empresa = _nome_em(experiencia.get("company"))
        cargo = _nome_em(experiencia.get("title"))
        inicio = _data_parcial(experiencia.get("start_date"))
        if inicio is not None and (empresa or cargo):
            historico.append(
                Experiencia(
                    empresa=limpar_texto_externo(empresa),
                    cargo=limpar_texto_externo(cargo),
                    inicio=inicio,
                    fim=_data_parcial(experiencia.get("end_date")),
                    descricao="",
                )
            )
        elif empresa or cargo:
            sem_data.append(" em ".join(p for p in (cargo, empresa) if p))
    return historico, sem_data


def _formacoes(dados: dict[str, Any]) -> list[str]:
    bruto = dados.get("education")
    frases = []
    for formacao in bruto if isinstance(bruto, list) else []:
        if not isinstance(formacao, dict):
            continue
        escola = _nome_em(formacao.get("school"))
        graus = formacao.get("degrees")
        titulos = [g for g in graus if isinstance(g, str)] if isinstance(graus, list) else []
        if escola:
            frases.append(" em ".join([*titulos[:1], escola]))
    return frases


def _url_publica(valor: Any) -> str | None:
    """`github_url` vem sem esquema. Se a política recusar o endereço, ele não entra no item."""
    if not isinstance(valor, str) or not valor:
        return None
    url = valor if "://" in valor else f"https://{valor}"
    try:
        validar_forma(url)
    except UrlRecusada:
        return None
    return url


def _perfil_de_url(url: str) -> str | None:
    """Uma URL só serve de perfil em rede aceita. Site pessoal não identifica ninguém aqui."""
    try:
        validar_forma(url)
    except UrlRecusada:
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0].casefold().removeprefix("www.")
    return url if host in HOSTS_DE_PERFIL else None


class ProvedorPeopleDataLabs:
    """Implementa `ProvedorDados`. Abaixo de `min_likelihood`, a resposta conta como não achada."""

    nome = NOME

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        min_likelihood: int = MIN_LIKELIHOOD_PADRAO,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
        url: str = URL_ENRIQUECIMENTO,
        custo_credito_usd: float = CUSTO_CREDITO_USD,
    ) -> None:
        if (
            not isinstance(min_likelihood, int)
            or isinstance(min_likelihood, bool)
            or not PISO_MIN_LIKELIHOOD <= min_likelihood <= MAX_LIKELIHOOD
        ):
            raise ValueError(
                f"min_likelihood deve ser inteiro de {PISO_MIN_LIKELIHOOD} a {MAX_LIKELIHOOD}"
            )
        self._chave = chave
        self._transporte = transporte
        self._min_likelihood = min_likelihood
        self._relogio = relogio
        self._url = url
        self._custo = custo_credito_usd

    def aceita(self, consulta: ConsultaProvedor) -> bool:
        return self._parametros(consulta) is not None

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        return self._custo

    @staticmethod
    def _parametros_da_identidade(identidade: IdentidadeConsulta) -> dict[str, Any] | None:
        """Combinação mínima da documentação: e-mail, perfil, ou nome com mais um dado."""
        parametros: dict[str, Any] = {}
        if identidade.email and identidade.email.strip():
            parametros["email"] = [identidade.email.strip()]
        if identidade.perfil and identidade.perfil.strip():
            parametros["profile"] = [identidade.perfil.strip()]
        nome = (identidade.nome or "").strip()
        empresa = (identidade.empresa or "").strip()
        local = (identidade.local or "").strip()
        if nome and (empresa or local):
            parametros["name"] = [nome]
            if empresa:
                parametros["company"] = empresa
            if local:
                parametros["location"] = local
        return parametros or None

    def _parametros(self, consulta: ConsultaProvedor) -> dict[str, Any] | None:
        if consulta.identidade is not None:
            return self._parametros_da_identidade(consulta.identidade)
        if consulta.url is not None:
            perfil = _perfil_de_url(consulta.url)
            return {"profile": [perfil]} if perfil else None
        return None

    @rastreado(ETAPA_PDL)
    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor:
        parametros = self._parametros(consulta)
        if parametros is None:
            raise ErroProvedor(MotivoTroca.CONSULTA_NAO_SUPORTADA)
        for perfil in parametros.get("profile", []):
            validar_forma(perfil if "://" in perfil else f"https://{perfil}")
        resposta = self._transporte.enviar(
            PedidoHttp(
                metodo="POST",
                url=self._url,
                cabecalhos={"X-Api-Key": self._chave, "Content-Type": "application/json"},
                corpo_json={
                    **parametros,
                    "min_likelihood": self._min_likelihood,
                    "data_include": ",".join(CAMPOS_PEDIDOS),
                    "titlecase": False,
                },
            )
        )
        return self._interpretar(resposta)

    def _interpretar(self, resposta: RespostaHttp) -> RespostaProvedor:
        status = resposta.status
        if status == 404:
            return RespostaProvedor()
        if status == 401:
            raise ErroProvedor(MotivoTroca.AUTENTICACAO)
        if status == 402:
            raise ErroProvedor(MotivoTroca.SEM_CREDITOS)
        if status in TEMPORARIOS or status >= 500:
            raise FonteIndisponivel(f"{NOME}: status {status}")
        if status != 200:
            raise ErroProvedor(MotivoTroca.RECUSADO_PELO_PROVEDOR)
        return self._encontrado(resposta)

    def _encontrado(self, resposta: RespostaHttp) -> RespostaProvedor:
        """Toda resposta 200 consome crédito, mesmo quando o conteúdo não for aproveitado."""
        try:
            corpo = json.loads(resposta.corpo)
        except ValueError:
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo) from None
        likelihood = corpo.get("likelihood") if isinstance(corpo, dict) else None
        dados = corpo.get("data") if isinstance(corpo, dict) else None
        if not isinstance(likelihood, int) or isinstance(likelihood, bool):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo)
        if not isinstance(dados, dict):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo)
        if likelihood < self._min_likelihood:
            return RespostaProvedor(custo_usd=self._custo)
        return RespostaProvedor(itens=[self._item(dados, likelihood)], custo_usd=self._custo)

    def _item(self, dados: dict[str, Any], likelihood: int) -> ItemColetado:
        """Lê só os campos pedidos: o que vier a mais fica de fora."""
        historico, sem_data = _experiencias(dados)
        atributos = {"likelihood": str(likelihood)}
        for campo, atributo in (
            ("job_title", "cargo"),
            ("job_company_name", "empresa_atual"),
            ("location_name", "local"),
        ):
            if _texto(dados.get(campo)):
                atributos[atributo] = dados[campo]
        competencias = dados.get("skills")
        if isinstance(competencias, list):
            nomes = [c for c in competencias if isinstance(c, str)]
            if nomes:
                atributos["competencias"] = ", ".join(nomes)
        email = _texto(dados.get("work_email")).strip()
        return ItemColetado(
            provedor=NOME,
            fonte=f"{NOME}:person_enrich",
            coletado_em=self._relogio(),
            url=_url_publica(dados.get("github_url")),
            confianca=ConfiancaDado.INFERIDO,
            nome=_texto(dados.get("full_name")),
            texto=". ".join(
                parte
                for parte in (_texto(dados.get("summary")), *sem_data, *_formacoes(dados))
                if parte
            ),
            atributos=atributos,
            historico=historico,
            contatos=(
                [ContatoColetado(tipo="email", valor=email)] if _EMAIL.fullmatch(email) else []
            ),
        )
