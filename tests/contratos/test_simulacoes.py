from datetime import date

import pytest
from pydantic import BaseModel

from backend.contratos import interfaces
from backend.contratos.erros import FonteIndisponivel, RespostaInvalida
from backend.contratos.modelos import (
    Competencia,
    Convite,
    EstadoBanco,
    PacoteContexto,
    Requisito,
    TipoConvite,
    Vaga,
)
from backend.contratos.simulacoes import (
    AgenteSemAgendaSimulado,
    AnalisadorSimulado,
    BancoTalentosSimulado,
    ClienteModeloSimulado,
    ClienteNaraSimulado,
    FonteSimulada,
    MensageiroSimulado,
    RevisorSimulado,
    candidato_simulado,
)

HOJE = date(2026, 11, 7)


def _vaga() -> Vaga:
    return Vaga(
        id="v1",
        empresa_id="empresa-a",
        titulo="Backend Python",
        descricao="Vaga sintética",
        requisitos=[],
        competencias=[],
        meta_candidatos=5,
        prazo_dias=7,
        max_tentativas_contato=2,
    )


def _convite(chave: str = "empresa-a:v1:c1:vaga:1") -> Convite:
    return Convite(
        id="cv1",
        empresa_id="empresa-a",
        tipo=TipoConvite.VAGA,
        canal="mensageiro_simulado",
        vaga_id="v1",
        candidato_id="c1",
        mensagem="Olá",
        link_agendamento="https://nara.simulada.local/agendar/v1/c1",
        chave_idempotencia=chave,
        simulado=True,
    )


def _pacote(empresa_id: str = "empresa-a") -> PacoteContexto:
    return PacoteContexto(
        empresa_id=empresa_id,
        vaga_id="v1",
        candidato_id="c1",
        motivo_por_criterio={},
        historico=[],
        evidencias=[],
        lacunas=[],
        pontos_a_aprofundar=[],
        ressalvas_revisor=[],
        autorizacao="valida",
        fonte="banco",
        rastro_id="r1",
        chave_idempotencia="v1:c1:entrega",
        simulado=True,
    )


def test_simulacoes_seguem_as_interfaces():
    pares = [
        (FonteSimulada([]), interfaces.FonteCandidatos),
        (BancoTalentosSimulado(hoje=HOJE), interfaces.BancoTalentos),
        (AnalisadorSimulado(), interfaces.Analisador),
        (RevisorSimulado(), interfaces.Revisor),
        (MensageiroSimulado(), interfaces.Mensageiro),
        (ClienteNaraSimulado(), interfaces.AgenteRecrutador),
        (AgenteSemAgendaSimulado(), interfaces.AgenteRecrutador),
        (ClienteModeloSimulado(), interfaces.ClienteModelo),
    ]
    for simulacao, interface in pares:
        assert isinstance(simulacao, interface), type(simulacao).__name__


@pytest.mark.parametrize(
    "fonte",
    [FonteSimulada([]), BancoTalentosSimulado(hoje=HOJE)],
    ids=["fonte", "banco"],
)
def test_busca_exige_empresa_id(fonte):
    with pytest.raises(ValueError):
        fonte.buscar("", "python")


def test_banco_isola_empresas_e_exige_autorizacao_valida():
    banco = BancoTalentosSimulado(hoje=HOJE)
    banco.importar("empresa-a", [{"nome": "Ana Fictícia", "perfil_texto": "Python"}])
    banco.importar("empresa-b", [{"nome": "Bia Fictícia", "perfil_texto": "Python"}])

    assert banco.buscar("empresa-a", "python") == []

    [pessoa] = banco.importar("empresa-a", [{"nome": "Caio Fictício", "perfil_texto": "Python"}])
    banco.registrar_autorizacao("empresa-a", pessoa.id, date(2027, 1, 1))
    encontrados = banco.buscar("empresa-a", "python")
    assert [c.id for c in encontrados] == [pessoa.id]
    assert all(c.empresa_id == "empresa-a" for c in encontrados)
    assert all(c.simulado for c in encontrados)

    with pytest.raises(KeyError):
        banco.atualizar("empresa-b", pessoa.id, {"cidade": "Recife"})

    banco.remover("empresa-a", pessoa.id)
    assert banco.buscar("empresa-a", "python") == []


