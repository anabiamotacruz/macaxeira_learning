"""A Brave é só descoberta transitória: o que ela devolve nunca é gravado.

Termos da Brave Search API, seção 3(b)(i): nada de guardar, fazer cache ou montar base com os
resultados, salvo armazenamento transitório. O título, o trecho e qualquer outro texto dela só
existem em memória, durante a execução, para escolher a página a ler. O que fica é o que veio da
leitura da própria página, com a URL dela e a data da leitura. Todos os dados são sintéticos.
"""

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from backend.agente.auditoria import contexto_rastro
from backend.agente.fluxo import FluxoVaga
from backend.agente.persistencia import Repositorio
from backend.contratos.erros import FonteIndisponivel
from backend.contratos.modelos import Politica
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteNaraSimulado,
    MensageiroSimulado,
)
from backend.fontes.provedores.brave import URL_BUSCA, ProvedorBrave
from backend.fontes.provedores.bright_data import URL_API
from backend.fontes.provedores.cadeia import CadeiaProvedores
from backend.fontes.provedores.configuracao import montar_fonte_externa
from backend.fontes.provedores.controles import (
    CACHE_DESCOBERTAS_MAXIMO,
    TTL_DESCOBERTAS_S,
    CacheConsultas,
    CacheDescobertas,
    OrcamentoProvedores,
)
from backend.fontes.provedores.fonte import FonteProvedores, candidato_de_item
from backend.fontes.provedores.modelos import (
    ConfiancaDado,
    ConsultaProvedor,
    ItemColetado,
    RespostaProvedor,
    ResultadoCadeia,
    SituacaoConsulta,
)
from backend.fontes.provedores.transporte import PedidoHttp, RespostaHttp
from backend.modelos.resiliencia import Resiliencia
from tests.agente.apoio import AnalisadorComEvidencias, Relogio, RevisorSemRessalva, vaga_exemplo
from tests.fontes.provedores.apoio import (
    CHAVE_BRAVE,
    MOMENTO,
    TOKEN_BRIGHT,
    TransporteSimulado,
    relogio_fixo,
    resolver_publico,
    resposta_json,
)

EMPRESA = "empresa-a"
URL_PAGINA = "https://portfolio-ficticio.com.br/pessoa"
TITULO_BRAVE = "TituloExclusivoBraveQ7x"
TRECHO_BRAVE = "TrechoExclusivoBraveZ4k"
EXTRA_BRAVE = "SnippetExtraExclusivoBraveK3"
PERFIL_BRAVE = "PerfilExclusivoBraveM8"
DATA_BRAVE = "2019-07-13T11:22:33"
TEXTOS_DA_BRAVE = (TITULO_BRAVE, TRECHO_BRAVE, EXTRA_BRAVE, PERFIL_BRAVE, DATA_BRAVE)
TEXTO_DA_PAGINA = "Cinco anos com Python. Liderou APIs em produção."
AMBIENTE = {
    "BRAVE_API_KEY": CHAVE_BRAVE,
    "BRIGHTDATA_API_TOKEN": TOKEN_BRIGHT,
    "BRIGHTDATA_ZONA_WEB": "zona_web",
}


def resultado_brave(url: str = URL_PAGINA) -> dict:
    """Um resultado no formato da referência, com todo texto exclusivo da Brave."""
    return {
        "type": "search_result",
        "title": f"<strong>{TITULO_BRAVE}</strong>",
        "url": url,
        "description": TRECHO_BRAVE,
        "page_age": DATA_BRAVE,
        "extra_snippets": [EXTRA_BRAVE],
        "profile": {"name": PERFIL_BRAVE, "long_name": PERFIL_BRAVE},
    }


def busca_brave(*resultados: dict) -> RespostaHttp:
    return resposta_json({"type": "search", "web": {"type": "search", "results": list(resultados)}})


def pagina_lida(texto: str = TEXTO_DA_PAGINA) -> RespostaHttp:
    """Envelope `format: json` do Web Unlocker com a página pedida."""
    return resposta_json(
        {
            "status_code": 200,
            "headers": {"content-type": "text/html"},
            "body": f"<html><head><title>Página lida</title></head><p>{texto}</p></html>",
        }
    )


