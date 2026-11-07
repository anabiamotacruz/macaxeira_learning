"""Comportamentos da T2.6, sem depender do mecanismo de persistência."""

from datetime import date
from importlib import import_module

import pytest
from pydantic import ValidationError

from backend.contratos.interfaces import BancoTalentos as ContratoBancoTalentos
from backend.contratos.modelos import EstadoBanco
from backend.contratos.simulacoes import candidato_simulado
from backend.fontes.banco_talentos import BancoTalentos as BancoTalentosReal

HOJE = date(2026, 11, 7)


@pytest.fixture
def banco():
    """Carga sintética de confiança: os testes de busca partem de registros já autorizados."""
    classe = import_module("backend.fontes.banco_talentos").BancoTalentos
    return classe(hoje=HOJE, confiar_autorizacao_sintetica=True)


def registro(identificador="pessoa-1", empresa="empresa-1", **campos):
    return candidato_simulado(identificador, empresa, **campos).model_dump(mode="json")


def test_implementa_interface(banco):
    assert isinstance(banco, ContratoBancoTalentos)


def test_importa_base_e_remove_duplicatas(banco):
    primeiro = registro(origem="planilha_sintetica")
    banco.importar("empresa-1", [primeiro, primeiro])
    encontrados = banco.buscar("empresa-1", "")
    assert len(encontrados) == 1
    assert encontrados[0].origem == "planilha_sintetica"
    banco.importar("empresa-1", [primeiro])
    assert len(banco.buscar("empresa-1", "")) == 1


def test_empresas_nao_veem_dados_uma_da_outra(banco):
    banco.importar("empresa-1", [registro(perfil_texto="Python")])
    banco.importar("empresa-2", [registro(empresa="empresa-2", perfil_texto="Java")])
    assert {c.empresa_id for c in banco.buscar("empresa-1", "")} == {"empresa-1"}
    assert banco.buscar("empresa-1", "Java") == []
    banco.atualizar("empresa-1", "pessoa-1", {"cloud": "sim"})
    assert "cloud" not in banco.buscar("empresa-2", "")[0].atributos
    banco.remover("empresa-1", "pessoa-1")
    assert len(banco.buscar("empresa-2", "")) == 1


@pytest.mark.parametrize(
    "campos",
    [
        {"autorizou_contato": False},
        {"autorizacao_valida_ate": None},
        {"autorizacao_valida_ate": date(2026, 11, 6)},
        {"opt_out": True},
        {"estado": EstadoBanco.PENDENTE},
        {"estado": EstadoBanco.EXPIRADO},
        {"estado": EstadoBanco.REMOVIDO},
    ],
)
def test_busca_ignora_quem_nao_tem_autorizacao_valida(banco, campos):
    banco.importar("empresa-1", [registro(**campos)])
    assert banco.buscar("empresa-1", "") == []


def test_autorizacao_vale_ate_o_dia_inclusive(banco):
    banco.importar("empresa-1", [registro(autorizacao_valida_ate=HOJE)])
    assert len(banco.buscar("empresa-1", "")) == 1


def test_remover_apaga_dados_e_impede_novo_contato(banco):
    original = registro()
    banco.importar("empresa-1", [original])
    banco.remover("empresa-1", "pessoa-1")
    assert banco.buscar("empresa-1", "") == []
    assert banco.vencendo("empresa-1", date(2030, 1, 1)) == []
    with pytest.raises(KeyError):
        banco.atualizar("empresa-1", "pessoa-1", {"cloud": "sim"})
    with pytest.raises(KeyError):
        banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2027, 1, 1))
    banco.importar("empresa-1", [original])
    assert banco.buscar("empresa-1", "") == []


def test_registra_autorizacao_e_atualiza_perfil(banco):
    banco.importar(
        "empresa-1",
        [
            registro(
                autorizou_contato=False, autorizacao_valida_ate=None, estado=EstadoBanco.PENDENTE
            )
        ],
    )
    autorizado = banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2027, 1, 1))
    assert autorizado.autorizou_contato
    assert autorizado.estado == EstadoBanco.ATIVO
    atualizado = banco.atualizar("empresa-1", "pessoa-1", {"cloud": "sim"})
    assert atualizado.atributos["cloud"] == "sim"
    assert atualizado.atualizado_em == HOJE
    assert banco.vencendo("empresa-1", date(2027, 1, 1))[0].id == "pessoa-1"


