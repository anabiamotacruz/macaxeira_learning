"""Liga a cadeia pelo ambiente: cada provedor com chave entra, nesta ordem.

1. Busca da People Data Labs (Person Search), a principal: devolve perfis com cargo, competências
   e experiência. Entra com `PDL_API_KEY`; `PDL_PAIS` e `PDL_TAMANHO_PAGINA` ajustam a consulta.
2. Brave, a busca na web, que assume quando o PDL falha ou não acha.
3. Bright Data, que lê páginas. A SERP dela usa alvo Google e só entra com `BRIGHTDATA_ZONA_BUSCA`
   e `BRIGHTDATA_BUSCA_HABILITADA=1`.
4. Enriquecimento da People Data Labs (Person Enrichment), só por identidade.

Sem `PDL_API_KEY`, a ordem fica Brave, Bright Data. Cada registro do PDL custa até US$ 0,28: com o
orçamento de execução padrão, uma página não cabe, a busca do PDL fica fora e o estado avisa.

`MODO_DADOS=sinteticos` manda sobre as chaves: nenhum provedor nem transporte é criado.
"""

import logging
import math
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from backend.contratos.interfaces import BancoTalentos, FonteCandidatos
from backend.fontes.provedores.brave import ProvedorBrave
from backend.fontes.provedores.bright_data import ProvedorBrightData
from backend.fontes.provedores.cadeia import CadeiaProvedores, ModoDados, VerificadorSupressao
from backend.fontes.provedores.controles import OrcamentoProvedores
from backend.fontes.provedores.fonte import FonteProvedores, SituacaoFontes
from backend.fontes.provedores.modelos import ProvedorDados
from backend.fontes.provedores.people_data_labs import (
    MIN_LIKELIHOOD_PADRAO,
    ProvedorPeopleDataLabs,
)
from backend.fontes.provedores.people_data_labs_busca import (
    PAIS_PADRAO,
    TAMANHO_PAGINA_PADRAO,
    ProvedorPeopleDataLabsBusca,
    validar_pais,
    validar_tamanho_pagina,
)
from backend.fontes.provedores.transporte import Transporte, TransporteHttp
from backend.fontes.provedores.url_segura import Resolvedor, resolver_dns

__all__ = ["NOMES_DE_AMBIENTE", "SituacaoFontes", "montar_fonte_externa"]

logger = logging.getLogger(__name__)

