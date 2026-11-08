"""Testes do rastro. O Langfuse real roda com exportador em memória, sem rede."""

import json
import uuid

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from backend.modelos import rastro as modulo
from backend.modelos.rastro import (
    RastroLangfuse,
    RastroLocal,
    RegistroChamada,
    criar_rastro,
    mascarar_segredos,
)

CHAVE = "rc_chave_sintetica_de_teste_0123456789"
SECRETA = "sk-lf-sintetica-0123456789"


def registro(**campos) -> RegistroChamada:
    return RegistroChamada(
        **{
            "etapa": "analise",
            "modelo": "modelo/teste",
            "resultado": "ok",
            "tokens_entrada": 10,
            "tokens_saida": 20,
            "custo_usd": 0.5,
            "custo_estimado": True,
            "tempo_s": 1.5,
            "erro": None,
            **campos,
        }
    )


@pytest.fixture
def exportador():
    return InMemorySpanExporter()


@pytest.fixture
def langfuse(exportador):
    """Cliente real do Langfuse, com projeto próprio e nada enviado à rede."""
    return Langfuse(
        public_key=f"pk-lf-{uuid.uuid4()}",
        secret_key=SECRETA,
        base_url="http://127.0.0.1:9",
        tracer_provider=TracerProvider(),
        span_exporter=exportador,
    )


def atributos(langfuse: Langfuse, exportador: InMemorySpanExporter) -> dict:
    langfuse.flush()
    return dict(exportador.get_finished_spans()[-1].attributes)


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", CHAVE)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRETA)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)


def test_sem_credenciais_usa_rastro_local(monkeypatch):
    monkeypatch.delenv("LANGFUSE_SECRET_KEY")

    def proibido(**_):
        raise AssertionError("Langfuse não deve ser criado sem credenciais")

    monkeypatch.setattr(modulo, "Langfuse", proibido)

    assert isinstance(criar_rastro(), RastroLocal)


def test_credencial_pela_metade_usa_rastro_local(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", " ")

    assert isinstance(criar_rastro(), RastroLocal)


def test_com_credenciais_usa_langfuse(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setattr(modulo, "Langfuse", lambda: object())

    assert isinstance(criar_rastro(), RastroLangfuse)


def test_falha_ao_criar_langfuse_usa_rastro_local(monkeypatch, caplog):
    def quebrado():
        raise RuntimeError(f"erro com {SECRETA}")

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setattr(modulo, "Langfuse", quebrado)

    with caplog.at_level("WARNING"):
        assert isinstance(criar_rastro(), RastroLocal)

    assert "RuntimeError" in caplog.text
    assert SECRETA not in caplog.text


def test_rastro_local_registra_e_loga_sem_conteudo(caplog):
    rastro = RastroLocal()

    with caplog.at_level("INFO"):
        marca = rastro.iniciar(etapa="analise", modelo="m", sistema="s", usuario=CHAVE)
        rastro.concluir(marca, registro(), saida=f"saída {CHAVE}")

    assert list(rastro.registros) == [registro()]
    assert "analise" in caplog.text
    assert CHAVE not in caplog.text


def test_rastro_local_tem_tamanho_limitado():
    rastro = RastroLocal(maximo=2)

    for indice in range(3):
        rastro.concluir(None, registro(tokens_saida=indice), saida=None)

    assert [r.tokens_saida for r in rastro.registros] == [1, 2]


def test_mascara_chaves_do_ambiente_em_qualquer_estrutura():
    dados = {
        "texto": f"a {CHAVE} b",
        "lista": [f"Bearer abc123 {SECRETA}", {"interno": CHAVE}],
        "numero": 3,
    }

    mascarado = json.dumps(mascarar_segredos(dados))

    assert CHAVE not in mascarado
    assert SECRETA not in mascarado
    assert "abc123" not in mascarado
    assert '"numero": 3' in mascarado


def test_mascara_ignora_variavel_vazia(monkeypatch):
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    assert mascarar_segredos("texto") == "texto"


def test_langfuse_recebe_geracao_com_uso_e_custo(langfuse, exportador):
    rastro = RastroLangfuse(langfuse, RastroLocal())

    marca = rastro.iniciar(etapa="analise", modelo="modelo/teste", sistema="s", usuario="u")
    rastro.concluir(marca, registro(), saida="resposta")

    atributos_do_rastro = atributos(langfuse, exportador)
    conteudo = json.dumps(atributos_do_rastro)
    assert exportador.get_finished_spans()[-1].name == "analise"
    assert atributos_do_rastro["langfuse.observation.type"] == "generation"
    assert atributos_do_rastro["langfuse.observation.model.name"] == "modelo/teste"
    assert json.loads(atributos_do_rastro["langfuse.observation.usage_details"]) == {
        "input": 10,
        "output": 20,
    }
    assert json.loads(atributos_do_rastro["langfuse.observation.cost_details"]) == {"total": 0.5}
    assert "custo_estimado" in conteudo
    assert "resposta" in conteudo


def test_rastro_nao_contem_chave(langfuse, exportador):
    rastro = RastroLangfuse(langfuse, RastroLocal())

    marca = rastro.iniciar(etapa="analise", modelo="m", sistema=f"s {CHAVE}", usuario=SECRETA)
    rastro.concluir(marca, registro(), saida=f"saída {CHAVE}")

    conteudo = json.dumps(atributos(langfuse, exportador))
    assert CHAVE not in conteudo
    assert SECRETA not in conteudo


def test_falha_aparece_como_erro_no_langfuse(langfuse, exportador):
    rastro = RastroLangfuse(langfuse, RastroLocal())

    marca = rastro.iniciar(etapa="analise", modelo="m", sistema="s", usuario="u")
    rastro.concluir(marca, registro(resultado="indisponivel", erro="HTTP 500"), saida=None)

    atributos_do_rastro = atributos(langfuse, exportador)
    assert atributos_do_rastro["langfuse.observation.level"] == "ERROR"
    assert atributos_do_rastro["langfuse.observation.status_message"] == "HTTP 500"


def test_langfuse_sempre_mantem_registro_local(langfuse):
    local = RastroLocal()
    rastro = RastroLangfuse(langfuse, local)

    rastro.concluir(None, registro(), saida=None)

    assert list(local.registros) == [registro()]
