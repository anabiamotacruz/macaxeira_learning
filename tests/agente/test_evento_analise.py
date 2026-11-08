"""O diário do agente mostra cada análise concluída, para a vaga não parecer parada."""

from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import montar_demo
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-diario"}


def _vaga(tmp_path, monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    cliente = TestClient(criar_app(montar_demo(tmp_path / "demo.db")))
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    return cliente, vaga


def _eventos(cliente, vaga) -> list[dict]:
    return cliente.get(f"/vagas/{vaga}/eventos?limite=100", headers=SESSAO).json()["itens"]


def test_cada_analise_concluida_vira_um_evento(tmp_path, monkeypatch):
    cliente, vaga = _vaga(tmp_path, monkeypatch)

    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]
    analises = [e for e in _eventos(cliente, vaga) if e["etapa"] == "analise"]

    assert resumo["analisados"] > 0
    assert len(analises) == resumo["analisados"]
    assert all(e["candidato_id"] for e in analises)
    assert analises[-1]["mensagem"].endswith(f"({resumo['analisados']} até agora)")


def test_evento_de_analise_nao_leva_texto_do_perfil(tmp_path, monkeypatch):
    cliente, vaga = _vaga(tmp_path, monkeypatch)
    itens = cliente.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    perfis = [i["candidato"].get("perfil_texto", "") for i in itens]

    analises = [e["mensagem"] for e in _eventos(cliente, vaga) if e["etapa"] == "analise"]

    assert analises
    assert not any(perfil and perfil[:40] in mensagem for perfil in perfis for mensagem in analises)
