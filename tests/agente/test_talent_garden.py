"""Talent Garden: o agente sugere, o RH confirma. Quem pediu para sair nunca entra."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.fluxo import (
    GARDEN_ALEM_DO_ENCAMINHAMENTO,
    GARDEN_NAO_AGORA,
    eh_nao_agora,
)
from backend.agente.montagem import montar_demo
from backend.contratos.modelos import DestinoPessoa, RespostaCandidato, TipoResposta
from tests.agente.apoio import candidato_exemplo, pedido_mandato
from tests.agente.test_fluxo import (
    Montagem,
    _assinar_fluxo,
    _convites_por_candidato,
    _dois_candidatos,
)


def _recusar(fluxo, m: Montagem, candidato_id: str, texto: str) -> None:
    convite_id = _convites_por_candidato(m)[candidato_id]
    fluxo.registrar_resposta(
        RespostaCandidato(convite_id=convite_id, tipo=TipoResposta.RECUSA, texto=texto)
    )


@pytest.mark.parametrize(
    "texto",
    [
        "Agora não posso, mas quem sabe mais para frente",
        "No momento não, estou terminando um projeto",
        "Daqui a uns meses eu topo",
        "Talvez depois, numa próxima oportunidade",
    ],
)
def test_reconhece_nao_agora(texto: str) -> None:
    assert eh_nao_agora(texto)


@pytest.mark.parametrize("texto", ["Não tenho interesse", "Não, obrigado", ""])
def test_recusa_definitiva_nao_e_nao_agora(texto: str) -> None:
    assert not eh_nao_agora(texto)


def test_nao_agora_vira_sugestao_de_talent_garden(tmp_path: Path) -> None:
    m = Montagem(tmp_path, _dois_candidatos())
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo)

    _recusar(fluxo, m, "c1", "Agora não, mas daqui a uns meses sim")

    [item] = fluxo.talent_garden()
    assert item.candidato_id == "c1"
    assert item.motivo == GARDEN_NAO_AGORA
    assert item.confirmado is False
    assert item.simulado is True
    assert any(e.etapa == "talent_garden" for e in fluxo.eventos)


def test_texto_da_pessoa_nao_vai_ao_evento(tmp_path: Path) -> None:
    m = Montagem(tmp_path, _dois_candidatos())
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo)

    _recusar(fluxo, m, "c1", "Agora não, estou de licença médica")

    assert all("licença" not in e.mensagem for e in fluxo.eventos)


def test_recusa_definitiva_nao_entra_no_garden(tmp_path: Path) -> None:
    m = Montagem(tmp_path, _dois_candidatos())
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo)

    _recusar(fluxo, m, "c1", "Não tenho interesse")

    assert fluxo.talent_garden() == []


def test_nao_agora_recebe_resposta_com_saida(tmp_path: Path) -> None:
    m = Montagem(tmp_path, _dois_candidatos())
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo)

    _recusar(fluxo, m, "c1", "Agora não")

    [resposta] = [c for c in m.mensageiro.enviados.values() if ":garden" in c.id]
    assert resposta.candidato_id == "c1"
    assert "SAIR" in resposta.mensagem
    assert resposta.link_agendamento is None


def test_rh_confirma_e_o_item_fica_confirmado(tmp_path: Path) -> None:
    m = Montagem(tmp_path, _dois_candidatos())
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo)
    _recusar(fluxo, m, "c1", "Agora não")

    fluxo.registrar_destino("c1", DestinoPessoa.TALENT_GARDEN, "Ana Recrutadora")

    [item] = fluxo.talent_garden()
    assert item.confirmado is True


def test_opt_out_sai_do_garden(tmp_path: Path) -> None:
    m = Montagem(tmp_path, _dois_candidatos())
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo)
    _recusar(fluxo, m, "c1", "Agora não")

    convite_id = _convites_por_candidato(m)["c1"]
    fluxo.registrar_resposta(RespostaCandidato(convite_id=convite_id, tipo=TipoResposta.OPT_OUT))

    assert fluxo.talent_garden() == []


def test_quem_passa_do_encaminhamento_e_sugerido_ao_garden(tmp_path: Path) -> None:
    candidatos = [candidato_exemplo(f"c{i}") for i in range(1, 4)]
    m = Montagem(tmp_path, candidatos)
    fluxo = m.fluxo()

    _assinar_fluxo(fluxo, max_indicacoes=1)

    sugeridos = {i.candidato_id: i.motivo for i in fluxo.talent_garden()}
    assert sugeridos
    assert set(sugeridos.values()) == {GARDEN_ALEM_DO_ENCAMINHAMENTO}


# ---------- API ----------

SESSAO = {"X-Empresa-Id": "empresa-garden"}


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "garden.db")))


def _vaga(cliente: TestClient) -> str:
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    resposta = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    assert resposta.status_code == 201, resposta.text
    return vaga


def test_api_lista_o_garden_e_o_rh_confirma(cliente: TestClient) -> None:
    vaga = _vaga(cliente)
    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    convite = next(c for c in convites if c["estado"] == "aguardando")
    resposta = cliente.post(
        f"/convites/{convite['id']}/resposta",
        headers=SESSAO,
        json={
            "vaga_id": vaga,
            "tipo": "recusa",
            "texto": "Agora não, talvez mais para frente",
            "chave_idempotencia": "nao-agora-1",
        },
    )
    assert resposta.status_code == 200, resposta.text

    garden = cliente.get(f"/vagas/{vaga}/talent-garden", headers=SESSAO)
    assert garden.status_code == 200, garden.text
    corpo = garden.json()
    assert corpo["simulado"] is True
    item = next(i for i in corpo["itens"] if i["candidato_id"] == convite["candidato_id"])
    assert item["motivo"] == GARDEN_NAO_AGORA
    assert item["confirmado"] is False

    confirmado = cliente.post(
        f"/candidatos/{convite['candidato_id']}/destino",
        headers=SESSAO,
        json={
            "vaga_id": vaga,
            "destino": "talent_garden",
            "responsavel": "Ana Recrutadora",
            "chave_idempotencia": "garden-1",
        },
    )
    assert confirmado.status_code in (200, 201), confirmado.text
    depois = cliente.get(f"/vagas/{vaga}/talent-garden", headers=SESSAO).json()["itens"]
    item = next(i for i in depois if i["candidato_id"] == convite["candidato_id"])
    assert item["confirmado"] is True


def test_api_garden_de_outra_empresa_nao_aparece(cliente: TestClient) -> None:
    vaga = _vaga(cliente)

    alheia = cliente.get(f"/vagas/{vaga}/talent-garden", headers={"X-Empresa-Id": "outra"})

    assert alheia.status_code == 404
