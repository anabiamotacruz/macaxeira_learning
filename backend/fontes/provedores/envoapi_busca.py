"""Busca de pessoas da EnvoAPI: a fonte principal da busca real (decisão do usuário em 8/11/2026).

"Faça esse caminho e coloque o Brave como fallback." A extração por perfil custa 1 crédito por
pessoa; a busca custa 1 crédito por chamada e devolve até 10 perfis completos. Medido em 8/11:
1 crédito trouxe 6 perfis, e o agente indicou 4. O `linkedin_brave` (Brave mais extração) vira a
reserva, logo depois deste provedor na cadeia.

Referência consultada em 8/11/2026: docs.envoapi.com/api/operations/searchpeoplebykeyword/.
- `GET https://api.envoapi.com/v1/profiles/search`, com `Authorization: Bearer <chave>`.
- Parâmetros: `keywords` (1 a 120 caracteres), `profileLanguage` e `offset` (0 a 50). `location`
  exige ids de outra busca e não é usado.
- Resposta: `data.profiles[]` (`publicId`, `name`, `headline`, `summary`, `location`,
  `countryISOCode`, `linkedinUrl`, `positions[]`, `education[]`, `skills[]`) e `meta.paging`
  (`hasMore`, `nextOffset`). `meta.creditCost` é 1.

Decisões:
- O filtro de país (`countryISOCode`) é local: a chamada já foi paga, mesmo que nenhum perfil
  sobre. Perfil sem país fica fora enquanto o filtro estiver ligado.
- A página N usa o `nextOffset` guardado pela página N-1 da mesma consulta. Sem ele, sem `hasMore`
  ou acima de 50, a página termina vazia e sem custo.
- O `linkedinUrl` só vira `atributos["usuario_linkedin"]`, para a consulta de contato. Nenhuma URL
  do LinkedIn vira `item.url`, e nenhum contato entra: o `item_de_registro` só lê os campos
  convertidos, e e-mail não está entre eles.
- Limitador de ritmo, espera do 429 e mapeamento de erro são os mesmos da extração de perfil.
"""

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores import envoapi
from backend.fontes.provedores.envoapi import (
    CREDITOS_POR_CONSULTA,
    CUSTO_CREDITO_USD,
    TENTATIVAS_APOS_429,
    URL_BASE,
    LimitadorDePedidos,
    registro_de_perfil_envo,
    usuario_de,
)
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.modelos import ConsultaProvedor, ItemColetado, RespostaProvedor
from backend.fontes.provedores.people_data_labs import item_de_registro
from backend.fontes.provedores.transporte import (
    USER_AGENT_PADRAO,
    PedidoHttp,
    RespostaHttp,
    Transporte,
)
from backend.fontes.provedores.url_segura import validar_texto_de_busca

logger = logging.getLogger(__name__)

NOME = "envoapi_busca"
ETAPA_ENVOAPI_BUSCA = "provedor_envoapi_busca"
URL_BUSCA = f"{URL_BASE}/v1/profiles/search"
IDIOMA_PERFIL = "pt"
PAIS_PADRAO = "BR"
TAMANHO_MAXIMO_PALAVRAS = 120
OFFSET_MAXIMO = 50
OFFSETS_GUARDADOS = 1000
_PAIS = re.compile(r"[A-Z]{2}")


def validar_pais(pais: Any) -> str:
    """Código ISO de duas letras, como o `countryISOCode`. Devolve em maiúsculas."""
    normalizado = pais.strip().upper() if isinstance(pais, str) else ""
    if not _PAIS.fullmatch(normalizado):
        raise ValueError("use o código ISO do país, com duas letras (por exemplo, BR)")
    return normalizado


def palavras_chave(texto: str) -> str:
    """O texto em até 120 caracteres, sem cortar palavra no meio."""
    palavras = texto.split()
    saida = ""
    for palavra in palavras:
        candidata = f"{saida} {palavra}" if saida else palavra
        if len(candidata) > TAMANHO_MAXIMO_PALAVRAS:
            break
        saida = candidata
    return saida or (palavras[0][:TAMANHO_MAXIMO_PALAVRAS] if palavras else "")


def _offset_valido(valor: Any) -> int | None:
    if isinstance(valor, int) and not isinstance(valor, bool) and 0 <= valor <= OFFSET_MAXIMO:
        return valor
    return None


def _adaptado(perfil: dict[str, Any]) -> dict[str, Any]:
    """Leva o perfil da busca ao formato do de detalhes, que `registro_de_perfil_envo` lê."""
    return {
        "fullName": perfil.get("name"),
        "headline": perfil.get("headline"),
        "summary": perfil.get("summary"),
        "location": perfil.get("location"),
        "experience": perfil.get("positions"),
        "education": perfil.get("education"),
        "skills": perfil.get("skills"),
    }


