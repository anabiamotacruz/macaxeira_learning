import logging
from pathlib import Path

import pytest

from backend.contratos.simulacoes import FonteSimulada, candidato_simulado
from backend.fontes.provedores.bright_data import ProvedorBrightData
from backend.fontes.provedores.cadeia import ModoDados
from backend.fontes.provedores.configuracao import (
    NOMES_DE_AMBIENTE,
    SituacaoFontes,
    montar_fonte_externa,
)
from backend.fontes.provedores.erros import ProvedoresIndisponiveis
from backend.fontes.provedores.modelos import ConsultaProvedor, IdentidadeConsulta
from backend.fontes.provedores.people_data_labs import ProvedorPeopleDataLabs
from tests.fontes.provedores.apoio import (
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
    "BRIGHTDATA_ZONA_BUSCA": "zona_busca",
}
AMBIENTE_PDL = {"PDL_API_KEY": CHAVE_PDL}


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


@pytest.mark.parametrize("vazio", ["", "   "])
def test_chave_em_branco_conta_como_ausente(vazio):
    assert nomes(montar({"BRIGHTDATA_API_TOKEN": vazio, "PDL_API_KEY": vazio})) == []


def test_so_bright_data():
    fonte = montar(AMBIENTE_BRIGHT)
    assert nomes(fonte) == ["bright_data"]
    assert isinstance(fonte.cadeia.provedores[0], ProvedorBrightData)
    assert fonte.estado().situacao == SituacaoFontes.ATIVA


def test_so_pdl():
    fonte = montar(AMBIENTE_PDL)
    assert nomes(fonte) == ["people_data_labs"]
    assert isinstance(fonte.cadeia.provedores[0], ProvedorPeopleDataLabs)


def test_com_as_duas_chaves_bright_data_vem_primeiro():
    assert nomes(montar({**AMBIENTE_PDL, **AMBIENTE_BRIGHT})) == [
        "bright_data",
        "people_data_labs",
    ]


def test_token_sem_zona_entra_na_cadeia_e_avisa():
    fonte = montar({"BRIGHTDATA_API_TOKEN": TOKEN_BRIGHT})
    assert nomes(fonte) == ["bright_data"]
    avisos = " ".join(fonte.estado().avisos)
    assert "BRIGHTDATA_ZONA_WEB" in avisos
    assert "BRIGHTDATA_ZONA_BUSCA" in avisos
    assert TOKEN_BRIGHT not in avisos


def test_modo_sintetico_nao_cria_provedor_nem_transporte_mesmo_com_chaves(monkeypatch):
    def proibido(*_args, **_kwargs):
        raise AssertionError("não pode criar transporte no modo sintético")

    monkeypatch.setattr("backend.fontes.provedores.configuracao.TransporteHttp", proibido)
    transporte = TransporteSimulado()
    fonte = montar_fonte_externa(
        {**AMBIENTE_BRIGHT, **AMBIENTE_PDL, "MODO_DADOS": "sinteticos"},
        supressao=SemSupressao(),
        fonte_sintetica=FonteSimulada(
            [candidato_simulado("s-1", EMPRESA, perfil_texto="python")]
        ),
    )
    assert fonte.cadeia.provedores == ()
    assert fonte.cadeia.modo is ModoDados.SINTETICOS
    assert fonte.estado().situacao == SituacaoFontes.SOMENTE_SINTETICOS
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


def test_nomes_de_ambiente_estao_no_exemplo_sem_valores():
    linhas = RAIZ.joinpath(".env.example").read_text(encoding="utf-8").splitlines()
    declarados = {linha.split("=")[0]: linha.split("=", 1)[1] for linha in linhas if "=" in linha}
    for nome in NOMES_DE_AMBIENTE:
        assert declarados.get(nome) == "", nome
    assert {
        "BRIGHTDATA_API_TOKEN",
        "PDL_API_KEY",
        "MODO_DADOS",
    } <= set(NOMES_DE_AMBIENTE)