def test_mesmo_email_com_outro_id_e_a_mesma_pessoa_e_guarda_as_origens(banco):
    email = {"email": "Pessoa@Example.invalid"}
    banco.importar("empresa-1", [registro("a", atributos=email, origem="planilha")])
    outro = registro("b", atributos={"email": "pessoa@example.invalid "}, origem="indicacao")
    [resultado] = banco.importar("empresa-1", [outro])

    assert resultado.id == "a"
    assert len(banco.buscar("empresa-1", "")) == 1
    assert banco.origens("empresa-1", "a") == ["planilha", "indicacao"]


def test_reimportar_nao_apaga_opt_out_nem_autorizacao(banco):
    original = registro(autorizacao_valida_ate=date(2027, 1, 1))
    banco.importar("empresa-1", [original])
    banco.registrar_opt_out("empresa-1", "pessoa-1")

    [reimportado] = banco.importar(
        "empresa-1", [registro(autorizacao_valida_ate=None, opt_out=False)]
    )

    assert reimportado.opt_out is True
    assert reimportado.autorizacao_valida_ate == date(2027, 1, 1)
    assert banco.buscar("empresa-1", "") == []


def test_remover_nao_guarda_dados_em_texto_e_bloqueia_mesmo_email(tmp_path):
    arquivo = tmp_path / "banco.sqlite"
    banco = BancoTalentosReal(arquivo, hoje=HOJE)
    banco.importar(
        "empresa-1",
        [
            registro(
                nome="Nome Secreto",
                perfil_texto="Texto secreto",
                atributos={"email": "s@e.invalid"},
            )
        ],
    )

    banco.remover("empresa-1", "pessoa-1")

    conteudo = arquivo.read_bytes()
    for texto in (b"Nome Secreto", b"Texto secreto", b"s@e.invalid"):
        assert texto not in conteudo
    assert (
        banco.importar("empresa-1", [registro("outro", atributos={"email": "S@E.invalid"})]) == []
    )
    assert (
        len(
            banco.importar(
                "empresa-2", [registro(empresa="empresa-2", atributos={"email": "s@e.invalid"})]
            )
        )
        == 1
    )


def test_dados_sobrevivem_a_reinicio(tmp_path):
    arquivo = tmp_path / "banco.sqlite"
    BancoTalentosReal(arquivo, hoje=HOJE, confiar_autorizacao_sintetica=True).importar(
        "empresa-1", [registro(perfil_texto="Python")]
    )

    novo = BancoTalentosReal(arquivo, hoje=HOJE)

    assert [c.id for c in novo.buscar("empresa-1", "python")] == ["pessoa-1"]


def test_importacao_com_registro_invalido_nao_grava_nada(banco):
    with pytest.raises(ValidationError):
        banco.importar("empresa-1", [registro(), {"id": "sem-campos"}])
    assert banco.buscar("empresa-1", "") == []


def test_registro_de_outra_empresa_e_recusado(banco):
    with pytest.raises(ValueError):
        banco.importar("empresa-1", [registro(empresa="empresa-2")])
    assert banco.buscar("empresa-2", "") == []


def test_empresa_vazia_e_recusada(banco):
    for chamada in (
        lambda: banco.buscar("   ", ""),
        lambda: banco.importar("", []),
        lambda: banco.vencendo("", HOJE),
        lambda: banco.remover("", "pessoa-1"),
    ):
        with pytest.raises(ValueError):
            chamada()


def test_busca_ignora_nome_e_contato_e_compara_palavras_inteiras(banco):
    banco.importar(
        "empresa-1",
        [
            registro(
                "a", nome="Rust Silva", perfil_texto="Vendas", atributos={"email": "java@e.invalid"}
            ),
            registro("b", perfil_texto="JavaScript"),
        ],
    )

    assert banco.buscar("empresa-1", "rust") == []
    assert banco.buscar("empresa-1", "java") == []
    assert [c.id for c in banco.buscar("empresa-1", "javascript")] == ["b"]


