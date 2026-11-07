from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.agente.mandato import (
    Mandato,
    MandatoInvalido,
    ModoEntrega,
    Politica,
    assinar,
    hash_da_vaga,
    mandato_valido,
)
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Competencia, Requisito, Vaga

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _sem_problemas(_vaga: Vaga) -> list[str]:
    return []


def _vaga(**extra) -> Vaga:
    dados = {
        "id": "v1",
        "empresa_id": "empresa-a",
        "titulo": "Pessoa Desenvolvedora Python",
        "descricao": "Vaga sintética",
        "requisitos": [
            Requisito(id="r1", descricao="Python", campo="linguagem", valor_esperado="python")
        ],
        "competencias": [Competencia(nome="backend", peso=1.0)],
        "meta_candidatos": 3,
        "prazo_dias": 10,
        "max_tentativas_contato": 2,
    }
    dados.update(extra)
    return Vaga(**dados)


def _politica(**extra) -> Politica:
    dados = {"limiar_verde": 0.7, "piso_nota": 0.3, "max_indicacoes": 3, "max_ampliacoes": 1}
    dados.update(extra)
    return Politica(**dados)


def _assinar(vaga: Vaga | None = None, **extra) -> Mandato:
    dados = {
        "vaga": vaga or _vaga(),
        "assinante": "Pessoa Recrutadora",
        "limite_gasto_usd": 5.0,
        "politica": _politica(),
        "agora": AGORA,
        "validar_criterios": _sem_problemas,
    }
    dados.update(extra)
    return assinar(**dados)


def test_mandato_exige_assinante_limite_e_hash_da_vaga():
    vaga = _vaga()

    mandato = _assinar(vaga)

    assert mandato.assinante == "Pessoa Recrutadora"
    assert mandato.limite_gasto_usd == 5.0
    assert mandato.hash_vaga == hash_da_vaga(vaga)
    assert mandato.empresa_id == "empresa-a"
    assert mandato.vaga_id == "v1"
    assert mandato.assinado_em == AGORA
    assert mandato.versao == 1
    assert mandato.id
    assert mandato_valido(mandato, vaga, AGORA)


@pytest.mark.parametrize("assinante", ["", "   "])
def test_recusa_assinante_vazio(assinante):
    with pytest.raises(MandatoInvalido, match="assinante"):
        _assinar(assinante=assinante)


@pytest.mark.parametrize("limite", [0, -1.0, float("nan"), float("inf"), True])
def test_recusa_limite_nao_positivo_ou_nao_numerico(limite):
    with pytest.raises(MandatoInvalido, match="limite_gasto_usd"):
        _assinar(limite_gasto_usd=limite)


def test_aceita_limite_inteiro():
    assert _assinar(limite_gasto_usd=5).limite_gasto_usd == 5.0


def test_recusa_vaga_com_critero_sensivel_usando_a_funcao_injetada():
    recebidas = []

    def validar(vaga: Vaga) -> list[str]:
        recebidas.append(vaga)
        return ["critério sensível: idade"]

    vaga = _vaga()
    with pytest.raises(MandatoInvalido, match="idade"):
        _assinar(vaga, validar_criterios=validar)
    assert recebidas == [vaga]


def test_verificacao_de_criterio_e_obrigatoria():
    with pytest.raises(TypeError):
        assinar(_vaga(), "Pessoa Recrutadora", 5.0, _politica(), AGORA)


def test_falha_na_verificacao_de_criterio_nao_gera_mandato():
    def validar(_vaga: Vaga) -> list[str]:
        raise RuntimeError("verificador fora do ar")

    with pytest.raises(RuntimeError):
        _assinar(validar_criterios=validar)


def test_recusa_momento_sem_fuso():
    with pytest.raises(MandatoInvalido, match="assinado_em"):
        _assinar(agora=datetime(2026, 11, 7, 12, 0))


@pytest.mark.parametrize(
    "alteracao",
    [
        {"titulo": "Outro título"},
        {"descricao": "Outra descrição"},
        {
            "requisitos": [
                Requisito(id="r1", descricao="Python", campo="linguagem", valor_esperado="java")
            ]
        },
        {"requisitos": []},
        {"competencias": [Competencia(nome="backend", peso=0.5)]},
        {"meta_candidatos": 4},
        {"prazo_dias": 11},
        {"max_tentativas_contato": 3},
    ],
    ids=lambda alteracao: next(iter(alteracao)),
)
def test_vaga_alterada_invalida_mandato(alteracao):
    mandato = _assinar()

    assert not mandato_valido(mandato, _vaga(**alteracao), AGORA)