class Roteador:
    """Transporte simulado: a busca responde a primeira vez, a página responde sempre igual."""

    def __init__(self, busca: RespostaHttp, pagina: RespostaHttp | Exception) -> None:
        self._buscas = [busca]
        self._pagina = pagina
        self.pedidos: list[PedidoHttp] = []

    def enviar(self, pedido: PedidoHttp) -> RespostaHttp:
        self.pedidos.append(pedido)
        if pedido.url == URL_BUSCA:
            return self._buscas.pop(0) if self._buscas else busca_brave()
        if pedido.url == URL_API:
            if isinstance(self._pagina, Exception):
                raise self._pagina
            return self._pagina
        raise AssertionError("pedido a host inesperado")


class SemSupressao:
    def suprimida(self, empresa_id, candidato_id, email):
        return False


def fonte_externa(transporte, ambiente=None) -> FonteProvedores:
    return montar_fonte_externa(
        AMBIENTE if ambiente is None else ambiente,
        transporte=transporte,
        supressao=SemSupressao(),
        relogio=relogio_fixo,
        resolver=resolver_publico,
        dormir=lambda _: None,
    )


def item_brave(url: str = URL_PAGINA) -> ItemColetado:
    [item] = (
        ProvedorBrave(
            CHAVE_BRAVE, TransporteSimulado(busca_brave(resultado_brave(url))), relogio=relogio_fixo
        )
        .consultar(ConsultaProvedor(texto="python"))
        .itens
    )
    return item


class AnalisadorQueGuarda(AnalisadorComEvidencias):
    """Guarda o candidato inteiro que chegou à análise."""

    def __init__(self) -> None:
        super().__init__()
        self.candidatos = []

    def analisar(self, vaga, candidato):
        self.candidatos.append(candidato)
        return super().analisar(vaga, candidato)


def rodar_fluxo(tmp_path: Path, fonte: FonteProvedores) -> tuple[FluxoVaga, AnalisadorQueGuarda]:
    analisador = AnalisadorQueGuarda()
    fluxo = FluxoVaga(
        vaga_exemplo(),
        repositorio=Repositorio(tmp_path / "agente.db"),
        banco=BancoTalentosSimulado(),
        fontes=[fonte],
        analisador=analisador,
        revisor=RevisorSemRessalva(),
        mensageiro=MensageiroSimulado(),
        destino=ClienteNaraSimulado(),
        relogio=Relogio(),
        medidor_gasto=lambda: 0.0,
        resiliencia=Resiliencia(dormir=lambda _: None),
    )
    fluxo.iniciar()
    fluxo.assinar_mandato(
        "Pessoa Recrutadora",
        5.0,
        Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=3, max_ampliacoes=0),
    )
    return fluxo, analisador


