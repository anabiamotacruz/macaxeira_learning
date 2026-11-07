import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult

from backend.agente import api
from backend.agente.mandato import ModoEntrega, Politica
from backend.agente.mcp import criar_servidor_mcp, main
from backend.agente.montagem import montar_demo
from backend.agente.servico import ServicoVagas
from backend.contratos.erros import ErroContrato
from backend.contratos.simulacoes import ClienteNaraSimulado
from tests.agente.apoio import (
    AGORA,
    PEDIDO_VAGA,
    CapturaRastro,
    NaraForaDoAr,
    Relogio,
    servico_de_teste,
)

EMPRESA = "empresa-a"
CANDIDATO = "verde"
PESSOA = "Pessoa Responsável Fictícia"
RAIZ = Path(__file__).resolve().parents[2]


def _chamar(servidor: Any, ferramenta: str, argumentos: dict[str, Any]) -> CallToolResult:
    async def chamar() -> CallToolResult:
        async with Client(servidor) as cliente:
            return await cliente.call_tool(ferramenta, argumentos)

    return asyncio.run(chamar())


def _texto(resultado: CallToolResult) -> str:
    return " ".join(bloco.text for bloco in resultado.content)


def _politica(modo: ModoEntrega = ModoEntrega.NA_DECISAO) -> Politica:
    return Politica(
        limiar_verde=0.8, piso_nota=0.5, max_indicacoes=2, max_ampliacoes=0, modo_entrega=modo
    )


class Cenario:
    """Uma vaga real, conduzida pelo serviço, e o servidor MCP da mesma empresa."""

    def __init__(self, caminho: Path, **pecas: Any) -> None:
        self.destino = pecas.setdefault("destino", ClienteNaraSimulado())
        self.relogio = pecas.setdefault("relogio", Relogio())
        self.servico: ServicoVagas = servico_de_teste(caminho, **pecas)
        self.vaga = self.servico.criar_vaga(EMPRESA, PEDIDO_VAGA).vaga.id
        self.servidor = criar_servidor_mcp(EMPRESA, self.servico)

    def assinar(self, modo: ModoEntrega = ModoEntrega.NA_DECISAO, **kwargs: Any) -> None:
        self.servico.assinar(
            EMPRESA, self.vaga, PESSOA, 5.0, _politica(modo), kwargs.get("valido_ate")
        )
        self.servico.executar(EMPRESA, self.vaga)

    def chamar(self, ferramenta: str, **argumentos: Any) -> CallToolResult:
        return _chamar(self.servidor, ferramenta, argumentos)


@pytest.fixture
def cenario(tmp_path: Path) -> Cenario:
    return Cenario(tmp_path / "agente.db")


def test_expoe_as_ferramentas_sem_empresa_nos_argumentos(cenario: Cenario) -> None:
    async def listar() -> list[Any]:
        async with Client(cenario.servidor) as cliente:
            return (await cliente.list_tools()).tools

    ferramentas = asyncio.run(listar())

    assert {f.name for f in ferramentas} == {
        "buscar_candidatos",
        "explicar_escolha",
        "entregar_candidatos",
    }
    assert all("empresa_id" not in f.input_schema["properties"] for f in ferramentas)


def test_buscar_candidatos_devolve_o_mesmo_que_a_api(cenario: Cenario) -> None:
    cenario.assinar()

    resultado = cenario.chamar("buscar_candidatos", vaga_id=cenario.vaga, limite=1)

    esperado = api.listar_candidatos(cenario.vaga, EMPRESA, cenario.servico, limite=1)
    assert resultado.is_error is False
    assert resultado.structured_content == esperado.model_dump(mode="json")
    assert resultado.structured_content["total"] > 1


def test_explicar_escolha_devolve_o_mesmo_que_a_api(cenario: Cenario) -> None:
    cenario.assinar()

    resultado = cenario.chamar("explicar_escolha", candidato_id=CANDIDATO)

    esperado = api.consultar_decisao(CANDIDATO, EMPRESA, cenario.servico)
    assert resultado.structured_content == esperado.model_dump(mode="json")
    assert resultado.structured_content["decisao"]["regra"]
    assert resultado.structured_content["decisao"]["rastro_id"]


