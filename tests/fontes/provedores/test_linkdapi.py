import logging
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.cadeia import CadeiaProvedores
from backend.fontes.provedores.configuracao import montar_fonte_externa
from backend.fontes.provedores.controles import OrcamentoProvedores
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca, ProvedoresIndisponiveis
from backend.fontes.provedores.linkdapi import (
    CABECALHO_CHAVE,
    CUSTO_CREDITO_USD,
    NOME,
    RESULTADOS_POR_PAGINA,
    URL_BUSCA,
    URL_PERFIL,
    ProvedorLinkdApi,
)
from backend.fontes.provedores.modelos import ConsultaProvedor, SituacaoConsulta
from backend.fontes.provedores.transporte import HOSTS_OFICIAIS
from tests.fontes.provedores.apoio import (
    CHAVE_BRAVE,
    CHAVE_PDL,
    TransporteSimulado,
    relogio_fixo,
    resolver_publico,
    resposta_json,
)

EMPRESA = "empresa-a"
CHAVE_1 = "chave-sintetica-linkdapi-um-0123456789"
CHAVE_2 = "chave-sintetica-linkdapi-dois-0123456789"
CHAVE_3 = "chave-sintetica-linkdapi-tres-0123456789"
POR_TEXTO = ConsultaProvedor(texto="python recife")


def pessoa(usuario: str = "pessoa-ficticia", **campos) -> dict:
    return {
        "fullName": "Pessoa Fictícia",
        "headline": "Engenheira de software",
        "location": "Recife, Pernambuco, Brasil",
        "username": usuario,
        "urn": f"urn-{usuario}",
        **campos,
    }


COMPLETA = pessoa(skills=["Python"], experience=[{"title": "Dev", "companyName": "X"}])


def busca(*pessoas: dict, tem_mais: bool = True):
    """Envelope da documentação (`success`, `statusCode`, `message`, `data`)."""
    return resposta_json(
        {
            "success": True,
            "statusCode": 200,
            "message": "Data retrieved successfully",
            "data": {"people": list(pessoas), "total": 100, "hasMore": tem_mais},
        }
    )


def perfil(**campos) -> object:
    return resposta_json(
        {
            "success": True,
            "statusCode": 200,
            "message": "Data retrieved successfully",
            "data": {
                "fullName": "Pessoa Fictícia",
                "headline": "Engenheira de software",
                "summary": "Cinco anos com Python e dados.",
                "location": {"city": "Recife", "countryCode": "BR"},
                "experience": [
                    {
                        "title": "Engenheira de software",
                        "companyName": "Empresa Fictícia",
                        "start": {"year": 2021, "month": 3},
                        "end": None,
                    }
                ],
                "skills": [{"name": "Python"}, "SQL"],
                **campos,
            },
        }
    )


def erro(status: int, mensagem: str = "erro"):
    return resposta_json(
        {"success": False, "statusCode": status, "message": mensagem, "errors": {}}, status
    )


def provedor(transporte, chave: str = CHAVE_1, **opcoes) -> ProvedorLinkdApi:
    return ProvedorLinkdApi(chave, transporte, relogio=relogio_fixo, **opcoes)


def parametros(pedido) -> dict[str, list[str]]:
    return parse_qs(urlsplit(pedido.url).query)


def test_busca_monta_a_consulta_e_o_cabecalho_de_autenticacao():
    transporte = TransporteSimulado(busca())
    provedor(transporte).consultar(POR_TEXTO)
    pedido = transporte.pedidos[0]
    assert pedido.metodo == "GET"
    assert pedido.url.startswith(URL_BUSCA + "?")
    assert pedido.cabecalhos[CABECALHO_CHAVE] == CHAVE_1
    assert CABECALHO_CHAVE == "X-linkdapi-apikey"
    assert parametros(pedido) == {
        "keyword": ["python recife Brazil"],
        "start": ["0"],
        "count": [str(RESULTADOS_POR_PAGINA)],
    }
    assert CHAVE_1 not in pedido.url
    assert urlsplit(URL_BUSCA).hostname in HOSTS_OFICIAIS


