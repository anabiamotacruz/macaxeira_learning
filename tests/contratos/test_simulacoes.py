from datetime import date

import pytest
from pydantic import BaseModel

from backend.contratos import interfaces
from backend.contratos.erros import FonteIndisponivel, RespostaInvalida
from backend.contratos.modelos import (
    Convite,
    EstadoBanco,
    PacoteNara,
    TipoConvite,
    Vaga,
)
from backend.contratos.simulacoes import (
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
        link_nara="https://nara.simulada.local/agendar/v1/c1",
        chave_idempotencia=chave,
        simulado=True,
    )


def _pacote() -> PacoteNara:
    return PacoteNara(
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
        chave_idempotencia="empresa-a:v1:c1:entrega",
    )


def test_simulacoes_seguem_as_interfaces():
    pares = [
        (FonteSimulada([]), interfaces.FonteCandidatos),
        (BancoTalentosSimulado(hoje=HOJE), interfaces.BancoTalentos),
        (AnalisadorSimulado(), interfaces.Analisador),
        (RevisorSimulado(), interfaces.Revisor),
        (MensageiroSimulado(), interfaces.Mensageiro),
        (ClienteNaraSimulado(), interfaces.ClienteNara),
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

    resultados = nara.resultados("v1")
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
