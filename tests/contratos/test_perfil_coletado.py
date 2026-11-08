"""Contrato do perfil estruturado: esquema versionado e exemplo sintético."""

import json
from datetime import date

import pytest
from pydantic import ValidationError

from backend.contratos.gerar_esquema_perfil import (
    ARQUIVO_ESQUEMA,
    ARQUIVO_EXEMPLO,
    gerar,
    texto_esquema,
)
from backend.contratos.modelos import ContatoColetado, FatoColetado, PerfilColetado, TipoFato


def _fato(**campos) -> dict:
    dados = {
        "texto": "Usa Python em produção.",
        "fonte": "documento_enviado",
        "documento": "curriculo-ficticio.pdf",
        "coletado_em": date(2026, 11, 7),
        "trecho": "Python em produção",
        "tipo": TipoFato.DECLARADO,
    }
    dados.update(campos)
    return dados


def _contato(**campos) -> dict:
    dados = {
        "tipo": "email",
        "valor": "pessoa@example.invalid",
        "fonte": "documento_enviado",
        "documento": "curriculo-ficticio.pdf",
        "coletado_em": date(2026, 11, 7),
        "publicado_pela_pessoa": True,
    }
    dados.update(campos)
    return dados


def test_fato_traz_fonte_origem_data_trecho_e_tipo():
    fato = FatoColetado(**_fato())

    assert fato.tipo is TipoFato.DECLARADO
    assert fato.url is None


@pytest.mark.parametrize("campos", [{"documento": None}, {"url": "https://a.example.invalid"}])
def test_fato_exige_exatamente_uma_origem(campos):
    with pytest.raises(ValidationError):
        FatoColetado(**_fato(**campos))


@pytest.mark.parametrize("url", ["ftp://a.example.invalid", "a.example.invalid", "file:///x"])
def test_origem_em_url_precisa_ser_http(url):
    with pytest.raises(ValidationError):
        FatoColetado(**_fato(documento=None, url=url))


@pytest.mark.parametrize("campo", ["fonte", "coletado_em", "trecho", "tipo", "texto"])
def test_fato_nao_dispensa_campos(campo):
    dados = _fato()
    del dados[campo]

    with pytest.raises(ValidationError):
        FatoColetado(**dados)


def test_trecho_vazio_e_recusado():
    with pytest.raises(ValidationError):
        FatoColetado(**_fato(trecho="   "))


def test_contato_exige_dizer_se_foi_publicado_pela_pessoa():
    dados = _contato()
    del dados["publicado_pela_pessoa"]

    with pytest.raises(ValidationError):
        ContatoColetado(**dados)


def test_perfil_exige_marcar_simulacao():
    with pytest.raises(ValidationError):
        PerfilColetado(empresa_id="e", candidato_id="c", coletado_em=date(2026, 11, 7))


def test_campo_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        FatoColetado(**_fato(confianca=0.9))


def test_esquema_versionado_e_o_gerado_pelo_codigo():
    assert ARQUIVO_ESQUEMA.read_text(encoding="utf-8") == texto_esquema()


def test_esquema_descreve_a_origem_e_o_tipo():
    esquema = json.loads(texto_esquema())

    fato = esquema["$defs"]["FatoColetado"]["properties"]
    assert {"fonte", "url", "documento", "coletado_em", "trecho", "tipo"} <= set(fato)
    assert esquema["$defs"]["TipoFato"]["enum"] == ["comprovado", "declarado", "inferido"]
    contato = esquema["$defs"]["ContatoColetado"]
    assert "publicado_pela_pessoa" in contato["required"]


def test_exemplo_e_valido_sintetico_e_marcado_como_simulacao():
    texto = ARQUIVO_EXEMPLO.read_text(encoding="utf-8")
    perfil = PerfilColetado.model_validate_json(texto)

    assert perfil.simulado is True
    assert perfil.fatos
    assert perfil.contatos
    assert {f.tipo for f in perfil.fatos} == set(TipoFato)
    for contato in perfil.contatos:
        assert "example.invalid" in contato.valor or "00000" in contato.valor
    assert "linkedin.com" not in texto


def test_gerar_grava_o_mesmo_texto(tmp_path):
    destino = tmp_path / "pasta" / "esquema.json"

    gerar(destino)

    assert destino.read_text(encoding="utf-8") == texto_esquema()
