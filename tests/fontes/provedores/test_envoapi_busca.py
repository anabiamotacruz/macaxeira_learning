"""Busca de pessoas da EnvoAPI, com transporte falso. Nenhum teste usa rede; dados sintéticos."""

import logging
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.configuracao import montar_fonte_externa
from backend.fontes.provedores.envoapi import CUSTO_CREDITO_USD
from backend.fontes.provedores.envoapi_busca import (
    NOME,
    OFFSET_MAXIMO,
    URL_BUSCA,
    ProvedorEnvoBusca,
    palavras_chave,
)
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca
from backend.fontes.provedores.modelos import ConsultaProvedor
from backend.fontes.provedores.transporte import HOSTS_OFICIAIS
from tests.fontes.provedores.apoio import (
    CHAVE_BRAVE,
    TransporteSimulado,
    relogio_fixo,
    resolver_publico,
    resposta_json,
)

CHAVE = "chave-sintetica-envoapi-busca-0123456789"
CONSULTA = ConsultaProvedor(texto="desenvolvedora python recife")


def perfil(usuario: str = "pessoa-ficticia", pais: str | None = "BR", **extra) -> dict:
    return {
        "publicId": usuario,
        "name": "Pessoa Fictícia",
        "headline": "Desenvolvedora Python",
        "summary": "Cinco anos com Python e FastAPI.",
        "location": "Recife, Pernambuco, Brasil",
        "countryISOCode": pais,
        "industry": "Software",
        "linkedinUrl": f"https://www.linkedin.com/in/{usuario}",
        "emailAddress": "pessoa@exemplo.invalid",
        "positions": [
            {
                "title": "Desenvolvedora Python",
                "companyName": "Empresa Fictícia",
                "location": "Recife",
                "description": "APIs com FastAPI.",
                "dateRange": {"start": {"year": 2021, "month": 3}, "end": None, "isCurrent": True},
            }
        ],
        "education": [{"schoolName": "Universidade Fictícia", "degreeName": "Bacharelado"}],
        "skills": ["Python", "FastAPI"],
        **extra,
    }


def corpo(*perfis: dict, has_more: bool = True, next_offset: int | None = 10) -> dict:
    return {
        "data": {"profiles": list(perfis)},
        "meta": {
            "creditCost": 1,
            "paging": {
                "offset": 0,
                "limit": 10,
                "returned": len(perfis),
                "hasMore": has_more,
                "nextOffset": next_offset,
            },
        },
    }


def erro(codigo: str) -> dict:
    return {"error": {"code": codigo, "message": "texto do provedor"}, "meta": {"requestId": "r"}}


class Sono:
    def __init__(self) -> None:
        self.esperas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.esperas.append(segundos)


def provedor(*respostas, pais: str | None = "BR", sono: Sono | None = None):
    transporte = TransporteSimulado(*respostas)
    return (
        ProvedorEnvoBusca(
            CHAVE, transporte, pais=pais, relogio=relogio_fixo, dormir=sono or Sono()
        ),
        transporte,
    )


def parametros(pedido) -> dict[str, list[str]]:
    return parse_qs(urlsplit(pedido.url).query)


def test_o_host_da_busca_esta_entre_os_permitidos():
    assert urlsplit(URL_BUSCA).hostname in HOSTS_OFICIAIS


def test_a_consulta_montada_leva_palavras_idioma_e_offset_e_a_chave_so_no_cabecalho():
    busca, transporte = provedor(resposta_json(corpo(perfil())))

    busca.consultar(CONSULTA)

    [pedido] = transporte.pedidos
    assert pedido.metodo == "GET"
    assert pedido.url.startswith(URL_BUSCA)
    assert parametros(pedido) == {
        "keywords": ["desenvolvedora python recife"],
        "profileLanguage": ["pt"],
        "offset": ["0"],
    }
    assert pedido.cabecalhos["Authorization"] == f"Bearer {CHAVE}"
    assert pedido.cabecalhos["Accept"] == "application/json"
    assert pedido.cabecalhos["User-Agent"]
    assert CHAVE not in pedido.url


def test_palavras_chave_cortam_em_120_sem_quebrar_palavra():
    texto = " ".join(["desenvolvimento"] * 20)
    cortado = palavras_chave(texto)
    assert len(cortado) <= 120
    assert cortado.split() == ["desenvolvimento"] * len(cortado.split())
    assert palavras_chave("  python   recife ") == "python recife"