class DestinoInstavel(ClienteNaraSimulado):
    fora = True

    def entregar(self, pacote):
        return False if self.fora else super().entregar(pacote)


def test_entregar_candidatos_envia_ao_destino_o_que_o_fluxo_liberou(tmp_path: Path) -> None:
    destino = DestinoInstavel()
    cenario = Cenario(tmp_path / "agente.db", destino=destino)
    cenario.assinar()
    assert destino.entregues == {}

    destino.fora = False
    cenario.servico.retomar(EMPRESA, cenario.vaga, PESSOA, "destino voltou")
    resultado = cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)

    assert resultado.is_error is False
    assert resultado.structured_content["entregues"] == [CANDIDATO]
    assert resultado.structured_content["pendentes"] == []
    assert [p.candidato_id for p in destino.entregues.values()] == [CANDIDATO]


def test_entregar_candidatos_repetido_nao_duplica(cenario: Cenario) -> None:
    cenario.assinar()

    cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)
    resultado = cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)

    assert resultado.structured_content["entregues"] == [CANDIDATO]
    assert len(cenario.destino.entregues) == 1


def test_entregar_candidatos_com_destino_fora_do_ar_fica_pendente(tmp_path: Path) -> None:
    cenario = Cenario(tmp_path / "agente.db", destino=NaraForaDoAr())
    cenario.assinar()

    resultado = cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)

    assert resultado.is_error is False
    assert resultado.structured_content["entregues"] == []
    assert resultado.structured_content["pendentes"] == [CANDIDATO]


def test_entregar_candidatos_nao_entrega_quem_ainda_nao_aceitou(cenario: Cenario) -> None:
    cenario.assinar(ModoEntrega.APOS_ACEITE)
    assert cenario.servico.consultar(EMPRESA, cenario.vaga).estado == "convidando"

    resultado = cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)

    assert resultado.structured_content["entregues"] == []
    assert resultado.structured_content["pendentes"] == []
    assert cenario.destino.entregues == {}


def test_entregar_candidatos_com_vaga_parada_nao_entrega(tmp_path: Path) -> None:
    destino = DestinoInstavel()
    cenario = Cenario(tmp_path / "agente.db", destino=destino)
    cenario.assinar()
    assert cenario.servico.consultar(EMPRESA, cenario.vaga).estado == "pausada"

    destino.fora = False
    resultado = cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)

    assert resultado.structured_content["pendentes"] == [CANDIDATO]
    assert destino.entregues == {}


def test_entregar_candidatos_com_mandato_vencido_nao_entrega(tmp_path: Path) -> None:
    destino = DestinoInstavel()
    relogio = Relogio()
    cenario = Cenario(tmp_path / "agente.db", destino=destino, relogio=relogio)
    cenario.assinar(valido_ate=AGORA + timedelta(days=1))
    cenario.servico.retomar(EMPRESA, cenario.vaga, PESSOA, "destino voltou")

    relogio.avancar(days=2)
    destino.fora = False
    resultado = cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)

    assert resultado.is_error is False
    assert destino.entregues == {}


@pytest.mark.parametrize(
    ("ferramenta", "argumentos"),
    [
        ("buscar_candidatos", {}),
        ("explicar_escolha", {"candidato_id": CANDIDATO}),
        ("entregar_candidatos", {}),
    ],
)
def test_empresa_vem_da_configuracao_nunca_do_argumento(
    cenario: Cenario, ferramenta: str, argumentos: dict[str, Any]
) -> None:
    cenario.assinar()
    entregas_antes = len(cenario.destino.entregues)
    outra = criar_servidor_mcp("empresa-b", cenario.servico)
    if ferramenta != "explicar_escolha":
        argumentos = {**argumentos, "vaga_id": cenario.vaga}

    resultado = _chamar(outra, ferramenta, {**argumentos, "empresa_id": EMPRESA})

    assert resultado.is_error is True
    assert resultado.structured_content is None
    assert len(cenario.destino.entregues) == entregas_antes


def test_argumento_de_empresa_nao_troca_a_empresa_configurada(cenario: Cenario) -> None:
    cenario.assinar()

    resultado = cenario.chamar("buscar_candidatos", vaga_id=cenario.vaga, empresa_id="empresa-b")

    esperado = api.listar_candidatos(cenario.vaga, EMPRESA, cenario.servico)
    assert resultado.structured_content == esperado.model_dump(mode="json")