def tudo_do_sqlite(caminho: Path) -> str:
    """Todas as linhas de todas as tabelas, como texto."""
    linhas = []
    with sqlite3.connect(caminho) as conexao:
        tabelas = [
            nome
            for (nome,) in conexao.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        assert tabelas, "o fluxo precisa ter gravado no banco"
        for tabela in tabelas:
            linhas.extend(repr(linha) for linha in conexao.execute(f'SELECT * FROM "{tabela}"'))
    return "\n".join(linhas)


def tudo_dos_arquivos(pasta: Path) -> str:
    return "\n".join(
        arquivo.read_bytes().decode("utf-8", errors="replace")
        for arquivo in sorted(pasta.rglob("*"))
        if arquivo.is_file()
    )


def todo_o_rastro(rastro) -> str:
    return json.dumps([r.model_dump(mode="json") for r in rastro.registros], ensure_ascii=False)


# Provedor: cada resultado é só descoberta.


def test_resultado_da_brave_e_so_descoberta():
    assert item_brave().descoberta is True


def test_descoberta_da_brave_nunca_vira_candidato_sozinha():
    with pytest.raises(ValueError, match="descoberta"):
        candidato_de_item(EMPRESA, item_brave())


# Fonte: só a leitura da página fica.


def test_descoberta_lida_vira_candidato_com_a_fonte_e_a_data_da_pagina():
    transporte = Roteador(busca_brave(resultado_brave()), pagina_lida())
    fonte = fonte_externa(transporte)

    [candidato] = fonte.buscar(EMPRESA, "python")

    assert candidato.fonte == "bright_data:pagina"
    assert candidato.origem == URL_PAGINA
    assert candidato.atributos["url"] == URL_PAGINA
    assert candidato.atributos["provedor"] == "bright_data"
    assert candidato.atributos["coletado_em"] == MOMENTO.isoformat()
    assert candidato.atualizado_em == MOMENTO.date()
    assert candidato.perfil_texto == TEXTO_DA_PAGINA
    despejo = candidato.model_dump_json()
    assert all(texto not in despejo for texto in TEXTOS_DA_BRAVE)


@pytest.mark.parametrize(
    "falha",
    [
        ConnectionError("queda"),
        resposta_json({"status_code": 404, "headers": {}, "body": ""}),
        resposta_json({"status_code": 200, "headers": {"content-type": "image/png"}, "body": ""}),
    ],
    ids=["queda", "pagina_404", "nao_e_texto"],
)
def test_descoberta_sem_leitura_nao_deixa_nada_da_brave(falha, caplog):
    caplog.set_level(logging.DEBUG)
    fonte = fonte_externa(Roteador(busca_brave(resultado_brave()), falha))

    resultado = fonte.coletar(EMPRESA, ConsultaProvedor(texto="python"))

    assert resultado.itens == []
    assert resultado.situacao == SituacaoConsulta.NAO_ENCONTRADO
    assert resultado.descobertas_sem_leitura == 1
    assert fonte.metricas()["descobertas_sem_leitura"] == 1
    assert "descobertas sem leitura: 1" in caplog.text
    despejo = resultado.model_dump_json() + caplog.text + json.dumps(fonte.metricas())
    assert URL_PAGINA not in despejo
    assert all(texto not in despejo for texto in TEXTOS_DA_BRAVE)


def test_sem_quem_leia_a_pagina_a_descoberta_some():
    fonte = fonte_externa(
        TransporteSimulado(busca_brave(resultado_brave())), {"BRAVE_API_KEY": CHAVE_BRAVE}
    )
    assert fonte.buscar(EMPRESA, "python") == []
    assert fonte.metricas()["descobertas_sem_leitura"] == 1


def test_descoberta_alem_das_paginas_lidas_some_em_vez_de_virar_trecho():
    urls = [f"https://portfolio-ficticio.com.br/{i}" for i in range(4)]
    transporte = Roteador(busca_brave(*map(resultado_brave, urls)), pagina_lida())
    fonte = fonte_externa(transporte)

    candidatos = fonte.buscar(EMPRESA, "python")

    lidas = [p.corpo_json["url"] for p in transporte.pedidos if p.url == URL_API]
    assert lidas == urls[:3]
    assert [c.origem for c in candidatos] == urls[:3]
    assert fonte.metricas()["descobertas_sem_leitura"] == 1


def test_o_estado_avisa_quando_a_brave_nao_tem_quem_leia_as_paginas():
    fonte = fonte_externa(TransporteSimulado(), {"BRAVE_API_KEY": CHAVE_BRAVE})
    assert "só descobre" in " ".join(fonte.estado().avisos)
    com_leitura = fonte_externa(TransporteSimulado())
    assert "só descobre" not in " ".join(com_leitura.estado().avisos)


# Cache: só da execução, curto e com limite.


class Descoberta:
    """Provedor que só descobre, como a Brave, sem rede."""

    nome = "brave"
    so_descoberta = True

    def __init__(self) -> None:
        self.consultas = []

    def aceita(self, consulta):
        return consulta.texto is not None

    def custo_maximo(self, consulta):
        return 0.005

    def consultar(self, consulta):
        self.consultas.append(consulta)
        return RespostaProvedor(
            itens=[
                ItemColetado(
                    provedor="brave",
                    fonte="brave:busca",
                    coletado_em=MOMENTO,
                    url=URL_PAGINA,
                    confianca=ConfiancaDado.DECLARADO,
                    texto=TRECHO_BRAVE,
                    descoberta=True,
                )
            ],
            custo_usd=0.005,
        )


def cadeia_de_descoberta(provedor, **opcoes) -> CadeiaProvedores:
    return CadeiaProvedores(
        [provedor],
        supressao=SemSupressao(),
        orcamento=OrcamentoProvedores(limite_empresa_usd=10, limite_execucao_usd=10),
        dormir=lambda _: None,
        **opcoes,
    )


POR_TEXTO = ConsultaProvedor(texto="python")


def test_descoberta_nao_entra_no_cache_de_consultas():
    persistente = CacheConsultas()
    cadeia = cadeia_de_descoberta(Descoberta(), cache=persistente)
    with contexto_rastro(empresa_id=EMPRESA, execucao_id="exec-1"):
        cadeia.consultar(EMPRESA, POR_TEXTO)
    assert persistente.obter(EMPRESA, POR_TEXTO.chave()) is None


def test_na_mesma_execucao_a_descoberta_nao_e_paga_duas_vezes():
    provedor = Descoberta()
    cadeia = cadeia_de_descoberta(provedor)
    with contexto_rastro(empresa_id=EMPRESA, execucao_id="exec-1"):
        cadeia.consultar(EMPRESA, POR_TEXTO)
        segunda = cadeia.consultar(EMPRESA, POR_TEXTO)
    assert segunda.do_cache
    assert len(provedor.consultas) == 1


def test_a_descoberta_nao_passa_de_uma_execucao_para_outra():
    provedor = Descoberta()
    cadeia = cadeia_de_descoberta(provedor)
    for execucao in ("exec-1", "exec-2"):
        with contexto_rastro(empresa_id=EMPRESA, execucao_id=execucao):
            assert not cadeia.consultar(EMPRESA, POR_TEXTO).do_cache
    assert len(provedor.consultas) == 2


def test_fora_de_uma_execucao_a_descoberta_nao_e_guardada():
    provedor = Descoberta()
    cadeia = cadeia_de_descoberta(provedor)
    cadeia.consultar(EMPRESA, POR_TEXTO)
    assert not cadeia.consultar(EMPRESA, POR_TEXTO).do_cache
    assert len(provedor.consultas) == 2


def test_nao_encontrado_da_brave_tambem_fica_so_na_execucao():
    class Vazia(Descoberta):
        def consultar(self, consulta):
            self.consultas.append(consulta)
            return RespostaProvedor(custo_usd=0.005)

    persistente = CacheConsultas()
    cadeia = cadeia_de_descoberta(Vazia(), cache=persistente)
    with contexto_rastro(empresa_id=EMPRESA, execucao_id="exec-1"):
        cadeia.consultar(EMPRESA, POR_TEXTO)
    assert persistente.obter(EMPRESA, POR_TEXTO.chave()) is None


def guardado() -> ResultadoCadeia:
    return ResultadoCadeia(situacao=SituacaoConsulta.NAO_ENCONTRADO)


def test_cache_de_descobertas_tem_prazo_curto_e_limite():
    assert TTL_DESCOBERTAS_S <= 10 * 60
    assert CACHE_DESCOBERTAS_MAXIMO <= 64


def test_cache_de_descobertas_expira_no_prazo():
    agora = [0.0]
    cache = CacheDescobertas(ttl_s=60, relogio=lambda: agora[0])
    cache.guardar(EMPRESA, "exec-1", "k", guardado())
    agora[0] = 59
    assert cache.obter(EMPRESA, "exec-1", "k") is not None
    agora[0] = 61
    assert cache.obter(EMPRESA, "exec-1", "k") is None
    assert len(cache) == 0


def test_cache_de_descobertas_descarta_o_mais_antigo_no_limite():
    cache = CacheDescobertas(maximo=2, relogio=lambda: 0.0)
    for chave in ("a", "b", "c"):
        cache.guardar(EMPRESA, "exec-1", chave, guardado())
    assert len(cache) == 2
    assert cache.obter(EMPRESA, "exec-1", "a") is None


def test_cache_de_descobertas_separa_execucao_e_empresa():
    cache = CacheDescobertas(relogio=lambda: 0.0)
    cache.guardar(EMPRESA, "exec-1", "k", guardado())
    assert cache.obter(EMPRESA, "exec-2", "k") is None
    assert cache.obter("empresa-b", "exec-1", "k") is None


def test_vencidos_saem_mesmo_sem_ninguem_os_pedir():
    agora = [0.0]
    cache = CacheDescobertas(ttl_s=60, relogio=lambda: agora[0])
    cache.guardar(EMPRESA, "exec-1", "a", guardado())
    agora[0] = 61
    cache.guardar(EMPRESA, "exec-2", "b", guardado())
    assert len(cache) == 1


# Execução completa: nada da Brave em tabela, arquivo, rastro ou log.


def test_execucao_completa_nao_grava_texto_da_brave_e_guarda_a_pagina_lida(
    tmp_path, caplog, rastro
):
    caplog.set_level(logging.DEBUG)
    transporte = Roteador(busca_brave(resultado_brave()), pagina_lida())
    fonte = fonte_externa(transporte)

    fluxo, analisador = rodar_fluxo(tmp_path, fonte)

    assert any(p.url == URL_BUSCA for p in transporte.pedidos)
    assert [p.corpo_json["url"] for p in transporte.pedidos if p.url == URL_API] == [URL_PAGINA]
    [analisado] = analisador.candidatos
    assert analisado.perfil_texto == TEXTO_DA_PAGINA
    assert analisado.fonte == "bright_data:pagina"
    assert analisado.origem == URL_PAGINA
    assert analisado.atualizado_em == MOMENTO.date()
    banco = tudo_do_sqlite(tmp_path / "agente.db")
    assert TEXTO_DA_PAGINA in banco
    assert URL_PAGINA in banco
    gravado = "\n".join([banco, tudo_dos_arquivos(tmp_path), todo_o_rastro(rastro), caplog.text])
    for texto in TEXTOS_DA_BRAVE:
        assert texto not in gravado, texto
    assert all(texto not in analisado.model_dump_json() for texto in TEXTOS_DA_BRAVE)
    assert fluxo.eventos


@pytest.mark.parametrize(
    "falha",
    [ConnectionError("queda"), resposta_json({"status_code": 404, "headers": {}, "body": ""})],
    ids=["queda", "pagina_404"],
)
def test_execucao_completa_com_falha_na_leitura_nao_guarda_nada_da_descoberta(
    tmp_path, caplog, rastro, falha
):
    caplog.set_level(logging.DEBUG)
    transporte = Roteador(busca_brave(resultado_brave()), falha)
    fonte = fonte_externa(transporte)

    _, analisador = rodar_fluxo(tmp_path, fonte)

    assert any(p.url == URL_API for p in transporte.pedidos)
    assert analisador.candidatos == []
    assert fonte.metricas()["descobertas_sem_leitura"] >= 1
    assert "descobertas sem leitura" in caplog.text
    gravado = "\n".join(
        [
            tudo_do_sqlite(tmp_path / "agente.db"),
            tudo_dos_arquivos(tmp_path),
            todo_o_rastro(rastro),
            caplog.text,
        ]
    )
    assert URL_PAGINA not in gravado
    assert "portfolio-ficticio" not in gravado
    for texto in TEXTOS_DA_BRAVE:
        assert texto not in gravado, texto


def test_falha_temporaria_na_leitura_nao_derruba_a_busca():
    fonte = fonte_externa(Roteador(busca_brave(resultado_brave()), FonteIndisponivel("fora")))
    assert fonte.buscar(EMPRESA, "python") == []
