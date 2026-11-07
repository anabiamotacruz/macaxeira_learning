"""Decisão com destino e score: portão duro, sinal, garden e registro."""

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.agente.auditoria import responsavel_do_mandato
from backend.agente.decisao_final import (
    PORTAO_TRECHO_INEXISTENTE,
    REDUCAO_SINAL_EXTERNO,
    RespostaCriterio,
    autorizar_garden,
    classificar_destino,
    como_decisao,
    confirmar_lapidar,
    decisao_final_do_registro,
    encerrar_garden,
    insights_da_vaga,
    nivel_da_nota,
    pontos_a_explorar,
    propor_garden,
    reavaliar_criterios,
    rever_garden,
    situacao_do_garden,
)
from backend.agente.mandato import Mandato, MandatoInvalido, Politica, assinar
from backend.agente.persistencia import Repositorio
from backend.agente.regras import FONTE_REGRA, decidir, validar_criterios
from backend.contratos.modelos import (
    Analise,
    Candidato,
    Competencia,
    DestinoDecisao,
    EstadoBanco,
    EstadoGarden,
    Evidencia,
    FaixaScore,
    FatoIndisponibilidade,
    NivelCriterio,
    OrigemDecisao,
    QualidadeDado,
    Requisito,
    SeloCalibracao,
    TipoDecisao,
    TipoPonto,
    Vaga,
)
from backend.contratos.simulacoes import candidato_simulado

HOJE = date(2026, 11, 7)
AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TRECHO_REQ = "Cinco anos com Python"
TRECHO_BACK = "Liderou APIs em produção"
TRECHO_DADOS = "Modelou dados de vendas"
PERFIL = f"{TRECHO_REQ}. {TRECHO_BACK}. {TRECHO_DADOS}."


def vaga_teste(*requisitos: Requisito, **campos) -> Vaga:
    dados = {
        "id": "v1",
        "empresa_id": "empresa-a",
        "titulo": "Pessoa Desenvolvedora",
        "descricao": "Vaga sintética",
        "requisitos": list(requisitos)
        or [Requisito(id="r1", descricao="Sabe Python", campo="python", valor_esperado="sim")],
        "competencias": [
            Competencia(nome="backend", peso=2.0),
            Competencia(nome="dados", peso=1.0),
        ],
        "meta_candidatos": 2,
        "prazo_dias": 10,
        "max_tentativas_contato": 2,
    }
    return Vaga(**{**dados, **campos})


def candidato_teste(**campos) -> Candidato:
    dados = {
        "fonte": "rede_simulada",
        "perfil_texto": PERFIL,
        "atributos": {"python": "sim"},
    }
    return candidato_simulado("c1", "empresa-a", **{**dados, **campos})


def analise_teste(vaga: Vaga, **campos) -> Analise:
    dados = {
        "empresa_id": vaga.empresa_id,
        "vaga_id": vaga.id,
        "candidato_id": "c1",
        "requisitos_ok": {r.id: True for r in vaga.requisitos},
        "notas": {"backend": 0.9, "dados": 0.9},
        "evidencias": [
            *(
                Evidencia(criterio=r.id, trecho=TRECHO_REQ, fonte="rede_simulada")
                for r in vaga.requisitos
            ),
            Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
            Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="rede_simulada"),
        ],
        "lacunas": [],
        "pontos_a_aprofundar": [],
        "alertas": [],
    }
    return Analise(**{**dados, **campos})


def mandato_teste(vaga: Vaga, **politica) -> Mandato:
    dados = {"limiar_verde": 0.8, "piso_nota": 0.5, "max_indicacoes": 5, "max_ampliacoes": 1}
    return assinar(
        vaga,
        "Pessoa Responsável Fictícia",
        5.0,
        Politica(**{**dados, **politica}),
        AGORA,
        validar_criterios=validar_criterios,
    )


def decidir_teste(vaga=None, candidato=None, analise=None, mandato=None, **kwargs):
    vaga = vaga or vaga_teste()
    return classificar_destino(
        vaga,
        candidato or candidato_teste(),
        analise or analise_teste(vaga),
        mandato or mandato_teste(vaga),
        HOJE,
        AGORA,
        "rastro-1",
        **kwargs,
    )


# Saídas


def test_aprova_quem_passa_nos_portoes_e_tem_nota_alta() -> None:
    decisao = decidir_teste()
    assert decisao.destino == DestinoDecisao.APROVAR
    assert decisao.score.faixa == FaixaScore.ALTA
    assert decisao.score.nota_geral == pytest.approx(0.9)
    assert decisao.portoes == []
    assert decisao.rastro_id == "rastro-1"
    assert decisao.responsavel.startswith("agente:mandato:")


def test_recusa_por_requisito_comprovadamente_nao_atendido() -> None:
    decisao = decidir_teste(candidato=candidato_teste(atributos={"python": "nao"}))
    assert decisao.destino == DestinoDecisao.RECUSAR
    assert decisao.regra == "requisito_eliminatorio:r1"


@pytest.mark.parametrize(
    "campos",
    [
        {"opt_out": True},
        {"autorizou_contato": False},
        {"autorizacao_valida_ate": date(2026, 11, 6)},
        {"estado": EstadoBanco.REMOVIDO},
    ],
)
def test_sem_autorizacao_recusa_por_regra_objetiva(campos: dict) -> None:
    decisao = decidir_teste(candidato=candidato_teste(**campos))
    assert decisao.destino == DestinoDecisao.RECUSAR
    assert decisao.regra == "sem_autorizacao"


