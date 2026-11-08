"""A Brave acha os links do LinkedIn, e a EnvoAPI (ou a LinkdAPI, na falha) extrai o perfil.

Tudo sem rede: o transporte é falso, e os perfis e chaves são sintéticos.
"""

import logging
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.fontes.provedores.brave import EXCLUSAO_NA_BUSCA, ProvedorBrave
from backend.fontes.provedores.bright_data import ProvedorBrightData
from backend.fontes.provedores.configuracao import montar_fonte_externa
from backend.fontes.provedores.envoapi import URL_DETALHES, ExtratorPerfilEnvo
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca, UrlRecusada
from backend.fontes.provedores.linkdapi import CABECALHO_CHAVE, URL_PERFIL, ProvedorLinkdApi
from backend.fontes.provedores.linkedin_por_brave import (
    NOME,
    SITE_PERFIS_LINKEDIN,
    ProvedorLinkedinPorBrave,
    usuario_de_url_perfil,
)
from backend.fontes.provedores.modelos import ConsultaProvedor
from tests.fontes.provedores.apoio import (
    CHAVE_BRAVE,
    TOKEN_BRIGHT,
    TransporteSimulado,
    relogio_fixo,
    resolver_publico,
    resposta_json,
)

CHAVE_ENVO = "chave-sintetica-envo-0123456789"
CHAVE_LINK_1 = "chave-sintetica-linkdapi-um-0123456789"
CHAVE_LINK_2 = "chave-sintetica-linkdapi-dois-0123456789"
CHAVES = (CHAVE_BRAVE, CHAVE_ENVO, CHAVE_LINK_1, CHAVE_LINK_2)
POR_TEXTO = ConsultaProvedor(texto="python recife")


def links(*urls: str):
    return resposta_json(
        {"web": {"results": [{"title": "T", "url": url, "description": "D"} for url in urls]}}
    )


def perfil_envo(nome: str = "Pessoa Fictícia"):
    """Formato de docs.envoapi.com/api/operations/getprofiledetailsbyurl/."""
    return resposta_json(
        {
            "data": {
                "publicId": "profile_ficticio",
                "username": "pessoa-ficticia",
                "fullName": nome,
                "headline": "Engenheira de software",
                "about": "Cinco anos com Python e dados.",
                "location": {"displayName": "Recife, Pernambuco, Brasil", "countryCode": "BR"},
                "experience": [
                    {
                        "title": "Engenheira de software",
                        "company": {"name": "Empresa Fictícia"},
                        "dateRange": {
                            "start": {"year": 2021, "month": 3, "day": None},
                            "end": None,
                            "isCurrent": True,
                        },
                    }
                ],
                "education": [{"school": {"name": "Universidade Fictícia"}, "degree": "BSc"}],
                "skills": ["Python", "SQL"],
            },
            "meta": {"creditCost": 1},
        }
    )


def perfil_linkdapi():
    return resposta_json(
        {
            "success": True,
            "statusCode": 200,
            "message": "ok",
            "data": {
                "fullName": "Pessoa Fictícia",
                "headline": "Engenheira de dados",
                "summary": "Pipelines em Python.",
                "experience": [{"title": "Engenheira de dados", "companyName": "Outra Fictícia"}],
                "skills": [{"name": "Python"}],
            },
        }
    )


def erro_envo(status: int, codigo: str):
    return resposta_json({"error": {"code": codigo, "message": "x", "retryable": False}}, status)


def sem_credito_linkdapi():
    return resposta_json(
        {"success": False, "statusCode": 403, "message": "You dont have enough credits"}, 403
    )


def montar_provedor(
    *respostas, envo: bool = True, chaves_linkdapi: tuple[str, ...] = (CHAVE_LINK_1,), perfis=10
):
    transporte = TransporteSimulado(*respostas)
    extratores = []
    if envo:
        extratores.append(ExtratorPerfilEnvo(CHAVE_ENVO, transporte))
    extratores.extend(
        ProvedorLinkdApi(chave, transporte, indice=indice, relogio=relogio_fixo)
        for indice, chave in enumerate(chaves_linkdapi, start=1)
    )
    provedor = ProvedorLinkedinPorBrave(
        ProvedorBrave(CHAVE_BRAVE, transporte, relogio=relogio_fixo),
        extratores,
        perfis_por_pagina=perfis,
        relogio=relogio_fixo,
    )
    return provedor, transporte


def hosts(transporte) -> list[str]:
    return [urlsplit(p.url).hostname for p in transporte.pedidos]


def test_a_consulta_a_brave_pede_perfis_do_linkedin_sem_a_exclusao():
    provedor, transporte = montar_provedor(links())
    provedor.consultar(POR_TEXTO)
    consulta = transporte.pedidos[0].corpo_json["q"]
    assert consulta.startswith(f"{SITE_PERFIS_LINKEDIN} ")
    assert "python recife" in consulta
    assert EXCLUSAO_NA_BUSCA not in consulta