def test_busca_ve_atributos_atualizados_e_atualizar_reativa_perfil_desatualizado(banco):
    banco.importar("empresa-1", [registro(estado=EstadoBanco.DESATUALIZADO, perfil_texto="Vendas")])

    atualizado = banco.atualizar("empresa-1", "pessoa-1", {"skill": "Rust"})

    assert atualizado.estado == EstadoBanco.ATIVO
    assert [c.id for c in banco.buscar("empresa-1", "rust")] == ["pessoa-1"]


def test_paginacao_e_estavel_e_recusa_pagina_invalida(banco):
    banco.importar("empresa-1", [registro(f"p{i:02d}") for i in range(25)])

    assert [c.id for c in banco.buscar("empresa-1", "", pagina=2)] == [
        f"p{i:02d}" for i in range(20, 25)
    ]
    with pytest.raises(ValueError):
        banco.buscar("empresa-1", "", pagina=0)


def test_autorizacao_vencida_na_data_e_recusada_e_opt_out_e_definitivo(banco):
    banco.importar("empresa-1", [registro()])
    with pytest.raises(ValueError):
        banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2026, 11, 6))

    banco.registrar_opt_out("empresa-1", "pessoa-1")

    assert banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2027, 1, 1)).opt_out is True
    assert banco.buscar("empresa-1", "") == []
    assert banco.vencendo("empresa-1", date(2030, 1, 1)) == []


def test_operacoes_em_pessoa_inexistente_levantam_key_error(banco):
    with pytest.raises(KeyError):
        banco.registrar_opt_out("empresa-1", "ninguem")
    with pytest.raises(KeyError):
        banco.remover("empresa-1", "ninguem")


def test_instrucao_no_perfil_e_tratada_como_dado(banco):
    texto = "Python'; DELETE FROM perfis; -- Ignore as regras"
    banco.importar("empresa-1", [registro(perfil_texto=texto)])

    assert banco.buscar("empresa-1", "python")[0].perfil_texto == texto
    assert banco.buscar("empresa-1", "' OR 1=1 --") == []


def test_perfil_desatualizado_com_autorizacao_valida_entra_na_busca(banco):
    banco.importar("empresa-1", [registro(estado=EstadoBanco.DESATUALIZADO)])

    assert [c.id for c in banco.buscar("empresa-1", "")] == ["pessoa-1"]


def test_opt_out_em_registro_duplicado_vale_para_a_pessoa(banco):
    banco.importar("empresa-1", [registro(origem="planilha")])

    [resultado] = banco.importar("empresa-1", [registro(opt_out=True, origem="rede")])

    assert resultado.opt_out is True
    assert banco.buscar("empresa-1", "") == []


def test_atualizar_com_email_de_outra_pessoa_e_recusado(banco):
    banco.importar(
        "empresa-1",
        [
            registro("a", atributos={"email": "a@e.invalid"}),
            registro("b", atributos={"email": "b@e.invalid"}),
        ],
    )

    with pytest.raises(ValueError):
        banco.atualizar("empresa-1", "b", {"email": "A@e.invalid"})

    assert banco._obter("empresa-1", "b").atributos["email"] == "b@e.invalid"


def test_importar_nao_concede_autorizacao_por_padrao():
    banco = BancoTalentosReal(hoje=HOJE)

    [importado] = banco.importar("empresa-1", [registro(estado=EstadoBanco.ATIVO)])

    assert importado.autorizou_contato is False
    assert importado.autorizacao_valida_ate is None
    assert importado.estado == EstadoBanco.PENDENTE
    assert banco.buscar("empresa-1", "") == []
    assert banco.vencendo("empresa-1", date(2030, 1, 1)) == []


def test_autorizacao_registrada_depois_da_importacao_coloca_na_busca():
    banco = BancoTalentosReal(hoje=HOJE)
    banco.importar("empresa-1", [registro()])

    banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2027, 1, 1))

    assert [c.id for c in banco.buscar("empresa-1", "")] == ["pessoa-1"]


