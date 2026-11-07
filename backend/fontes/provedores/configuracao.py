"""Liga a cadeia pelo ambiente: cada provedor com chave entra, sem nenhum outro interruptor.

`MODO_DADOS=sinteticos` manda sobre as chaves: nenhum provedor nem transporte é criado.
"""

import logging
import math
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from backend.contratos.interfaces import BancoTalentos, FonteCandidatos
from backend.fontes.provedores.bright_data import ProvedorBrightData
from backend.fontes.provedores.cadeia import CadeiaProvedores, ModoDados, VerificadorSupressao
from backend.fontes.provedores.controles import OrcamentoProvedores
from backend.fontes.provedores.fonte import FonteProvedores, SituacaoFontes
from backend.fontes.provedores.modelos import ProvedorDados
from backend.fontes.provedores.people_data_labs import (
    MIN_LIKELIHOOD_PADRAO,
    ProvedorPeopleDataLabs,
)
from backend.fontes.provedores.transporte import Transporte, TransporteHttp
from backend.fontes.provedores.url_segura import Resolvedor, resolver_dns

__all__ = ["NOMES_DE_AMBIENTE", "SituacaoFontes", "montar_fonte_externa"]

logger = logging.getLogger(__name__)

MODO_DADOS = "MODO_DADOS"
BRIGHTDATA_API_TOKEN = "BRIGHTDATA_API_TOKEN"
BRIGHTDATA_ZONA_WEB = "BRIGHTDATA_ZONA_WEB"
BRIGHTDATA_ZONA_BUSCA = "BRIGHTDATA_ZONA_BUSCA"
PDL_API_KEY = "PDL_API_KEY"
PDL_MIN_LIKELIHOOD = "PDL_MIN_LIKELIHOOD"
ORCAMENTO_EMPRESA = "PROVEDORES_ORCAMENTO_EMPRESA_USD"
ORCAMENTO_EXECUCAO = "PROVEDORES_ORCAMENTO_EXECUCAO_USD"
NOMES_DE_AMBIENTE = (
    MODO_DADOS,
    BRIGHTDATA_API_TOKEN,
    BRIGHTDATA_ZONA_WEB,
    BRIGHTDATA_ZONA_BUSCA,
    PDL_API_KEY,
    PDL_MIN_LIKELIHOOD,
    ORCAMENTO_EMPRESA,
    ORCAMENTO_EXECUCAO,
)
ORCAMENTO_EMPRESA_PADRAO_USD = 5.0
ORCAMENTO_EXECUCAO_PADRAO_USD = 1.0


def _valor(ambiente: Mapping[str, str], nome: str) -> str | None:
    return (ambiente.get(nome) or "").strip() or None


def _modo(ambiente: Mapping[str, str]) -> ModoDados:
    """Erro de digitação não pode ligar provedor real no link público: impede a subida."""
    valor = (_valor(ambiente, MODO_DADOS) or ModoDados.REAIS.value).casefold()
    try:
        return ModoDados(valor)
    except ValueError:
        raise ValueError(f"{MODO_DADOS} inválido: use sinteticos ou deixe em branco") from None


def _limite(ambiente: Mapping[str, str], nome: str, padrao: float) -> float:
    texto = _valor(ambiente, nome)
    if texto is None:
        return padrao
    try:
        valor = float(texto)
    except ValueError:
        raise ValueError(f"{nome} inválido: use um número") from None
    if not math.isfinite(valor) or valor < 0:
        raise ValueError(f"{nome} inválido: use um número finito e não negativo")
    return valor


def _provedor_bright_data(
    ambiente: Mapping[str, str],
    transporte: Transporte,
    relogio: Callable[[], datetime],
    resolver: Resolvedor,
    avisos: list[str],
) -> ProvedorBrightData | None:
    token = _valor(ambiente, BRIGHTDATA_API_TOKEN)
    if token is None:
        return None
    zona_web = _valor(ambiente, BRIGHTDATA_ZONA_WEB)
    zona_busca = _valor(ambiente, BRIGHTDATA_ZONA_BUSCA)
    if zona_web is None:
        avisos.append(f"{BRIGHTDATA_ZONA_WEB} ausente: leitura de páginas indisponível")
    if zona_busca is None:
        avisos.append(f"{BRIGHTDATA_ZONA_BUSCA} ausente: busca indisponível")
    return ProvedorBrightData(
        token,
        transporte,
        zona_web=zona_web,
        zona_busca=zona_busca,
        relogio=relogio,
        resolver=resolver,
    )


def _provedor_pdl(
    ambiente: Mapping[str, str], transporte: Transporte, relogio: Callable[[], datetime]
) -> ProvedorPeopleDataLabs | None:
    chave = _valor(ambiente, PDL_API_KEY)
    if chave is None:
        return None
    try:
        minimo = int(_valor(ambiente, PDL_MIN_LIKELIHOOD) or MIN_LIKELIHOOD_PADRAO)
        return ProvedorPeopleDataLabs(chave, transporte, min_likelihood=minimo, relogio=relogio)
    except ValueError as erro:
        raise ValueError(f"{PDL_MIN_LIKELIHOOD} inválido: {erro}") from None


def montar_fonte_externa(
    ambiente: Mapping[str, str] | None = None,
    *,
    supressao: VerificadorSupressao,
    transporte: Transporte | None = None,
    relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
    resolver: Resolvedor = resolver_dns,
    banco: BancoTalentos | None = None,
    fonte_sintetica: FonteCandidatos | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> FonteProvedores:
    """Monta a fonte e registra o estado. A supressão é obrigatória: sem ela, não há cadeia."""
    ambiente = os.environ if ambiente is None else ambiente
    modo = _modo(ambiente)
    orcamento = OrcamentoProvedores(
        limite_empresa_usd=_limite(ambiente, ORCAMENTO_EMPRESA, ORCAMENTO_EMPRESA_PADRAO_USD),
        limite_execucao_usd=_limite(ambiente, ORCAMENTO_EXECUCAO, ORCAMENTO_EXECUCAO_PADRAO_USD),
    )
    avisos: list[str] = []
    provedores: list[ProvedorDados] = []
    if modo is ModoDados.REAIS and any(
        _valor(ambiente, nome) for nome in (BRIGHTDATA_API_TOKEN, PDL_API_KEY)
    ):
        saida = transporte or TransporteHttp()
        for provedor in (
            _provedor_bright_data(ambiente, saida, relogio, resolver, avisos),
            _provedor_pdl(ambiente, saida, relogio),
        ):
            if provedor is not None:
                provedores.append(provedor)
    fonte = FonteProvedores(
        CadeiaProvedores(
            provedores, supressao=supressao, orcamento=orcamento, modo=modo, dormir=dormir
        ),
        supressao=supressao,
        banco=banco,
        fonte_sintetica=fonte_sintetica,
        avisos=avisos,
    )
    _registrar_estado(fonte)
    return fonte


def _registrar_estado(fonte: FonteProvedores) -> None:
    estado = fonte.estado()
    if estado.situacao is SituacaoFontes.SEM_FONTES_EXTERNAS:
        logger.warning("%s: o agente segue só com o banco de talentos", estado.rotulo)
    else:
        logger.info("%s: provedores=%s", estado.rotulo, ",".join(estado.provedores) or "-")
    for aviso in estado.avisos:
        logger.warning("%s", aviso)
