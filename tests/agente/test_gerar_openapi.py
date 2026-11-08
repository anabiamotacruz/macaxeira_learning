import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.agente import exemplos_api as exemplos
from backend.agente.api import app, rotas
from backend.agente.auditoria import _mandato_citado
from backend.agente.gerar_openapi import ARQUIVO_OPENAPI, gerar, texto_openapi

COMANDO = "uv run python -m backend.agente.gerar_openapi"
RAIZ = Path(__file__).resolve().parents[2]


def _operacoes() -> list[tuple[str, str, dict]]:
    return [
        (metodo, caminho, operacao)
        for caminho, operacoes in app.openapi()["paths"].items()
        for metodo, operacao in operacoes.items()
    ]


def _ids(valor: tuple) -> str:
    return f"{valor[0]} {valor[1]}"


def _status_de_sucesso(operacao: dict) -> str:
    return next(status for status in operacao["responses"] if status.startswith("2"))


def test_openapi_versionado_e_o_gerado_pelo_codigo():
    assert ARQUIVO_OPENAPI == RAIZ / "docs" / "api" / "openapi.json"
    assert ARQUIVO_OPENAPI.read_text(encoding="utf-8") == texto_openapi(), (
        f"docs/api/openapi.json divergiu do código. Rode: {COMANDO}"
    )


def test_gerar_grava_o_mesmo_texto(tmp_path):
    destino = tmp_path / "pasta" / "openapi.json"
    gerar(destino)
    assert destino.read_text(encoding="utf-8") == texto_openapi()


def test_texto_gerado_e_estavel_e_legivel():
    assert texto_openapi() == texto_openapi()
    assert "exemplo_fixo" in texto_openapi()
    assert json.loads(texto_openapi()) == app.openapi()


def test_arquivo_nao_tem_chave_nem_dado_de_contato():
    texto = ARQUIVO_OPENAPI.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]{8,}", texto)
    assert "FEATHERLESS_API_KEY" not in texto
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", texto)


def test_comando_esta_documentado():
    assert COMANDO in (RAIZ / "docs" / "api" / "README.md").read_text(encoding="utf-8")
    assert COMANDO in app.openapi()["info"]["description"]


def test_exemplo_mostra_taxa_nao_medida_com_valor_nulo():
    operacao = app.openapi()["paths"]["/vagas/{id}/metricas"]["get"]
    exemplo = operacao["responses"]["200"]["content"]["application/json"]["example"]
    assert exemplo["erros_por_tipo"]["descarte_errado"] == {
        "valor": None,
        "casos": 0,
        "wilson_inferior": None,
        "wilson_superior": None,
    }


def test_esquema_exige_identificacao_da_simulacao_em_toda_resposta():
    esquemas = app.openapi()["components"]["schemas"]
    respostas = {nome: modelo for nome, modelo in esquemas.items() if nome.startswith("Resposta")}
    assert len(respostas) >= 12
    for nome, modelo in respostas.items():
        assert "simulado" in modelo["required"], nome
        assert modelo["properties"]["simulado"]["const"] is True, nome
        if nome != "RespostaErro":
            assert "exemplo_fixo" in modelo["required"], nome


def test_rota_servida_devolve_o_mesmo_openapi():
    assert TestClient(app).get("/openapi.json").json() == app.openapi()


def test_todo_erro_documentado_segue_o_formato_padrao():
    esquemas = app.openapi()["components"]["schemas"]
    assert "HTTPValidationError" not in esquemas
    for _, _, operacao in _operacoes():
        erros = [status for status in operacao["responses"] if not status.startswith("2")]
        assert {"401", "500"} <= set(erros)
        for status in erros:
            conteudo = operacao["responses"][status]["content"]["application/json"]
            assert conteudo["schema"] == {"$ref": "#/components/schemas/RespostaErro"}
            assert set(conteudo["example"]) == {"erro", "simulado"}
            assert conteudo["example"]["simulado"] is True


def test_toda_rota_exige_a_sessao_simulada():
    assert app.openapi()["components"]["securitySchemes"]["SessaoSimulada"]["name"] == (
        "X-Empresa-Id"
    )
    for _, _, operacao in _operacoes():
        assert operacao["security"] == [{"SessaoSimulada": []}]


def test_parametros_e_corpos_nao_aceitam_empresa():
    esquema = app.openapi()
    for _, _, operacao in _operacoes():
        assert "empresa_id" not in {p["name"] for p in operacao.get("parameters", [])}
    for nome, modelo in esquema["components"]["schemas"].items():
        if nome.startswith("Pedido"):
            assert "empresa_id" not in modelo["properties"]


ROTAS_POR_NOME = {rota.name: rota for rota in rotas.routes}


@pytest.mark.parametrize("item", _operacoes(), ids=_ids)
def test_exemplo_do_openapi_segue_o_formato_da_resposta(item):
    _, _, operacao = item
    status = _status_de_sucesso(operacao)
    exemplo = operacao["responses"][status]["content"]["application/json"]["example"]
    assert exemplo["simulado"] is True
    ROTAS_POR_NOME[operacao["operationId"]].response_model.model_validate(exemplo)


@pytest.mark.parametrize("item", _operacoes(), ids=_ids)
def test_exemplo_marca_como_fixo_so_o_que_ainda_e_fixo(item):
    _, caminho, operacao = item
    status = _status_de_sucesso(operacao)
    exemplo = operacao["responses"][status]["content"]["application/json"]["example"]
    assert exemplo["exemplo_fixo"] is caminho.endswith("/metricas")


def test_responsavel_dos_exemplos_e_o_que_a_auditoria_exige():
    assert _mandato_citado(exemplos.RESPONSAVEL_AGENTE) is not None
    agente = [d for d in exemplos.DECISOES.values() if d.responsavel.startswith("agente:")]
    assert len(agente) == len(exemplos.DECISOES)
    assert exemplos.DECISAO_REVERTIDA.responsavel.startswith("humano:")
    assert all(d.evidencias for d in [*exemplos.DECISOES.values(), exemplos.DECISAO_REVERTIDA])


def test_formato_de_vaga_e_controle_continua_publicado():
    esquemas = app.openapi()["components"]["schemas"]
    assert "EstadoVaga" in esquemas
    assert "EstadoFluxo" not in esquemas
    assert esquemas["RespostaVaga"]["properties"]["estado"] == {
        "$ref": "#/components/schemas/EstadoVaga"
    }