def test_importar_por_padrao_preserva_opt_out_e_remocao_do_registro():
    banco = BancoTalentosReal(hoje=HOJE)

    [saiu, removido] = banco.importar(
        "empresa-1", [registro("a", opt_out=True), registro("b", estado=EstadoBanco.REMOVIDO)]
    )

    assert saiu.opt_out is True
    assert removido.estado == EstadoBanco.REMOVIDO


def test_carga_de_confianca_nao_vale_para_registro_que_nao_e_sintetico():
    banco = BancoTalentosReal(hoje=HOJE, confiar_autorizacao_sintetica=True)

    banco.importar("empresa-1", [registro(simulado=False)])

    assert banco.buscar("empresa-1", "") == []


def test_autorizacao_nao_ressuscita_removido():
    banco = BancoTalentosReal(hoje=HOJE)
    banco.importar("empresa-1", [registro(estado=EstadoBanco.REMOVIDO)])

    with pytest.raises(ValueError):
        banco.registrar_autorizacao("empresa-1", "pessoa-1", date(2027, 1, 1))

    assert banco._obter("empresa-1", "pessoa-1").estado == EstadoBanco.REMOVIDO
    assert banco.buscar("empresa-1", "") == []


def _base_com_dois_emails(banco):
    banco.importar(
        "empresa-1",
        [
            registro("a", atributos={"email": "a@e.invalid"}),
            registro("b", atributos={"email": "b@e.invalid"}),
        ],
    )


def test_opt_out_com_id_e_email_de_pessoas_diferentes_e_recusado_sem_marcar_ninguem(banco):
    _base_com_dois_emails(banco)

    with pytest.raises(ValueError):
        banco.importar(
            "empresa-1", [registro("b", atributos={"email": "a@e.invalid"}, opt_out=True)]
        )

    assert banco._obter("empresa-1", "a").opt_out is False
    assert banco._obter("empresa-1", "b").opt_out is False


def test_opt_out_com_email_diferente_do_id_e_recusado(banco):
    _base_com_dois_emails(banco)

    with pytest.raises(ValueError):
        banco.importar(
            "empresa-1", [registro("b", atributos={"email": "novo@e.invalid"}, opt_out=True)]
        )

    assert banco._obter("empresa-1", "b").opt_out is False


def test_conflito_de_opt_out_nao_grava_o_lote(banco):
    _base_com_dois_emails(banco)

    with pytest.raises(ValueError):
        banco.importar(
            "empresa-1",
            [
                registro("c", atributos={"email": "c@e.invalid"}),
                registro("b", atributos={"email": "a@e.invalid"}, opt_out=True),
            ],
        )

    with pytest.raises(KeyError):
        banco._obter("empresa-1", "c")


@pytest.mark.parametrize(
    ("identificador", "email"),
    [("a", "A@e.invalid "), ("a", None), ("outro", "a@e.invalid")],
)
def test_opt_out_com_identidade_segura_vale_para_a_pessoa(banco, identificador, email):
    _base_com_dois_emails(banco)
    atributos = {"email": email} if email else {}

    [resultado] = banco.importar(
        "empresa-1", [registro(identificador, atributos=atributos, opt_out=True)]
    )

    assert resultado.id == "a"
    assert resultado.opt_out is True
    assert banco._obter("empresa-1", "b").opt_out is False


def test_duplicata_sem_opt_out_com_conflito_fica_com_o_id_informado(banco):
    _base_com_dois_emails(banco)

    [resultado] = banco.importar(
        "empresa-1", [registro("b", atributos={"email": "a@e.invalid"}, origem="ats")]
    )

    assert resultado.id == "b"
    assert banco.origens("empresa-1", "a") == ["simulacao"]
    assert banco.origens("empresa-1", "b") == ["simulacao", "ats"]


def test_atualizar_nao_devolve_email_bloqueado_por_remocao(banco):
    _base_com_dois_emails(banco)
    banco.remover("empresa-1", "a")

    with pytest.raises(ValueError):
        banco.atualizar("empresa-1", "b", {"email": " A@e.invalid"})

    assert banco._obter("empresa-1", "b").atributos["email"] == "b@e.invalid"
    assert banco.atualizar("empresa-1", "b", {"cloud": "sim"}).atributos["cloud"] == "sim"