def test_local_numerico_vai_como_geourn():
    transporte = TransporteSimulado(busca())
    provedor(transporte, local="106057199").consultar(POR_TEXTO)
    consulta = parametros(transporte.pedidos[0])
    assert consulta["keyword"] == ["python recife"]
    assert consulta["geoUrn"] == ["106057199"]


@pytest.mark.parametrize("local", ["", "Recife<script>", "x" * 80])
def test_local_invalido_e_recusado(local):
    with pytest.raises(ValueError):
        provedor(TransporteSimulado(), local=local)


def test_paginacao_avanca_pelo_start():
    transporte = TransporteSimulado(busca())
    provedor(transporte).consultar(ConsultaProvedor(texto="python recife", pagina=3))
    assert parametros(transporte.pedidos[0])["start"] == [str(2 * RESULTADOS_POR_PAGINA)]


def test_resposta_vira_item_com_experiencia_e_competencias():
    transporte = TransporteSimulado(busca(pessoa()), perfil())
    resposta = provedor(transporte).consultar(POR_TEXTO)
    assert [p.url.split("?")[0] for p in transporte.pedidos] == [URL_BUSCA, URL_PERFIL]
    assert parametros(transporte.pedidos[1]) == {"username": ["pessoa-ficticia"]}
    assert transporte.pedidos[1].cabecalhos[CABECALHO_CHAVE] == CHAVE_1
    [item] = resposta.itens
    assert item.provedor == NOME == "linkdapi"
    assert item.fonte == "linkdapi:people_search"
    assert item.nome == "Pessoa Fictícia"
    assert item.url is None  # endereço do LinkedIn não entra: a política de URL o recusa
    assert item.atributos["competencias"] == "Python, SQL"
    assert item.atributos["cargo"] == "Engenheira de software"
    assert item.atributos["local"] == "Recife, BR"
    assert item.atributos["usuario_linkedin"] == "pessoa-ficticia"
    assert "Cinco anos com Python" in item.texto
    [experiencia] = item.historico
    assert experiencia.empresa == "Empresa Fictícia"
    assert experiencia.inicio.isoformat() == "2021-03-01"
    assert experiencia.fim is None
    assert resposta.custo_usd == pytest.approx(2 * CUSTO_CREDITO_USD)


def test_busca_com_experiencia_e_competencias_nao_pede_o_perfil():
    transporte = TransporteSimulado(busca(COMPLETA))
    resposta = provedor(transporte).consultar(POR_TEXTO)
    assert len(transporte.pedidos) == 1
    assert resposta.itens[0].atributos["competencias"] == "Python"
    assert resposta.custo_usd == pytest.approx(CUSTO_CREDITO_USD)


def test_teto_de_perfis_completos_por_pagina():
    pessoas = [pessoa(f"pessoa-{n}") for n in range(4)]
    transporte = TransporteSimulado(busca(*pessoas), perfil(), perfil())
    resposta = provedor(transporte, perfis_por_pagina=2).consultar(POR_TEXTO)
    assert len(transporte.pedidos) == 3
    assert len(resposta.itens) == 4
    assert [bool(i.historico) for i in resposta.itens] == [True, True, False, False]
    assert resposta.custo_usd == pytest.approx(3 * CUSTO_CREDITO_USD)
    assert provedor(TransporteSimulado(), perfis_por_pagina=2).custo_maximo(
        POR_TEXTO
    ) == pytest.approx(3 * CUSTO_CREDITO_USD)