def test_a_brave_normal_continua_excluindo_o_linkedin():
    transporte = TransporteSimulado(links("https://site-ficticio.com.br/"))
    ProvedorBrave(CHAVE_BRAVE, transporte, relogio=relogio_fixo).consultar(POR_TEXTO)
    consulta = transporte.pedidos[0].corpo_json["q"]
    assert consulta.endswith(EXCLUSAO_NA_BUSCA)
    assert SITE_PERFIS_LINKEDIN not in consulta


def test_texto_que_ja_pede_o_linkedin_continua_recusado():
    provedor, transporte = montar_provedor()
    with pytest.raises(UrlRecusada):
        provedor.consultar(ConsultaProvedor(texto="python site:linkedin.com"))
    assert transporte.pedidos == []


@pytest.mark.parametrize(
    ("url", "usuario"),
    [
        ("https://www.linkedin.com/in/ana-silva/", "ana-silva"),
        ("https://br.linkedin.com/in/Bruno.Souza", "bruno.souza"),
        ("https://linkedin.com/in/carla_lima?originalSubdomain=br", "carla_lima"),
        ("http://www.linkedin.com/in/ana-silva/", None),
        ("https://pt.linkedin.com/in/ana-silva/", None),
        ("https://www.linkedin.com/company/empresa-ficticia/", None),
        ("https://www.linkedin.com/in/ana-silva/pt", None),
        ("https://www.linkedin.com/pub/dir/ana/silva", None),
        ("https://www.linkedin.com.site-ficticio.com/in/ana-silva/", None),
        ("https://site-ficticio.com.br/in/ana-silva/", None),
        ("https://user:senha@www.linkedin.com/in/ana-silva/", None),
        ("https://www.linkedin.com:8443/in/ana-silva/", None),
        ("https://www.linkedin.com/in/.../", None),
        (None, None),
    ],
)
def test_so_urls_de_perfil_validas_viram_usuario(url, usuario):
    assert usuario_de_url_perfil(url) == usuario


def test_so_os_usuarios_validos_e_sem_repeticao_sao_extraidos():
    provedor, transporte = montar_provedor(
        links(
            "https://www.linkedin.com/in/ana-silva/",
            "https://www.linkedin.com/company/empresa-ficticia/",
            "https://br.linkedin.com/in/ana-silva",
            "https://site-ficticio.com.br/in/carla/",
            "https://br.linkedin.com/in/bruno-souza/",
        ),
        perfil_envo("Ana"),
        perfil_envo("Bruno"),
    )
    resposta = provedor.consultar(POR_TEXTO)
    pedidos_envo = [p for p in transporte.pedidos if p.url.startswith(URL_DETALHES)]
    alvos = [parse_qs(urlsplit(p.url).query)["url"][0] for p in pedidos_envo]
    assert alvos == [
        "https://www.linkedin.com/in/ana-silva/",
        "https://www.linkedin.com/in/bruno-souza/",
    ]
    assert [item.atributos["usuario_linkedin"] for item in resposta.itens] == [
        "ana-silva",
        "bruno-souza",
    ]


def test_nenhum_pedido_vai_direto_ao_linkedin():
    provedor, transporte = montar_provedor(
        links("https://www.linkedin.com/in/ana-silva/"),
        erro_envo(402, "insufficient_credits"),
        perfil_linkdapi(),
    )
    provedor.consultar(POR_TEXTO)
    assert hosts(transporte) == ["api.search.brave.com", "api.envoapi.com", "linkdapi.com"]


def test_a_envoapi_extrai_no_caso_normal_e_a_linkdapi_nao_e_chamada():
    provedor, transporte = montar_provedor(
        links("https://www.linkedin.com/in/ana-silva/"), perfil_envo()
    )
    resposta = provedor.consultar(POR_TEXTO)
    (item,) = resposta.itens
    assert item.provedor == NOME
    assert item.fonte == f"{NOME}:envoapi"
    assert hosts(transporte) == ["api.search.brave.com", "api.envoapi.com"]
    pedido = transporte.pedidos[1]
    assert pedido.cabecalhos["Authorization"] == f"Bearer {CHAVE_ENVO}"
    assert CHAVE_ENVO not in pedido.url
    assert resposta.custo_usd == pytest.approx(0.005 + 0.01)


