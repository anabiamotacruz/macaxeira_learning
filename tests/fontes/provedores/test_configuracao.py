import logging
from pathlib import Path

import pytest

from backend.contratos.simulacoes import FonteSimulada, candidato_simulado
from backend.fontes.provedores.brave import URL_BUSCA, ProvedorBrave
from backend.fontes.provedores.bright_data import URL_API, ProvedorBrightData
from backend.fontes.provedores.cadeia import ModoDados
from backend.fontes.provedores.configuracao import (
    NOMES_DE_AMBIENTE,
    SituacaoFontes,
    montar_fonte_externa,
)
from backend.fontes.provedores.erros import MotivoTroca, ProvedoresIndisponiveis
from backend.fontes.provedores.modelos import (
    ConsultaProvedor,
    IdentidadeConsulta,
    SituacaoConsulta,
)
from backend.fontes.provedores.people_data_labs import (
    CUSTO_CREDITO_USD,
    URL_ENRIQUECIMENTO,
    ProvedorPeopleDataLabs,
)
from backend.fontes.provedores.people_data_labs_busca import (
    URL_BUSCA as URL_BUSCA_PDL,
)
from backend.fontes.provedores.people_data_labs_busca import (
    ProvedorPeopleDataLabsBusca,
)
from tests.fontes.provedores.apoio import (
    CHAVE_BRAVE,
    CHAVE_PDL,
    TOKEN_BRIGHT,
    TransporteSimulado,
    relogio_fixo,
    resolver_publico,
    resposta_json,
)

RAIZ = Path(__file__).resolve().parents[3]
EMPRESA = "empresa-a"
AMBIENTE_BRIGHT = {
    "BRIGHTDATA_API_TOKEN": TOKEN_BRIGHT,
    "BRIGHTDATA_ZONA_WEB": "zona_web",
}
SERP_LIGADA = {"BRIGHTDATA_ZONA_BUSCA": "zona_busca", "BRIGHTDATA_BUSCA_HABILITADA": "1"}
AMBIENTE_PDL = {"PDL_API_KEY": CHAVE_PDL}
ORCAMENTO_PARA_PDL = {"PROVEDORES_ORCAMENTO_EXECUCAO_USD": "5"}
AMBIENTE_BRAVE = {"BRAVE_API_KEY": CHAVE_BRAVE}
POR_TEXTO = ConsultaProvedor(texto="python recife")
RESPOSTA_BRAVE = {
    "web": {
        "results": [
            {
                "title": "Portfólio fictício",
                "url": "https://site-ficticio.com.br/",
                "description": "Cinco anos com Python",
            }
        ]
    }
}
RESPOSTA_PDL = {
    "status": 200,
    "data": [{"full_name": "pessoa ficticia", "skills": ["python"]}],
    "scroll_token": "1117$12.176522",
    "total": 1,
}
RESPOSTA_SERP = {
    "organic": [
        {
            "title": "Título",
            "link": "https://site-ficticio.com.br/serp",
            "description": "Trecho",
        }
    ]
}


class SemSupressao:
    def suprimida(self, empresa_id, candidato_id, email):
        return False


def montar(ambiente, transporte=None, **opcoes):
    return montar_fonte_externa(
        ambiente,
        transporte=transporte or TransporteSimulado(),
        supressao=SemSupressao(),
        relogio=relogio_fixo,
        resolver=resolver_publico,
        **opcoes,
    )


def nomes(fonte):
    return [p.nome for p in fonte.cadeia.provedores]


def test_sem_chave_nenhuma_o_estado_diz_sem_fontes_externas(caplog):
    caplog.set_level(logging.WARNING)
    fonte = montar({})
    estado = fonte.estado()
    assert estado.situacao == SituacaoFontes.SEM_FONTES_EXTERNAS
    assert estado.rotulo == "sem fontes externas"
    assert estado.provedores == ()
    assert "sem fontes externas" in caplog.text
    assert "BRAVE_API_KEY" in " ".join(estado.avisos)


@pytest.mark.parametrize("vazio", ["", "   "])
def test_chave_em_branco_conta_como_ausente(vazio):
    ambiente = {"BRIGHTDATA_API_TOKEN": vazio, "PDL_API_KEY": vazio, "BRAVE_API_KEY": vazio}
    assert nomes(montar(ambiente)) == []


def test_so_bright_data():
    fonte = montar(AMBIENTE_BRIGHT)
    assert nomes(fonte) == ["bright_data"]
    assert isinstance(fonte.cadeia.provedores[0], ProvedorBrightData)
    assert fonte.estado().situacao == SituacaoFontes.ATIVA