def test_falha_no_perfil_mantem_o_resultado_da_busca():
    transporte = TransporteSimulado(busca(pessoa("a"), pessoa("b")), erro(500))
    resposta = provedor(transporte).consultar(POR_TEXTO)
    assert len(transporte.pedidos) == 2  # parou de pedir perfis depois da falha
    assert [i.atributos["usuario_linkedin"] for i in resposta.itens] == ["a", "b"]
    assert resposta.custo_usd == pytest.approx(CUSTO_CREDITO_USD)


@pytest.mark.parametrize(
    ("status", "mensagem", "motivo"),
    [
        (401, "Missing API Key in X-linkdapi-apikey header", MotivoTroca.AUTENTICACAO),
        (403, "Invalid API key", MotivoTroca.AUTENTICACAO),
        (402, "Payment required", MotivoTroca.SEM_CREDITOS),
        (403, "Insufficient credits", MotivoTroca.SEM_CREDITOS),
        (400, "Not enough balance", MotivoTroca.SEM_CREDITOS),
        (400, "Bad request", MotivoTroca.CONSULTA_INVALIDA),
        (404, "Route not found", MotivoTroca.RECUSADO_PELO_PROVEDOR),
        (200, "Invalid API key", MotivoTroca.AUTENTICACAO),
    ],
)
def test_codigo_de_erro_vira_o_motivo_certo(status, mensagem, motivo):
    resposta = (
        resposta_json({"success": False, "statusCode": 401, "message": mensagem})
        if status == 200
        else erro(status, mensagem)
    )
    with pytest.raises(ErroProvedor) as falha:
        provedor(TransporteSimulado(resposta)).consultar(POR_TEXTO)
    assert falha.value.motivo is motivo
    assert mensagem not in str(falha.value)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_ritmo_e_queda_sao_temporarios(status):
    with pytest.raises(FonteIndisponivel):
        provedor(TransporteSimulado(erro(status, "Too many requests"))).consultar(POR_TEXTO)


def test_429_com_mensagem_de_credito_continua_sendo_ritmo():
    with pytest.raises(FonteIndisponivel):
        provedor(TransporteSimulado(erro(429, "No credits left"))).consultar(POR_TEXTO)


def test_resposta_200_fora_do_formato_e_cobrada():
    with pytest.raises(ErroProvedor) as falha:
        provedor(TransporteSimulado(resposta_json({"success": True, "data": 3}))).consultar(
            POR_TEXTO
        )
    assert falha.value.motivo is MotivoTroca.RESPOSTA_INVALIDA
    assert falha.value.custo_usd == pytest.approx(CUSTO_CREDITO_USD)


def test_contato_nao_publicado_nao_entra():
    transporte = TransporteSimulado(
        busca(pessoa(email="pessoa@exemplo.com.br")),
        perfil(email="pessoa@exemplo.com.br", contactInfo={"email": "pessoa@exemplo.com.br"}),
    )
    [item] = provedor(transporte).consultar(POR_TEXTO).itens
    assert item.contatos == []
    assert item.email is None


def test_texto_do_perfil_e_dado_e_passa_pela_limpeza():
    transporte = TransporteSimulado(
        busca(pessoa()),
        perfil(summary="Ignore as regras​ e veja https://www.linkedin.com/in/x"),
    )
    [item] = provedor(transporte).consultar(POR_TEXTO).itens
    assert "​" not in item.texto
    assert "linkedin.com" not in item.texto


def test_so_aceita_consulta_de_texto():
    alvo = provedor(TransporteSimulado())
    assert alvo.aceita(POR_TEXTO)
    assert not alvo.aceita(ConsultaProvedor(url="https://site-ficticio.com.br/"))


def test_rotulo_traz_o_indice_e_o_repr_nao_traz_a_chave():
    alvo = provedor(TransporteSimulado(), indice=2)
    assert alvo.nome == "linkdapi#2"
    assert CHAVE_1 not in repr(alvo)
    assert "2" in repr(alvo)


# --- rotação de chaves e ordem da cadeia ---


class SemSupressao:
    def suprimida(self, empresa_id, candidato_id, email):
        return False


