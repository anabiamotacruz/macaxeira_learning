"""Sugestão de ajuste pela API: só alerta; nada muda na vaga sem uma pessoa."""

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.contratos.modelos import ResultadoEntrevista
from backend.contratos.simulacoes import ClienteNaraSimulado
from tests.agente.apoio import PEDIDO_VAGA, pedido_mandato, servico_de_teste

SESSAO = {"X-Empresa-Id": "empresa-a"}


class NaraComReprovacoes(ClienteNaraSimulado):
    """Devolve entrevistas em que todos reprovam no mesmo critério."""

    def __init__(self) -> None:
        super().__init__()
        self.vaga_id = ""

    def resultados(self, empresa_id: str, vaga_id: str) -> list[ResultadoEntrevista]:
        return [
            ResultadoEntrevista(
                empresa_id=empresa_id,
                vaga_id=vaga_id,
                candidato_id=f"c{i}",
                notas={"APIs": 0.2},
                aprovado=False,
            )
            for i in range(4)
        ]


@pytest.fixture
def vaga_e_cliente(tmp_path):
    def montar(destino):
        cliente = TestClient(criar_app(servico_de_teste(tmp_path / "a.db", destino=destino)))
        vaga = cliente.post("/vagas", headers=SESSAO, json=PEDIDO_VAGA).json()["vaga"]["id"]
        cliente.post(f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato())
        return cliente, vaga

    return montar


def test_reprovacao_repetida_vira_sugestao(vaga_e_cliente):
    cliente, vaga = vaga_e_cliente(NaraComReprovacoes())

    resposta = cliente.get(f"/vagas/{vaga}/ajuste", headers=SESSAO)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["simulado"] is True
    sugestao = corpo["sugestao"]
    assert "APIs" in sugestao["motivo"]
    assert sugestao["criterio"] == "APIs"
    assert sugestao["peso_atual"] == 1.0
    assert sugestao["peso_sugerido"] > 1.0
    assert sugestao["aplicada"] is False


def test_sem_padrao_nao_ha_sugestao(vaga_e_cliente):
    cliente, vaga = vaga_e_cliente(ClienteNaraSimulado())

    resposta = cliente.get(f"/vagas/{vaga}/ajuste", headers=SESSAO)

    assert resposta.status_code == 200
    assert resposta.json()["sugestao"] is None


def test_sugestao_nao_muda_a_vaga(vaga_e_cliente):
    cliente, vaga = vaga_e_cliente(NaraComReprovacoes())
    antes = cliente.get(f"/vagas/{vaga}", headers=SESSAO).json()["vaga"]

    cliente.get(f"/vagas/{vaga}/ajuste", headers=SESSAO)

    assert cliente.get(f"/vagas/{vaga}", headers=SESSAO).json()["vaga"] == antes


def test_outra_empresa_nao_ve_a_sugestao(vaga_e_cliente):
    cliente, vaga = vaga_e_cliente(NaraComReprovacoes())

    resposta = cliente.get(f"/vagas/{vaga}/ajuste", headers={"X-Empresa-Id": "outra"})

    assert resposta.status_code == 404