def test_so_pdl_liga_a_busca_e_o_enriquecimento_nessa_ordem():
    fonte = montar({**AMBIENTE_PDL, **ORCAMENTO_PARA_PDL})
    assert nomes(fonte) == ["people_data_labs_busca", "people_data_labs"]
    assert isinstance(fonte.cadeia.provedores[0], ProvedorPeopleDataLabsBusca)
    assert isinstance(fonte.cadeia.provedores[1], ProvedorPeopleDataLabs)


def test_so_brave():
    fonte = montar(AMBIENTE_BRAVE)
    assert nomes(fonte) == ["brave"]
    assert isinstance(fonte.cadeia.provedores[0], ProvedorBrave)
    assert fonte.estado().situacao == SituacaoFontes.ATIVA
    assert "BRAVE_API_KEY" not in " ".join(fonte.estado().avisos)


def test_com_as_tres_chaves_a_busca_do_pdl_vem_primeiro():
    ambiente = {**AMBIENTE_PDL, **AMBIENTE_BRIGHT, **AMBIENTE_BRAVE, **ORCAMENTO_PARA_PDL}
    assert nomes(montar(ambiente)) == [
        "people_data_labs_busca",
        "brave",
        "bright_data",
        "people_data_labs",
    ]


def test_sem_chave_do_pdl_a_ordem_nao_muda():
    assert nomes(montar({**AMBIENTE_BRIGHT, **AMBIENTE_BRAVE})) == ["brave", "bright_data"]


