from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.contratos.modelos import (
    Analise,
    Candidato,
    Convite,
    Decisao,
    DestinoPessoa,
    EstadoBanco,
    EventoFluxo,
    PacoteContexto,
    ResultadoEntrevista,
    ResumoExecucao,
    SaidaPersonalizada,
    TaxaMedida,
    TipoConvite,
    TipoDecisao,
    TipoErro,
    Vaga,
)


def _candidato(**extra) -> dict:
    dados = {
        "id": "c1",
        "empresa_id": "empresa-a",
        "nome": "Pessoa Fictícia",
        "fonte": "banco",
        "simulado": True,
        "origem": "planilha",
        "atualizado_em": date(2026, 11, 1),
        "autorizacao_valida_ate": date(2027, 5, 1),
        "estado": EstadoBanco.ATIVO,
        "perfil_texto": "Desenvolvedora Python",
        "atributos": {},
        "historico": [],
        "autorizou_contato": True,
    }
    dados.update(extra)
    return dados


def _vaga(**extra) -> dict:
    dados = {
        "id": "v1",
        "empresa_id": "empresa-a",
        "titulo": "Backend Python",
        "descricao": "Vaga sintética",
        "requisitos": [],
        "competencias": [],
        "meta_candidatos": 5,
        "prazo_dias": 7,
        "max_tentativas_contato": 2,
    }
    dados.update(extra)
    return dados


def _pacote(**extra) -> dict:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "motivo_por_criterio": {},
        "historico": [],
        "evidencias": [],
        "lacunas": [],
        "pontos_a_aprofundar": [],
        "ressalvas_revisor": [],
        "autorizacao": "valida ate 2027-05-01",
        "fonte": "banco",
        "rastro_id": "r1",
        "chave_idempotencia": "empresa-a:v1:c1:entrega",
        "simulado": True,
    }
    dados.update(extra)
    return dados


def _convite(**extra) -> dict:
    dados = {
        "id": "cv1",
        "empresa_id": "empresa-a",
        "tipo": TipoConvite.VAGA,
        "canal": "mensageiro_simulado",
        "vaga_id": "v1",
        "candidato_id": "c1",
        "mensagem": "Olá",
        "link_agendamento": "https://nara.simulada.local/agendar/v1/c1",
        "chave_idempotencia": "empresa-a:v1:c1:vaga:1",
        "simulado": True,
    }
    dados.update(extra)
    return dados


def test_candidato_tem_empresa_e_validade_de_autorizacao():
    candidato = Candidato(**_candidato())
    assert candidato.empresa_id == "empresa-a"
    assert candidato.autorizacao_valida_ate == date(2027, 5, 1)
    assert candidato.opt_out is False

    sem_empresa = _candidato()
    del sem_empresa["empresa_id"]
    with pytest.raises(ValidationError):
        Candidato(**sem_empresa)

    with pytest.raises(ValidationError):
        Candidato(**_candidato(empresa_id=""))


def test_vaga_nao_aprovada_por_padrao():
    assert Vaga(**_vaga()).aprovada is False


def test_pacote_exige_chave_idempotencia():
    assert PacoteContexto(**_pacote()).chave_idempotencia

    sem_chave = _pacote()
    del sem_chave["chave_idempotencia"]
    with pytest.raises(ValidationError):
        PacoteContexto(**sem_chave)

    with pytest.raises(ValidationError):
        PacoteContexto(**_pacote(chave_idempotencia=""))


def test_convite_identifica_simulacao():
    assert Convite(**_convite()).simulado is True

    sem_marcacao = _convite()
    del sem_marcacao["simulado"]
    with pytest.raises(ValidationError):
        Convite(**sem_marcacao)


def test_campo_desconhecido_e_rejeitado():
    with pytest.raises(ValidationError):
        Vaga(**_vaga(campo_inventado="x"))


def test_decisao_guarda_regra_evidencias_e_responsavel():
    decisao = Decisao(
        empresa_id="empresa-a",
        vaga_id="v1",
        candidato_id="c1",
        tipo=TipoDecisao.DESCARTAR,
        regra="requisito_eliminatorio:python",
        motivo="Sem Python no perfil",
        responsavel="regras",
        rastro_id="r1",
        entrada={"requisito": "python"},
        evidencias=[],
        momento=datetime(2026, 11, 7, 12, tzinfo=UTC),
    )
    assert decisao.regra and decisao.responsavel


@pytest.mark.parametrize(
    "modelo", [Decisao, Analise, PacoteContexto, ResultadoEntrevista, EventoFluxo]
)
def test_contratos_de_dados_por_empresa_exigem_empresa_id(modelo):
    assert modelo.model_fields["empresa_id"].is_required()


def test_pacote_identifica_simulacao():
    assert PacoteContexto(**_pacote()).simulado is True

    sem_marcacao = _pacote()
    del sem_marcacao["simulado"]
    with pytest.raises(ValidationError):
        PacoteContexto(**sem_marcacao)


def test_momento_exige_fuso():
    with pytest.raises(ValidationError):
        EventoFluxo(
            empresa_id="empresa-a",
            vaga_id="v1",
            etapa="busca",
            mensagem="ok",
            momento=datetime(2026, 11, 7, 12),
        )
    with pytest.raises(ValidationError):
        Decisao(
            empresa_id="empresa-a",
            vaga_id="v1",
            candidato_id="c1",
            tipo=TipoDecisao.DESCARTAR,
            regra="regra",
            motivo="motivo",
            responsavel="regras",
            rastro_id="r1",
            entrada={},
            evidencias=[],
            momento=datetime(2026, 11, 7, 12),
        )