def test_fonte_simulada_injeta_falha():
    fonte = FonteSimulada([candidato_simulado("c1", "empresa-a")])
    assert len(fonte.buscar("empresa-a", "")) == 1
    assert fonte.buscar("empresa-b", "") == []
    fonte.falhar = True
    with pytest.raises(FonteIndisponivel):
        fonte.buscar("empresa-a", "")


def test_mensageiro_nao_duplica_e_permite_repetir_apos_falha():
    mensageiro = MensageiroSimulado(falhas_restantes=1)
    convite = _convite()
    assert mensageiro.enviar(convite) is False
    assert mensageiro.enviar(convite) is True
    assert mensageiro.enviar(convite) is True
    assert len(mensageiro.enviados) == 1


def test_nara_simulada_identifica_simulacao_e_nao_duplica():
    nara = ClienteNaraSimulado(semente=7)
    assert "simulada" in nara.link_agendamento("v1", "c1")
    assert nara.entregar(_pacote()) is True
    assert nara.entregar(_pacote()) is True
    assert len(nara.entregues) == 1

    resultados = nara.resultados("empresa-a", "v1")
    assert resultados and all(r.simulado for r in resultados)
    assert ClienteNaraSimulado(semente=7).resultados_para(_pacote()) == resultados[0]


def test_analisador_e_revisor_simulados_marcam_ressalva():
    vaga = _vaga()
    candidato = candidato_simulado("c1", "empresa-a")
    analise = AnalisadorSimulado().analisar(vaga, candidato)
    assert analise.candidato_id == "c1"
    revisada = RevisorSimulado(ressalvas=["exagero"]).revisar(vaga, candidato, analise)
    assert revisada.ressalvas_revisor == ["exagero"]


class _Saida(BaseModel):
    texto: str


def test_modelo_simulado_responde_por_etapa_e_falha_sem_resposta():
    modelo = ClienteModeloSimulado(respostas={"convite": {"texto": "oi"}})
    saida = modelo.completar("sistema", "usuario", _Saida, etapa="convite")
    assert saida == _Saida(texto="oi")
    assert modelo.chamadas[0]["etapa"] == "convite"

    with pytest.raises(RespostaInvalida):
        modelo.completar("sistema", "usuario", _Saida, etapa="desconhecida")


def test_candidato_simulado_padrao_e_ativo_e_autorizado():
    candidato = candidato_simulado("c1", "empresa-a")
    assert candidato.simulado
    assert candidato.estado == EstadoBanco.ATIVO
    assert candidato.autorizou_contato


def test_nara_isola_resultados_e_entregas_por_empresa():
    nara = ClienteNaraSimulado()
    nara.entregar(_pacote("empresa-a"))
    nara.entregar(_pacote("empresa-b"))

    assert len(nara.entregues) == 2
    assert [r.empresa_id for r in nara.resultados("empresa-a", "v1")] == ["empresa-a"]
    assert [r.empresa_id for r in nara.resultados("empresa-b", "v1")] == ["empresa-b"]


def test_analisador_simulado_traz_evidencia_para_cada_criterio():
    vaga = _vaga().model_copy(
        update={
            "requisitos": [
                Requisito(id="r1", descricao="Python", campo="skill", valor_esperado="python")
            ],
            "competencias": [Competencia(nome="APIs", peso=1.0)],
        }
    )
    candidato = candidato_simulado("c1", "empresa-a")

    analise = AnalisadorSimulado().analisar(vaga, candidato)

    assert analise.empresa_id == "empresa-a"
    assert {e.criterio for e in analise.evidencias} == {"r1", "APIs"}
    assert all(e.trecho and e.fonte for e in analise.evidencias)


def test_reimportar_nao_apaga_opt_out_nem_autorizacao():
    banco = BancoTalentosSimulado(hoje=HOJE)
    banco.importar("empresa-a", [{"id": "c1", "perfil_texto": "Python"}])
    banco.registrar_autorizacao("empresa-a", "c1", date(2027, 1, 1))
    banco.registrar_opt_out("empresa-a", "c1")

    [reimportado] = banco.importar("empresa-a", [{"id": "c1", "perfil_texto": "Python"}])

    assert reimportado.opt_out is True
    assert reimportado.autorizou_contato is True
    assert banco.buscar("empresa-a", "python") == []


