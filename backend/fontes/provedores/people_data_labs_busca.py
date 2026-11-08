"""People Data Labs: Person Search pela API oficial, a fonte principal da busca real.

Referências: docs.peopledatalabs.com/docs/reference-person-search-api,
/docs/input-parameters-person-search-api, /docs/examples-person-search-api,
/docs/elasticsearch-mapping, /docs/authentication e /docs/errors.

Cobrança: um crédito por registro devolvido em `data`. O 404 significa sem resultado e não cobra.
A consulta vai no corpo do POST e a chave no cabeçalho `X-Api-Key`, nunca na URL.

Paginação: cada resposta traz um `scroll_token`, que pede o lote seguinte da mesma consulta.
O token fica guardado por consulta, em memória. Sem ele, a página seguinte termina vazia.

Pessoa vinda daqui chega sem autorização de contato, como as da Brave, e para no funil.
"""

import json
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from backend.agente.auditoria import rastreado
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.modelos import ConsultaProvedor, ItemColetado, RespostaProvedor
from backend.fontes.provedores.people_data_labs import (
    CAMPOS_PEDIDOS,
    CUSTO_CREDITO_USD,
    conferir_status,
    item_de_registro,
)
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp, Transporte
from backend.fontes.provedores.url_segura import validar_texto_de_busca

NOME = "people_data_labs_busca"
ETAPA_PDL_BUSCA = "provedor_people_data_labs_busca"
URL_BUSCA = "https://api.peopledatalabs.com/v5/person/search"
PAIS_PADRAO = "brazil"
"""`location_country` é `keyword`, com o nome do país em inglês e minúsculas."""
TAMANHO_PAGINA_PADRAO = 10
TAMANHO_PAGINA_MAXIMO = 100
"""A documentação aceita `size` de 1 a 100."""
CAMPOS_DE_BUSCA = ("job_title", "skills", "summary", "experience.title.name")
TAMANHO_MINIMO_TERMO = 3
"""Deixa de fora conectivos como `de` e `em`, que achariam qualquer resumo em português."""
CONECTIVOS = frozenset({"com", "das", "dos", "para", "por", "uma", "and", "for", "the", "with"})
TOKENS_GUARDADOS = 1000
_PAIS = re.compile(r"[a-z][a-z ]{1,59}")
_TOKEN = re.compile(r"[A-Za-z0-9$._-]{1,256}")


def _ler_json(resposta: RespostaHttp) -> Any:
    try:
        return json.loads(resposta.corpo)
    except (ValueError, RecursionError):
        return None


def termos_da_consulta(texto: str) -> list[str]:
    """O texto inteiro, que acha cargo e competência exatos, e cada palavra relevante dele.

    O PDL guarda o texto em minúsculas, e `job_title`, `skills` e `experience.title.name` são
    `keyword`: só o valor inteiro casa. Por isso cada palavra também vira termo.
    """
    palavras = texto.casefold().split()
    termos = [" ".join(palavras)]
    for palavra in palavras:
        if len(palavra) >= TAMANHO_MINIMO_TERMO and palavra not in CONECTIVOS:
            if palavra not in termos:
                termos.append(palavra)
    return termos


def validar_pais(pais: Any) -> str:
    """Nome do país em inglês, como no `location_country` do PDL. Devolve em minúsculas."""
    normalizado = pais.strip().casefold() if isinstance(pais, str) else ""
    if not _PAIS.fullmatch(normalizado):
        raise ValueError("use o nome do país em inglês, só com letras e espaços")
    return normalizado


def validar_tamanho_pagina(tamanho: Any) -> int:
    if (
        not isinstance(tamanho, int)
        or isinstance(tamanho, bool)
        or not 1 <= tamanho <= TAMANHO_PAGINA_MAXIMO
    ):
        raise ValueError(f"use um inteiro de 1 a {TAMANHO_PAGINA_MAXIMO}")
    return tamanho