def test_identificador_so_com_espacos_e_recusado():
    with pytest.raises(ValidationError):
        Candidato(**_candidato(empresa_id="   "))


def test_convite_pode_nao_ter_link_de_agendamento():
    sem_link = _convite()
    del sem_link["link_agendamento"]
    assert Convite(**sem_link).link_agendamento is None


def _taxa(**extra) -> dict:
    dados = {"valor": 0.8, "casos": 20, "wilson_inferior": 0.584, "wilson_superior": 0.919}
    dados.update(extra)
    return dados


def test_destino_pessoa_so_aceita_banco_talent_garden_e_contratada():
    assert {destino.value for destino in DestinoPessoa} == {
        "banco",
        "talent_garden",
        "contratada",
    }
    with pytest.raises(ValueError):
        DestinoPessoa("entrevista")


def test_tipo_erro_lista_os_seis_tipos_medidos():
    assert {tipo.value for tipo in TipoErro} == {
        "indicacao_errada",
        "descarte_errado",
        "violacao_eliminatoria",
        "contato_opt_out",
        "mudanca_nome_genero",
        "afirmacao_sem_evidencia",
    }


def test_taxa_medida_guarda_valor_casos_e_intervalo():
    taxa = TaxaMedida(**_taxa())
    assert (taxa.valor, taxa.casos) == (0.8, 20)
    assert (taxa.wilson_inferior, taxa.wilson_superior) == (0.584, 0.919)


def test_taxa_nao_medida_tem_valor_e_intervalo_nulos():
    taxa = TaxaMedida(valor=None, casos=0, wilson_inferior=None, wilson_superior=None)
    assert taxa.valor is None


def test_taxa_sem_casos_nao_vira_zero():
    with pytest.raises(ValidationError):
        TaxaMedida(valor=0.0, casos=0, wilson_inferior=0.0, wilson_superior=0.0)


@pytest.mark.parametrize(
    "extra",
    [
        {"valor": None},
        {"wilson_inferior": None},
        {"wilson_superior": None},
        {"valor": 1.2, "wilson_superior": 1.3},
        {"valor": -0.1, "wilson_inferior": -0.2},
        {"valor": float("nan")},
        {"casos": -1},
        {"wilson_inferior": 0.85},
        {"wilson_superior": 0.75},
    ],
)
def test_taxa_incoerente_e_recusada(extra):
    with pytest.raises(ValidationError):
        TaxaMedida(**_taxa(**extra))


def test_taxa_nao_medida_com_casos_e_recusada():
    with pytest.raises(ValidationError):
        TaxaMedida(valor=None, casos=3, wilson_inferior=None, wilson_superior=None)


def _resumo(**extra) -> dict:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "estado": "decidindo",
        "analisados": 3,
        "indicados": 1,
        "descartados": 1,
        "na_fila_humana": 1,
        "revertidos": 0,
        "gasto_usd": 0.42,
        "limite_gasto_usd": 5.0,
        "simulado": True,
        "momento": datetime(2026, 11, 7, 12, 0, tzinfo=UTC),
    }
    dados.update(extra)
    return dados


def test_resumo_execucao_exige_identificar_simulacao_e_empresa():
    assert ResumoExecucao(**_resumo()).simulado is True
    for campo in ("simulado", "empresa_id"):
        dados = _resumo()
        del dados[campo]
        with pytest.raises(ValidationError):
            ResumoExecucao(**dados)


@pytest.mark.parametrize(
    "extra",
    [
        {"analisados": -1},
        {"gasto_usd": -0.01},
        {"gasto_usd": float("inf")},
        {"limite_gasto_usd": 0},
        {"momento": datetime(2026, 11, 7, 12, 0)},
        {"campo_novo": 1},
    ],
)
def test_resumo_execucao_recusa_dado_invalido(extra):
    with pytest.raises(ValidationError):
        ResumoExecucao(**_resumo(**extra))


def _saida(**extra) -> dict:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "v1",
        "pacotes": [PacoteContexto(**_pacote())],
        "simulado": True,
        "momento": datetime(2026, 11, 7, 12, 0, tzinfo=UTC),
    }
    dados.update(extra)
    return dados


def test_saida_personalizada_traz_pacotes_identificados():
    saida = SaidaPersonalizada(**_saida())
    assert saida.simulado is True
    assert saida.pacotes[0].candidato_id == "c1"


def test_saida_personalizada_pode_vir_sem_indicados():
    assert SaidaPersonalizada(**_saida(pacotes=[])).pacotes == []


def test_saida_nao_mistura_pacote_de_outra_empresa():
    with pytest.raises(ValidationError):
        SaidaPersonalizada(**_saida(pacotes=[PacoteContexto(**_pacote(empresa_id="empresa-b"))]))


def test_saida_nao_mistura_pacote_de_outra_vaga():
    with pytest.raises(ValidationError):
        SaidaPersonalizada(**_saida(pacotes=[PacoteContexto(**_pacote(vaga_id="v2"))]))


def test_saida_com_pacote_simulado_precisa_estar_identificada():
    with pytest.raises(ValidationError):
        SaidaPersonalizada(**_saida(simulado=False))