@pytest.mark.parametrize(
    "falha",
    [
        erro_envo(402, "insufficient_credits"),
        erro_envo(401, "invalid_api_key"),
        resposta_json({}, 403),
        resposta_json({}, 503),
        ConnectionError("falha"),
    ],
)
def test_falha_da_envoapi_cai_na_linkdapi(falha):
    provedor, transporte = montar_provedor(
        links("https://www.linkedin.com/in/ana-silva/", "https://www.linkedin.com/in/bruno/"),
        falha,
        perfil_linkdapi(),
        perfil_linkdapi(),
    )
    resposta = provedor.consultar(POR_TEXTO)
    assert [item.fonte for item in resposta.itens] == [f"{NOME}:linkdapi"] * 2
    assert hosts(transporte) == [
        "api.search.brave.com",
        "api.envoapi.com",
        "linkdapi.com",
        "linkdapi.com",
    ]
    pedido = transporte.pedidos[2]
    assert pedido.url.startswith(URL_PERFIL)
    assert parse_qs(urlsplit(pedido.url).query) == {"username": ["ana-silva"]}
    assert resposta.custo_usd == pytest.approx(0.005 + 2 * 0.01)


def test_sem_envoapi_a_linkdapi_gira_as_chaves_quando_uma_fica_sem_credito():
    provedor, transporte = montar_provedor(
        links("https://www.linkedin.com/in/ana-silva/"),
        sem_credito_linkdapi(),
        perfil_linkdapi(),
        envo=False,
        chaves_linkdapi=(CHAVE_LINK_1, CHAVE_LINK_2),
    )
    (item,) = provedor.consultar(POR_TEXTO).itens
    assert item.fonte == f"{NOME}:linkdapi"
    chaves = [p.cabecalhos.get(CABECALHO_CHAVE) for p in transporte.pedidos[1:]]
    assert chaves == [CHAVE_LINK_1, CHAVE_LINK_2]


def test_perfil_nao_extraido_nao_vira_candidato():
    provedor, _ = montar_provedor(
        links("https://www.linkedin.com/in/ana-silva/", "https://www.linkedin.com/in/bruno/"),
        erro_envo(404, "resource_not_found"),
        perfil_envo("Bruno"),
    )
    resposta = provedor.consultar(POR_TEXTO)
    assert [item.atributos["usuario_linkedin"] for item in resposta.itens] == ["bruno"]
    assert resposta.custo_usd == pytest.approx(0.005 + 2 * 0.01)


def test_sem_nenhum_extrator_de_pe_nada_entra_so_com_o_trecho_da_busca():
    provedor, transporte = montar_provedor(
        links("https://www.linkedin.com/in/ana-silva/", "https://www.linkedin.com/in/bruno/"),
        erro_envo(402, "insufficient_credits"),
        sem_credito_linkdapi(),
    )
    with pytest.raises(ErroProvedor) as erro:
        provedor.consultar(POR_TEXTO)
    assert erro.value.motivo is MotivoTroca.SEM_CREDITOS
    assert erro.value.custo_usd == pytest.approx(0.005)
    assert len(transporte.pedidos) == 3


def test_o_item_tem_experiencia_competencias_resumo_e_usuario_sem_contato():
    provedor, _ = montar_provedor(links("https://www.linkedin.com/in/ana-silva/"), perfil_envo())
    (item,) = provedor.consultar(POR_TEXTO).itens
    assert item.nome == "Pessoa Fictícia"
    assert item.atributos["usuario_linkedin"] == "ana-silva"
    assert item.atributos["competencias"] == "Python, SQL"
    assert item.atributos["cargo"] == "Engenheira de software"
    assert item.atributos["local"] == "Recife, Pernambuco, Brasil"
    (experiencia,) = item.historico
    assert experiencia.empresa == "Empresa Fictícia"
    assert "Cinco anos com Python" in item.texto
    assert item.contatos == []
    assert item.url is None


def test_o_teto_de_perfis_por_pagina_e_respeitado():
    urls = [f"https://www.linkedin.com/in/pessoa-{n}/" for n in range(6)]
    provedor, transporte = montar_provedor(
        links(*urls), perfil_envo(), perfil_envo(), perfil_envo(), perfis=3
    )
    resposta = provedor.consultar(POR_TEXTO)
    assert len(resposta.itens) == 3
    assert len(transporte.pedidos) == 4
    assert provedor.custo_maximo(POR_TEXTO) == pytest.approx(0.005 + 3 * 0.01)


def test_pagina_alem_da_ultima_da_brave_nao_gasta_nada():
    provedor, transporte = montar_provedor()
    resposta = provedor.consultar(ConsultaProvedor(texto="python recife", pagina=11))
    assert resposta.itens == []
    assert transporte.pedidos == []