def test_perfil_desatualizado_vai_para_uma_pessoa() -> None:
    decisao = decidir_teste(candidato=candidato_teste(estado=EstadoBanco.DESATUALIZADO))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert decisao.regra == "perfil_desatualizado"


@pytest.mark.parametrize("nota", [0.0, 0.1, 0.49])
def test_nota_baixa_nunca_recusa(nota: float) -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(analise=analise_teste(vaga, notas={"backend": nota, "dados": nota}))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert decisao.regra == "nota_baixa_nao_priorizada"
    assert decisao.score.faixa == FaixaScore.BAIXA


def test_nota_no_meio_vai_para_uma_pessoa() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(analise=analise_teste(vaga, notas={"backend": 0.6, "dados": 0.6}))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert decisao.regra == "faixa_media"
    assert decisao.score.faixa == FaixaScore.MEDIA


def test_sem_limiar_nada_e_aprovado_sozinho() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(vaga=vaga, mandato=mandato_teste(vaga, limiar_verde=None))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert decisao.regra == "limiar_nao_definido"


# Portões duros


def test_sem_dado_em_requisito_nunca_aprova_sozinho() -> None:
    decisao = decidir_teste(candidato=candidato_teste(atributos={}))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert "requisito_sem_dado:r1" in decisao.portoes


def test_sem_dado_com_trecho_e_declarada_aceita_continua_sem_aprovar() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(
        vaga=vaga,
        candidato=candidato_teste(atributos={}),
        mandato=mandato_teste(vaga, aceitar_declarada=True),
    )
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


def test_requisito_so_com_evidencia_declarada_nao_passa_sem_a_politica() -> None:
    candidato = candidato_teste(fonte="curriculo")
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="curriculo"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="curriculo"),
        Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="curriculo"),
    ]
    analise = analise_teste(vaga, evidencias=evidencias)
    assert (
        decidir_teste(candidato=candidato, analise=analise).destino == DestinoDecisao.REVISAO_HUMANA
    )
    aceita = decidir_teste(
        vaga=vaga,
        candidato=candidato,
        analise=analise,
        mandato=mandato_teste(vaga, aceitar_declarada=True),
    )
    assert aceita.destino == DestinoDecisao.APROVAR


def test_analise_que_nao_confirma_requisito_e_portao() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(analise=analise_teste(vaga, requisitos_ok={"r1": False}))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert "requisito_nao_confirmado:r1" in decisao.portoes


def test_instrucao_detectada_e_portao_duro() -> None:
    vaga = vaga_teste()
    alerta = "instrucao_no_perfil: o perfil traz texto dirigido ao avaliador."
    decisao = decidir_teste(analise=analise_teste(vaga, alertas=[alerta]))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert "instrucao_detectada" in decisao.portoes


def test_trecho_inexistente_em_requisito_e_portao_duro() -> None:
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho="Trecho que não existe", fonte="rede_simulada"),
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
        Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="rede_simulada"),
    ]
    decisao = decidir_teste(analise=analise_teste(vaga, evidencias=evidencias))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert "trecho_inexistente_em_requisito:r1" in decisao.portoes


@pytest.mark.parametrize(
    ("ressalva", "grave"),
    [
        ('r1: exagero concreto. Trecho: "Cinco anos com Python"', True),
        ("revisor_ressalva_sem_trecho", True),
        ("revisor_resposta_invalida", True),
        ("texto livre que o código não entende", True),
        ("nota_sem_evidencia: r1", True),
        ('backend: exagero concreto. Trecho: "Liderou APIs"', False),
        ("nota_sem_evidencia: backend", False),
    ],
)
def test_ressalva_grave_e_portao_e_leve_so_reduz(ressalva: str, grave: bool) -> None:
    vaga = vaga_teste()
    limpa = decidir_teste()
    decisao = decidir_teste(analise=analise_teste(vaga, ressalvas_revisor=[ressalva]))
    if grave:
        assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
        assert any(p.startswith("ressalva_grave") for p in decisao.portoes)
    else:
        assert decisao.destino == DestinoDecisao.APROVAR
        assert decisao.portoes == []
        assert decisao.score.nota_geral == pytest.approx(
            limpa.score.nota_geral - REDUCAO_SINAL_EXTERNO
        )


def test_recusa_por_requisito_vem_antes_do_portao_de_instrucao() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(
        candidato=candidato_teste(atributos={"python": "nao"}),
        analise=analise_teste(vaga, alertas=["instrucao_no_perfil: texto"]),
    )
    assert decisao.destino == DestinoDecisao.RECUSAR
    assert decisao.alertas


def test_vaga_sem_requisito_vai_para_uma_pessoa() -> None:
    vaga = vaga_teste(requisitos=[])
    decisao = decidir_teste(vaga=vaga, analise=analise_teste(vaga), mandato=mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert "vaga_sem_requisitos" in decisao.portoes


# Sinais


def test_trecho_inexistente_em_competencia_so_reduz_a_nota() -> None:
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
        Evidencia(criterio="dados", trecho="Inventado pelo modelo", fonte="rede_simulada"),
    ]
    analise = analise_teste(vaga, notas={"backend": 1.0, "dados": 1.0}, evidencias=evidencias)
    decisao = decidir_teste(analise=analise)
    assert decisao.score.nota_geral == pytest.approx((2 * 1.0 + 1 * 0.5) / 3, abs=1e-5)
    assert decisao.destino == DestinoDecisao.APROVAR
    dados = next(c for c in decisao.score.criterios if c.criterio == "dados")
    assert dados.qualidade == QualidadeDado.INFERIDO
    assert dados.trechos == []
    assert any(s.criterio == "dados" for s in decisao.score.sinais)