class ProvedorPeopleDataLabsBusca:
    """Implementa `ProvedorDados`, só para consultas de texto."""

    nome = NOME

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        pais: str = PAIS_PADRAO,
        tamanho_pagina: int = TAMANHO_PAGINA_PADRAO,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
        custo_credito_usd: float = CUSTO_CREDITO_USD,
    ) -> None:
        self._chave = chave
        self._transporte = transporte
        self._pais = validar_pais(pais)
        self._tamanho = validar_tamanho_pagina(tamanho_pagina)
        self._relogio = relogio
        self._custo_credito = custo_credito_usd
        self._tokens: OrderedDict[str, str] = OrderedDict()
        self._trava = threading.Lock()

    @property
    def custo_por_pagina(self) -> float:
        """A busca cobra por registro: o pior caso é a página inteira."""
        return self._tamanho * self._custo_credito

    def aceita(self, consulta: ConsultaProvedor) -> bool:
        return consulta.texto is not None

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        return self.custo_por_pagina

    def _consulta_elasticsearch(self, texto: str) -> dict[str, Any]:
        return {
            "bool": {
                "should": [
                    {"match": {campo: termo}}
                    for termo in termos_da_consulta(texto)
                    for campo in CAMPOS_DE_BUSCA
                ],
                "minimum_should_match": 1,
                "filter": [{"term": {"location_country": self._pais}}],
            }
        }

    @rastreado(ETAPA_PDL_BUSCA)
    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor:
        if consulta.texto is None:
            raise ErroProvedor(MotivoTroca.CONSULTA_NAO_SUPORTADA)
        validar_texto_de_busca(consulta.texto)
        corpo: dict[str, Any] = {
            "query": self._consulta_elasticsearch(consulta.texto),
            "size": self._tamanho,
            "data_include": ",".join(CAMPOS_PEDIDOS),
        }
        if consulta.pagina > 1:
            token = self._token_de(consulta)
            if token is None:
                return RespostaProvedor()
            corpo["scroll_token"] = token
        resposta = self._transporte.enviar(
            PedidoHttp(
                metodo="POST",
                url=URL_BUSCA,
                cabecalhos={"X-Api-Key": self._chave, "Content-Type": "application/json"},
                corpo_json=corpo,
            )
        )
        if not conferir_status(resposta, NOME):
            return RespostaProvedor()
        return self._encontrados(consulta, resposta)

    def _token_de(self, consulta: ConsultaProvedor) -> str | None:
        with self._trava:
            return self._tokens.get(consulta.chave())

    def _guardar_token(self, consulta: ConsultaProvedor, token: Any) -> None:
        """O token vale para a página seguinte desta consulta. Fora do formato, não é usado."""
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return
        seguinte = consulta.model_copy(update={"pagina": consulta.pagina + 1}).chave()
        with self._trava:
            self._tokens[seguinte] = token
            self._tokens.move_to_end(seguinte)
            while len(self._tokens) > TOKENS_GUARDADOS:
                self._tokens.popitem(last=False)

    def _encontrados(self, consulta: ConsultaProvedor, resposta: RespostaHttp) -> RespostaProvedor:
        """Toda resposta 200 já foi cobrada. Sem saber quantos registros vieram, conta a página."""
        corpo = _ler_json(resposta)
        registros = corpo.get("data") if isinstance(corpo, dict) else None
        if not isinstance(registros, list):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self.custo_por_pagina)
        self._guardar_token(consulta, corpo.get("scroll_token"))
        itens = [item for item in map(self._item, registros) if item is not None]
        return RespostaProvedor(itens=itens, custo_usd=len(registros) * self._custo_credito)

    def _item(self, registro: Any) -> ItemColetado | None:
        """Registro fora do formato fica de fora sem derrubar os outros, já cobrados."""
        if not isinstance(registro, dict):
            return None
        try:
            return item_de_registro(
                registro,
                provedor=NOME,
                fonte=f"{NOME}:person_search",
                coletado_em=self._relogio(),
            )
        except ValidationError:  # o erro do pydantic copia o dado recebido: não vai adiante
            return None
