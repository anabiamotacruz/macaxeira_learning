from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.contratos.modelos import (
    Candidato,
    Convite,
    Decisao,
    EstadoBanco,
    PacoteNara,
    TipoConvite,
    TipoDecisao,
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
        "link_nara": "https://nara.simulada.local/agendar/v1/c1",
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
    assert PacoteNara(**_pacote()).chave_idempotencia

    sem_chave = _pacote()
    del sem_chave["chave_idempotencia"]
    with pytest.raises(ValidationError):
        PacoteNara(**sem_chave)

    with pytest.raises(ValidationError):
        PacoteNara(**_pacote(chave_idempotencia=""))


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