def test_competencia_sem_evidencia_vale_nivel_minimo_sem_anular_a_nota() -> None:
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
    ]
    analise = analise_teste(vaga, notas={"backend": 0.9}, evidencias=evidencias)
    decisao = decidir_teste(analise=analise)
    assert decisao.score.nota_geral == pytest.approx(0.6)
    dados = next(c for c in decisao.score.criterios if c.criterio == "dados")
    assert dados.qualidade == QualidadeDado.SEM_DADO
    assert dados.nota_considerada == 0
    assert any(lacuna.criterio == "dados" for lacuna in decisao.lacunas)


def test_nota_dada_sem_evidencia_nao_conta() -> None:
    vaga = vaga_teste()
    evidencias = [Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada")]
    analise = analise_teste(vaga, evidencias=evidencias)
    decisao = decidir_teste(analise=analise)
    assert decisao.score.nota_geral == 0
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


def test_nota_invalida_do_modelo_vira_nivel_minimo() -> None:
    vaga = vaga_teste()
    analise = analise_teste(vaga, notas={"backend": float("nan"), "dados": 7.0})
    decisao = decidir_teste(analise=analise)
    assert decisao.score.nota_geral == 0
    assert all(c.nota is None for c in decisao.score.criterios)


def test_alerta_que_nao_e_instrucao_so_reduz() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(analise=analise_teste(vaga, alertas=["fonte parcial"]))
    assert decisao.destino == DestinoDecisao.APROVAR
    assert decisao.score.nota_geral == pytest.approx(0.9 - REDUCAO_SINAL_EXTERNO)


def test_peso_invalido_para_em_uma_pessoa() -> None:
    vaga = vaga_teste(competencias=[Competencia(nome="backend", peso=-1.0)])
    analise = analise_teste(vaga, notas={"backend": 0.9})
    decisao = decidir_teste(vaga=vaga, analise=analise, mandato=mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert decisao.score.nota_geral is None


def test_sinais_mudam_o_resultado_que_a_faixa_verde_mandaria_para_a_fila() -> None:
    """Relatado na entrega: `decidir` segue igual, e esta função nova aprova o que ele enfileira."""
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
        Evidencia(criterio="dados", trecho="Inventado pelo modelo", fonte="rede_simulada"),
    ]
    analise = analise_teste(vaga, notas={"backend": 1.0, "dados": 1.0}, evidencias=evidencias)
    candidato = candidato_teste()
    mandato = mandato_teste(vaga)
    antiga = decidir(vaga, candidato, analise, mandato, HOJE, AGORA, "r")
    assert antiga.tipo == TipoDecisao.PEDIR_HUMANO
    assert decidir_teste(vaga, candidato, analise, mandato).destino == DestinoDecisao.APROVAR


# Score


@pytest.mark.parametrize(
    ("nota", "nivel"),
    [
        (0.0, NivelCriterio.NEGA),
        (0.3, NivelCriterio.GENERICA),
        (0.6, NivelCriterio.PARCIAL),
        (0.8, NivelCriterio.DIRETA),
        (1.0, NivelCriterio.DIRETA),
    ],
)
def test_nivel_segue_a_escala_ancorada(nota: float, nivel: NivelCriterio) -> None:
    assert nivel_da_nota(nota) == nivel


def test_score_traz_nivel_peso_trecho_qualidade_e_selo() -> None:
    decisao = decidir_teste()
    backend = next(c for c in decisao.score.criterios if c.criterio == "backend")
    assert backend.nota == pytest.approx(0.9)
    assert backend.nivel == NivelCriterio.DIRETA
    assert backend.peso == 2.0
    assert backend.qualidade == QualidadeDado.COMPROVADO
    assert backend.trechos[0].trecho == TRECHO_BACK
    assert backend.trechos[0].fonte == "rede_simulada"
    requisito = next(c for c in decisao.score.criterios if c.criterio == "r1")
    assert requisito.status_requisito == "atende"
    assert requisito.nota is None
    assert decisao.score.qualidade[QualidadeDado.COMPROVADO] == 3
    assert decisao.score.selo == SeloCalibracao.NAO_CALIBRADO


def test_qualidade_separa_declarado_de_comprovado() -> None:
    candidato = candidato_teste(fonte="curriculo")
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="curriculo"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="github"),
        Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="curriculo"),
    ]
    decisao = decidir_teste(candidato=candidato, analise=analise_teste(vaga, evidencias=evidencias))
    assert all(c.qualidade == QualidadeDado.DECLARADO for c in decisao.score.criterios), (
        "citar github num currículo não promove"
    )


def test_selo_so_muda_com_o_limiar_certificado_igual_ao_do_mandato() -> None:
    assert decidir_teste(limiar_certificado=0.8).score.selo == SeloCalibracao.CERTIFICADO
    assert decidir_teste(limiar_certificado=0.7).score.selo == SeloCalibracao.NAO_CALIBRADO


