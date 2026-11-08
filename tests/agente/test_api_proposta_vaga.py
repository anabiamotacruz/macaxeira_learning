"""O agente propõe os critérios a partir da descrição; a pessoa revisa, cria e assina."""

from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.configuracao import ETAPA_CONFIGURACAO
from backend.agente.montagem import montar_com_modelo, montar_demo
from backend.contratos.simulacoes import ClienteModeloSimulado
from backend.fontes.consultas import ETAPA_GERAR

SESSAO = {"X-Empresa-Id": "empresa-proposta"}
DESCRICAO = (
    "Procuramos pessoa desenvolvedora Python, presencial em São Paulo, com experiência em "
    "produção e SQL. Queremos 5 candidatos em 14 dias."
)
PROPOSTA = {
    "titulo": "Pessoa Desenvolvedora Python",
    "requisitos": [
        {
            "id": "presencial_sp",
            "descricao": "Disponibilidade para trabalho presencial em São Paulo",
            "campo": "presencial_sp",
            "valor_esperado": "sim",
        }
    ],
    "competencias": [{"nome": "Python", "peso": 0.7}, {"nome": "SQL", "peso": 0.3}],
    "meta_candidatos": 5,
    "prazo_dias": 14,
    "duvidas": [],
}


def _cliente(tmp_path, proposta: dict) -> TestClient:
    modelo = ClienteModeloSimulado(
        {ETAPA_CONFIGURACAO: proposta, ETAPA_GERAR: {"consultas": ["python"]}}
    )
    servico = montar_com_modelo(tmp_path / "a.db", cliente=modelo, medidor_gasto=lambda: 0.0)
    return TestClient(criar_app(servico))


def _propor(cliente: TestClient, descricao: str = DESCRICAO):
    return cliente.post("/vagas/proposta", headers=SESSAO, json={"descricao": descricao})


def test_agente_propoe_criterios_da_descricao(tmp_path):
    cliente = _cliente(tmp_path, PROPOSTA)

    resposta = _propor(cliente)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["pergunta"] is None
    vaga = corpo["proposta"]
    assert vaga["titulo"] == "Pessoa Desenvolvedora Python"
    assert vaga["descricao"] == DESCRICAO
    assert [r["id"] for r in vaga["requisitos"]] == ["presencial_sp"]
    assert {c["nome"] for c in vaga["competencias"]} == {"Python", "SQL"}
    assert vaga["meta_candidatos"] == 5


def test_proposta_pode_virar_vaga_pelo_post_de_sempre(tmp_path):
    cliente = _cliente(tmp_path, PROPOSTA)
    vaga = _propor(cliente).json()["proposta"]

    criada = cliente.post("/vagas", headers=SESSAO, json=vaga)

    assert criada.status_code == 201, criada.text
    assert criada.json()["estado"] == "aguardando_mandato"


def test_duvida_do_modelo_volta_como_observacao_junto_da_proposta(tmp_path):
    cliente = _cliente(tmp_path, {**PROPOSTA, "duvidas": ["Qual é a senioridade?"]})

    corpo = _propor(cliente).json()

    assert corpo["proposta"]["titulo"] == "Pessoa Desenvolvedora Python"
    assert corpo["pergunta"] is None
    assert corpo["observacoes"] == ["Qual é a senioridade?"]


def test_meta_e_prazo_ausentes_viram_padrao_na_api(tmp_path):
    cliente = _cliente(tmp_path, {**PROPOSTA, "meta_candidatos": None, "prazo_dias": None})

    corpo = _propor(cliente).json()

    assert (corpo["proposta"]["meta_candidatos"], corpo["proposta"]["prazo_dias"]) == (5, 14)
    assert len(corpo["observacoes"]) == 2


def test_descricao_vazia_vira_pergunta(tmp_path):
    corpo = _propor(_cliente(tmp_path, PROPOSTA), "   ").json()

    assert corpo["proposta"] is None
    assert corpo["pergunta"]


def test_sem_modelo_a_proposta_e_recusada_com_motivo(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    cliente = TestClient(criar_app(montar_demo(tmp_path / "a.db")))

    resposta = _propor(cliente)

    assert resposta.status_code == 409
    assert resposta.json()["erro"]["codigo"] == "proposta_sem_modelo"


def test_proposta_exige_sessao(tmp_path):
    cliente = _cliente(tmp_path, PROPOSTA)

    resposta = cliente.post("/vagas/proposta", json={"descricao": DESCRICAO})

    assert resposta.status_code == 401


def test_campos_para_eliminatorio_vem_do_banco(tmp_path):
    cliente = _cliente(tmp_path, PROPOSTA)

    corpo = cliente.get("/vagas/campos", headers=SESSAO).json()

    assert corpo["campos"]["presencial_sp"] == ["sim"]
    assert "email" not in corpo["campos"]
