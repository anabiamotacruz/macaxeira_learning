from datetime import UTC, datetime
from itertools import product

import pytest
from pydantic import ValidationError

from backend.agente.fluxo import (
    ESTADOS_ATIVOS,
    TRANSICOES,
    EstadoFluxo,
    TransicaoInvalida,
    _transitar,
)
from backend.agente.mandato import Mandato, Politica, assinar
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Vaga

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

E = EstadoFluxo

ATIVOS = {
    E.BUSCANDO,
    E.ANALISANDO,
    E.REVISANDO,
    E.DECIDINDO,
    E.META_EM_RISCO,
    E.CONVIDANDO,
    E.ENTREGANDO,
}

# Tabela da seção 2, repetida de propósito para o teste não copiar o código.
LISTADAS = {
    (E.RASCUNHO, E.AGUARDANDO_MANDATO),
    (E.AGUARDANDO_MANDATO, E.BUSCANDO),
    (E.AGUARDANDO_MANDATO, E.RASCUNHO),
    (E.BUSCANDO, E.ANALISANDO),
    (E.BUSCANDO, E.META_EM_RISCO),
    (E.ANALISANDO, E.REVISANDO),
    (E.REVISANDO, E.DECIDINDO),
    (E.DECIDINDO, E.BUSCANDO),
    (E.DECIDINDO, E.META_EM_RISCO),
    (E.DECIDINDO, E.CONVIDANDO),
    (E.DECIDINDO, E.ENTREGANDO),
    (E.META_EM_RISCO, E.CONVIDANDO),
    (E.META_EM_RISCO, E.ENTREGANDO),
    (E.META_EM_RISCO, E.CONCLUIDA),
    (E.CONVIDANDO, E.ENTREGANDO),
    (E.ENTREGANDO, E.CONCLUIDA),
    *((ativo, E.PAUSADA) for ativo in ATIVOS),
    *((E.PAUSADA, ativo) for ativo in ATIVOS),
}


def _vaga(**extra) -> Vaga:
    dados = {
        "id": "v1",
        "empresa_id": "empresa-a",
        "titulo": "Pessoa Desenvolvedora Python",
        "descricao": "Vaga sintética",
        "requisitos": [],
        "competencias": [],
        "meta_candidatos": 3,
        "prazo_dias": 10,
        "max_tentativas_contato": 2,
    }
    dados.update(extra)
    return Vaga(**dados)


def _mandato(vaga: Vaga) -> Mandato:
    return assinar(
        vaga,
        "Pessoa Recrutadora",
        5.0,
        Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=3, max_ampliacoes=1),
        AGORA,
        validar_criterios=lambda _vaga: [],
    )


def _ir(estado, destino, *, mandato="valido", vaga=None, **extra):
    vaga = vaga or _vaga()
    if mandato == "valido":
        mandato = _mandato(vaga)
    return _transitar(estado, destino, vaga=vaga, mandato=mandato, agora=AGORA, **extra)


NAO_LISTADAS = sorted(set(product(E, E)) - LISTADAS)


@pytest.mark.parametrize(("origem", "destino"), NAO_LISTADAS)
def test_transicao_nao_listada_e_recusada(origem, destino):
    with pytest.raises(TransicaoInvalida):
        _ir(origem, destino, estado_anterior=destino)


@pytest.mark.parametrize(("origem", "destino"), sorted(LISTADAS))
def test_transicao_listada_e_aceita(origem, destino):
    novo, _evento = _ir(origem, destino, estado_anterior=destino)

    assert novo is destino


def test_tabela_no_codigo_e_igual_a_da_secao_2():
    no_codigo = {
        (origem, destino) for origem, destinos in TRANSICOES.items() for destino in destinos
    }

    assert no_codigo == LISTADAS
    assert set(TRANSICOES) == set(E)
    assert ESTADOS_ATIVOS == ATIVOS


def test_tabela_nao_pode_ser_alterada_em_execucao():
    with pytest.raises(TypeError):
        TRANSICOES[E.RASCUNHO] = frozenset({E.CONCLUIDA})


def test_nao_existe_estado_de_aprovacao_de_lote():
    assert "AGUARDANDO_LOTE" not in E.__members__
    assert "aguardando_lote" not in {estado.value for estado in E}


def test_nenhum_estado_depende_de_um_destino_especifico():
    termos = ("NARA", "AGENDA", "ENTREVISTA", "RESULTADO")

    assert not [estado for estado in E.__members__ for termo in termos if termo in estado]


def test_concluida_e_o_unico_estado_final():
    assert [estado for estado, destinos in TRANSICOES.items() if not destinos] == [E.CONCLUIDA]


def test_todo_estado_consegue_chegar_a_concluida():
    alcancam = {E.CONCLUIDA}
    while True:
        novos = {o for o, destinos in TRANSICOES.items() if destinos & alcancam} - alcancam
        if not novos:
            break
        alcancam |= novos

    assert alcancam == set(E)


