"""Contato pelo e-mail que a própria pessoa publicou: regras determinísticas, sem modelo."""

from datetime import date

import pytest

from backend.agente.contato_publicado import (
    contato_publicado,
    mensagem_pelo_contato_publicado,
    motivo_sem_contato,
)
from backend.agente.regras import (
    corte_de_autorizacao,
    externo_sem_autorizacao,
    pode_contatar,
    pode_contatar_pelo_publicado,
)
from backend.contato.prompts import AVISO_SIMULACAO, PALAVRA_SAIDA
from backend.contratos.modelos import EstadoBanco
from backend.fontes.provedores.modelos import CONTATO_NAO_PUBLICADO
from tests.agente.apoio import AnalisadorComEvidencias, candidato_exemplo, vaga_exemplo

HOJE = date(2026, 11, 8)
ORIGEM = "https://pessoa.exemplo.invalid/sobre"
EMAIL = "pessoa@exemplo.invalid"


def externo(candidato_id: str = "ext", **campos):
    atributos = campos.pop("atributos", {"python": "sim", "email": EMAIL})
    dados = {
        "fonte": "site_publico",
        "simulado": False,
        "origem": ORIGEM,
        "autorizacao_valida_ate": None,
        "autorizou_contato": False,
        "estado": EstadoBanco.PENDENTE,
        "atributos": atributos,
    }
    dados.update(campos)
    return candidato_exemplo(candidato_id, **dados)


def test_externo_sem_autorizacao_e_reconhecido():
    assert externo_sem_autorizacao(externo())
    assert corte_de_autorizacao(externo(), HOJE) is None


@pytest.mark.parametrize(
    "campos",
    [
        {"simulado": True},
        {"opt_out": True},
        {"estado": EstadoBanco.REMOVIDO},
        {"estado": EstadoBanco.EXPIRADO},
        {"autorizou_contato": True, "autorizacao_valida_ate": date(2026, 11, 1)},
    ],
)
def test_opt_out_remocao_e_vencida_nao_sao_externo_sem_autorizacao(campos):
    candidato = externo(**campos)

    assert not externo_sem_autorizacao(candidato)
    assert corte_de_autorizacao(candidato, HOJE) is not None


def test_email_publicado_pela_pessoa_vira_contato_com_origem():
    contato = contato_publicado(externo())

    assert contato is not None
    assert contato.endereco == EMAIL
    assert contato.url_origem == ORIGEM
    assert contato.publicado_para_contato


def test_email_inferido_ou_de_provedor_nunca_e_usado():
    inferido = externo(atributos={"email": EMAIL, "contato_origem": CONTATO_NAO_PUBLICADO})

    assert contato_publicado(inferido) is None
    assert motivo_sem_contato(inferido) == "contato_nao_publicado"


def test_email_de_item_inferido_nunca_e_usado():
    inferido = externo(atributos={"email": EMAIL, "confianca": "inferido"})

    assert contato_publicado(inferido) is None


def test_sem_email_publicado_o_motivo_fica_registrado():
    sem_email = externo(atributos={"python": "sim"})

    assert contato_publicado(sem_email) is None
    assert motivo_sem_contato(sem_email) == "contato_nao_publicado"


def test_email_sem_url_de_origem_nao_serve():
    sem_origem = externo(origem="site_publico")

    assert contato_publicado(sem_origem) is None
    assert motivo_sem_contato(sem_origem) == "contato_sem_origem"


def test_pode_contatar_pelo_publicado_so_com_contato_e_dentro_do_limite():
    vaga = vaga_exemplo(max_tentativas_contato=5)
    candidato = externo()

    assert not pode_contatar(candidato, 0, vaga, HOJE)
    assert pode_contatar_pelo_publicado(candidato, 0, vaga, tem_contato_publicado=True)
    assert pode_contatar_pelo_publicado(candidato, 1, vaga, tem_contato_publicado=True)
    assert not pode_contatar_pelo_publicado(candidato, 2, vaga, tem_contato_publicado=True)
    assert not pode_contatar_pelo_publicado(candidato, 0, vaga, tem_contato_publicado=False)
    assert not pode_contatar_pelo_publicado(
        externo(opt_out=True), 0, vaga, tem_contato_publicado=True
    )


def test_mensagem_diz_de_onde_veio_o_contato_por_que_e_como_sair():
    vaga = vaga_exemplo()
    candidato = externo()
    analise = AnalisadorComEvidencias().analisar(vaga, candidato)
    contato = contato_publicado(candidato)

    mensagem = mensagem_pelo_contato_publicado(vaga, candidato, analise, contato, None, 1)

    assert ORIGEM in mensagem
    assert "Por que você recebeu" in mensagem
    assert vaga.titulo in mensagem
    assert PALAVRA_SAIDA in mensagem
    assert "Não quero mais contato" in mensagem
    assert AVISO_SIMULACAO in mensagem
    assert candidato.nome in mensagem
    assert "{nome}" not in mensagem


def test_lembrete_pelo_contato_publicado_mantem_origem_e_saida():
    vaga = vaga_exemplo()
    candidato = externo()
    analise = AnalisadorComEvidencias().analisar(vaga, candidato)

    mensagem = mensagem_pelo_contato_publicado(
        vaga, candidato, analise, contato_publicado(candidato), "https://agenda.invalid/x", 2
    )

    assert "único lembrete" in mensagem
    assert ORIGEM in mensagem
    assert PALAVRA_SAIDA in mensagem
    assert "https://agenda.invalid/x" in mensagem