@pytest.mark.parametrize(
    "argumentos",
    [{"pagina": 0}, {"limite": 0}, {"limite": api.LIMITE_MAXIMO + 1}],
)
def test_paginacao_segue_os_limites_da_api(cenario: Cenario, argumentos: dict[str, Any]) -> None:
    resultado = cenario.chamar("buscar_candidatos", vaga_id=cenario.vaga, **argumentos)

    assert resultado.is_error is True


def test_erro_previsivel_devolve_a_mensagem_da_api(cenario: Cenario) -> None:
    resultado = cenario.chamar("buscar_candidatos", vaga_id="nao-existe")

    assert resultado.is_error is True
    assert "Vaga não encontrada nesta empresa." in _texto(resultado)


@pytest.mark.parametrize(
    ("ferramenta", "argumentos"),
    [
        ("buscar_candidatos", {}),
        ("explicar_escolha", {"candidato_id": CANDIDATO}),
        ("entregar_candidatos", {}),
    ],
)
def test_simulacao_e_identificada(
    cenario: Cenario, ferramenta: str, argumentos: dict[str, Any]
) -> None:
    cenario.assinar()
    if ferramenta != "explicar_escolha":
        argumentos = {**argumentos, "vaga_id": cenario.vaga}

    dados = cenario.chamar(ferramenta, **argumentos).structured_content

    assert dados["simulado"] is True
    assert dados["exemplo_fixo"] is False


@pytest.mark.parametrize("empresa_id", ["", "  ", "empresa com espaço"])
def test_empresa_invalida_na_configuracao_e_recusada(cenario: Cenario, empresa_id: str) -> None:
    with pytest.raises(ErroContrato):
        criar_servidor_mcp(empresa_id, cenario.servico)


def test_toda_chamada_gera_rastro(cenario: Cenario, rastro: CapturaRastro) -> None:
    cenario.assinar()
    rastro.registros.clear()

    cenario.chamar("buscar_candidatos", vaga_id=cenario.vaga)
    cenario.chamar("explicar_escolha", candidato_id=CANDIDATO, vaga_id=cenario.vaga)
    cenario.chamar("entregar_candidatos", vaga_id=cenario.vaga)
    cenario.chamar("buscar_candidatos", vaga_id="nao-existe")

    registros = [r for r in rastro.registros if r.etapa.startswith("mcp_ferramenta:")]
    assert [r.etapa for r in registros] == [
        "mcp_ferramenta:buscar_candidatos",
        "mcp_ferramenta:explicar_escolha",
        "mcp_ferramenta:entregar_candidatos",
        "mcp_ferramenta:buscar_candidatos",
    ]
    assert all(r.empresa_id == EMPRESA for r in registros)
    assert registros[1].candidato_id == CANDIDATO
    assert registros[1].vaga_id == cenario.vaga
    assert [r.sucesso for r in registros] == [True, True, True, False]
    assert registros[-1].erro_tipo == "VagaInexistente"


def _parametros_stdio(**ambiente: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "backend.agente.mcp"], env=ambiente, cwd=str(RAIZ)
    )


def test_servidor_por_stdio_usa_a_empresa_da_variavel_de_ambiente(tmp_path: Path) -> None:
    banco = tmp_path / "demo.db"
    cliente_api = TestClient(api.criar_app(montar_demo(banco)))
    resposta = cliente_api.post("/vagas", headers={"X-Empresa-Id": EMPRESA}, json=PEDIDO_VAGA)
    vaga = resposta.json()["vaga"]["id"]

    async def chamar() -> CallToolResult:
        parametros = _parametros_stdio(MCP_EMPRESA_ID=EMPRESA, MCP_BANCO=str(banco))
        async with Client(parametros) as cliente:
            return await cliente.call_tool("buscar_candidatos", {"vaga_id": vaga})

    resultado = asyncio.run(chamar())

    assert resultado.is_error is False
    assert resultado.structured_content["simulado"] is True


def test_servidor_sem_empresa_configurada_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_EMPRESA_ID", raising=False)

    with pytest.raises(SystemExit, match="MCP_EMPRESA_ID"):
        main()