def test_busca_do_pdl_responde_e_a_brave_nao_e_chamada():
    transporte = TransporteSimulado(resposta_json(RESPOSTA_PDL))
    ambiente = {**AMBIENTE_PDL, **AMBIENTE_BRAVE, **AMBIENTE_BRIGHT, **ORCAMENTO_PARA_PDL}
    resultado = montar(ambiente, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    assert resultado.provedor == "people_data_labs_busca"
    assert [p.url for p in transporte.pedidos] == [URL_BUSCA_PDL]
    assert resultado.custo_usd == pytest.approx(CUSTO_CREDITO_USD)


def test_falha_da_busca_do_pdl_passa_para_a_brave():
    transporte = TransporteSimulado(resposta_json({}, 401), resposta_json(RESPOSTA_BRAVE))
    ambiente = {**AMBIENTE_PDL, **AMBIENTE_BRAVE, **ORCAMENTO_PARA_PDL}
    resultado = montar(ambiente, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    assert [p.url for p in transporte.pedidos] == [URL_BUSCA_PDL, URL_BUSCA]
    assert resultado.provedor == "brave"
    assert resultado.trocas[0].de == "people_data_labs_busca"
    assert resultado.trocas[0].motivo == MotivoTroca.AUTENTICACAO


def test_pais_e_tamanho_da_pagina_vem_do_ambiente():
    transporte = TransporteSimulado(resposta_json(RESPOSTA_PDL))
    ambiente = {
        **AMBIENTE_PDL,
        "PDL_PAIS": "Portugal",
        "PDL_TAMANHO_PAGINA": "3",
        **ORCAMENTO_PARA_PDL,
    }
    montar(ambiente, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    corpo = transporte.pedidos[0].corpo_json
    assert corpo["size"] == 3
    assert corpo["query"]["bool"]["filter"] == [{"term": {"location_country": "portugal"}}]


@pytest.mark.parametrize(
    ("nome", "valor"),
    [
        ("PDL_TAMANHO_PAGINA", "0"),
        ("PDL_TAMANHO_PAGINA", "101"),
        ("PDL_TAMANHO_PAGINA", "dez"),
        ("PDL_PAIS", "brazil; drop"),
    ],
)
def test_pais_ou_tamanho_invalido_impede_a_subida(nome, valor):
    with pytest.raises(ValueError) as erro:
        montar({**AMBIENTE_PDL, nome: valor})
    assert nome in str(erro.value)
    assert CHAVE_PDL not in str(erro.value)


def test_orcamento_padrao_deixa_a_busca_do_pdl_fora_da_cadeia_e_avisa():
    fonte = montar({**AMBIENTE_PDL, **AMBIENTE_BRAVE, **AMBIENTE_BRIGHT})
    assert nomes(fonte) == ["brave", "bright_data", "people_data_labs"]
    assert "PROVEDORES_ORCAMENTO_EXECUCAO_USD" in " ".join(fonte.estado().avisos)


def test_orcamento_padrao_a_brave_responde_sem_cobertura_parcial():
    transporte = TransporteSimulado(resposta_json(RESPOSTA_BRAVE))
    fonte = montar({**AMBIENTE_PDL, **AMBIENTE_BRAVE}, transporte)
    resultado = fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    assert [p.url for p in transporte.pedidos] == [URL_BUSCA]
    assert resultado.provedor == "brave"
    assert resultado.trocas == []
    assert not resultado.cobertura_parcial


def test_orcamento_que_cabe_uma_pagina_poe_o_pdl_primeiro_sem_aviso():
    fonte = montar({**AMBIENTE_PDL, **AMBIENTE_BRAVE, **ORCAMENTO_PARA_PDL})
    assert nomes(fonte) == ["people_data_labs_busca", "brave", "people_data_labs"]
    assert "PROVEDORES_ORCAMENTO_EXECUCAO_USD" not in " ".join(fonte.estado().avisos)


def test_orcamento_exato_de_uma_pagina_basta():
    limite = {"PROVEDORES_ORCAMENTO_EXECUCAO_USD": str(3 * CUSTO_CREDITO_USD)}
    fonte = montar({**AMBIENTE_PDL, "PDL_TAMANHO_PAGINA": "3", **limite})
    assert nomes(fonte)[0] == "people_data_labs_busca"


def test_sem_chave_da_brave_ela_fica_de_fora_e_aparece_no_estado():
    fonte = montar({**AMBIENTE_BRIGHT, **AMBIENTE_PDL})
    assert "brave" not in nomes(fonte)
    assert "BRAVE_API_KEY" in " ".join(fonte.estado().avisos)


def test_token_sem_zona_entra_na_cadeia_e_avisa():
    fonte = montar({"BRIGHTDATA_API_TOKEN": TOKEN_BRIGHT})
    assert nomes(fonte) == ["bright_data"]
    avisos = " ".join(fonte.estado().avisos)
    assert "BRIGHTDATA_ZONA_WEB" in avisos
    assert TOKEN_BRIGHT not in avisos


def test_brave_responde_a_busca_e_a_bright_data_nao_e_chamada():
    transporte = TransporteSimulado(
        resposta_json(RESPOSTA_BRAVE),
    )
    fonte = montar({**AMBIENTE_BRAVE, **AMBIENTE_BRIGHT}, transporte)
    resultado = fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    assert resultado.provedor == "brave"
    assert [p.url for p in transporte.pedidos] == [URL_BUSCA]


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"BRIGHTDATA_ZONA_BUSCA": "zona_busca"},
        {"BRIGHTDATA_BUSCA_HABILITADA": "1"},
        {"BRIGHTDATA_ZONA_BUSCA": "zona_busca", "BRIGHTDATA_BUSCA_HABILITADA": "0"},
        {"BRIGHTDATA_ZONA_BUSCA": "zona_busca", "BRIGHTDATA_BUSCA_HABILITADA": "true"},
    ],
)
def test_bright_data_nao_faz_busca_sem_a_zona_e_o_interruptor_juntos(extra):
    transporte = TransporteSimulado()
    fonte = montar({**AMBIENTE_BRIGHT, **extra}, transporte)
    resultado = fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    assert resultado.situacao == SituacaoConsulta.NAO_SUPORTADA
    assert transporte.pedidos == []


@pytest.mark.parametrize(
    ("extra", "aviso"),
    [
        ({"BRIGHTDATA_ZONA_BUSCA": "z"}, "BRIGHTDATA_BUSCA_HABILITADA"),
        ({"BRIGHTDATA_BUSCA_HABILITADA": "1"}, "BRIGHTDATA_ZONA_BUSCA"),
    ],
)
def test_interruptor_incompleto_nao_fica_em_silencio(extra, aviso):
    fonte = montar({**AMBIENTE_BRIGHT, **extra})
    assert aviso in " ".join(fonte.estado().avisos)


def test_serp_ligada_de_proposito_avisa_que_o_alvo_e_o_google():
    fonte = montar({**AMBIENTE_BRIGHT, **SERP_LIGADA})
    assert "Google" in " ".join(fonte.estado().avisos)