def test_nao_busca_sem_mandato():
    vaga = _vaga()

    with pytest.raises(TransicaoInvalida, match="mandato"):
        _ir(E.AGUARDANDO_MANDATO, E.BUSCANDO, mandato=None, vaga=vaga)


def test_nao_busca_a_partir_do_rascunho_mesmo_com_mandato():
    with pytest.raises(TransicaoInvalida):
        _ir(E.RASCUNHO, E.BUSCANDO)


def test_nao_busca_com_mandato_de_vaga_alterada():
    assinada = _vaga()
    editada = _vaga(titulo="Outro título")

    with pytest.raises(TransicaoInvalida, match="mandato"):
        _ir(E.AGUARDANDO_MANDATO, E.BUSCANDO, mandato=_mandato(assinada), vaga=editada)


def test_nao_busca_com_mandato_de_outra_empresa():
    outra = _vaga(empresa_id="empresa-b")

    with pytest.raises(TransicaoInvalida, match="mandato"):
        _ir(E.AGUARDANDO_MANDATO, E.BUSCANDO, mandato=_mandato(outra))


@pytest.mark.parametrize(
    ("origem", "destino"),
    sorted((o, d) for o, d in LISTADAS if d in ATIVOS and o is not E.PAUSADA),
)
def test_avancar_para_estado_ativo_exige_mandato_valido(origem, destino):
    assinada = _vaga()
    editada = _vaga(titulo="Outro título")

    with pytest.raises(TransicaoInvalida, match="mandato"):
        _ir(origem, destino, mandato=_mandato(assinada), vaga=editada)


@pytest.mark.parametrize("ativo", sorted(ATIVOS))
def test_pausar_nao_depende_de_mandato_valido(ativo):
    novo, _evento = _ir(ativo, E.PAUSADA, mandato=None)

    assert novo is E.PAUSADA


@pytest.mark.parametrize("origem", [E.META_EM_RISCO, E.ENTREGANDO])
def test_concluir_nao_depende_de_mandato_valido(origem):
    novo, _evento = _ir(origem, E.CONCLUIDA, mandato=None)

    assert novo is E.CONCLUIDA


@pytest.mark.parametrize("anterior", sorted(ATIVOS))
def test_retomar_volta_ao_estado_anterior(anterior):
    novo, _evento = _ir(E.PAUSADA, anterior, estado_anterior=anterior)

    assert novo is anterior


def test_retomar_para_outro_estado_e_recusado():
    with pytest.raises(TransicaoInvalida, match="anterior"):
        _ir(E.PAUSADA, E.ENTREGANDO, estado_anterior=E.BUSCANDO)


def test_retomar_sem_estado_anterior_salvo_e_recusado():
    with pytest.raises(TransicaoInvalida, match="anterior"):
        _ir(E.PAUSADA, E.BUSCANDO)


def test_retomar_com_mandato_invalido_e_recusado():
    assinada = _vaga()
    editada = _vaga(titulo="Outro título")

    with pytest.raises(TransicaoInvalida, match="mandato"):
        _ir(
            E.PAUSADA,
            E.BUSCANDO,
            mandato=_mandato(assinada),
            vaga=editada,
            estado_anterior=E.BUSCANDO,
        )


@pytest.mark.parametrize("estado", [E.RASCUNHO, E.AGUARDANDO_MANDATO, E.CONCLUIDA, E.PAUSADA])
def test_estado_sem_execucao_nao_pausa(estado):
    with pytest.raises(TransicaoInvalida):
        _ir(estado, E.PAUSADA)


def test_transicao_gera_evento_da_empresa_e_da_vaga():
    novo, evento = _ir(E.BUSCANDO, E.PAUSADA, motivo="PARADA_PELO_RH")

    assert novo is E.PAUSADA
    assert evento.empresa_id == "empresa-a"
    assert evento.vaga_id == "v1"
    assert evento.etapa == "pausada"
    assert evento.momento == AGORA
    assert evento.candidato_id is None
    assert evento.custo_usd == 0
    assert "buscando" in evento.mensagem
    assert "pausada" in evento.mensagem
    assert "PARADA_PELO_RH" in evento.mensagem


def test_transicao_recusada_nomeia_origem_e_destino():
    with pytest.raises(TransicaoInvalida, match="concluida.*buscando"):
        _ir(E.CONCLUIDA, E.BUSCANDO)


@pytest.mark.parametrize(
    ("origem", "destino"),
    [("xpto", E.BUSCANDO), (E.BUSCANDO, "xpto")],
)
def test_estado_desconhecido_e_recusado(origem, destino):
    with pytest.raises(TransicaoInvalida):
        _ir(origem, destino)


def test_evento_recusa_momento_sem_fuso():
    vaga = _vaga()

    with pytest.raises(ValidationError):
        _transitar(
            E.BUSCANDO,
            E.PAUSADA,
            vaga=vaga,
            mandato=_mandato(vaga),
            agora=datetime(2026, 11, 7, 12, 0),
        )


def test_erro_de_transicao_e_erro_previsivel_do_projeto():
    assert issubclass(TransicaoInvalida, ErroContrato)
