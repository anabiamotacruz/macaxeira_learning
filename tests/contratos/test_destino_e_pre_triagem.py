"""Contratos da decisão com destino, pré-triagem, contexto e feedback."""

import hashlib
import json
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.agente.mandato import hash_da_vaga
from backend.contratos.criterios import julgamentos_proibidos, termos_proibidos_em_conversa
from backend.contratos.modelos import (
    Competencia,
    DecisaoFinal,
    DestinoDecisao,
    EntradaGarden,
    EstadoGarden,
    FaixaScore,
    FatoIndisponibilidade,
    FeedbackCandidato,
    NotaCriterio,
    PerguntaRoteiro,
    Politica,
    PontoExplorar,
    QualidadeDado,
    Requisito,
    ResultadoPreTriagem,
    ScoreRecrutador,
    SeloCalibracao,
    SituacaoPreTriagem,
    StatusFeedback,
    TipoCriterio,
    TipoPergunta,
    TipoPonto,
    Vaga,
)

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _vaga(requisito: Requisito) -> Vaga:
    return Vaga(
        id="v1",
        empresa_id="empresa-a",
        titulo="Pessoa Desenvolvedora",
        descricao="Vaga sintética",
        requisitos=[requisito],
        competencias=[Competencia(nome="backend", peso=1.0)],
        meta_candidatos=1,
        prazo_dias=10,
        max_tentativas_contato=2,
    )


def _requisito(**campos) -> Requisito:
    dados = {"id": "r1", "descricao": "Python", "campo": "linguagem", "valor_esperado": "python"}
    return Requisito(**{**dados, **campos})


def _score(**campos) -> ScoreRecrutador:
    dados = {
        "criterios": [],
        "nota_geral": 0.9,
        "faixa": FaixaScore.ALTA,
        "sinais": [],
        "selo": SeloCalibracao.NAO_CALIBRADO,
        "qualidade": {},
    }
    return ScoreRecrutador(**{**dados, **campos})


def _decisao(**campos) -> DecisaoFinal:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "destino": DestinoDecisao.REVISAO_HUMANA,
        "regra": "faixa_media",
        "motivo": "motivo sintético",
        "responsavel": "agente:mandato:m1:v1:assinante:Pessoa",
        "rastro_id": "rastro",
        "score": _score(),
        "entrada": {"vaga_id": "v1"},
        "evidencias": [],
        "simulado": True,
        "momento": AGORA,
    }
    return DecisaoFinal(**{**dados, **campos})


def _nota_requisito(status: str) -> NotaCriterio:
    return NotaCriterio(
        criterio="r1",
        tipo=TipoCriterio.REQUISITO,
        descricao="Python",
        peso=0,
        qualidade=QualidadeDado.SEM_DADO,
        status_requisito=status,
        eliminatorio=True,
    )