def test_marcar_vaga_como_aprovada_nao_invalida_mandato():
    vaga = _vaga()
    mandato = _assinar(vaga)

    assert mandato_valido(mandato, vaga.model_copy(update={"aprovada": True}), AGORA)


def test_assinar_nao_altera_a_vaga():
    vaga = _vaga()
    antes = vaga.model_copy(deep=True)

    _assinar(vaga)

    assert vaga == antes


@pytest.mark.parametrize("alteracao", [{"empresa_id": "empresa-b"}, {"id": "v2"}])
def test_mandato_nao_vale_para_outra_empresa_ou_vaga(alteracao):
    mandato = _assinar()

    assert not mandato_valido(mandato, _vaga(**alteracao), AGORA)


def test_mandato_com_ids_trocados_nao_vale_mesmo_com_hash_igual():
    vaga = _vaga()
    mandato = _assinar(vaga).model_copy(update={"empresa_id": "empresa-b"})

    assert not mandato_valido(mandato, vaga, AGORA)


def test_hash_nao_depende_da_instancia():
    assert hash_da_vaga(_vaga()) == hash_da_vaga(_vaga())
    assert len(hash_da_vaga(_vaga())) == 64


def test_mandato_nao_pode_ser_alterado_depois_de_assinado():
    mandato = _assinar()

    with pytest.raises(ValidationError):
        mandato.limite_gasto_usd = 1000.0
    with pytest.raises(ValidationError):
        mandato.politica.limiar_verde = 0.1


def test_mandato_salvo_e_recarregado_continua_valido():
    vaga = _vaga()
    mandato = _assinar(vaga)

    recarregado = Mandato.model_validate_json(mandato.model_dump_json())

    assert recarregado == mandato
    assert mandato_valido(recarregado, vaga, AGORA)


def test_id_e_versao_identificam_o_mandato_de_forma_reprodutivel():
    assert _assinar().id == _assinar().id
    assert _assinar(versao=2).versao == 2
    with pytest.raises(MandatoInvalido, match="versao"):
        _assinar(versao=0)


def test_erro_de_mandato_e_erro_previsivel_do_projeto():
    assert issubclass(MandatoInvalido, ErroContrato)


def test_politica_entrega_depois_do_aceite_por_padrao():
    assert _politica().modo_entrega is ModoEntrega.APOS_ACEITE


def test_politica_aceita_limiar_nao_definido():
    assert _politica(limiar_verde=None).limiar_verde is None


@pytest.mark.parametrize(
    "alteracao",
    [
        {"limiar_verde": 1.1},
        {"limiar_verde": -0.1},
        {"limiar_verde": float("nan")},
        {"piso_nota": 1.1},
        {"piso_nota": -0.1},
        {"piso_nota": 0.8},
        {"max_indicacoes": 0},
        {"max_ampliacoes": -1},
    ],
)
def test_politica_incoerente_e_recusada(alteracao):
    with pytest.raises(ValidationError):
        _politica(**alteracao)


def test_assinaturas_diferentes_tem_identificadores_diferentes():
    vaga = _vaga()
    primeira = assinar(vaga, "Ana", 10.0, _politica(), AGORA, validar_criterios=_sem_problemas)
    segunda = assinar(vaga, "Bia", 10.0, _politica(), AGORA, validar_criterios=_sem_problemas)
    assert primeira.id != segunda.id


def test_mandato_vencido_nao_vale():
    vaga = _vaga()
    mandato = assinar(
        vaga,
        "Ana",
        10.0,
        _politica(),
        AGORA,
        validar_criterios=_sem_problemas,
        valido_ate=AGORA + timedelta(days=1),
    )
    assert mandato_valido(mandato, vaga, AGORA)
    assert not mandato_valido(mandato, vaga, AGORA + timedelta(days=2))


def test_mandato_e_contrato_compartilhado():
    from backend.contratos.modelos import Mandato as MandatoContrato
    from backend.contratos.modelos import Politica as PoliticaContrato

    assert Mandato is MandatoContrato
    assert Politica is PoliticaContrato
    assert (
        PoliticaContrato(
            limiar_verde=None, piso_nota=0.2, max_indicacoes=1, max_ampliacoes=0
        ).aceitar_declarada
        is False
    )
