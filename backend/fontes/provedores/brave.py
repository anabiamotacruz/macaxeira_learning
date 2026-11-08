"""Brave Search: busca de texto na web pela API oficial, em índice próprio da Brave.

Referências: api-dashboard.search.brave.com/api-reference/web/search/post (também documenta o GET),
/documentation/guides/rate-limiting, /terms-of-service e brave.com/search/api (preço e FAQ).

Usa o POST, com a consulta no corpo: o cliente HTTP registra a URL em log, e a consulta não pode
aparecer lá. A referência só descreve o erro de 404, 422 e 429. O 401, o 403 e o código
`SUBSCRIPTION_TOKEN_INVALID` num 422 foram tratados por precaução, sem confirmação oficial.

Armazenamento: os termos (seção 3(b)(i)) proíbem guardar, fazer cache ou montar base de resultados,
salvo armazenamento transitório necessário à operação. O FAQ só libera com plano que inclua esse
direito, e a Brave não publica qual é. Enquanto ele não estiver contratado, resultado desta fonte
não pode ser gravado no banco de talentos: ver a questão Q4 da spec 004.
"""

import html
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca, UrlRecusada
from backend.fontes.provedores.modelos import (
    ConfiancaDado,
    ConsultaProvedor,
    ItemColetado,
    RespostaProvedor,
)
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte
from backend.fontes.provedores.url_segura import validar_forma, validar_texto_de_busca

logger = logging.getLogger(__name__)

NOME = "brave"
ETAPA_BRAVE = "provedor_brave"
URL_BUSCA = "https://api.search.brave.com/res/v1/web/search"
CUSTO_REQUISICAO_USD = 0.005
"""Plano Search: US$ 5 por mil requisições. Só requisição sem erro é cobrada."""
RESULTADOS_POR_PAGINA = 20
"""O máximo da API, e o preço é por requisição."""
OFFSET_MAXIMO = 9
"""`offset` conta páginas, não resultados, e vai de 0 a 9."""
MAX_PALAVRAS_CONSULTA = 75
"""Limite de `q` na API, junto de 600 caracteres, que `ConsultaProvedor` já não deixa chegar."""
EXCLUSAO_NA_BUSCA = "-site:linkedin.com"
_TOKEN_INVALIDO = "SUBSCRIPTION_TOKEN_INVALID"
_CODIGO_SEGURO = re.compile(r"[A-Z0-9_]{1,64}")
_MARCACAO = re.compile(r"</?[a-zA-Z][^<>]*>")


def _ler_json(resposta: RespostaHttp) -> Any:
    try:
        return json.loads(resposta.corpo)
    except (ValueError, RecursionError):
        return None


def _codigo_de_erro(resposta: RespostaHttp) -> str:
    """`error.code` da resposta. O `detail` nunca é lido: pode repetir a consulta."""
    dados = _ler_json(resposta)
    erro = dados.get("error") if isinstance(dados, dict) else None
    codigo = erro.get("code") if isinstance(erro, dict) else None
    return codigo if isinstance(codigo, str) and _CODIGO_SEGURO.fullmatch(codigo) else "-"


def _valor_mensal(cabecalhos: dict[str, str], nome: str) -> int | None:
    """Os cabeçalhos de limite trazem `por segundo, por mês`, como em `1, 15000`."""
    partes = cabecalhos.get(nome, "").split(",")
    if len(partes) != 2 or not partes[1].strip().isdigit():
        return None
    return int(partes[1])


def _cota_mensal_esgotada(cabecalhos: dict[str, str]) -> bool:
    """Limite mensal 0 significa ilimitado, segundo a documentação."""
    limite = _valor_mensal(cabecalhos, "x-ratelimit-limit")
    return bool(limite) and _valor_mensal(cabecalhos, "x-ratelimit-remaining") == 0


def _sem_marcacao(valor: Any) -> str:
    """A API destaca os termos com HTML no título e no trecho."""
    return html.unescape(_MARCACAO.sub("", valor)).strip() if isinstance(valor, str) else ""