def test_nenhuma_chave_aparece_em_log_excecao_ou_repr(caplog):
    caplog.set_level(logging.DEBUG)
    provedor, _ = montar_provedor(
        links("https://www.linkedin.com/in/ana-silva/"),
        erro_envo(401, "invalid_api_key"),
        sem_credito_linkdapi(),
    )
    with pytest.raises(ErroProvedor) as erro:
        provedor.consultar(POR_TEXTO)
    visivel = " ".join(
        [caplog.text, str(erro.value), repr(erro.value), repr(provedor)]
        + [repr(e) for e in provedor.extratores]
    )
    for chave in CHAVES:
        assert chave not in visivel


def test_a_bright_data_continua_recusando_o_perfil_do_linkedin():
    transporte = TransporteSimulado()
    bright = ProvedorBrightData(
        TOKEN_BRIGHT,
        transporte,
        zona_web="zona",
        zona_busca=None,
        relogio=relogio_fixo,
        resolver=resolver_publico,
    )
    with pytest.raises(UrlRecusada):
        bright.consultar(ConsultaProvedor(url="https://br.linkedin.com/in/ana-silva/"))
    assert transporte.pedidos == []


class SemSupressao:
    def suprimida(self, empresa_id, candidato_id, email):
        return False


def nomes(ambiente):
    fonte = montar_fonte_externa(
        ambiente,
        transporte=TransporteSimulado(),
        supressao=SemSupressao(),
        relogio=relogio_fixo,
        resolver=resolver_publico,
    )
    return [p.nome for p in fonte.cadeia.provedores], fonte


@pytest.mark.parametrize(
    ("ambiente", "esperado"),
    [
        ({"BRAVE_API_KEY": CHAVE_BRAVE}, ["brave"]),
        (
            {"BRAVE_API_KEY": CHAVE_BRAVE, "ENVO_API_KEY": CHAVE_ENVO},
            ["envoapi_busca", NOME, "brave"],
        ),
        (
            {"BRAVE_API_KEY": CHAVE_BRAVE, "LINK_API_KEY": CHAVE_LINK_1},
            [NOME, "linkdapi#1", "brave"],
        ),
        (
            {"ENVO_API_KEY": CHAVE_ENVO, "LINK_API_KEY": CHAVE_LINK_1},
            ["envoapi_busca", "linkdapi#1"],
        ),
        ({"ENVO_API_KEY": CHAVE_ENVO}, ["envoapi_busca"]),
    ],
)
def test_ordem_da_cadeia_com_e_sem_as_chaves(ambiente, esperado):
    assert nomes(ambiente)[0] == esperado


def test_a_envoapi_vem_antes_das_chaves_da_linkdapi_no_extrator():
    _, fonte = nomes(
        {
            "BRAVE_API_KEY": CHAVE_BRAVE,
            "ENVO_API_KEY": CHAVE_ENVO,
            "LINK_API_KEY": CHAVE_LINK_1,
            "LINK_API_KEY_2": CHAVE_LINK_2,
        }
    )
    provedor = fonte.cadeia.provedores[1]
    assert [e.nome for e in provedor.extratores] == ["envoapi", "linkdapi#1", "linkdapi#2"]


def test_perfis_por_pagina_vem_do_ambiente():
    _, fonte = nomes(
        {
            "BRAVE_API_KEY": CHAVE_BRAVE,
            "ENVO_API_KEY": CHAVE_ENVO,
            "LINKEDIN_PERFIS_POR_PAGINA": "4",
        }
    )
    assert fonte.cadeia.provedores[1].custo_maximo(POR_TEXTO) == pytest.approx(0.005 + 0.04)


def test_teto_que_nao_cabe_no_orcamento_e_reduzido_e_o_estado_avisa():
    _, fonte = nomes(
        {
            "BRAVE_API_KEY": CHAVE_BRAVE,
            "ENVO_API_KEY": CHAVE_ENVO,
            "PROVEDORES_ORCAMENTO_EXECUCAO_USD": "0.05",
        }
    )
    provedor = fonte.cadeia.provedores[1]
    assert provedor.nome == NOME
    assert provedor.custo_maximo(POR_TEXTO) <= 0.05
    assert provedor.custo_maximo(POR_TEXTO) == pytest.approx(0.005 + 4 * 0.01)
    assert any("LINKEDIN_PERFIS_POR_PAGINA" in aviso for aviso in fonte.estado().avisos)


def test_sem_orcamento_nem_para_um_perfil_o_provedor_fica_fora_e_avisa():
    nomes_cadeia, fonte = nomes(
        {
            "BRAVE_API_KEY": CHAVE_BRAVE,
            "ENVO_API_KEY": CHAVE_ENVO,
            "PROVEDORES_ORCAMENTO_EXECUCAO_USD": "0.01",
        }
    )
    assert nomes_cadeia == ["envoapi_busca", "brave"]
    assert any(NOME in aviso for aviso in fonte.estado().avisos)
