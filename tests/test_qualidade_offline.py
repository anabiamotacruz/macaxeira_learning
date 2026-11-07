import pytest

from evals.qualidade_offline import (
    DecisaoHumana,
    FluxoFalso,
    PoliticaRetry,
    ProvedorFalso,
    ProvedorIndisponivel,
    RespostaInvalida,
    exigir_decisao_humana,
    obter_com_retry,
    validar_recomendacao,
    validar_resposta_modelo,
    validar_rubrica,
)


def rubrica_com_n(quantidade: int, peso: int = 3) -> dict:
    return {
        "criterios": [
            {
                "id": f"c-{indice}",
                "dimensao": "competencia",
                "eliminatorio": False,
                "peso": peso,
            }
            for indice in range(quantidade)
        ]
    }


def test_rejeita_json_invalido_e_campos_ausentes():
    # Protege contra decisões baseadas em uma resposta de modelo ilegível ou incompleta.
    with pytest.raises(RespostaInvalida, match="JSON inválido"):
        validar_resposta_modelo("{")
    with pytest.raises(RespostaInvalida, match="campo ausente"):
        validar_resposta_modelo('{"criterios": [{"id": "x"}]}')


@pytest.mark.parametrize("peso", [0, 6, 3.5])
def test_rejeita_peso_fora_de_1_a_5(peso):
    # Protege a comparabilidade da rubrica e impede pesos que contornem a regra aprovada.
    with pytest.raises(RespostaInvalida, match="peso"):
        validar_rubrica(rubrica_com_n(4, peso))


@pytest.mark.parametrize("quantidade", [3, 9])
def test_rejeita_rubrica_fora_do_limite_de_criterios(quantidade):
    # Protege contra avaliações subespecificadas ou grandes demais para auditoria humana.
    with pytest.raises(RespostaInvalida, match="4 e 8"):
        validar_rubrica(rubrica_com_n(quantidade))


def test_repete_timeout_e_erro_do_provedor_ate_o_limite():
    # Protege a execução contra uma falha transitória sem chamar rede ou modelo real.
    provedor = ProvedorFalso(
        [TimeoutError("tempo esgotado"), ProvedorIndisponivel("indisponível"), '{"ok": true}']
    )
    assert obter_com_retry(provedor) == '{"ok": true}'
    assert provedor.chamadas == 3


def test_para_apos_tres_falhas_recuperaveis():
    # Protege custo e latência ao impedir retries infinitos em um provedor indisponível.
    provedor = ProvedorFalso([TimeoutError("1"), TimeoutError("2"), TimeoutError("3")])
    with pytest.raises(TimeoutError):
        obter_com_retry(provedor, PoliticaRetry(max_tentativas=3))
    assert provedor.chamadas == 3


def test_opt_out_nunca_chega_ao_passo_de_convite():
    # Protege o direito de saída e evita contato proibido.
    fluxo = FluxoFalso()
    fluxo.analisar_e_convidar(
        {"id": "c-opt-out", "opt_out": True, "autorizacao_contato": True}
    )
    assert fluxo.convites == []


def test_recomendacao_sem_evidencia_falha():
    # Protege contra indicação sem explicação verificável para o recrutador.
    with pytest.raises(RespostaInvalida, match="evidencia"):
        validar_recomendacao({"candidato_id": "c-1", "evidencias": []})


def test_decisao_sem_registro_humano_falha():
    # Protege o princípio de humano no controle sobre decisões relativas a pessoas.
    with pytest.raises(RespostaInvalida, match="decisão humana"):
        exigir_decisao_humana("c-1", None)


def test_decisao_humana_registrada_e_aceita():
    # Protege a rastreabilidade quando uma pessoa autoriza o resultado do fluxo.
    decisao = DecisaoHumana("c-1", "revisar", "Caso ambíguo")
    assert exigir_decisao_humana("c-1", decisao) is decisao


@pytest.mark.xfail(
    reason="PENDENTE: integrar este contrato ao fluxo real do agente quando a frente do agente entregar o adaptador"
)
def test_fluxo_real_deve_bloquear_opt_out():
    # Protege a integração ponta a ponta; permanece pendente enquanto o agente não existe.
    raise NotImplementedError