class ProvedorEnvoBusca:
    """Implementa `ProvedorDados`, só para consultas de texto."""

    nome = NOME

    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        *,
        pais: str | None = PAIS_PADRAO,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
        custo_credito_usd: float = CUSTO_CREDITO_USD,
        dormir: Callable[[float], None] = time.sleep,
        limitador: LimitadorDePedidos | None = None,
    ) -> None:
        self._chave = chave
        self._transporte = transporte
        self.pais = None if pais is None else validar_pais(pais)
        self._relogio = relogio
        self._custo = custo_credito_usd
        self._dormir = dormir
        self._limitador = limitador or envoapi.limitador_do_processo()
        self._offsets: OrderedDict[str, int] = OrderedDict()
        self._trava = threading.Lock()

    def __repr__(self) -> str:
        return f"ProvedorEnvoBusca(pais={self.pais})"

    @property
    def custo_por_chamada_usd(self) -> float:
        return CREDITOS_POR_CONSULTA * self._custo

    def aceita(self, consulta: ConsultaProvedor) -> bool:
        return consulta.texto is not None

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        return self.custo_por_chamada_usd

    def _enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        self._limitador.esperar_a_vez()
        try:
            return self._transporte.enviar(pedido)
        except (ConnectionError, TimeoutError) as erro:
            logger.warning("envoapi_busca indisponível: erro de rede (%s)", type(erro).__name__)
            raise FonteIndisponivel(f"{NOME}: erro de rede") from None

    def _pedido(self, texto: str, offset: int) -> PedidoHttp:
        parametros = {
            "keywords": palavras_chave(texto),
            "profileLanguage": IDIOMA_PERFIL,
            "offset": str(offset),
        }
        return PedidoHttp(
            metodo="GET",
            url=f"{URL_BUSCA}?{urlencode(parametros)}",
            cabecalhos={
                "Authorization": f"Bearer {self._chave}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT_PADRAO,
            },
        )

    @rastreado(ETAPA_ENVOAPI_BUSCA)
    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor:
        if consulta.texto is None:
            raise ErroProvedor(MotivoTroca.CONSULTA_NAO_SUPORTADA)
        validar_texto_de_busca(consulta.texto)
        offset = 0
        if consulta.pagina > 1:
            with self._trava:
                guardado = self._offsets.get(consulta.chave())
            if guardado is None:
                return RespostaProvedor()
            offset = guardado
        pedido = self._pedido(consulta.texto, offset)
        resposta = self._enviar(pedido)
        for _ in range(TENTATIVAS_APOS_429):
            if resposta.status != 429:
                break
            espera = envoapi._espera(resposta)
            logger.warning("envoapi_busca: limite de ritmo, nova tentativa em %.0f s", espera)
            self._dormir(espera)
            resposta = self._enviar(pedido)
        corpo = envoapi._ler_json(resposta)
        if resposta.status == 404:
            return RespostaProvedor(custo_usd=self.custo_por_chamada_usd)
        if resposta.status != 200:
            envoapi._levantar_erro(resposta, corpo)
        return self._encontrados(consulta, corpo)

    def _encontrados(self, consulta: ConsultaProvedor, corpo: Any) -> RespostaProvedor:
        """A chamada 200 já foi cobrada, aproveite ou não algum perfil."""
        dados = corpo.get("data") if isinstance(corpo, dict) else None
        perfis = dados.get("profiles") if isinstance(dados, dict) else None
        if not isinstance(perfis, list):
            raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, self.custo_por_chamada_usd)
        self._guardar_offset(consulta, corpo.get("meta"))
        do_pais = [p for p in perfis if isinstance(p, dict) and self._no_pais(p)]
        itens = [item for item in map(self._item, do_pais) if item is not None]
        logger.info(
            "envoapi_busca: %s perfil(is) recebido(s), %s no país, %s aproveitado(s), "
            "%s crédito(s)",
            len(perfis),
            len(do_pais),
            len(itens),
            CREDITOS_POR_CONSULTA,
        )
        return RespostaProvedor(itens=itens, custo_usd=self.custo_por_chamada_usd)

    def _guardar_offset(self, consulta: ConsultaProvedor, meta: Any) -> None:
        paging = meta.get("paging") if isinstance(meta, dict) else None
        if not isinstance(paging, dict) or paging.get("hasMore") is not True:
            return
        offset = _offset_valido(paging.get("nextOffset"))
        if offset is None:
            return
        seguinte = consulta.model_copy(update={"pagina": consulta.pagina + 1}).chave()
        with self._trava:
            self._offsets[seguinte] = offset
            self._offsets.move_to_end(seguinte)
            while len(self._offsets) > OFFSETS_GUARDADOS:
                self._offsets.popitem(last=False)

    def _no_pais(self, perfil: dict[str, Any]) -> bool:
        if self.pais is None:
            return True
        codigo = perfil.get("countryISOCode")
        return isinstance(codigo, str) and codigo.strip().upper() == self.pais

    def _item(self, perfil: dict[str, Any]) -> ItemColetado | None:
        """Perfil fora do formato fica de fora sem derrubar os outros, já cobrados."""
        atributos: dict[str, str] = {}
        url = perfil.get("linkedinUrl")
        usuario = usuario_de(url) if isinstance(url, str) and "/in/" in url else None
        if usuario is not None:
            atributos["usuario_linkedin"] = usuario.casefold()
        try:
            return item_de_registro(
                registro_de_perfil_envo(_adaptado(perfil)),
                provedor=NOME,
                fonte=f"{NOME}:busca",
                coletado_em=self._relogio(),
                atributos=atributos,
            )
        except ValidationError:  # o erro do pydantic copia o dado recebido: não vai adiante
            return None