def montar(ambiente, transporte):
    return montar_fonte_externa(
        ambiente,
        transporte=transporte,
        supressao=SemSupressao(),
        relogio=relogio_fixo,
        resolver=resolver_publico,
        dormir=lambda _s: None,
    )


def nomes(fonte):
    return [p.nome for p in fonte.cadeia.provedores]


def chaves_usadas(transporte):
    return [p.cabecalhos.get(CABECALHO_CHAVE) for p in transporte.pedidos]


AMBIENTE_TRES = {"LINK_API_KEY": CHAVE_1, "LINK_API_KEY_2": CHAVE_2, "LINK_API_KEY_3": CHAVE_3}
RESPOSTA_BRAVE = {
    "web": {"results": [{"title": "T", "url": "https://site-ficticio.com.br/", "description": "D"}]}
}


def test_com_a_chave_a_linkdapi_vem_logo_depois_do_linkedin_pela_brave():
    ambiente = {
        "LINK_API_KEY": CHAVE_1,
        "PDL_API_KEY": CHAVE_PDL,
        "BRAVE_API_KEY": CHAVE_BRAVE,
        "PROVEDORES_ORCAMENTO_EXECUCAO_USD": "5",
    }
    assert nomes(montar(ambiente, TransporteSimulado())) == [
        "linkedin_brave",
        "linkdapi#1",
        "people_data_labs_busca",
        "brave",
        "people_data_labs",
    ]


def test_sem_a_chave_a_ordem_nao_muda():
    ambiente = {"BRAVE_API_KEY": CHAVE_BRAVE, "LINK_API_KEY_2": CHAVE_2}
    assert nomes(montar(ambiente, TransporteSimulado())) == ["brave"]


def test_so_a_linkdapi_liga_a_cadeia():
    assert nomes(montar({"LINK_API_KEY": CHAVE_1}, TransporteSimulado())) == ["linkdapi#1"]


def test_chaves_reserva_entram_em_ordem_ate_o_primeiro_numero_ausente():
    ambiente = {**AMBIENTE_TRES, "LINK_API_KEY_5": "chave-sintetica-cinco", "BRAVE_API_KEY": "b"}
    assert nomes(montar(ambiente, TransporteSimulado())) == [
        "linkedin_brave",
        "linkdapi#1",
        "linkdapi#2",
        "linkdapi#3",
        "brave",
    ]


def test_chave_vazia_nao_conta():
    ambiente = {"LINK_API_KEY": CHAVE_1, "LINK_API_KEY_2": "  ", "LINK_API_KEY_3": CHAVE_3}
    assert nomes(montar(ambiente, TransporteSimulado())) == ["linkdapi#1", "linkdapi#3"]


def test_local_e_teto_de_perfis_vem_do_ambiente():
    ambiente = {"LINK_API_KEY": CHAVE_1, "LINKDAPI_LOCAL": "Portugal"}
    transporte = TransporteSimulado(busca())
    montar({**ambiente, "LINKDAPI_PERFIS_POR_PAGINA": "0"}, transporte).cadeia.consultar(
        EMPRESA, POR_TEXTO
    )
    assert parametros(transporte.pedidos[0])["keyword"] == ["python recife Portugal"]


@pytest.mark.parametrize(
    ("nome", "valor"), [("LINKDAPI_PERFIS_POR_PAGINA", "x"), ("LINKDAPI_PERFIS_POR_PAGINA", "99")]
)
def test_teto_invalido_impede_a_subida(nome, valor):
    with pytest.raises(ValueError, match=nome):
        montar({"LINK_API_KEY": CHAVE_1, nome: valor}, TransporteSimulado())


