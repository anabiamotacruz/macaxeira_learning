from backend.contato import conversa, email_inicial, mensageiro, pos_entrevista, prompts, recontato


def test_aviso_de_simulacao_tem_uma_fonte_so():
    assert mensageiro.AVISO_SIMULACAO is prompts.AVISO_SIMULACAO
    assert pos_entrevista.AVISO_SIMULACAO is prompts.AVISO_SIMULACAO


def test_modulos_nao_repetem_o_texto_do_aviso():
    for modulo in (conversa, email_inicial, recontato, mensageiro, pos_entrevista):
        codigo = open(modulo.__file__, encoding="utf-8").read()
        assert prompts.AVISO_SIMULACAO not in codigo, modulo.__name__