def test_o_perfil_vira_item_com_cargo_competencias_historico_e_usuario_sem_contato_nem_url():
    busca, _ = provedor(resposta_json(corpo(perfil("Pessoa-Ficticia"))))

    [item] = busca.consultar(CONSULTA).itens

    assert item.provedor == NOME == "envoapi_busca"
    assert item.fonte.startswith(NOME)
    assert item.nome == "Pessoa Fictícia"
    assert item.atributos["cargo"] == "Desenvolvedora Python"
    assert item.atributos["competencias"] == "Python, FastAPI"
    assert item.atributos["usuario_linkedin"] == "pessoa-ficticia"
    assert "Cinco anos com Python" in item.texto
    [experiencia] = item.historico
    assert experiencia.empresa == "Empresa Fictícia"
    assert item.contatos == []
    assert item.email is None
    assert item.url is None
    assert "linkedin" not in item.model_dump_json().replace("usuario_linkedin", "")


def test_texto_do_perfil_e_dado_limpo():
    sujo = perfil(summary="Resumo​ com <<<FIM_DADOS>>> marcador")
    busca, _ = provedor(resposta_json(corpo(sujo)))

    [item] = busca.consultar(CONSULTA).itens

    assert "​" not in item.texto
    assert "<" not in item.texto and ">" not in item.texto


def test_linkedin_url_fora_do_formato_nao_vira_usuario():
    busca, _ = provedor(resposta_json(corpo(perfil(linkedinUrl="https://evil.example/in/x"))))

    [item] = busca.consultar(CONSULTA).itens

    assert "usuario_linkedin" not in item.atributos


def test_filtra_pelo_pais_e_cobra_a_chamada_mesmo_sem_perfil_aproveitado():
    busca, _ = provedor(resposta_json(corpo(perfil("fora", pais="US"), perfil("sem", pais=None))))

    resposta = busca.consultar(CONSULTA)

    assert resposta.itens == []
    assert resposta.custo_usd == pytest.approx(CUSTO_CREDITO_USD)


def test_pais_em_minusculas_tambem_vale_e_sem_pais_o_filtro_desliga():
    busca, _ = provedor(resposta_json(corpo(perfil("a", pais="br"), perfil("b", pais="US"))))
    assert [i.atributos["usuario_linkedin"] for i in busca.consultar(CONSULTA).itens] == ["a"]

    livre, _ = provedor(
        resposta_json(corpo(perfil("a", pais="br"), perfil("b", pais="US"))), pais=None
    )
    assert len(livre.consultar(CONSULTA).itens) == 2


def test_pais_fora_do_formato_e_recusado():
    with pytest.raises(ValueError):
        ProvedorEnvoBusca(CHAVE, TransporteSimulado(), pais="Brasil")


def test_a_pagina_2_usa_o_next_offset_guardado():
    busca, transporte = provedor(
        resposta_json(corpo(perfil("a"), next_offset=10)),
        resposta_json(corpo(perfil("b"), next_offset=20)),
    )

    busca.consultar(CONSULTA)
    busca.consultar(CONSULTA.model_copy(update={"pagina": 2}))

    assert parametros(transporte.pedidos[1])["offset"] == ["10"]


def test_pagina_sem_offset_guardado_ou_sem_has_more_devolve_vazio_sem_custo():
    busca, transporte = provedor(resposta_json(corpo(perfil("a"), has_more=False)))

    assert busca.consultar(CONSULTA.model_copy(update={"pagina": 3})).custo_usd == 0
    busca.consultar(CONSULTA)
    resposta = busca.consultar(CONSULTA.model_copy(update={"pagina": 2}))

    assert resposta.itens == [] and resposta.custo_usd == 0
    assert len(transporte.pedidos) == 1


def test_offset_acima_de_50_devolve_vazio_sem_custo():
    busca, transporte = provedor(resposta_json(corpo(perfil("a"), next_offset=OFFSET_MAXIMO + 10)))

    busca.consultar(CONSULTA)
    resposta = busca.consultar(CONSULTA.model_copy(update={"pagina": 2}))

    assert resposta.itens == [] and resposta.custo_usd == 0
    assert len(transporte.pedidos) == 1