class ProvedorBrave:
    """Implementa `ProvedorDados`, só para consultas de texto."""

    nome = NOME

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
        custo_requisicao_usd: float = CUSTO_REQUISICAO_USD,
    ) -> None:
        self._chave = chave
        self._transporte = transporte
        self._relogio = relogio
        self._custo = custo_requisicao_usd

    def aceita(self, consulta: ConsultaProvedor) -> bool:
        return consulta.texto is not None

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        return self._custo

    @rastreado(ETAPA_BRAVE)
    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor:
        if consulta.texto is None:
            raise ErroProvedor(MotivoTroca.CONSULTA_NAO_SUPORTADA)
        validar_texto_de_busca(consulta.texto)
        texto = f"{consulta.texto} {EXCLUSAO_NA_BUSCA}"
        if len(texto.split()) > MAX_PALAVRAS_CONSULTA:
            raise ErroProvedor(MotivoTroca.CONSULTA_INVALIDA)
        offset = consulta.pagina - 1
        if offset > OFFSET_MAXIMO:
            return RespostaProvedor()
        resposta = self._transporte.enviar(
            PedidoHttp(
                metodo="POST",
                url=URL_BUSCA,
                cabecalhos={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Subscription-Token": self._chave,
                },
                corpo_json={
                    "q": texto,
                    "country": "BR",
                    "search_lang": "pt-br",
                    "ui_lang": "pt-BR",
                    "count": RESULTADOS_POR_PAGINA,
                    "offset": offset,
                },
            )
        )
        self._conferir_status(resposta)
        return RespostaProvedor(
            itens=[item for item in map(self._item, self._resultados(resposta)) if item],
            custo_usd=self._custo,
        )

    @staticmethod
    def _conferir_status(resposta: RespostaHttp) -> None:
        status = resposta.status
        if 200 <= status < 300:
            return
        if status >= 500:
            raise FonteIndisponivel(f"{NOME}: status {status}")
        if status == 429 and not _cota_mensal_esgotada(resposta.cabecalhos):
            raise FonteIndisponivel(f"{NOME}: limite de requisições excedido (status 429)")
        codigo = _codigo_de_erro(resposta)
        logger.warning("brave recusou a consulta: status=%s codigo=%s", status, codigo)
        if status == 429:
            raise ErroProvedor(MotivoTroca.SEM_CREDITOS)
        if status == 401 or codigo == _TOKEN_INVALIDO:
            raise ErroProvedor(MotivoTroca.AUTENTICACAO)
        if status == 422:
            raise ErroProvedor(MotivoTroca.CONSULTA_INVALIDA)
        if status >= 400:
            raise ErroProvedor(MotivoTroca.RECUSADO_PELO_PROVEDOR)
        raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA)

    def _resultados(self, resposta: RespostaHttp) -> list[Any]:
        """Sem `web`, não achou nada. A requisição já foi cobrada, mesmo com resposta inválida."""
        dados = _ler_json(resposta)
        web = dados.get("web", {}) if isinstance(dados, dict) else None
        resultados = web.get("results", []) if isinstance(web, dict) else None
        if not isinstance(resultados, list):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self._custo)
        return resultados

    def _item(self, resultado: Any) -> ItemColetado | None:
        if not isinstance(resultado, dict):
            return None
        url = resultado.get("url")
        try:
            validar_forma(url)
        except UrlRecusada:
            return None
        titulo = _sem_marcacao(resultado.get("title"))
        partes = [parte for parte in (titulo, _sem_marcacao(resultado.get("description"))) if parte]
        if not partes:
            return None
        atributos = {"titulo": titulo} if titulo else {}
        data_pagina = resultado.get("page_age")
        if isinstance(data_pagina, str) and data_pagina:
            atributos["data_pagina"] = data_pagina
        return ItemColetado(
            provedor=NOME,
            fonte=f"{NOME}:busca",
            coletado_em=self._relogio(),
            url=url,
            confianca=ConfiancaDado.DECLARADO,
            texto=". ".join(partes),
            atributos=atributos,
        )
