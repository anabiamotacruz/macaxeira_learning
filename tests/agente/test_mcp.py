import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult

from backend.agente import api
from backend.agente import exemplos_api as exemplos
from backend.agente.conector_mcp import ConectorMCP, DestinoMCP
from backend.agente.mcp import criar_servidor_mcp, main
from backend.contratos.erros import ErroContrato
from backend.contratos.simulacoes import ClienteNaraSimulado
from tests.agente.apoio import CapturaRastro, NaraForaDoAr
from tests.agente.servidor_mcp_sintetico import porta_livre, url_da_porta

EMPRESA = exemplos.EMPRESA_EXEMPLO
VAGA = exemplos.VAGA_EXEMPLO
CANDIDATO = exemplos.CANDIDATOS[0].id
RAIZ = Path(__file__).resolve().parents[2]


def _chamar(servidor: Any, ferramenta: str, argumentos: dict[str, Any]) -> CallToolResult:
    async def chamar() -> CallToolResult:
        async with Client(servidor) as cliente:
            return await cliente.call_tool(ferramenta, argumentos)

    return asyncio.run(chamar())


def _servidor(empresa_id: str = EMPRESA, destino: Any = None) -> Any:
    return criar_servidor_mcp(empresa_id, destino or ClienteNaraSimulado())


def _texto(resultado: CallToolResult) -> str:
    return " ".join(bloco.text for bloco in resultado.content)


def test_expoe_as_ferramentas_sem_empresa_nos_argumentos() -> None:
    async def listar() -> list[Any]:
        async with Client(_servidor()) as cliente:
            return (await cliente.list_tools()).tools

    ferramentas = asyncio.run(listar())

    assert {f.name for f in ferramentas} == {
        "buscar_candidatos",
        "explicar_escolha",
        "entregar_a_nara",
    }
    assert all("empresa_id" not in f.input_schema["properties"] for f in ferramentas)


def test_buscar_candidatos_devolve_o_mesmo_que_a_api() -> None:
    resultado = _chamar(_servidor(), "buscar_candidatos", {"vaga_id": VAGA, "limite": 1})

    esperado = api.listar_candidatos(VAGA, EMPRESA, limite=1).model_dump(mode="json")
    assert resultado.is_error is False
    assert resultado.structured_content == esperado


def test_explicar_escolha_devolve_o_mesmo_que_a_api() -> None:
    resultado = _chamar(_servidor(), "explicar_escolha", {"candidato_id": CANDIDATO})

    esperado = api.consultar_decisao(CANDIDATO, EMPRESA).model_dump(mode="json")
    assert resultado.structured_content == esperado
    assert resultado.structured_content["decisao"]["regra"]
    assert resultado.structured_content["decisao"]["rastro_id"]


def test_entregar_a_nara_envia_os_pacotes_da_api_ao_destino() -> None:
    destino = ClienteNaraSimulado()

    resultado = _chamar(_servidor(destino=destino), "entregar_a_nara", {"vaga_id": VAGA})

    pacotes = api.consultar_entrega(VAGA, EMPRESA).saida.pacotes
    assert list(destino.entregues.values()) == pacotes
    assert resultado.structured_content["entregues"] == [p.candidato_id for p in pacotes]
    assert resultado.structured_content["pendentes"] == []


def test_entregar_a_nara_repetido_nao_duplica() -> None:
    destino = ClienteNaraSimulado()
    servidor = _servidor(destino=destino)

    _chamar(servidor, "entregar_a_nara", {"vaga_id": VAGA})
    _chamar(servidor, "entregar_a_nara", {"vaga_id": VAGA})

    assert len(destino.entregues) == len(api.consultar_entrega(VAGA, EMPRESA).saida.pacotes)


@pytest.mark.parametrize(
    "destino",
    [
        pytest.param(NaraForaDoAr(), id="destino_devolve_falso"),
        pytest.param(
            ConectorMCP(
                DestinoMCP(
                    nome="nara",
                    empresa_id=EMPRESA,
                    url=url_da_porta(porta_livre()),
                    ferramenta_entrega="receber",
                    tempo_limite_s=2,
                )
            ),
            id="conector_sem_servidor",
        ),
    ],
)
def test_entregar_a_nara_com_destino_fora_do_ar_fica_pendente(destino: Any) -> None:
    resultado = _chamar(_servidor(destino=destino), "entregar_a_nara", {"vaga_id": VAGA})

    pacotes = api.consultar_entrega(VAGA, EMPRESA).saida.pacotes
    assert resultado.is_error is False
    assert resultado.structured_content["entregues"] == []
    assert resultado.structured_content["pendentes"] == [p.candidato_id for p in pacotes]