def test_entrada_nao_guarda_nome_nem_atributos() -> None:
    decisao = decidir_teste(candidato=candidato_teste(nome="Nome Sintético Único"))
    entrada = " ".join(decisao.entrada.values())
    assert "Nome Sintético Único" not in entrada
    assert "mandato_id" in decisao.entrada
    assert all(v.strip() for v in decisao.entrada.values())


def test_trecho_sensivel_nao_aparece_para_o_recrutador_nem_muda_a_decisao() -> None:
    trecho = "Liderou APIs sendo mulher"
    candidato = candidato_teste(perfil_texto=f"{TRECHO_REQ}. {trecho}. {TRECHO_DADOS}.")
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
        Evidencia(criterio="backend", trecho=trecho, fonte="rede_simulada"),
        Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="rede_simulada"),
    ]
    decisao = decidir_teste(candidato=candidato, analise=analise_teste(vaga, evidencias=evidencias))
    assert decisao.destino == DestinoDecisao.APROVAR
    backend = next(c for c in decisao.score.criterios if c.criterio == "backend")
    assert backend.trechos == []
    assert trecho not in decisao.model_dump_json()


def test_pecas_de_empresas_diferentes_sao_recusadas() -> None:
    with pytest.raises(ValueError):
        decidir_teste(candidato=candidato_simulado("c1", "empresa-b"))


def test_mandato_de_vaga_alterada_para_a_decisao() -> None:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga)
    alterada = vaga.model_copy(update={"descricao": "Outra descrição"})
    with pytest.raises(MandatoInvalido):
        decidir_teste(vaga=alterada, analise=analise_teste(alterada), mandato=mandato)


# Equidade


@pytest.mark.parametrize(
    ("nome", "atributos"),
    [
        ("Maria Fictícia", {"python": "sim", "genero": "feminino"}),
        ("João Fictício", {"python": "sim", "genero": "masculino"}),
        ("Nome Neutro", {"python": "sim"}),
    ],
)
def test_trocar_nome_ou_genero_nao_muda_a_decisao(nome: str, atributos: dict) -> None:
    base = decidir_teste(candidato=candidato_teste(nome="Outra Pessoa"))
    trocada = decidir_teste(candidato=candidato_teste(nome=nome, atributos=atributos))
    assert trocada.destino == base.destino
    assert trocada.score == base.score
    assert trocada.regra == base.regra


# Garden a lapidar


def _vaga_com_desenvolvivel() -> Vaga:
    return vaga_teste(
        Requisito(id="r1", descricao="Sabe Python", campo="python", valor_esperado="sim"),
        Requisito(
            id="r2",
            descricao="Conhece Kafka",
            campo="kafka",
            valor_esperado="sim",
            desenvolvivel=True,
        ),
    )