MODO_DADOS = "MODO_DADOS"
BRAVE_API_KEY = "BRAVE_API_KEY"
BRIGHTDATA_API_TOKEN = "BRIGHTDATA_API_TOKEN"
BRIGHTDATA_ZONA_WEB = "BRIGHTDATA_ZONA_WEB"
BRIGHTDATA_ZONA_BUSCA = "BRIGHTDATA_ZONA_BUSCA"
BRIGHTDATA_BUSCA_HABILITADA = "BRIGHTDATA_BUSCA_HABILITADA"
PDL_API_KEY = "PDL_API_KEY"
PDL_MIN_LIKELIHOOD = "PDL_MIN_LIKELIHOOD"
PDL_PAIS = "PDL_PAIS"
PDL_TAMANHO_PAGINA = "PDL_TAMANHO_PAGINA"
ORCAMENTO_EMPRESA = "PROVEDORES_ORCAMENTO_EMPRESA_USD"
ORCAMENTO_EXECUCAO = "PROVEDORES_ORCAMENTO_EXECUCAO_USD"
NOMES_DE_AMBIENTE = (
    MODO_DADOS,
    BRAVE_API_KEY,
    BRIGHTDATA_API_TOKEN,
    BRIGHTDATA_ZONA_WEB,
    BRIGHTDATA_ZONA_BUSCA,
    BRIGHTDATA_BUSCA_HABILITADA,
    PDL_API_KEY,
    PDL_MIN_LIKELIHOOD,
    PDL_PAIS,
    PDL_TAMANHO_PAGINA,
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


def _provedor_brave(
    ambiente: Mapping[str, str], transporte: Transporte, relogio: Callable[[], datetime]
) -> ProvedorBrave | None:
    chave = _valor(ambiente, BRAVE_API_KEY)
    return None if chave is None else ProvedorBrave(chave, transporte, relogio=relogio)


def _zona_da_serp(ambiente: Mapping[str, str], avisos: list[str]) -> str | None:
    """A SERP só liga com as duas variáveis. Configuração pela metade não fica em silêncio."""
    zona = _valor(ambiente, BRIGHTDATA_ZONA_BUSCA)
    habilitada = _valor(ambiente, BRIGHTDATA_BUSCA_HABILITADA) == "1"
    if zona is not None and habilitada:
        avisos.append("SERP da Bright Data ligada: usa alvo Google, fora da arquitetura")
        return zona
    if zona is not None:
        avisos.append(f"{BRIGHTDATA_BUSCA_HABILITADA} não é 1: SERP da Bright Data desligada")
    elif habilitada:
        avisos.append(f"{BRIGHTDATA_ZONA_BUSCA} ausente: SERP da Bright Data desligada")
    return None


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
    if zona_web is None:
        avisos.append(f"{BRIGHTDATA_ZONA_WEB} ausente: leitura de páginas indisponível")
    return ProvedorBrightData(
        token,
        transporte,
        zona_web=zona_web,
        zona_busca=_zona_da_serp(ambiente, avisos),
        relogio=relogio,
        resolver=resolver,
    )


def _provedor_pdl_busca(
    ambiente: Mapping[str, str],
    transporte: Transporte,
    relogio: Callable[[], datetime],
    limite_execucao_usd: float,
    avisos: list[str],
) -> ProvedorPeopleDataLabsBusca | None:
    """Se uma página não cabe no orçamento de execução, o provedor fica fora e o estado avisa.

    Dentro da cadeia, ele só acumularia trocas por orçamento: toda resposta seguinte sairia como
    cobertura parcial, e o resultado vazio deixaria de ir para o cache.
    """
    chave = _valor(ambiente, PDL_API_KEY)
    if chave is None:
        return None
    try:
        pais = validar_pais(_valor(ambiente, PDL_PAIS) or PAIS_PADRAO)
    except ValueError as erro:
        raise ValueError(f"{PDL_PAIS} inválido: {erro}") from None
    try:
        tamanho = validar_tamanho_pagina(
            int(_valor(ambiente, PDL_TAMANHO_PAGINA) or TAMANHO_PAGINA_PADRAO)
        )
    except ValueError as erro:
        raise ValueError(f"{PDL_TAMANHO_PAGINA} inválido: {erro}") from None
    provedor = ProvedorPeopleDataLabsBusca(
        chave, transporte, pais=pais, tamanho_pagina=tamanho, relogio=relogio
    )
    if provedor.custo_por_pagina > limite_execucao_usd:
        avisos.append(
            f"busca do PDL fora do orçamento: uma página custa até US$ "
            f"{provedor.custo_por_pagina:.2f}, acima de {ORCAMENTO_EXECUCAO}; fica fora da cadeia"
        )
        return None
    return provedor


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
    limite_execucao = _limite(ambiente, ORCAMENTO_EXECUCAO, ORCAMENTO_EXECUCAO_PADRAO_USD)
    orcamento = OrcamentoProvedores(
        limite_empresa_usd=_limite(ambiente, ORCAMENTO_EMPRESA, ORCAMENTO_EMPRESA_PADRAO_USD),
        limite_execucao_usd=limite_execucao,
    )
    avisos: list[str] = []
    provedores: list[ProvedorDados] = []
    if modo is ModoDados.REAIS and _valor(ambiente, BRAVE_API_KEY) is None:
        avisos.append(f"{BRAVE_API_KEY} ausente: busca na web indisponível")
    if modo is ModoDados.REAIS and any(
        _valor(ambiente, nome) for nome in (BRAVE_API_KEY, BRIGHTDATA_API_TOKEN, PDL_API_KEY)
    ):
        saida = transporte or TransporteHttp()
        for provedor in (
            _provedor_pdl_busca(ambiente, saida, relogio, limite_execucao, avisos),
            _provedor_brave(ambiente, saida, relogio),
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
