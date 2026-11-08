"""Testes da classificação de canal e da cobertura do conjunto."""

from datetime import date

import pytest

from avaliacoes.canal import (
    CHAVE_DE_ENDERECO,
    CHAVE_DE_URL_DE_ORIGEM,
    SituacaoCanal,
    contato_do_candidato,
    medir_cobertura,
    situacao_do_candidato,
)
from avaliacoes.casos import Caso, Particao, carregar_casos
from backend.contato.email_inicial import ContatoBloqueado, _conferir_contato
from backend.contato.supressao import ListaSupressao
from backend.contratos.modelos import EstadoBanco
from backend.contratos.simulacoes import candidato_simulado

HOJE = date(2026, 11, 7)
URL_PUBLICADA = "https://exemplo.invalid/pessoa-000/contato"


@pytest.fixture(scope="module")
def casos():
    return carregar_casos()


@pytest.fixture(scope="module")
def vaga(casos):
    return casos[0].vaga


def _candidato(**atributos):
    """Candidato ativo e autorizado; os atributos decidem o canal."""
    return candidato_simulado("pessoa-000", "empresa-demo-1", atributos=atributos)


def _caso(vaga, candidato, identificador="caso-000") -> Caso:
    return Caso(
        id_caso=identificador,
        cenario="perfil_solido",
        particao=Particao.AJUSTE,
        grupo=f"{candidato.empresa_id}:{candidato.id}",
        vaga=vaga,
        candidato=candidato,
        elegivel_esperado=True,
        hoje=HOJE,
    )