def test_a_lapidar_com_fatos_e_proposto_e_espera_o_rh() -> None:
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(
        vaga,
        requisitos_ok={"r1": True, "r2": False},
        evidencias=[
            Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
            Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
            Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="rede_simulada"),
        ],
    )
    decisao = decidir_teste(vaga=vaga, analise=analise, mandato=mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.GARDEN_A_LAPIDAR
    assert decisao.pendente_confirmacao is True
    assert [lacuna.criterio for lacuna in decisao.lacunas] == ["r2"]
    assert decisao.lacunas[0].desenvolvivel is True


def test_a_lapidar_pode_dispensar_confirmacao_pela_politica() -> None:
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(vaga, requisitos_ok={"r1": True, "r2": False})
    decisao = decidir_teste(
        vaga=vaga, analise=analise, mandato=mandato_teste(vaga, lapidar_exige_confirmacao=False)
    )
    assert decisao.destino == DestinoDecisao.GARDEN_A_LAPIDAR
    assert decisao.pendente_confirmacao is False


def test_requisito_desenvolvivel_nao_atendido_com_nota_alta_vira_a_lapidar() -> None:
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(vaga, requisitos_ok={"r1": True, "r2": False})
    candidato = candidato_teste(atributos={"python": "sim", "kafka": "nao"})
    decisao = decidir_teste(vaga, candidato, analise, mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.GARDEN_A_LAPIDAR


def test_requisito_desenvolvivel_com_nota_que_nao_e_alta_vai_para_uma_pessoa() -> None:
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(
        vaga, requisitos_ok={"r1": True, "r2": False}, notas={"backend": 0.2, "dados": 0.2}
    )
    candidato = candidato_teste(atributos={"python": "sim", "kafka": "nao"})
    decisao = decidir_teste(vaga, candidato, analise, mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


def test_lacuna_em_requisito_nao_desenvolvivel_nao_vira_a_lapidar() -> None:
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(vaga, requisitos_ok={"r1": True, "r2": False})
    candidato = candidato_teste(atributos={})
    decisao = decidir_teste(vaga, candidato, analise, mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


def test_a_lapidar_exige_evidencia_nas_competencias() -> None:
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(
        vaga,
        requisitos_ok={"r1": True, "r2": False},
        notas={"backend": 1.0, "dados": 1.0},
        evidencias=[
            Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
            Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
            Evidencia(criterio="dados", trecho="Inventado", fonte="rede_simulada"),
        ],
    )
    decisao = decidir_teste(vaga, candidato_teste(), analise, mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


def test_portao_de_integridade_impede_a_lapidar() -> None:
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(
        vaga, requisitos_ok={"r1": True, "r2": False}, alertas=["instrucao_no_perfil: x"]
    )
    decisao = decidir_teste(vaga, candidato_teste(), analise, mandato_teste(vaga))
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


def _proposta_a_lapidar():
    vaga = _vaga_com_desenvolvivel()
    analise = analise_teste(vaga, requisitos_ok={"r1": True, "r2": False})
    return decidir_teste(vaga, candidato_teste(), analise, mandato_teste(vaga))


def test_rh_confirma_a_lapidar() -> None:
    decisao = confirmar_lapidar(_proposta_a_lapidar(), "humano:Pessoa RH", True, AGORA)
    assert decisao.destino == DestinoDecisao.GARDEN_A_LAPIDAR
    assert decisao.pendente_confirmacao is False
    assert decisao.responsavel == "humano:Pessoa RH"
    assert decisao.origem == OrigemDecisao.CONFIRMACAO_HUMANA


def test_rh_nega_a_lapidar_e_ninguem_e_recusado() -> None:
    decisao = confirmar_lapidar(_proposta_a_lapidar(), "humano:Pessoa RH", False, AGORA)
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA
    assert decisao.regra == "a_lapidar_nao_confirmado"


@pytest.mark.parametrize("responsavel", ["agente:mandato:m1", "Pessoa sem prefixo", "humano:  "])
def test_so_uma_pessoa_identificada_confirma(responsavel: str) -> None:
    with pytest.raises(ValueError):
        confirmar_lapidar(_proposta_a_lapidar(), responsavel, True, AGORA)


def test_nao_confirma_o_que_nao_espera_confirmacao() -> None:
    with pytest.raises(ValueError):
        confirmar_lapidar(decidir_teste(), "humano:Pessoa RH", True, AGORA)


# Garden de indisponível


def _fato(**campos) -> FatoIndisponibilidade:
    dados = {
        "trecho": "Só consigo a partir de março",
        "fonte": "pre_triagem",
        "voltar_em": date(2027, 3, 1),
    }
    return FatoIndisponibilidade(**{**dados, **campos})


def test_pessoa_boa_que_nao_pode_agora_vai_ao_garden_sem_confirmacao() -> None:
    decisao = decidir_teste(indisponibilidade=_fato())
    assert decisao.destino == DestinoDecisao.GARDEN_INDISPONIVEL
    assert decisao.pendente_confirmacao is False
    assert decisao.indisponibilidade.voltar_em == date(2027, 3, 1)
    assert decisao.responsavel.startswith("agente:")


def test_indisponivel_com_nota_baixa_nao_e_recusado_e_vai_para_uma_pessoa() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(
        analise=analise_teste(vaga, notas={"backend": 0.1, "dados": 0.1}),
        indisponibilidade=_fato(),
    )
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


def test_indisponivel_com_requisito_nao_atendido_continua_recusado() -> None:
    decisao = decidir_teste(
        candidato=candidato_teste(atributos={"python": "nao"}), indisponibilidade=_fato()
    )
    assert decisao.destino == DestinoDecisao.RECUSAR


def test_indisponivel_com_instrucao_vai_para_uma_pessoa() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(
        analise=analise_teste(vaga, alertas=["instrucao_no_perfil: x"]), indisponibilidade=_fato()
    )
    assert decisao.destino == DestinoDecisao.REVISAO_HUMANA


# Entrada no garden


def test_entrada_depende_da_autorizacao_da_pessoa() -> None:
    decisao = decidir_teste(indisponibilidade=_fato())
    entrada = propor_garden(decisao, HOJE, prazo_dias=180)
    assert entrada.estado == EstadoGarden.AGUARDANDO_AUTORIZACAO
    assert entrada.autorizada_em is None
    assert entrada.revisar_em == date(2027, 3, 1)
    assert entrada.motivo_retorno is None


def test_a_lapidar_pendente_nao_abre_entrada() -> None:
    with pytest.raises(ValueError):
        propor_garden(_proposta_a_lapidar(), HOJE, prazo_dias=180)


def test_decisao_que_nao_e_de_garden_nao_abre_entrada() -> None:
    with pytest.raises(ValueError):
        propor_garden(decidir_teste(), HOJE, prazo_dias=180)


def test_autorizacao_tem_prazo_limitado_pela_politica() -> None:
    entrada = propor_garden(decidir_teste(indisponibilidade=_fato()), HOJE, prazo_dias=30)
    candidato = candidato_teste()
    autorizada = autorizar_garden(entrada, candidato, HOJE, date(2030, 1, 1), prazo_dias=30)
    assert autorizada.estado == EstadoGarden.ATIVA
    assert autorizada.autorizada_em == HOJE
    assert autorizada.valida_ate == HOJE + timedelta(days=30)


def test_sem_autorizacao_valida_nao_entra_e_opt_out_nunca_entra() -> None:
    entrada = propor_garden(decidir_teste(indisponibilidade=_fato()), HOJE, prazo_dias=30)
    with pytest.raises(ValueError):
        autorizar_garden(entrada, candidato_teste(opt_out=True), HOJE, date(2027, 1, 1), 30)
    with pytest.raises(ValueError):
        autorizar_garden(entrada, candidato_teste(), HOJE, HOJE - timedelta(days=1), 30)


def _ativa():
    entrada = propor_garden(decidir_teste(indisponibilidade=_fato()), HOJE, prazo_dias=365)
    return autorizar_garden(entrada, candidato_teste(), HOJE, date(2027, 11, 1), prazo_dias=365)


def test_opt_out_sai_do_garden_sempre() -> None:
    saiu = situacao_do_garden(_ativa(), candidato_teste(opt_out=True), HOJE)
    assert saiu.estado == EstadoGarden.ENCERRADA
    assert saiu.motivo_encerramento == "opt_out"


def test_garden_vence_no_prazo_e_chega_a_hora_de_rever() -> None:
    candidato = candidato_teste()
    assert situacao_do_garden(_ativa(), candidato, HOJE).estado == EstadoGarden.ATIVA
    revisao = situacao_do_garden(_ativa(), candidato, date(2027, 3, 1))
    assert revisao.estado == EstadoGarden.PARA_REVISAO
    vencida = situacao_do_garden(_ativa(), candidato, date(2027, 11, 2))
    assert vencida.estado == EstadoGarden.ENCERRADA
    assert vencida.motivo_encerramento == "autorizacao_vencida"


def test_entrada_pode_ser_revista_por_uma_pessoa() -> None:
    entrada = situacao_do_garden(_ativa(), candidato_teste(), date(2027, 3, 1))
    mantida = rever_garden(entrada, "humano:Pessoa RH", date(2027, 6, 1))
    assert mantida.estado == EstadoGarden.ATIVA
    assert mantida.revisar_em == date(2027, 6, 1)
    encerrada = encerrar_garden(entrada, "humano:Pessoa RH", "vaga parecida encerrada")
    assert encerrada.estado == EstadoGarden.ENCERRADA
    with pytest.raises(ValueError):
        rever_garden(entrada, "agente:x", date(2027, 6, 1))


# Reavaliação


def _novo(criterio: str, trecho: str, nivel: NivelCriterio | None = None) -> RespostaCriterio:
    return RespostaCriterio(criterio, trecho, "pre_triagem", nivel)


def _sem_evidencia_de_requisito(vaga: Vaga, **campos) -> Analise:
    evidencias = [
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
        Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="rede_simulada"),
    ]
    return analise_teste(vaga, evidencias=evidencias, **campos)


def test_reavalia_so_o_criterio_afetado() -> None:
    vaga = vaga_teste()
    candidato = candidato_teste(atributos={})
    mandato = mandato_teste(vaga, aceitar_declarada=True)
    anterior = decidir_teste(vaga, candidato, _sem_evidencia_de_requisito(vaga), mandato)
    assert anterior.destino == DestinoDecisao.REVISAO_HUMANA
    atualizado = candidato.model_copy(update={"atributos": {"python": "sim"}})
    nova = reavaliar_criterios(
        anterior,
        vaga,
        atualizado,
        mandato,
        [_novo("r1", "Tenho Python há anos")],
        HOJE,
        AGORA,
        "rastro-2",
    )
    assert nova.reavaliados == ["r1"]
    assert nova.origem == OrigemDecisao.PRE_TRIAGEM
    assert nova.destino == DestinoDecisao.APROVAR
    antes = {c.criterio: c for c in anterior.score.criterios}
    depois = {c.criterio: c for c in nova.score.criterios}
    assert antes["backend"] == depois["backend"]
    assert antes["dados"] == depois["dados"]
    assert depois["r1"].qualidade == QualidadeDado.DECLARADO
    assert depois["r1"].trechos[-1].fonte == "pre_triagem"


def test_resposta_declarada_em_requisito_sem_a_politica_vai_para_uma_pessoa() -> None:
    vaga = vaga_teste()
    candidato = candidato_teste(atributos={})
    mandato = mandato_teste(vaga)
    anterior = decidir_teste(vaga, candidato, _sem_evidencia_de_requisito(vaga), mandato)
    atualizado = candidato.model_copy(update={"atributos": {"python": "sim"}})
    nova = reavaliar_criterios(
        anterior, vaga, atualizado, mandato, [_novo("r1", "Tenho Python")], HOJE, AGORA, "r2"
    )
    assert nova.destino == DestinoDecisao.REVISAO_HUMANA
    assert "requisito_sem_evidencia_aceita:r1" in nova.portoes


def test_reavaliacao_de_competencia_usa_o_nivel_e_nao_passa_de_direta() -> None:
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
    ]
    mandato = mandato_teste(vaga)
    anterior = decidir_teste(
        vaga,
        candidato_teste(),
        analise_teste(vaga, notas={"backend": 0.9}, evidencias=evidencias),
        mandato,
    )
    assert anterior.destino == DestinoDecisao.REVISAO_HUMANA
    nova = reavaliar_criterios(
        anterior,
        vaga,
        candidato_teste(),
        mandato,
        [_novo("dados", "Fiz modelagem para vendas", nivel=NivelCriterio.DIRETA)],
        HOJE,
        AGORA,
        "r2",
    )
    dados = next(c for c in nova.score.criterios if c.criterio == "dados")
    assert dados.nivel == NivelCriterio.DIRETA
    assert dados.qualidade == QualidadeDado.DECLARADO
    assert dados.nota == pytest.approx(0.8)
    assert nova.destino == DestinoDecisao.APROVAR
    assert any(e.criterio == "dados" and e.fonte == "pre_triagem" for e in nova.evidencias)


def test_portoes_de_integridade_sobrevivem_a_reavaliacao() -> None:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga)
    anterior = decidir_teste(
        vaga, candidato_teste(), analise_teste(vaga, alertas=["instrucao_no_perfil: x"]), mandato
    )
    nova = reavaliar_criterios(
        anterior,
        vaga,
        candidato_teste(),
        mandato,
        [_novo("dados", "Fiz modelagem", nivel=NivelCriterio.DIRETA)],
        HOJE,
        AGORA,
        "r2",
    )
    assert nova.destino == DestinoDecisao.REVISAO_HUMANA
    assert "instrucao_detectada" in nova.portoes


def test_trecho_inexistente_some_quando_a_pessoa_responde_o_requisito() -> None:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga, aceitar_declarada=True)
    evidencias = [
        Evidencia(criterio="r1", trecho="Não existe no perfil", fonte="rede_simulada"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="rede_simulada"),
        Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="rede_simulada"),
    ]
    anterior = decidir_teste(
        vaga, candidato_teste(), analise_teste(vaga, evidencias=evidencias), mandato
    )
    assert f"{PORTAO_TRECHO_INEXISTENTE}:r1" in anterior.portoes
    nova = reavaliar_criterios(
        anterior, vaga, candidato_teste(), mandato, [_novo("r1", "Uso Python")], HOJE, AGORA, "r2"
    )
    assert nova.destino == DestinoDecisao.APROVAR
    assert nova.portoes == []