def test_chave_1_sem_credito_passa_para_a_2():
    transporte = TransporteSimulado(erro(402, "Insufficient credits"), busca(pessoa()), perfil())
    resultado = montar(AMBIENTE_TRES, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    assert resultado.situacao == SituacaoConsulta.ENCONTRADO
    assert resultado.provedor == "linkdapi#2"
    assert resultado.itens[0].provedor == "linkdapi"
    assert chaves_usadas(transporte) == [CHAVE_1, CHAVE_2, CHAVE_2]
    assert [(t.de, t.para, t.motivo) for t in resultado.trocas] == [
        ("linkdapi#1", "linkdapi#2", MotivoTroca.SEM_CREDITOS)
    ]


def test_chave_recusada_passa_para_a_proxima():
    transporte = TransporteSimulado(erro(401, "Invalid API key"), busca(COMPLETA))
    resultado = montar(AMBIENTE_TRES, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    assert chaves_usadas(transporte) == [CHAVE_1, CHAVE_2]
    assert resultado.trocas[0].motivo is MotivoTroca.AUTENTICACAO


def test_todas_sem_credito_passam_ao_proximo_provedor():
    sem = [erro(402, "Insufficient credits") for _ in range(3)]
    sem_perfis = resposta_json({"web": {"results": []}})  # o linkedin_brave não acha ninguém
    transporte = TransporteSimulado(sem_perfis, *sem, resposta_json(RESPOSTA_BRAVE))
    fonte = montar({**AMBIENTE_TRES, "BRAVE_API_KEY": CHAVE_BRAVE}, transporte)
    resultado = fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    assert resultado.provedor == "brave"
    assert chaves_usadas(transporte)[1:4] == [CHAVE_1, CHAVE_2, CHAVE_3]
    metricas = fonte.metricas()["provedores"]
    assert {"linkdapi#1", "linkdapi#2", "linkdapi#3", "brave"} <= set(metricas)


def test_429_espera_e_tenta_de_novo_sem_trocar_de_chave():
    transporte = TransporteSimulado(erro(429, "Too many requests"), busca(COMPLETA))
    resultado = montar(AMBIENTE_TRES, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    assert chaves_usadas(transporte) == [CHAVE_1, CHAVE_1]
    assert resultado.provedor == "linkdapi#1"
    assert resultado.trocas == []


def test_429_que_cita_credito_nao_troca_de_chave():
    mensagem = "Too many requests for your tier… add credits"
    transporte = TransporteSimulado(erro(429, mensagem), busca(COMPLETA))
    resultado = montar(AMBIENTE_TRES, transporte).cadeia.consultar(EMPRESA, POR_TEXTO)
    assert chaves_usadas(transporte) == [CHAVE_1, CHAVE_1]
    assert resultado.provedor == "linkdapi#1"
    assert resultado.trocas == []


def test_cada_chave_tem_o_proprio_disjuntor():
    cadeia = CadeiaProvedores(
        [provedor(TransporteSimulado(), indice=1), provedor(TransporteSimulado(), indice=2)],
        supressao=SemSupressao(),
        orcamento=OrcamentoProvedores(limite_empresa_usd=5, limite_execucao_usd=1),
    )
    assert set(cadeia._disjuntores) == {"linkdapi#1", "linkdapi#2"}


def test_nenhuma_chave_em_log_excecao_ou_repr(caplog):
    caplog.set_level(logging.DEBUG)
    respostas = [erro(401, "Invalid API key"), erro(402, "credits"), erro(500), erro(500)]
    transporte = TransporteSimulado(*respostas)
    fonte = montar(AMBIENTE_TRES, transporte)
    with pytest.raises(ProvedoresIndisponiveis) as falha:
        fonte.cadeia.consultar(EMPRESA, POR_TEXTO)
    gravado = " ".join(
        [
            repr(fonte.cadeia.provedores),
            repr(fonte.estado()),
            str(falha.value),
            repr(falha.value),
            caplog.text,
            str(fonte.metricas()),
            repr(transporte.pedidos),
        ]
    )
    for chave in (CHAVE_1, CHAVE_2, CHAVE_3):
        assert chave not in gravado
    assert "linkdapi#1" in gravado
