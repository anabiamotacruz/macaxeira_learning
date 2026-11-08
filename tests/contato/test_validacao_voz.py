"""Validação do escopo: e-mail, áudio da pessoa e link de quem entrevista.

Sem chave de Deepgram, ElevenLabs ou Featherless. A voz é simulada.
"""

from datetime import timedelta

import pytest

from backend.contato.voz import (
    SintetizadorSimulado,
    VozIndisponivel,
    audio_simulado,
    reconhecedor_do_ambiente,
    sintetizador_do_ambiente,
)
from backend.contato.whatsapp import webhook_audio
from backend.contratos.simulacoes import ClienteNaraSimulado
from tests.contato.test_whatsapp import NUMERO, Cenario

AVISO_AUDIO = "Recebi um áudio e não consegui ouvir. Pode escrever a mensagem?"


def test_sem_voz_real_a_chave_nao_liga_provedor():
    ambiente = {"DEEPGRAM_API_KEY": "chave-de-teste", "ELEVENLABS_API_KEY": "chave-de-teste"}

    assert reconhecedor_do_ambiente(ambiente).provedor == "simulado"
    assert sintetizador_do_ambiente(ambiente) is None


def test_voz_real_sem_implementacao_nao_chama_rede():
    with pytest.raises(VozIndisponivel, match="reconhecimento real") as erro:
        reconhecedor_do_ambiente({"VOZ_REAL": "1", "DEEPGRAM_API_KEY": "chave-de-teste"})

    assert "chave-de-teste" not in str(erro.value)


def test_email_explica_a_origem_e_pede_que_a_pessoa_escreva():
    cenario = Cenario()
    texto = f"{cenario.email.convite.mensagem}\n{cenario.email.link_whatsapp}"

    assert "seu site pessoal" in texto
    assert "SAIR" in texto
    assert cenario.email.link_whatsapp.startswith("https://wa.me/5581900000000?text=Vaga%20")


def _falar(cenario: Cenario, texto: str) -> list[str]:
    cenario.relogio += timedelta(minutes=1)
    return cenario.atendente.atender(
        webhook_audio(NUMERO, audio_simulado(texto), cenario.relogio)
    )


def test_audio_da_pessoa_abre_a_conversa_e_a_resposta_sai_em_voz():
    cenario = Cenario(agente=ClienteNaraSimulado())
    voz = SintetizadorSimulado()
    cenario.atendente.sintetizador = voz

    respostas = _falar(cenario, f"Vaga {cenario.email.codigo}")

    assert "Backend Python" in respostas[0]
    entrada = cenario.canal.mensagens(NUMERO)[0]
    assert entrada.midia == "voz"
    assert entrada.provedor_voz == "simulado"
    assert entrada.simulado is True
    saida = cenario.canal.mensagens(NUMERO)[1]
    assert saida.direcao == "saida"
    assert saida.midia == "voz"
    assert saida.provedor_voz == "simulado"
    assert voz.falas[0] == respostas[0]


def test_audio_ilegivel_nao_abre_pre_triagem():
    cenario = Cenario()
    cenario.relogio += timedelta(minutes=1)

    respostas = cenario.atendente.atender(webhook_audio(NUMERO, b"nao-e-audio", cenario.relogio))

    assert respostas == [AVISO_AUDIO]
    assert cenario.atendente.pre_triagem(NUMERO) is None


def test_quem_confirma_recebe_o_link_de_agendamento():
    cenario = Cenario(agente=ClienteNaraSimulado())
    cenario.comecar()
    roteiro = cenario.atendente.pre_triagem(NUMERO)
    assert roteiro is not None
    respostas: list[str] = []
    for _ in roteiro.perguntas:
        respostas = cenario.escrever("sim")

    assert roteiro.resultado.value == "aprovado"
    assert "https://nara.simulada.local/agendar/v1/c1" in respostas[-1]
    assert cenario.aprovados


def test_nao_agora_nao_vira_aprovacao_nem_recusa():
    cenario = Cenario()
    cenario.comecar()

    respostas = cenario.escrever("não agora")

    pre = cenario.atendente.pre_triagem(NUMERO)
    assert pre is not None
    assert pre.resultado.value == "em_andamento"
    assert pre.link_agendamento is None
    assert "sim ou não" in respostas[0].lower()


def test_quem_nao_passa_fica_sem_link_e_pode_ir_ao_banco():
    cenario = Cenario(agente=ClienteNaraSimulado())
    cenario.comecar()

    respostas = cenario.escrever("não")

    pre = cenario.atendente.pre_triagem(NUMERO)
    assert pre is not None
    assert pre.resultado.value == "reprovado"
    assert pre.link_agendamento is None
    assert "BANCO" in respostas[0]
    assert "agendar" not in respostas[0]