def test_reavaliacao_com_requisito_negado_recusa_por_regra_objetiva() -> None:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga)
    anterior = decidir_teste(vaga, candidato_teste(atributos={}), analise_teste(vaga), mandato)
    negado = candidato_teste(atributos={"python": "nao_atende:sim"})
    nova = reavaliar_criterios(
        anterior, vaga, negado, mandato, [_novo("r1", "Não uso Python")], HOJE, AGORA, "r2"
    )
    assert nova.destino == DestinoDecisao.RECUSAR
    assert nova.regra == "requisito_eliminatorio:r1"


def test_opt_out_durante_a_reavaliacao_recusa_por_autorizacao() -> None:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga)
    anterior = decidir_teste(vaga, candidato_teste(), analise_teste(vaga), mandato)
    nova = reavaliar_criterios(
        anterior, vaga, candidato_teste(opt_out=True), mandato, [], HOJE, AGORA, "r2"
    )
    assert nova.destino == DestinoDecisao.RECUSAR
    assert nova.regra == "sem_autorizacao"


def test_reavaliacao_recusa_criterio_que_a_vaga_nao_tem() -> None:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga)
    anterior = decidir_teste(vaga, candidato_teste(), analise_teste(vaga), mandato)
    with pytest.raises(ValueError):
        reavaliar_criterios(
            anterior, vaga, candidato_teste(), mandato, [_novo("x", "t")], HOJE, AGORA, "r2"
        )


