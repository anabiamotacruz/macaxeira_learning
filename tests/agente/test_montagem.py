import ast
from datetime import date
from pathlib import Path

import pytest

from backend.agente import fluxo as modulo_fluxo
from backend.agente.montagem import consultas_por_modelo, priorizador_do_funil
from backend.agente.regras import CORTES_QUE_DESCARTAM, decisao_de_corte
from backend.contratos.erros import LimiteGastoAtingido
from backend.contratos.modelos import Requisito, TipoDecisao
from backend.contratos.simulacoes import ClienteModeloSimulado
from backend.fontes.consultas import ETAPA_AMPLIAR, ETAPA_GERAR
from backend.fontes.funil import Corte, RegraCorte
from tests.agente.apoio import candidato_exemplo, vaga_exemplo

HOJE = date(2026, 11, 7)


def test_fluxo_nao_importa_implementacao_de_outra_frente():
    arvore = ast.parse(Path(modulo_fluxo.__file__).read_text(encoding="utf-8"))
    modulos = {no.module for no in ast.walk(arvore) if isinstance(no, ast.ImportFrom) and no.module}
    assert not {modulo for modulo in modulos if modulo.startswith("backend.fontes")}


def test_primeira_rodada_gera_e_as_seguintes_ampliam_sem_perder_as_anteriores():
    cliente = ClienteModeloSimulado(
        {
            ETAPA_GERAR: {"consultas": ["desenvolvedora python"]},
            ETAPA_AMPLIAR: {"consultas": ["programadora"]},
        }
    )
    consultas = consultas_por_modelo(cliente)
    vaga = vaga_exemplo()

    primeira = consultas(vaga, 0, [])
    segunda = consultas(vaga, 1, primeira)

    assert primeira == [vaga.titulo, "desenvolvedora python"]
    assert segunda == ["programadora", *primeira]
    assert [chamada["etapa"] for chamada in cliente.chamadas] == [ETAPA_GERAR, ETAPA_AMPLIAR]


def test_consulta_sensivel_do_modelo_nao_passa():
    cliente = ClienteModeloSimulado({ETAPA_GERAR: {"consultas": ["mulher python", "backend"]}})

    consultas = consultas_por_modelo(cliente)(vaga_exemplo(), 0, [])

    assert "mulher python" not in consultas
    assert "backend" in consultas


def test_modelo_com_falha_cai_nas_consultas_basicas():
    vaga = vaga_exemplo()

    assert consultas_por_modelo(ClienteModeloSimulado())(vaga, 0, []) == [vaga.titulo]


def test_limite_de_gasto_sobe_para_o_fluxo_pausar():
    class ClienteSemVerba(ClienteModeloSimulado):
        def completar(self, sistema, usuario, esquema, etapa):
            raise LimiteGastoAtingido("limite")

    with pytest.raises(LimiteGastoAtingido):
        consultas_por_modelo(ClienteSemVerba())(vaga_exemplo(), 0, [])


def test_priorizador_usa_a_regra_de_requisito_do_agente():
    vaga = vaga_exemplo(
        requisitos=[Requisito(id="r1", descricao="Python", campo="python", valor_esperado="sim")]
    )
    cortes: list[Corte] = []

    selecionados = priorizador_do_funil()(
        vaga,
        [
            candidato_exemplo("c1"),
            candidato_exemplo("c2", atributos={"python": "nao"}),
            candidato_exemplo("c3", atributos={}),
        ],
        HOJE,
        cortes.append,
    )

    assert {c.id for c in selecionados} == {"c1", "c3"}
    assert [(c.candidato_id, c.regra) for c in cortes] == [
        ("c2", RegraCorte.REQUISITO_NAO_ATENDIDO)
    ]


def test_priorizador_respeita_o_limite():
    cortes: list[Corte] = []

    selecionados = priorizador_do_funil(limite=1)(
        vaga_exemplo(), [candidato_exemplo("c1"), candidato_exemplo("c2")], HOJE, cortes.append
    )

    assert [c.id for c in selecionados] == ["c1"]
    assert [c.regra for c in cortes] == [RegraCorte.FORA_DO_LIMITE]


def test_toda_regra_do_funil_tem_tipo_de_decisao_conhecido():
    assert {r.value for r in RegraCorte} == {
        *CORTES_QUE_DESCARTAM,
        "fora_do_limite",
        "perfil_desatualizado",
    }


@pytest.mark.parametrize("regra", list(RegraCorte))
def test_corte_real_vira_decisao_valida(regra):
    from datetime import UTC, datetime

    from backend.agente.mandato import Politica, assinar
    from backend.agente.regras import validar_criterios

    vaga = vaga_exemplo()
    agora = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    mandato = assinar(
        vaga,
        "Pessoa Recrutadora",
        5.0,
        Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=2, max_ampliacoes=0),
        agora,
        validar_criterios=validar_criterios,
    )
    corte = Corte("empresa-a", "v1", "c1", "rede_simulada", "", regra, "motivo")

    decisao = decisao_de_corte(corte, mandato, agora, "rastro-1")

    vao_para_uma_pessoa = (RegraCorte.FORA_DO_LIMITE, RegraCorte.PERFIL_DESATUALIZADO)
    esperado = TipoDecisao.PEDIR_HUMANO if regra in vao_para_uma_pessoa else TipoDecisao.DESCARTAR
    assert decisao.tipo is esperado
    assert decisao.regra == f"funil:{regra.value}"
    assert all(valor.strip() for valor in decisao.entrada.values())