def test_endereco_com_url_de_origem_e_canal_publicado():
    candidato = _candidato(
        **{CHAVE_DE_ENDERECO: "pessoa@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
    )
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.PUBLICADO


def test_email_sozinho_nao_e_canal_publicado():
    """O endereço sem a URL de onde a pessoa o publicou não autoriza contato."""
    candidato = _candidato(**{CHAVE_DE_ENDERECO: "pessoa@example.invalid"})
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.ENDERECO_SEM_ORIGEM


def test_url_de_origem_em_branco_nao_conta():
    candidato = _candidato(
        **{CHAVE_DE_ENDERECO: "pessoa@example.invalid", CHAVE_DE_URL_DE_ORIGEM: "   "}
    )
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.ENDERECO_SEM_ORIGEM


def test_sem_atributo_de_email_nao_ha_endereco():
    assert situacao_do_candidato(_candidato(), hoje=HOJE) is SituacaoCanal.SEM_ENDERECO


def test_endereco_em_branco_conta_como_sem_endereco():
    candidato = _candidato(**{CHAVE_DE_ENDERECO: "  ", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA})
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.SEM_ENDERECO


def test_opt_out_tem_precedencia_sobre_o_canal_publicado():
    candidato = _candidato(
        **{CHAVE_DE_ENDERECO: "pessoa@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
    ).model_copy(update={"opt_out": True})
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.SUPRIMIDO


def test_sem_autorizacao_tem_precedencia_sobre_o_canal():
    candidato = _candidato(
        **{CHAVE_DE_ENDERECO: "pessoa@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
    ).model_copy(
        update={
            "autorizou_contato": False,
            "autorizacao_valida_ate": None,
            "estado": EstadoBanco.PENDENTE,
        }
    )
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.SUPRIMIDO


def test_autorizacao_vencida_tem_precedencia_sobre_a_falta_de_endereco():
    """Quem já saiu da busca não entra na conta de quem não tem canal."""
    candidato = _candidato().model_copy(
        update={"autorizacao_valida_ate": date(2026, 11, 6), "estado": EstadoBanco.EXPIRADO}
    )
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.SUPRIMIDO


def test_autorizacao_que_vence_hoje_ainda_vale():
    candidato = _candidato(
        **{CHAVE_DE_ENDERECO: "pessoa@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
    ).model_copy(update={"autorizacao_valida_ate": HOJE})
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.PUBLICADO


def test_estado_removido_e_suprimido():
    candidato = _candidato(
        **{CHAVE_DE_ENDERECO: "pessoa@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
    ).model_copy(update={"estado": EstadoBanco.REMOVIDO})
    assert situacao_do_candidato(candidato, hoje=HOJE) is SituacaoCanal.SUPRIMIDO


def test_contato_do_candidato_sem_endereco_e_nulo():
    assert contato_do_candidato(_candidato()) is None


def test_contato_do_candidato_nao_inventa_origem():
    candidato = _candidato(**{CHAVE_DE_ENDERECO: "pessoa@example.invalid"})
    contato = contato_do_candidato(candidato)
    assert contato is not None
    assert contato.endereco == "pessoa@example.invalid"
    assert contato.url_origem == ""
    assert contato.publicado_para_contato is False


def test_o_portao_real_recusa_quem_so_tem_email(casos):
    """O código de produção, não o arnês, é quem recusa o contato.

    Pega um candidato do gerador sintético, monta o contato com o que o perfil
    oferece de fato e chama a conferência que roda antes de todo e-mail.
    """
    candidato = next(caso.candidato for caso in casos if caso.cenario == "perfil_solido")
    assert candidato.atributos.get(CHAVE_DE_ENDERECO)
    contato = contato_do_candidato(candidato)
    assert contato is not None
    with pytest.raises(ContatoBloqueado) as erro:
        _conferir_contato(candidato.empresa_id, contato, ListaSupressao(b"segredo-de-teste"))
    assert erro.value.regra == "contato_nao_publicado"


def test_o_portao_real_aceita_quem_tem_url_de_origem():
    candidato = _candidato(
        **{CHAVE_DE_ENDERECO: "pessoa@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
    )
    contato = contato_do_candidato(candidato)
    assert contato is not None
    _conferir_contato(candidato.empresa_id, contato, ListaSupressao(b"segredo-de-teste"))


def test_conjunto_vazio_tem_taxa_nula():
    cobertura = medir_cobertura([], hoje=HOJE)
    assert cobertura.total == 0
    assert cobertura.considerados == 0
    assert cobertura.taxa_de_canal_publicado.valor is None
    assert cobertura.taxa_de_canal_publicado.casos == 0
    assert cobertura.taxa_de_canal_publicado.wilson_inferior is None


def test_cobertura_soma_as_situacoes_e_fecha_o_total(vaga):
    pessoas = [
        _candidato(
            **{CHAVE_DE_ENDERECO: "a@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
        ),
        _candidato(**{CHAVE_DE_ENDERECO: "b@example.invalid"}),
        _candidato(),
        _candidato().model_copy(update={"opt_out": True}),
    ]
    casos = [
        _caso(vaga, pessoa.model_copy(update={"id": f"pessoa-{i:03d}"}), f"caso-{i:03d}")
        for i, pessoa in enumerate(pessoas)
    ]
    cobertura = medir_cobertura(casos, hoje=HOJE)
    assert cobertura.por_situacao == {
        SituacaoCanal.PUBLICADO: 1,
        SituacaoCanal.ENDERECO_SEM_ORIGEM: 1,
        SituacaoCanal.SEM_ENDERECO: 1,
        SituacaoCanal.SUPRIMIDO: 1,
    }
    assert cobertura.casos_lidos == 4
    assert cobertura.total == 4
    assert cobertura.considerados == 3
    assert cobertura.taxa_de_canal_publicado.casos == 3
    assert cobertura.taxa_de_canal_publicado.valor == pytest.approx(1 / 3)


def test_denominador_ignora_quem_esta_suprimido(vaga):
    """Suprimido não entra nem como numerador nem como denominador."""
    publicado = _candidato(
        **{CHAVE_DE_ENDERECO: "a@example.invalid", CHAVE_DE_URL_DE_ORIGEM: URL_PUBLICADA}
    )
    suprimidos = [
        publicado.model_copy(update={"id": "pessoa-001", "opt_out": True}),
        publicado.model_copy(update={"id": "pessoa-002", "autorizou_contato": False}),
    ]
    casos = [
        _caso(vaga, pessoa, f"caso-{i:03d}")
        for i, pessoa in enumerate([publicado, *suprimidos])
    ]
    cobertura = medir_cobertura(casos, hoje=HOJE)
    assert cobertura.total == 3
    assert cobertura.considerados == 1
    assert cobertura.taxa_de_canal_publicado.valor == 1.0
    assert cobertura.taxa_de_canal_publicado.casos == 1


def test_cobertura_conta_cada_pessoa_uma_vez(casos):
    """A duplicata do gerador é a mesma pessoa e não pode dobrar o denominador."""
    cobertura = medir_cobertura(casos)
    duplicatas = sum(1 for caso in casos if caso.cenario == "duplicata")
    assert duplicatas > 0
    assert cobertura.casos_lidos == len(casos)
    assert cobertura.total == len({caso.grupo for caso in casos})
    assert cobertura.total == len(casos) - duplicatas


def test_cobertura_do_conjunto_sintetico_nao_tem_canal_publicado(casos):
    cobertura = medir_cobertura(casos)
    assert cobertura.por_situacao[SituacaoCanal.PUBLICADO] == 0
    assert cobertura.por_situacao[SituacaoCanal.ENDERECO_SEM_ORIGEM] == cobertura.considerados
    assert cobertura.considerados > 0
    assert cobertura.taxa_de_canal_publicado.valor == 0.0


def test_hoje_explicito_vence_o_hoje_do_caso(casos):
    """Com uma data depois de toda validade, ninguém sobra para medir."""
    cobertura = medir_cobertura(casos, hoje=date(2030, 1, 1))
    assert cobertura.considerados == 0
    assert cobertura.taxa_de_canal_publicado.valor is None