# Registro


def test_decisao_final_cabe_no_registro_de_decisoes_e_volta_igual(tmp_path) -> None:
    final = decidir_teste()
    decisao = como_decisao(final)
    assert decisao.tipo == TipoDecisao.INDICAR
    assert decisao.responsavel == final.responsavel
    assert decisao.evidencias
    repositorio = Repositorio(tmp_path / "banco.db")
    repositorio.salvar_decisao(decisao)
    salva = repositorio.listar_decisoes("empresa-a", "v1")[-1]
    assert decisao_final_do_registro(salva) == final


@pytest.mark.parametrize(
    ("fabrica", "tipo"),
    [
        (
            lambda: decidir_teste(candidato=candidato_teste(atributos={"python": "nao"})),
            TipoDecisao.DESCARTAR,
        ),
        (lambda: decidir_teste(indisponibilidade=_fato()), TipoDecisao.PEDIR_HUMANO),
        (_proposta_a_lapidar, TipoDecisao.PEDIR_HUMANO),
        (lambda: decidir_teste(candidato=candidato_teste(atributos={})), TipoDecisao.PEDIR_HUMANO),
    ],
)
def test_destinos_viram_o_tipo_antigo_sem_descarte_por_nota(fabrica, tipo: TipoDecisao) -> None:
    assert como_decisao(fabrica()).tipo == tipo


def test_registro_sem_decisao_final_devolve_vazio() -> None:
    vaga = vaga_teste()
    antiga = decidir(
        vaga, candidato_teste(), analise_teste(vaga), mandato_teste(vaga), HOJE, AGORA, "r"
    )
    assert decisao_final_do_registro(antiga) is None


def test_lacunas_deixam_evidencia_da_regra_ligada_ao_criterio() -> None:
    decisao = decidir_teste(candidato=candidato_teste(atributos={"python": "nao"}))
    registrada = [e for e in decisao.evidencias if e.fonte == FONTE_REGRA and e.criterio == "r1"]
    assert registrada and registrada[0].trecho == "Sabe Python"


def test_responsavel_cita_o_mandato_assinado() -> None:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga)
    assert decidir_teste(vaga=vaga, mandato=mandato).responsavel == responsavel_do_mandato(mandato)


def test_decisao_gera_rastro(rastro) -> None:
    decidir_teste()
    assert any(r.etapa == "decisao_final" for r in rastro.registros)


# Pontos a explorar


def test_lacuna_traz_o_criterio_como_trecho_e_a_vaga_como_fonte() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(candidato=candidato_teste(atributos={}))
    pontos = pontos_a_explorar(decisao, vaga)
    lacuna = next(p for p in pontos if p.tipo == TipoPonto.LACUNA and p.criterio == "r1")
    assert lacuna.trecho == "Sabe Python"
    assert lacuna.fonte == "vaga:v1"
    assert lacuna.rotulo == "Não verificado"


