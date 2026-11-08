"""LinkdAPI: busca de pessoas e perfil completo do LinkedIn por API de terceiros (linkdapi.com).

Decisão do dono do produto em 8/11/2026: é a primeira fonte da busca real quando há chave, com
chaves de reserva (`LINK_API_KEY`, `LINK_API_KEY_2`…). Cada chave vira uma instância própria,
rotulada `linkdapi#N`, com o próprio disjuntor: quando uma fica sem crédito ou é recusada, a
cadeia passa para a seguinte. Os itens guardam o nome lógico `linkdapi` em `provedor` e `fonte`.

Referências consultadas em 8/11/2026:
- linkdapi.com/docs/intro: base `https://linkdapi.com`, chave no cabeçalho `X-linkdapi-apikey`,
  envelope `success`, `statusCode`, `message`, `data` (e `errors` no erro); 401 sem chave,
  404 rota inexistente e 429 limite de ritmo (com `current_limit` e `current_tier`).
- linkdapi.com/docs?endpoint=/api/v1/search/people: `GET /api/v1/search/people` com `keyword`,
  `title`, `geoUrn` (IDs de `/api/v1/geos/name-lookup`), `start` e `count` (1 a 50). Não há filtro
  de competência. Cada página pode vir com menos resultados: perfis restritos ficam de fora.
- linkdapi.com/docs?endpoint=/api/v1/profile/full: `GET /api/v1/profile/full` por `username` ou
  `urn`, com todos os campos numa chamada.
- linkdapi.com/docs/endpoints-cost: 1 crédito por requisição, salvo indicação.
- linkdapi.com (tabela de níveis) e /docs/account: créditos por dólar de 100 (nível Testing,
  US$ 0,01 por crédito) a 400; o limite por minuto depende do saldo.

Suposições, sem confirmação na documentação (não há chave para conferir):
- Formato dos itens: `data.people[]` com `fullName`, `headline`, `location`, `username`, `urn`
  (o exemplo da página inicial mostra `people`, `fullName`, `headline` e `location`). No perfil,
  `summary`/`about`, `experience`/`experiences`/`positions` (`title`, `companyName`, `start` com
  `year` e `month`) e `skills` (texto ou `{name}`).
- Falta de crédito e chave inválida: a documentação não publica o código. Tratados pelo status
  (401/403 chave, 402 crédito) e pela palavra da `message`, que nunca vai a log nem a exceção.
- Erro não é cobrado. Resposta 200 conta um crédito por requisição.

Local: `geoUrn` só aceita ID. Valor numérico em `LINKDAPI_LOCAL` vai como `geoUrn`; um nome, como o
padrão `Brazil`, entra na palavra-chave, sem gastar uma chamada na consulta de IDs.

O endereço do perfil é do LinkedIn: a política de URL o recusa em `ItemColetado.url`, e o texto
perde os links. O `username` fica em `atributos["usuario_linkedin"]`. Contato não entra: a
documentação não diz se a própria pessoa publicou (só o endpoint de contato, não usado, promete
isso), e na dúvida nada entra. Pessoa vinda daqui chega sem autorização, como as da Brave.
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.modelos import (
    ConsultaProvedor,
    ItemColetado,
    RespostaProvedor,
)
from backend.fontes.provedores.people_data_labs import item_de_registro
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte
from backend.fontes.provedores.url_segura import validar_texto_de_busca

logger = logging.getLogger(__name__)

NOME = "linkdapi"
ETAPA_LINKDAPI = "provedor_linkdapi"
URL_BASE = "https://linkdapi.com"
URL_BUSCA = f"{URL_BASE}/api/v1/search/people"
URL_PERFIL = f"{URL_BASE}/api/v1/profile/full"
CABECALHO_CHAVE = "X-linkdapi-apikey"
CUSTO_CREDITO_USD = 0.01
"""1 crédito por requisição; US$ 0,01 é o crédito mais caro da tabela (nível Testing): é o teto."""
RESULTADOS_POR_PAGINA = 10
"""`count` aceita até 50. Dez basta para uma página e combina com o teto padrão de perfis."""
LOCAL_PADRAO = "Brazil"
PERFIS_POR_PAGINA_PADRAO = 10
PERFIS_POR_PAGINA_MAXIMO = 50
_LOCAL = re.compile(r"[A-Za-zÀ-ÿ0-9 ,.-]{1,60}")
_IDENTIFICADOR = re.compile(r"[A-Za-z0-9_%.:-]{1,200}")
"""`username` ou `urn` do perfil. Fora do formato, o perfil completo não é pedido."""
_FALTA_CREDITO = re.compile(r"credit|balance|quota|insufficient|top ?up|saldo", re.IGNORECASE)
_CHAVE_INVALIDA = re.compile(r"api ?key|unauthori[sz]ed|forbidden", re.IGNORECASE)
_LISTAS_EXPERIENCIA = ("experience", "experiences", "positions", "position")
_LISTAS_FORMACAO = ("education", "educations")


def validar_local(local: Any) -> str:
    texto = local.strip() if isinstance(local, str) else ""
    if not _LOCAL.fullmatch(texto):
        raise ValueError("use um nome de local ou um geoUrn numérico, com até 60 caracteres")
    return texto


def validar_perfis_por_pagina(valor: Any) -> int:
    if (
        not isinstance(valor, int)
        or isinstance(valor, bool)
        or not 0 <= valor <= PERFIS_POR_PAGINA_MAXIMO
    ):
        raise ValueError(f"use um inteiro de 0 a {PERFIS_POR_PAGINA_MAXIMO}")
    return valor


def _ler_json(resposta: RespostaHttp) -> Any:
    try:
        return json.loads(resposta.corpo)
    except (ValueError, RecursionError):
        return None


def _mensagem(corpo: Any) -> str:
    """Só para classificar o erro. Nunca vai a log nem a exceção: pode repetir a consulta."""
    mensagem = corpo.get("message") if isinstance(corpo, dict) else None
    return mensagem[:500] if isinstance(mensagem, str) else ""


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def _nome_de(valor: Any) -> str:
    if isinstance(valor, dict):
        return _texto(valor.get("name"))
    return _texto(valor)


def _data(valor: Any) -> str | None:
    """`{year, month}` ou texto `AAAA-MM`, no formato que `item_de_registro` já lê."""
    if isinstance(valor, str):
        return valor or None
    if not isinstance(valor, dict):
        return None
    ano, mes = valor.get("year"), valor.get("month")
    if not isinstance(ano, int) or isinstance(ano, bool):
        return None
    if isinstance(mes, int) and not isinstance(mes, bool) and 1 <= mes <= 12:
        return f"{ano:04d}-{mes:02d}"
    return f"{ano:04d}"


def _local(valor: Any) -> str:
    if isinstance(valor, dict):
        partes = [_texto(valor.get(campo)) for campo in ("city", "country", "countryCode")]
        return ", ".join(dict.fromkeys(p for p in partes if p))
    return _texto(valor)


def _lista(dados: dict[str, Any], nomes: tuple[str, ...]) -> list[Any]:
    for nome in nomes:
        valor = dados.get(nome)
        if isinstance(valor, list):
            return valor
    return []


def _experiencias(dados: dict[str, Any]) -> list[dict[str, Any]]:
    convertidas = []
    for bruta in _lista(dados, _LISTAS_EXPERIENCIA):
        if not isinstance(bruta, dict):
            continue
        empresa = _nome_de(bruta.get("companyName")) or _nome_de(bruta.get("company"))
        convertidas.append(
            {
                "company": {"name": empresa},
                "title": {"name": _nome_de(bruta.get("title"))},
                "start_date": _data(bruta.get("start") or bruta.get("startDate")),
                "end_date": _data(bruta.get("end") or bruta.get("endDate")),
            }
        )
    return convertidas


def _formacoes(dados: dict[str, Any]) -> list[dict[str, Any]]:
    convertidas = []
    for bruta in _lista(dados, _LISTAS_FORMACAO):
        if not isinstance(bruta, dict):
            continue
        escola = _nome_de(bruta.get("schoolName")) or _nome_de(bruta.get("school"))
        grau = _nome_de(bruta.get("degreeName")) or _nome_de(bruta.get("degree"))
        convertidas.append({"school": {"name": escola}, "degrees": [grau] if grau else []})
    return convertidas


def registro_de_perfil(dados: dict[str, Any]) -> dict[str, Any]:
    """Converte para o formato lido por `item_de_registro`. Contato nunca é copiado."""
    competencias = [_nome_de(c) for c in dados.get("skills") or [] if _nome_de(c)]
    return {
        "full_name": _texto(dados.get("fullName")),
        "job_title": _texto(dados.get("headline")),
        "location_name": _local(dados.get("location")),
        "summary": _texto(dados.get("summary")) or _texto(dados.get("about")),
        "skills": competencias if isinstance(dados.get("skills"), list) else [],
        "experience": _experiencias(dados),
        "education": _formacoes(dados),
    }


def _tem_perfil(dados: dict[str, Any]) -> bool:
    """A busca já trouxe experiência e competências: o perfil completo seria pago à toa."""
    return bool(_lista(dados, _LISTAS_EXPERIENCIA)) and bool(dados.get("skills"))


class ProvedorLinkdApi:
    """Implementa `ProvedorDados` para uma chave. Só consultas de texto."""

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        indice: int = 1,
        local: str = LOCAL_PADRAO,
        perfis_por_pagina: int = PERFIS_POR_PAGINA_PADRAO,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
        custo_credito_usd: float = CUSTO_CREDITO_USD,
    ) -> None:
        self.nome = f"{NOME}#{indice}"
        self._indice = indice
        self._chave = chave
        self._transporte = transporte
        self._local = validar_local(local)
        self._perfis = validar_perfis_por_pagina(perfis_por_pagina)
        self._relogio = relogio
        self._custo = custo_credito_usd

    def __repr__(self) -> str:
        return f"ProvedorLinkdApi(chave=#{self._indice})"

    def aceita(self, consulta: ConsultaProvedor) -> bool:
        return consulta.texto is not None

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        """Uma busca mais o teto de perfis completos."""
        return (1 + self._perfis) * self._custo

    def _pedido(self, url: str, parametros: dict[str, str]) -> PedidoHttp:
        return PedidoHttp(
            metodo="GET",
            url=f"{url}?{urlencode(parametros)}",
            cabecalhos={CABECALHO_CHAVE: self._chave, "Accept": "application/json"},
        )

    def _parametros_da_busca(self, consulta: ConsultaProvedor) -> dict[str, str]:
        palavras = consulta.texto or ""
        parametros: dict[str, str] = {}
        if self._local.isdigit():
            parametros["geoUrn"] = self._local
        else:
            palavras = f"{palavras} {self._local}"
        parametros |= {
            "keyword": palavras,
            "start": str((consulta.pagina - 1) * RESULTADOS_POR_PAGINA),
            "count": str(RESULTADOS_POR_PAGINA),
        }
        return parametros

    @rastreado(ETAPA_LINKDAPI)
    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor:
        if consulta.texto is None:
            raise ErroProvedor(MotivoTroca.CONSULTA_NAO_SUPORTADA)
        validar_texto_de_busca(consulta.texto)
        resposta = self._transporte.enviar(
            self._pedido(URL_BUSCA, self._parametros_da_busca(consulta))
        )
        corpo = self._conferir(resposta)
        dados = corpo.get("data")
        pessoas = dados.get("people") if isinstance(dados, dict) else None
        if not isinstance(pessoas, list):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo)
        return self._itens([p for p in pessoas if isinstance(p, dict)])

    def _conferir(self, resposta: RespostaHttp) -> dict[str, Any]:
        """Devolve o corpo de uma resposta boa. Erro sobe com o motivo, sem texto da resposta."""
        corpo = _ler_json(resposta)
        status = resposta.status
        sucesso = isinstance(corpo, dict) and corpo.get("success") is not False
        if status == 200 and sucesso:
            return corpo
        if status >= 500:
            raise FonteIndisponivel(f"{NOME}: status {status}")
        mensagem = _mensagem(corpo)
        if status == 200 and not isinstance(corpo, dict):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo)
        if status == 402 or _FALTA_CREDITO.search(mensagem):
            motivo = MotivoTroca.SEM_CREDITOS
        elif status == 429:
            raise FonteIndisponivel(f"{NOME}: limite de requisições excedido (status 429)")
        elif status in (401, 403) or _CHAVE_INVALIDA.search(mensagem):
            motivo = MotivoTroca.AUTENTICACAO
        elif status in (400, 422):
            motivo = MotivoTroca.CONSULTA_INVALIDA
        else:
            motivo = MotivoTroca.RECUSADO_PELO_PROVEDOR
        logger.warning(
            "linkdapi recusou a consulta: chave=#%s status=%s motivo=%s",
            self._indice,
            status,
            motivo.value,
        )
        raise ErroProvedor(motivo)

    def _itens(self, pessoas: list[dict[str, Any]]) -> RespostaProvedor:
        """Pede o perfil completo até o teto. Falha num perfil encerra os pedidos da página."""
        chamadas = 1
        pedidos_de_perfil = 0
        itens: list[ItemColetado] = []
        for pessoa in pessoas:
            completo = None
            if pedidos_de_perfil < self._perfis and not _tem_perfil(pessoa):
                parametros = self._identificador(pessoa)
                if parametros is not None:
                    pedidos_de_perfil += 1
                    completo = self._perfil(parametros)
                    if completo is None:
                        pedidos_de_perfil = self._perfis
                    else:
                        chamadas += 1
            item = self._item(completo or pessoa, pessoa)
            if item is not None:
                itens.append(item)
        return RespostaProvedor(itens=itens, custo_usd=chamadas * self._custo)

    @staticmethod
    def _identificador(pessoa: dict[str, Any]) -> dict[str, str] | None:
        for campo, parametro in (
            ("username", "username"),
            ("publicIdentifier", "username"),
            ("urn", "urn"),
        ):
            valor = _texto(pessoa.get(campo))
            if _IDENTIFICADOR.fullmatch(valor):
                return {parametro: valor}
        return None

    def _perfil(self, parametros: dict[str, str]) -> dict[str, Any] | None:
        """`None` quando o perfil não veio: o item fica com o que a busca trouxe."""
        try:
            corpo = self._conferir(self._transporte.enviar(self._pedido(URL_PERFIL, parametros)))
        except (ErroProvedor, FonteIndisponivel, ConnectionError, TimeoutError) as erro:
            logger.warning(
                "linkdapi: perfil completo não lido, chave=#%s erro=%s",
                self._indice,
                type(erro).__name__,
            )
            return None
        dados = corpo.get("data")
        return dados if isinstance(dados, dict) else None

    def _item(self, dados: dict[str, Any], pessoa: dict[str, Any]) -> ItemColetado | None:
        """Registro fora do formato fica de fora sem derrubar os outros, já cobrados."""
        atributos = {}
        usuario = _texto(pessoa.get("username")) or _texto(pessoa.get("publicIdentifier"))
        if _IDENTIFICADOR.fullmatch(usuario):
            atributos["usuario_linkedin"] = usuario
        registro = registro_de_perfil(dados)
        if not registro["full_name"]:
            registro["full_name"] = _texto(pessoa.get("fullName"))
        try:
            return item_de_registro(
                registro,
                provedor=NOME,
                fonte=f"{NOME}:people_search",
                coletado_em=self._relogio(),
                atributos=atributos,
            )
        except ValidationError:  # o erro do pydantic copia o dado recebido: não vai adiante
            return None