def test_quem_foi_removido_nao_volta_por_importacao():
    banco = BancoTalentosSimulado(hoje=HOJE)
    banco.importar("empresa-a", [{"id": "c1", "perfil_texto": "Python"}])
    banco.remover("empresa-a", "c1")

    assert banco.importar("empresa-a", [{"id": "c1", "perfil_texto": "Python"}]) == []
    with pytest.raises(KeyError):
        banco.registrar_autorizacao("empresa-a", "c1", date(2027, 1, 1))

    assert len(banco.importar("empresa-b", [{"id": "c1", "perfil_texto": "Python"}])) == 1


def test_vencendo_nao_lista_quem_saiu():
    banco = BancoTalentosSimulado(hoje=HOJE)
    banco.importar("empresa-a", [{"id": "c1"}, {"id": "c2"}])
    banco.registrar_autorizacao("empresa-a", "c1", date(2026, 11, 10))
    banco.registrar_autorizacao("empresa-a", "c2", date(2026, 11, 10))
    banco.registrar_opt_out("empresa-a", "c2")

    assert [c.id for c in banco.vencendo("empresa-a", date(2026, 12, 1))] == ["c1"]


def test_busca_ve_dados_atualizados():
    banco = BancoTalentosSimulado(hoje=HOJE)
    banco.importar("empresa-a", [{"id": "c1", "perfil_texto": "Vendas"}])
    banco.registrar_autorizacao("empresa-a", "c1", date(2027, 1, 1))

    banco.atualizar("empresa-a", "c1", {"skill": "Rust"})

    assert [c.id for c in banco.buscar("empresa-a", "rust")] == ["c1"]


def test_registrar_opt_out_tira_da_busca_e_exige_a_mesma_empresa():
    banco = BancoTalentosSimulado(hoje=HOJE)
    banco.importar("empresa-a", [{"id": "c1", "perfil_texto": "Python"}])
    banco.registrar_autorizacao("empresa-a", "c1", date(2027, 1, 1))

    assert banco.registrar_opt_out("empresa-a", "c1").opt_out is True
    assert banco.buscar("empresa-a", "python") == []
    with pytest.raises(KeyError):
        banco.registrar_opt_out("empresa-b", "c1")


def test_busca_nao_depende_do_nome_e_compara_termos_inteiros():
    com_nome = candidato_simulado("c1", "empresa-a", nome="Rust Silva", perfil_texto="Vendas")
    javascript = candidato_simulado("c2", "empresa-a", perfil_texto="JavaScript")
    fonte = FonteSimulada([com_nome, javascript])

    assert fonte.buscar("empresa-a", "rust") == []
    assert fonte.buscar("empresa-a", "java") == []
    assert [c.id for c in fonte.buscar("empresa-a", "javascript")] == ["c2"]


def test_mensageiro_simula_falha_depois_de_envio_aceito():
    mensageiro = MensageiroSimulado(falhas_apos_envio=1)
    convite = _convite()

    assert mensageiro.enviar(convite) is False
    assert len(mensageiro.enviados) == 1
    assert mensageiro.enviar(convite) is True
    assert len(mensageiro.enviados) == 1


def test_nara_simula_indisponibilidade_sem_perder_a_entrega():
    nara = ClienteNaraSimulado(falhas_restantes=1)

    assert nara.entregar(_pacote()) is False
    assert nara.entregues == {}
    assert nara.entregar(_pacote()) is True
    assert len(nara.entregues) == 1


@pytest.mark.parametrize(
    "fonte",
    [FonteSimulada([]), BancoTalentosSimulado(hoje=HOJE)],
    ids=["fonte", "banco"],
)
def test_empresa_so_com_espacos_e_recusada(fonte):
    with pytest.raises(ValueError):
        fonte.buscar("   ", "python")


def test_agente_sem_agenda_recebe_pacote_sem_link_nem_resultado():
    agente = AgenteSemAgendaSimulado()

    assert agente.link_agendamento("v1", "c1") is None
    assert agente.entregar(_pacote()) is True
    assert agente.entregar(_pacote()) is True
    assert len(agente.entregues) == 1
    assert agente.resultados("empresa-a", "v1") == []