def test_afirmacao_sem_exemplo_e_experiencia_parecida_trazem_trecho() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(analise=analise_teste(vaga, notas={"backend": 0.3, "dados": 0.6}))
    pontos = {p.criterio: p for p in pontos_a_explorar(decisao, vaga)}
    assert pontos["backend"].tipo == TipoPonto.AFIRMACAO_SEM_EXEMPLO
    assert pontos["backend"].trecho == TRECHO_BACK
    assert pontos["backend"].fonte == "rede_simulada"
    assert pontos["backend"].verificado is True
    assert pontos["dados"].tipo == TipoPonto.EXPERIENCIA_PARECIDA
    assert pontos["dados"].inferencia is True
    assert pontos["dados"].rotulo == "Não verificado"


def test_contradicao_entre_analise_e_atributo_aparece_com_trecho() -> None:
    vaga = vaga_teste()
    decisao = decidir_teste(analise=analise_teste(vaga, requisitos_ok={"r1": False}))
    pontos = pontos_a_explorar(decisao, vaga)
    contradicao = next(p for p in pontos if p.tipo == TipoPonto.CONTRADICAO)
    assert contradicao.criterio == "r1"
    assert contradicao.trecho == TRECHO_REQ


def test_ponto_com_trecho_declarado_aparece_como_nao_verificado() -> None:
    candidato = candidato_teste(fonte="curriculo")
    vaga = vaga_teste()
    evidencias = [
        Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="curriculo"),
        Evidencia(criterio="backend", trecho=TRECHO_BACK, fonte="curriculo"),
        Evidencia(criterio="dados", trecho=TRECHO_DADOS, fonte="curriculo"),
    ]
    analise = analise_teste(vaga, notas={"backend": 0.3, "dados": 0.9}, evidencias=evidencias)
    decisao = decidir_teste(candidato=candidato, analise=analise)
    ponto = next(p for p in pontos_a_explorar(decisao, vaga) if p.criterio == "backend")
    assert ponto.verificado is False
    assert ponto.rotulo == "Não verificado"


def test_quem_nao_tem_o_que_explorar_devolve_lista_vazia() -> None:
    assert pontos_a_explorar(decidir_teste(), vaga_teste()) == []


def test_criterio_de_vaga_com_termo_proibido_nao_vira_ponto() -> None:
    vaga = vaga_teste(
        Requisito(id="r1", descricao="Sabe Python", campo="python", valor_esperado="sim"),
        competencias=[Competencia(nome="saude digital", peso=1.0)],
    )
    analise = analise_teste(
        vaga,
        notas={},
        evidencias=[
            Evidencia(criterio="r1", trecho=TRECHO_REQ, fonte="rede_simulada"),
        ],
    )
    decisao = decidir_teste(vaga, candidato_teste(), analise, mandato_teste(vaga))
    assert all(p.criterio != "saude digital" for p in pontos_a_explorar(decisao, vaga))


# Insights agregados


def _decisoes_da_vaga(total: int, sem_requisito: int) -> list:
    vaga = vaga_teste()
    mandato = mandato_teste(vaga)
    decisoes = []
    for indice in range(total):
        atributos = {} if indice < sem_requisito else {"python": "sim"}
        candidato = candidato_simulado(
            f"pessoa-{indice}",
            "empresa-a",
            fonte="rede_simulada",
            perfil_texto=PERFIL,
            atributos=atributos,
        )
        analise = analise_teste(vaga, candidato_id=f"pessoa-{indice}")
        decisoes.append(classificar_destino(vaga, candidato, analise, mandato, HOJE, AGORA, "r"))
    return decisoes


def test_insight_mostra_o_requisito_em_que_a_maioria_para_sem_expor_pessoas() -> None:
    insights = insights_da_vaga(vaga_teste(), _decisoes_da_vaga(8, 6))
    assert insights.suprimido is False
    assert insights.total == 8
    item = next(i for i in insights.insights if i.criterio == "r1")
    assert item.pessoas == 6
    assert item.trecho == "Sabe Python"
    assert item.fonte == "vaga:v1"
    assert "pessoa-" not in insights.model_dump_json()


def test_insight_some_com_poucas_pessoas() -> None:
    insights = insights_da_vaga(vaga_teste(), _decisoes_da_vaga(3, 3))
    assert insights.suprimido is True
    assert insights.insights == []


def test_insight_nao_aparece_quando_a_minoria_para() -> None:
    insights = insights_da_vaga(vaga_teste(), _decisoes_da_vaga(8, 2))
    assert all(i.criterio != "r1" for i in insights.insights)


def test_insight_recusa_decisao_de_outra_vaga_ou_empresa() -> None:
    decisoes = _decisoes_da_vaga(5, 0)
    outra = decisoes[0].model_copy(update={"empresa_id": "empresa-b"})
    with pytest.raises(ValueError):
        insights_da_vaga(vaga_teste(), [*decisoes, outra])


def test_insight_conta_a_ultima_decisao_de_cada_pessoa() -> None:
    decisoes = _decisoes_da_vaga(5, 5)
    novas = [
        d.model_copy(update={"lacunas": [], "momento": AGORA + timedelta(hours=1)})
        for d in decisoes
    ]
    insights = insights_da_vaga(vaga_teste(), [*decisoes, *novas])
    assert insights.total == 5
    assert insights.insights == []