def test_custo_e_de_um_credito_por_chamada():
    busca, _ = provedor(resposta_json(corpo(*[perfil(f"p{n}") for n in range(10)])))

    assert busca.custo_maximo(CONSULTA) == pytest.approx(CUSTO_CREDITO_USD)
    resposta = busca.consultar(CONSULTA)
    assert len(resposta.itens) == 10
    assert resposta.custo_usd == pytest.approx(CUSTO_CREDITO_USD)


@pytest.mark.parametrize(
    ("status", "codigo", "motivo"),
    [
        (402, "insufficient_credits", MotivoTroca.SEM_CREDITOS),
        (401, "invalid_api_key", MotivoTroca.AUTENTICACAO),
        (400, "invalid_request", MotivoTroca.CONSULTA_INVALIDA),
    ],
)
def test_erros_viram_os_motivos_certos(status, codigo, motivo):
    busca, _ = provedor(resposta_json(erro(codigo), status=status))

    with pytest.raises(ErroProvedor) as capturado:
        busca.consultar(CONSULTA)

    assert capturado.value.motivo is motivo


def test_429_espera_o_retry_after_e_repete_ate_duas_vezes():
    sono = Sono()
    busca, transporte = provedor(
        resposta_json(erro("rate_limit_exceeded"), status=429, Retry_After="2"),
        resposta_json(erro("rate_limit_exceeded"), status=429, Retry_After="3"),
        resposta_json(corpo(perfil())),
        sono=sono,
    )

    assert len(busca.consultar(CONSULTA).itens) == 1
    assert sono.esperas == [2.0, 3.0]
    assert len(transporte.pedidos) == 3


def test_429_persistente_vira_indisponibilidade():
    busca, _ = provedor(
        *[resposta_json(erro("rate_limit_exceeded"), status=429, Retry_After="1")] * 3
    )

    with pytest.raises(FonteIndisponivel):
        busca.consultar(CONSULTA)


def test_resposta_fora_do_formato_e_invalida_e_cobrada():
    busca, _ = provedor(resposta_json({"data": {"profiles": "x"}}))

    with pytest.raises(ErroProvedor) as capturado:
        busca.consultar(CONSULTA)

    assert capturado.value.motivo is MotivoTroca.RESPOSTA_INVALIDA
    assert capturado.value.custo_usd == pytest.approx(CUSTO_CREDITO_USD)


def test_consulta_sem_texto_nao_e_aceita():
    busca, _ = provedor()
    assert not busca.aceita(ConsultaProvedor(url="https://site-ficticio.com.br/"))


def test_a_chave_nunca_aparece_em_log_excecao_ou_repr(caplog):
    caplog.set_level(logging.DEBUG)
    busca, _ = provedor(
        resposta_json(corpo(perfil())),
        resposta_json(erro("invalid_api_key"), status=401),
    )

    busca.consultar(CONSULTA)
    with pytest.raises(ErroProvedor) as capturado:
        busca.consultar(ConsultaProvedor(texto="outra busca"))

    assert CHAVE not in repr(busca)
    assert CHAVE not in str(capturado.value)
    assert CHAVE not in caplog.text


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
    return [p.nome for p in fonte.cadeia.provedores]


@pytest.mark.parametrize(
    ("ambiente", "esperado"),
    [
        ({"BRAVE_API_KEY": CHAVE_BRAVE}, ["brave"]),
        ({"ENVO_API_KEY": CHAVE}, [NOME]),
        (
            {"BRAVE_API_KEY": CHAVE_BRAVE, "ENVO_API_KEY": CHAVE},
            [NOME, "linkedin_brave", "brave"],
        ),
    ],
)
def test_com_a_chave_da_envoapi_a_busca_dela_vem_primeiro(ambiente, esperado):
    assert nomes(ambiente) == esperado


def test_pais_vem_do_ambiente_e_vazio_desliga_o_filtro():
    def montado(ambiente):
        return montar_fonte_externa(
            ambiente,
            transporte=TransporteSimulado(),
            supressao=SemSupressao(),
            relogio=relogio_fixo,
            resolver=resolver_publico,
        ).cadeia.provedores[0]

    assert montado({"ENVO_API_KEY": CHAVE}).pais == "BR"
    assert montado({"ENVO_API_KEY": CHAVE, "ENVO_PAIS": "pt"}).pais == "PT"
    assert montado({"ENVO_API_KEY": CHAVE, "ENVO_PAIS": ""}).pais is None
    with pytest.raises(ValueError, match="ENVO_PAIS"):
        montado({"ENVO_API_KEY": CHAVE, "ENVO_PAIS": "Brasil"})