def _hash_de_antes_do_campo(vaga: Vaga) -> str:
    """O hash como era antes de `desenvolvivel` existir."""
    conteudo = vaga.model_dump(mode="json", exclude={"aprovada"})
    for requisito in conteudo["requisitos"]:
        del requisito["desenvolvivel"]
    canonico = json.dumps(conteudo, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def test_campo_novo_nao_invalida_mandato_ja_assinado() -> None:
    vaga = _vaga(_requisito())
    assert hash_da_vaga(vaga) == _hash_de_antes_do_campo(vaga)


def test_marcar_requisito_como_desenvolvivel_invalida_o_mandato() -> None:
    assert hash_da_vaga(_vaga(_requisito(desenvolvivel=True))) != hash_da_vaga(_vaga(_requisito()))


def test_politica_tem_confirmacao_humana_e_prazo_por_padrao() -> None:
    politica = Politica(limiar_verde=0.8, piso_nota=0.5, max_indicacoes=1, max_ampliacoes=0)
    assert politica.lapidar_exige_confirmacao is True
    assert politica.prazo_garden_dias > 0


@pytest.mark.parametrize(
    "regra", ["nota_baixa", "abaixo_do_piso", "faixa_media", "requisito_eliminatorio:"]
)
def test_recusa_exige_regra_objetiva(regra: str) -> None:
    with pytest.raises(ValidationError):
        _decisao(destino=DestinoDecisao.RECUSAR, regra=regra)


@pytest.mark.parametrize("regra", ["requisito_eliminatorio:r1", "sem_autorizacao"])
def test_recusa_aceita_regra_objetiva(regra: str) -> None:
    assert _decisao(destino=DestinoDecisao.RECUSAR, regra=regra).destino == DestinoDecisao.RECUSAR


def test_aprovacao_nao_passa_com_requisito_sem_dado() -> None:
    criterios = [_nota_requisito("sem_dado")]
    with pytest.raises(ValidationError):
        _decisao(
            destino=DestinoDecisao.APROVAR,
            regra="aprovacao_por_criterios_v1",
            score=_score(criterios=criterios),
        )


def test_aprovacao_nao_passa_com_portao_nem_sem_nota() -> None:
    with pytest.raises(ValidationError):
        _decisao(destino=DestinoDecisao.APROVAR, regra="x", portoes=["instrucao_detectada"])
    with pytest.raises(ValidationError):
        _decisao(destino=DestinoDecisao.APROVAR, regra="x", score=_score(nota_geral=None))


def test_garden_indisponivel_exige_fato_da_pessoa() -> None:
    with pytest.raises(ValidationError):
        _decisao(destino=DestinoDecisao.GARDEN_INDISPONIVEL, regra="pessoa_indisponivel")


def test_fato_de_indisponibilidade_exige_data_ou_motivo() -> None:
    with pytest.raises(ValidationError):
        FatoIndisponibilidade(trecho="não posso agora", fonte="pre_triagem")
    fato = FatoIndisponibilidade(
        trecho="volto em março", fonte="pre_triagem", voltar_em=date(2027, 3, 1)
    )
    assert fato.voltar_em == date(2027, 3, 1)


def test_garden_a_lapidar_exige_lacuna_listada() -> None:
    with pytest.raises(ValidationError):
        _decisao(destino=DestinoDecisao.GARDEN_A_LAPIDAR, regra="a_lapidar_por_fatos")


@pytest.mark.parametrize(
    "texto",
    [
        "Qual a sua idade?",
        "Você tem filhos?",
        "Qual a sua religião?",
        "Como está sua saúde?",
        "Você é casada?",
        "Qual seu estado civil?",
        "Pretende engravidar?",
        "Qual o seu gênero?",
        "Tem alguma doença?",
        "Quantos anos você tem?",
        "É filiada a sindicato?",
    ],
)
def test_pergunta_sensivel_nao_existe_no_contrato(texto: str) -> None:
    assert termos_proibidos_em_conversa(texto)
    with pytest.raises(ValidationError):
        PerguntaRoteiro(
            id="p1",
            ordem=1,
            tipo=TipoPergunta.REQUISITO,
            criterio="r1",
            texto=texto,
            motivo="motivo",
        )


def test_termos_de_experiencia_nao_contam_como_idade() -> None:
    assert not termos_proibidos_em_conversa("Tenho 5 anos de experiência com Python")
    assert termos_proibidos_em_conversa("Tenho 35 anos e moro perto")


def test_ponto_sem_personalidade_nem_dado_sensivel() -> None:
    assert julgamentos_proibidos("Parece ter ótimo fit cultural")
    for texto in ("Tem ótimo fit cultural", "Personalidade forte", "Mãe de dois"):
        with pytest.raises(ValidationError):
            PontoExplorar(
                tipo=TipoPonto.LACUNA,
                criterio="r1",
                descricao=texto,
                trecho="Python",
                fonte="vaga:v1",
                verificado=False,
            )


def test_ponto_mostra_nao_verificado_e_inferencia_nunca_e_verificada() -> None:
    ponto = PontoExplorar(
        tipo=TipoPonto.EXPERIENCIA_PARECIDA,
        criterio="backend",
        descricao="Experiência parecida",
        trecho="Fez APIs",
        fonte="github",
        verificado=False,
        inferencia=True,
    )
    assert ponto.rotulo == "Não verificado"
    with pytest.raises(ValidationError):
        PontoExplorar(
            tipo=TipoPonto.EXPERIENCIA_PARECIDA,
            criterio="backend",
            descricao="Experiência parecida",
            trecho="Fez APIs",
            fonte="github",
            verificado=True,
            inferencia=True,
        )


def test_ponto_volta_igual_do_json_e_o_rotulo_nao_pode_ser_forjado() -> None:
    ponto = PontoExplorar(
        tipo=TipoPonto.LACUNA,
        criterio="r1",
        descricao="Falta confirmar",
        trecho="Python",
        fonte="vaga:v1",
        verificado=False,
        rotulo="Verificado",
    )
    assert ponto.rotulo == "Não verificado"
    assert PontoExplorar.model_validate_json(ponto.model_dump_json()) == ponto


def test_experiencia_parecida_sempre_e_inferencia() -> None:
    with pytest.raises(ValidationError):
        PontoExplorar(
            tipo=TipoPonto.EXPERIENCIA_PARECIDA,
            criterio="backend",
            descricao="Experiência parecida",
            trecho="Fez APIs",
            fonte="github",
            verificado=False,
        )


def test_resultado_da_pre_triagem_precisa_bater_com_o_destino() -> None:
    revisao = _decisao(destino=DestinoDecisao.REVISAO_HUMANA)
    for situacao in (SituacaoPreTriagem.PASSOU, SituacaoPreTriagem.NAO_PASSOU):
        with pytest.raises(ValidationError):
            ResultadoPreTriagem(situacao=situacao, decisao=revisao)
    assert ResultadoPreTriagem(situacao=SituacaoPreTriagem.AMBIGUO, decisao=revisao)


def test_link_de_agendamento_so_para_quem_passou() -> None:
    with pytest.raises(ValidationError):
        ResultadoPreTriagem(
            situacao=SituacaoPreTriagem.AMBIGUO,
            decisao=_decisao(destino=DestinoDecisao.REVISAO_HUMANA),
            link_agendamento="https://exemplo.test/agendar",
        )


def test_entrada_no_garden_ativa_exige_autorizacao_com_prazo() -> None:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "destino": DestinoDecisao.GARDEN_INDISPONIVEL,
        "regra": "pessoa_indisponivel",
        "revisar_em": date(2027, 1, 1),
    }
    with pytest.raises(ValidationError):
        EntradaGarden(**dados, estado=EstadoGarden.ATIVA)
    entrada = EntradaGarden(
        **dados,
        estado=EstadoGarden.ATIVA,
        autorizada_em=date(2026, 11, 7),
        valida_ate=date(2027, 5, 1),
    )
    assert entrada.valida_ate == date(2027, 5, 1)


def test_feedback_nao_tem_campo_de_nota_nem_ranking() -> None:
    campos = set(FeedbackCandidato.model_fields)
    assert not campos & {"nota", "nota_geral", "faixa", "ranking", "posicao", "outros_candidatos"}
    with pytest.raises(ValidationError):
        FeedbackCandidato(status=StatusFeedback.GERADO, saudacao="Olá", texto="t", nota=0.5)
