"""Retorno depois da entrevista: o agente comunica o resultado da Nara, sem decidir nada."""

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from backend.contato.mensageiro import MensageiroSimulado
from backend.contratos.modelos import Convite
from tests.agente.apoio import PEDIDO_VAGA, TITULO_DE_TESTE, pedido_mandato, servico_de_teste

SESSAO = {"X-Empresa-Id": "empresa-retorno"}
SESSAO_DE_TESTE = {"X-Empresa-Id": "empresa-a"}


class MensageiroSemRetorno(MensageiroSimulado):
    """Envia convites, mas a primeira mensagem de retorno falha."""

    def __init__(self) -> None:
        super().__init__()
        self.falhas_de_retorno = 1

    def enviar(self, convite: Convite) -> bool:
        if convite.id.endswith(":retorno") and self.falhas_de_retorno > 0:
            self.falhas_de_retorno -= 1
            return False
        return super().enviar(convite)


def _vaga_com_aceite(
    cliente: TestClient, pedido_vaga: dict, sessao: dict = SESSAO, **politica
) -> tuple[str, dict]:
    vaga = cliente.post("/vagas", headers=sessao, json=pedido_vaga).json()["vaga"]["id"]
    assinado = cliente.post(
        f"/vagas/{vaga}/mandato", headers=sessao, json=pedido_mandato(**politica)
    )
    assert assinado.status_code == 201, assinado.text
    convites = cliente.get(f"/vagas/{vaga}/convites", headers=sessao).json()["itens"]
    convite = next(c for c in convites if c["estado"] == "aguardando")
    aceite = cliente.post(
        f"/convites/{convite['id']}/resposta",
        headers=sessao,
        json={"vaga_id": vaga, "tipo": "aceite", "chave_idempotencia": "a1"},
    )
    assert aceite.status_code == 200, aceite.text
    return vaga, convite


def _acompanhar(cliente: TestClient, vaga: str, chave: str = "e1", sessao: dict = SESSAO):
    return cliente.post(
        f"/vagas/{vaga}/retornos", headers=sessao, json={"chave_idempotencia": chave}
    )


@pytest.fixture
def demo(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "demo.db")))


@pytest.fixture
def vaga_demo(demo) -> tuple[str, dict, dict]:
    modelo = demo.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga, convite = _vaga_com_aceite(demo, modelo, aceitar_declarada=True)
    return vaga, convite, modelo


def test_quem_aceitou_recebe_o_retorno_da_entrevista(demo, vaga_demo):
    vaga, convite, modelo = vaga_demo

    resposta = _acompanhar(demo, vaga)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["simulado"] is True
    [retorno] = corpo["itens"]
    assert retorno["candidato_id"] == convite["candidato_id"]
    assert retorno["enviado"] is True
    assert retorno["simulado"] is True
    assert isinstance(retorno["aprovado"], bool)
    assert modelo["titulo"] in retorno["mensagem"]
    assert "{nome}" not in retorno["mensagem"]
    assert "Pessoa Fictícia" in retorno["mensagem"]


def test_o_retorno_aparece_no_convite(demo, vaga_demo):
    vaga, convite, _ = vaga_demo
    _acompanhar(demo, vaga)

    itens = demo.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]

    atual = next(c for c in itens if c["id"] == convite["id"])
    assert atual["retorno"]["enviado"] is True
    outros = [c for c in itens if c["id"] != convite["id"]]
    assert all(c["retorno"] is None for c in outros)


def test_o_retorno_nao_leva_nota_e_o_texto_nao_vai_aos_eventos(demo, vaga_demo):
    vaga, _, _ = vaga_demo

    [retorno] = _acompanhar(demo, vaga).json()["itens"]

    assert "notas" not in retorno
    eventos = demo.get(f"/vagas/{vaga}/eventos?limite=100", headers=SESSAO).json()["itens"]
    assert any(e["etapa"] == "pos_entrevista" for e in eventos)
    assert retorno["mensagem"] not in str(eventos)


def test_acompanhar_de_novo_nao_manda_outra_mensagem(demo, vaga_demo):
    vaga, _, _ = vaga_demo

    primeira = _acompanhar(demo, vaga, chave="e1").json()["itens"]
    segunda = _acompanhar(demo, vaga, chave="e2").json()["itens"]

    assert primeira == segunda
    eventos = demo.get(f"/vagas/{vaga}/eventos?limite=100", headers=SESSAO).json()["itens"]
    assert sum(e["etapa"] == "pos_entrevista" for e in eventos) == 1


def test_sem_entrega_nao_ha_retorno(demo):
    modelo = demo.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = demo.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    demo.post(f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True))

    resposta = _acompanhar(demo, vaga)

    assert resposta.status_code == 200
    assert resposta.json()["itens"] == []


def test_vaga_sem_mandato_nao_acompanha(demo):
    modelo = demo.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = demo.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]

    resposta = _acompanhar(demo, vaga)

    assert resposta.status_code == 409


def test_sem_redator_o_retorno_usa_texto_neutro(tmp_path):
    cliente = TestClient(criar_app(servico_de_teste(tmp_path / "agente.db")))
    vaga, _ = _vaga_com_aceite(cliente, PEDIDO_VAGA, SESSAO_DE_TESTE)

    [retorno] = _acompanhar(cliente, vaga, sessao=SESSAO_DE_TESTE).json()["itens"]

    assert retorno["enviado"] is True
    assert TITULO_DE_TESTE in retorno["mensagem"]
    assert "aprovad" not in retorno["mensagem"].lower()


def test_retorno_que_nao_saiu_e_reenviado_depois(tmp_path):
    cliente = TestClient(
        criar_app(servico_de_teste(tmp_path / "agente.db", mensageiro=MensageiroSemRetorno()))
    )
    vaga, _ = _vaga_com_aceite(cliente, PEDIDO_VAGA, SESSAO_DE_TESTE)

    [primeira] = _acompanhar(cliente, vaga, "e1", SESSAO_DE_TESTE).json()["itens"]
    [segunda] = _acompanhar(cliente, vaga, "e2", SESSAO_DE_TESTE).json()["itens"]

    assert primeira["enviado"] is False
    assert segunda["enviado"] is True