def test_serp_ligada_entra_depois_da_brave_quando_ela_falha():
    transporte = TransporteSimulado(
        resposta_json({}, 401),
        resposta_json(RESPOSTA_SERP),
    )
    fonte = montar({**AMBIENTE_BRAVE, **AMBIENTE_BRIGHT, **SERP_LIGADA}, transporte)
    resultado = fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    assert [p.url for p in transporte.pedidos] == [URL_BUSCA, URL_API]
    assert transporte.pedidos[1].corpo_json["url"].startswith("https://www.google.com/search?")
    assert resultado.provedor == "bright_data"
    assert resultado.cobertura_parcial
    assert resultado.trocas[0].de == "brave"
    assert resultado.trocas[0].motivo == MotivoTroca.AUTENTICACAO


def test_falha_da_busca_sem_serp_vira_cobertura_parcial_sem_usar_outros_provedores():
    transporte = TransporteSimulado(resposta_json({}, 401))
    fonte = montar({**AMBIENTE_BRAVE, **AMBIENTE_BRIGHT}, transporte)
    with pytest.raises(ProvedoresIndisponiveis) as erro:
        fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    assert erro.value.motivos == [("brave", MotivoTroca.AUTENTICACAO)]
    assert [p.url for p in transporte.pedidos] == [URL_BUSCA]


