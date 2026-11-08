"""LinkedIn pela Brave: a Brave acha os links dos perfis, e um extrator devolve o perfil completo.

Decisão do usuário em 8/11/2026: "o Brave só deve pegar os links dos perfis e jogar para o
LinkdAPI extrair os dados". Medido no mesmo dia: só com o trecho do buscador (cerca de 200 letras),
4 de 50 pessoas foram indicadas; com o perfil completo, 4 de 6. Depois, o dono do produto pôs a
EnvoAPI como extrator principal e a LinkdAPI como reserva, porque a chave da LinkdAPI estava sem
crédito.

Como funciona, por página:
1. Uma busca na Brave por `site:linkedin.com/in <texto>`, sem a exclusão do LinkedIn que o
   provedor `brave` normal acrescenta.
2. Dos resultados, só entram URLs de perfil (`https://(www.|br.)?linkedin.com/in/<usuario>`), e o
   usuário é normalizado. O resto é descartado.
3. Para cada usuário, até `perfis_por_pagina`, os extratores são tentados em ordem: EnvoAPI e, se
   ela falhar por falta de crédito, chave recusada ou indisponibilidade, a LinkdAPI, com uma
   instância por chave. Extrator que falha sai da página; o perfil segue para o próximo.
4. Quem não foi extraído não vira candidato: nunca entra só com o trecho do buscador.

Política de URL: o LinkedIn continua recusado para leitura de página. A URL ou o usuário só vão
como identificador nos pedidos à EnvoAPI e à LinkdAPI, que são hosts permitidos do transporte.
Nenhum pedido sai para o LinkedIn, e nenhuma URL do LinkedIn vira `ItemColetado.url`.

Cada item guarda a origem (`linkedin_brave:envoapi` ou `linkedin_brave:linkdapi`) e
`atributos["usuario_linkedin"]`, para a consulta de contato da EnvoAPI. Nenhum contato entra aqui,
e a pessoa chega sem autorização. O custo da página soma a busca da Brave e cada perfil cobrado.
"""

import logging
import re
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError

from backend.agente.auditoria import rastreado
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.brave import SITE_PERFIS_LINKEDIN, ProvedorBrave
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.linkdapi import (
    PERFIS_POR_PAGINA_PADRAO,
    validar_perfis_por_pagina,
)
from backend.fontes.provedores.modelos import ConsultaProvedor, ItemColetado, RespostaProvedor
from backend.fontes.provedores.people_data_labs import item_de_registro

__all__ = [
    "NOME",
    "PERFIS_POR_PAGINA_PADRAO",
    "SITE_PERFIS_LINKEDIN",
    "ExtratorPerfil",
    "ProvedorLinkedinPorBrave",
    "limpar_cache_de_perfis",
    "usuario_de_url_perfil",
]

logger = logging.getLogger(__name__)

NOME = "linkedin_brave"
ETAPA_LINKEDIN_BRAVE = "provedor_linkedin_brave"
TAMANHO_MAXIMO_URL = 2048
_HOSTS_PERFIL = frozenset({"linkedin.com", "www.linkedin.com", "br.linkedin.com"})
_CAMINHO_PERFIL = re.compile(r"/in/([A-Za-z0-9_%.-]{3,100})/?")
_TEM_LETRA_OU_NUMERO = re.compile(r"[A-Za-z0-9]")
_ERROS_DE_EXTRATOR = (FonteIndisponivel, ConnectionError, TimeoutError)


# Cache do processo, compartilhado por todas as instâncias e threads: cada crédito pago vira uma
# pessoa diferente. Guarda só o `ItemColetado` já limpo (nunca a resposta crua do extrator). `None`
# marca o perfil não encontrado (404) ou fora do formato, já cobrado e que não se tenta de novo.
# Falha de extrator (sem crédito, indisponível) não entra: a próxima consulta pode tentar.
_cache_de_perfis: dict[str, ItemColetado | None] = {}
_trava_do_cache = threading.Lock()
_travas_por_usuario: dict[str, threading.Lock] = {}


def limpar_cache_de_perfis() -> None:
    """Esvazia o cache de perfis. Usado nos testes."""
    with _trava_do_cache:
        _cache_de_perfis.clear()
        _travas_por_usuario.clear()


def _trava_do_usuario(usuario: str) -> threading.Lock:
    with _trava_do_cache:
        return _travas_por_usuario.setdefault(usuario, threading.Lock())


def _no_cache(usuario: str) -> bool:
    with _trava_do_cache:
        return usuario in _cache_de_perfis


class ExtratorPerfil(Protocol):
    """Devolve o registro no formato de `item_de_registro` e o custo cobrado.

    `None` no registro quando o perfil não existe ou veio fora do formato. Falta de crédito, chave
    recusada e indisponibilidade sobem como erro, para o extrator seguinte assumir.
    """

    nome: str
    origem: str

    @property
    def custo_por_perfil_usd(self) -> float: ...

    def perfil(self, usuario: str) -> tuple[dict[str, Any] | None, float]: ...


def usuario_de_url_perfil(url: Any) -> str | None:
    """O usuário de uma URL de perfil do LinkedIn, em minúsculas. Fora do formato, `None`."""
    if not isinstance(url, str) or len(url) > TAMANHO_MAXIMO_URL:
        return None
    try:
        partes = urlsplit(url.strip())
        porta = partes.port
    except ValueError:
        return None
    if (
        partes.scheme != "https"
        or partes.hostname not in _HOSTS_PERFIL
        or porta is not None
        or partes.username is not None
        or partes.password is not None
    ):
        return None
    achado = _CAMINHO_PERFIL.fullmatch(partes.path)
    if achado is None or not _TEM_LETRA_OU_NUMERO.search(achado.group(1)):
        return None
    return achado.group(1).casefold()