@pytest.mark.parametrize(
    ("ferramenta", "argumentos"),
    [
        ("buscar_candidatos", {"vaga_id": VAGA}),
        ("explicar_escolha", {"candidato_id": CANDIDATO}),
        ("entregar_a_nara", {"vaga_id": VAGA}),
    ],
)
def test_empresa_vem_da_configuracao_nunca_do_argumento(
    ferramenta: str, argumentos: dict[str, Any]
) -> None:
    destino = ClienteNaraSimulado()

    resultado = _chamar(
        _servidor("empresa-b", destino), ferramenta, {**argumentos, "empresa_id": EMPRESA}
    )

    assert resultado.is_error is True
    assert resultado.structured_content is None
    assert destino.entregues == {}


def test_argumento_de_empresa_nao_troca_a_empresa_configurada() -> None:
    argumentos = {"vaga_id": VAGA, "empresa_id": "empresa-b"}

    resultado = _chamar(_servidor(), "buscar_candidatos", argumentos)

    esperado = api.listar_candidatos(VAGA, EMPRESA).model_dump(mode="json")
    assert resultado.structured_content == esperado


@pytest.mark.parametrize(
    "argumentos",
    [
        {"vaga_id": VAGA, "pagina": 0},
        {"vaga_id": VAGA, "limite": 0},
        {"vaga_id": VAGA, "limite": api.LIMITE_MAXIMO + 1},
    ],
)
def test_paginacao_segue_os_limites_da_api(argumentos: dict[str, Any]) -> None:
    assert _chamar(_servidor(), "buscar_candidatos", argumentos).is_error is True


def test_erro_previsivel_devolve_a_mensagem_da_api() -> None:
    resultado = _chamar(_servidor(), "buscar_candidatos", {"vaga_id": "nao-existe"})

    assert resultado.is_error is True
    assert "Vaga não encontrada nesta empresa." in _texto(resultado)


@pytest.mark.parametrize(
    ("ferramenta", "argumentos"),
    [
        ("buscar_candidatos", {"vaga_id": VAGA}),
        ("explicar_escolha", {"candidato_id": CANDIDATO}),
        ("entregar_a_nara", {"vaga_id": VAGA}),
    ],
)
def test_simulacao_e_identificada(ferramenta: str, argumentos: dict[str, Any]) -> None:
    dados = _chamar(_servidor(), ferramenta, argumentos).structured_content

    assert dados["simulado"] is True
    assert dados["exemplo_fixo"] is True


def test_exemplo_fixo_nao_vai_para_destino_real() -> None:
    real = DestinoMCP(
        nome="nara",
        empresa_id=EMPRESA,
        url="https://destino.invalido/mcp",
        ferramenta_entrega="receber",
        simulado=False,
    )

    with pytest.raises(ValueError, match="destino real"):
        criar_servidor_mcp(EMPRESA, ConectorMCP(real))


@pytest.mark.parametrize("empresa_id", ["", "  ", "empresa com espaço"])
def test_empresa_invalida_na_configuracao_e_recusada(empresa_id: str) -> None:
    with pytest.raises(ErroContrato):
        _servidor(empresa_id)


def test_toda_chamada_gera_rastro(rastro: CapturaRastro) -> None:
    servidor = _servidor()

    _chamar(servidor, "buscar_candidatos", {"vaga_id": VAGA})
    _chamar(servidor, "explicar_escolha", {"candidato_id": CANDIDATO, "vaga_id": VAGA})
    _chamar(servidor, "entregar_a_nara", {"vaga_id": VAGA})
    _chamar(servidor, "buscar_candidatos", {"vaga_id": "nao-existe"})

    registros = rastro.registros
    assert [r.etapa for r in registros] == [
        "mcp_ferramenta:buscar_candidatos",
        "mcp_ferramenta:explicar_escolha",
        "mcp_ferramenta:entregar_a_nara",
        "mcp_ferramenta:buscar_candidatos",
    ]
    assert all(r.empresa_id == EMPRESA for r in registros)
    assert registros[1].candidato_id == CANDIDATO
    assert registros[1].vaga_id == VAGA
    assert [r.sucesso for r in registros] == [True, True, True, False]
    assert registros[-1].erro_tipo == "ErroApi"


def _parametros_stdio(**ambiente: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "backend.agente.mcp"], env=ambiente, cwd=str(RAIZ)
    )


def test_servidor_por_stdio_usa_a_empresa_da_variavel_de_ambiente() -> None:
    async def chamar() -> CallToolResult:
        parametros = _parametros_stdio(MCP_EMPRESA_ID=EMPRESA)
        async with Client(parametros) as cliente:
            return await cliente.call_tool("buscar_candidatos", {"vaga_id": VAGA})

    resultado = asyncio.run(chamar())

    assert resultado.is_error is False
    assert resultado.structured_content["simulado"] is True


def test_servidor_sem_empresa_configurada_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_EMPRESA_ID", raising=False)

    with pytest.raises(SystemExit, match="MCP_EMPRESA_ID"):
        main()