def test_falha_de_todas_as_buscas_nao_chama_o_enriquecimento():
    transporte = TransporteSimulado(resposta_json({}, 401), resposta_json({}, 401))
    ambiente = {**AMBIENTE_PDL, **AMBIENTE_BRAVE, **AMBIENTE_BRIGHT, **ORCAMENTO_PARA_PDL}
    with pytest.raises(ProvedoresIndisponiveis) as erro:
        montar(ambiente, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    assert erro.value.motivos == [
        ("people_data_labs_busca", MotivoTroca.AUTENTICACAO),
        ("brave", MotivoTroca.AUTENTICACAO),
    ]
    assert [p.url for p in transporte.pedidos] == [URL_BUSCA_PDL, URL_BUSCA]


def test_pessoa_e_enriquecida_so_pela_people_data_labs():
    transporte = TransporteSimulado(resposta_json({}, 404))
    fonte = montar({**AMBIENTE_BRAVE, **AMBIENTE_PDL}, transporte)
    fonte.enriquecer(EMPRESA, IdentidadeConsulta(email="p@ficticio.com.br"))
    assert [p.url for p in transporte.pedidos] == [URL_ENRIQUECIMENTO]


def test_leitura_de_pagina_continua_na_bright_data():
    corpo = {"status_code": 200, "headers": {"content-type": "text/html"}, "body": "<p>Oi</p>"}
    transporte = TransporteSimulado(resposta_json(corpo))
    fonte = montar({**AMBIENTE_BRAVE, **AMBIENTE_BRIGHT}, transporte)
    resultado = fonte.ler_pagina(EMPRESA, "https://site-ficticio.com.br/")
    assert resultado.provedor == "bright_data"
    assert [p.url for p in transporte.pedidos] == [URL_API]


def test_modo_sintetico_nao_cria_provedor_nem_transporte_mesmo_com_chaves(monkeypatch):
    def proibido(*_args, **_kwargs):
        raise AssertionError("não pode criar transporte no modo sintético")

    monkeypatch.setattr("backend.fontes.provedores.configuracao.TransporteHttp", proibido)
    transporte = TransporteSimulado()
    fonte = montar_fonte_externa(
        {**AMBIENTE_BRAVE, **AMBIENTE_BRIGHT, **AMBIENTE_PDL, "MODO_DADOS": "sinteticos"},
        supressao=SemSupressao(),
        fonte_sintetica=FonteSimulada([candidato_simulado("s-1", EMPRESA, perfil_texto="python")]),
    )
    assert fonte.cadeia.provedores == ()
    assert fonte.cadeia.modo is ModoDados.SINTETICOS
    assert fonte.estado().situacao == SituacaoFontes.SOMENTE_SINTETICOS
    assert fonte.estado().avisos == ()
    assert [c.id for c in fonte.buscar(EMPRESA, "python")] == ["s-1"]
    assert transporte.pedidos == []


@pytest.mark.parametrize("valor", ["SINTETICOS", " sinteticos ", "Sinteticos"])
def test_modo_sintetico_tolera_caixa_e_espacos(valor):
    fonte = montar({**AMBIENTE_PDL, "MODO_DADOS": valor})
    assert fonte.cadeia.provedores == ()


@pytest.mark.parametrize("valor", ["sintetico", "demo", "false"])
def test_modo_desconhecido_impede_a_subida_em_vez_de_chamar_provedor_real(valor):
    with pytest.raises(ValueError) as erro:
        montar({**AMBIENTE_PDL, "MODO_DADOS": valor})
    assert "MODO_DADOS" in str(erro.value)


@pytest.mark.parametrize("valor", ["", "  "])
def test_modo_em_branco_e_o_padrao(valor):
    assert nomes(montar({**AMBIENTE_PDL, "MODO_DADOS": valor})) == ["people_data_labs"]


def test_min_likelihood_vem_do_ambiente_e_e_validado():
    transporte = TransporteSimulado(resposta_json({}, 404))
    fonte = montar({**AMBIENTE_PDL, "PDL_MIN_LIKELIHOOD": "8"}, transporte)
    fonte.enriquecer(EMPRESA, IdentidadeConsulta(email="p@ficticio.com.br"))
    assert transporte.pedidos[0].corpo_json["min_likelihood"] == 8


@pytest.mark.parametrize("valor", ["3", "abc", "11", "6.5"])
def test_min_likelihood_invalido_impede_a_subida(valor):
    with pytest.raises(ValueError) as erro:
        montar({**AMBIENTE_PDL, "PDL_MIN_LIKELIHOOD": valor})
    assert "PDL_MIN_LIKELIHOOD" in str(erro.value)


@pytest.mark.parametrize(
    "nome", ["PROVEDORES_ORCAMENTO_EMPRESA_USD", "PROVEDORES_ORCAMENTO_EXECUCAO_USD"]
)
@pytest.mark.parametrize("valor", ["abc", "-1", "nan", "inf"])
def test_orcamento_invalido_impede_a_subida(nome, valor):
    with pytest.raises(ValueError) as erro:
        montar({**AMBIENTE_PDL, nome: valor})
    assert nome in str(erro.value)


def test_orcamento_do_ambiente_vale():
    transporte = TransporteSimulado()
    fonte = montar({**AMBIENTE_PDL, "PROVEDORES_ORCAMENTO_EXECUCAO_USD": "0"}, transporte)
    with pytest.raises(ProvedoresIndisponiveis, match="orcamento_esgotado"):
        fonte.enriquecer(EMPRESA, IdentidadeConsulta(email="p@ficticio.com.br"))
    assert transporte.pedidos == []


def test_chaves_nao_aparecem_em_repr_estado_nem_erro(caplog):
    caplog.set_level(logging.DEBUG)
    transporte = TransporteSimulado(
        resposta_json({"error": f"chave {CHAVE_PDL}"}, 401),
    )
    fonte = montar({**AMBIENTE_PDL, **AMBIENTE_BRIGHT}, transporte)
    consulta = ConsultaProvedor(identidade=IdentidadeConsulta(email="p@ficticio.com.br"))
    with pytest.raises(ProvedoresIndisponiveis) as erro:
        fonte.cadeia.consultar(EMPRESA, consulta)
    gravado = " ".join(
        [
            repr(fonte),
            repr(fonte.cadeia.provedores),
            repr(fonte.estado()),
            str(erro.value),
            repr(erro.value),
            caplog.text,
            str(fonte.metricas().get("provedores")),
        ]
    )
    assert TOKEN_BRIGHT not in gravado
    assert CHAVE_PDL not in gravado


def test_chave_da_brave_nao_aparece_em_repr_estado_nem_erro(caplog):
    caplog.set_level(logging.DEBUG)
    transporte = TransporteSimulado(resposta_json({"error": f"chave {CHAVE_BRAVE}"}, 401))
    fonte = montar(AMBIENTE_BRAVE, transporte)
    with pytest.raises(ProvedoresIndisponiveis) as erro:
        fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    gravado = " ".join(
        [
            repr(fonte.cadeia.provedores),
            repr(fonte.estado()),
            str(erro.value),
            repr(erro.value),
            caplog.text,
            str(fonte.metricas()),
        ]
    )
    assert CHAVE_BRAVE not in gravado


def test_nomes_de_ambiente_estao_no_exemplo_sem_valores():
    linhas = RAIZ.joinpath(".env.example").read_text(encoding="utf-8").splitlines()
    declarados = {linha.split("=")[0]: linha.split("=", 1)[1] for linha in linhas if "=" in linha}
    for nome in NOMES_DE_AMBIENTE:
        assert declarados.get(nome) == "", nome
    assert {
        "BRAVE_API_KEY",
        "BRIGHTDATA_API_TOKEN",
        "BRIGHTDATA_BUSCA_HABILITADA",
        "PDL_API_KEY",
        "PDL_PAIS",
        "PDL_TAMANHO_PAGINA",
        "MODO_DADOS",
    } <= set(NOMES_DE_AMBIENTE)