@dataclass
class _Pagina:
    ativos: list[ExtratorPerfil]
    custo: float
    perfis: Counter[str] = field(default_factory=Counter)
    do_cache: int = 0
    ultimo_motivo: MotivoTroca | None = None


class ProvedorLinkedinPorBrave:
    """Implementa `ProvedorDados`, só para consultas de texto."""

    nome = NOME

    def __init__(
        self,
        brave: ProvedorBrave,
        extratores: Sequence[ExtratorPerfil],
        *,
        perfis_por_pagina: int = PERFIS_POR_PAGINA_PADRAO,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not extratores:
            raise ValueError("informe pelo menos um extrator de perfil")
        self._brave = brave
        self.extratores = tuple(extratores)
        self._perfis = validar_perfis_por_pagina(perfis_por_pagina)
        self._relogio = relogio

    def __repr__(self) -> str:
        nomes = ",".join(extrator.nome for extrator in self.extratores)
        return f"ProvedorLinkedinPorBrave(extratores={nomes}, perfis={self._perfis})"

    def aceita(self, consulta: ConsultaProvedor) -> bool:
        return consulta.texto is not None

    def custo_maximo(self, consulta: ConsultaProvedor) -> float:
        """Uma busca da Brave mais o teto de perfis, pelo extrator mais caro."""
        preco = max(extrator.custo_por_perfil_usd for extrator in self.extratores)
        return self._brave.custo_requisicao_usd + self._perfis * preco

    @rastreado(ETAPA_LINKEDIN_BRAVE)
    def consultar(self, consulta: ConsultaProvedor) -> RespostaProvedor:
        resultados = self._brave.resultados_da_busca(consulta, perfis_linkedin=True)
        if resultados is None:
            return RespostaProvedor()
        usuarios = list(
            dict.fromkeys(
                usuario
                for usuario in (
                    usuario_de_url_perfil(r.get("url")) for r in resultados if isinstance(r, dict)
                )
                if usuario
            )
        )
        pagina = _Pagina(ativos=list(self.extratores), custo=self._brave.custo_requisicao_usd)
        itens: list[ItemColetado] = []
        novos = 0
        for usuario in usuarios:
            if not _no_cache(usuario):
                # O teto conta só quem ainda pode custar; quem está no cache entra de graça.
                if novos >= self._perfis:
                    continue
                novos += 1
            item = self._item_do_usuario(usuario, pagina)
            if item:
                itens.append(item)
        logger.warning(
            "linkedin_brave: página com %s usuário(s) achado(s), %s do cache, %s pago(s) "
            "(por extrator=%s), %s perfil(is) devolvido(s), custo US$ %.3f",
            len(usuarios),
            pagina.do_cache,
            sum(pagina.perfis.values()),
            dict(pagina.perfis),
            len(itens),
            pagina.custo,
        )
        if usuarios and not itens and not pagina.ativos:
            raise ErroProvedor(pagina.ultimo_motivo or MotivoTroca.FALHA_TEMPORARIA, pagina.custo)
        return RespostaProvedor(itens=itens, custo_usd=pagina.custo)

    def _item_do_usuario(self, usuario: str, pagina: _Pagina) -> ItemColetado | None:
        """Cache primeiro; só o que não está nele chama um extrator. Uma extração por usuário."""
        with _trava_do_usuario(usuario):
            with _trava_do_cache:
                if usuario in _cache_de_perfis:
                    pagina.do_cache += 1
                    return _cache_de_perfis[usuario]
            item, definitivo = self._extrair(usuario, pagina)
            if definitivo:
                with _trava_do_cache:
                    _cache_de_perfis[usuario] = item
            return item

    def _extrair(self, usuario: str, pagina: _Pagina) -> tuple[ItemColetado | None, bool]:
        """Tenta os extratores ativos em ordem. O que falha sai da página, sem texto do erro.

        O segundo valor diz se o resultado é definitivo (vai para o cache): perfil extraído ou não
        encontrado. Sem extrator disponível, não é.
        """
        while pagina.ativos:
            extrator = pagina.ativos[0]
            try:
                registro, custo = extrator.perfil(usuario)
            except ErroProvedor as erro:
                pagina.custo += erro.custo_usd
                self._desligar(pagina, extrator, erro.motivo)
                continue
            except _ERROS_DE_EXTRATOR as erro:
                logger.warning(
                    "linkedin_brave: extrator %s indisponível (%s)",
                    extrator.nome,
                    type(erro).__name__,
                )
                self._desligar(pagina, extrator, MotivoTroca.FALHA_TEMPORARIA)
                continue
            pagina.custo += custo
            if registro is None:
                return None, True
            pagina.perfis[extrator.origem] += 1
            return self._item(registro, usuario, extrator.origem), True
        return None, False

    @staticmethod
    def _desligar(pagina: _Pagina, extrator: ExtratorPerfil, motivo: MotivoTroca) -> None:
        pagina.ativos.remove(extrator)
        pagina.ultimo_motivo = motivo
        logger.warning(
            "linkedin_brave: extrator %s fora desta página, motivo=%s", extrator.nome, motivo.value
        )

    def _item(self, registro: dict[str, Any], usuario: str, origem: str) -> ItemColetado | None:
        """Registro fora do formato fica de fora sem derrubar os outros, já cobrados."""
        try:
            return item_de_registro(
                registro,
                provedor=NOME,
                fonte=f"{NOME}:{origem}",
                coletado_em=self._relogio(),
                atributos={"usuario_linkedin": usuario},
            )
        except ValidationError:  # o erro do pydantic copia o dado recebido: não vai adiante
            return None
