"""Fontes plugáveis: só entra o que estiver habilitado."""

import ast
from datetime import date
from pathlib import Path

import pytest

from backend.contratos.interfaces import FonteCandidatos
from backend.contratos.modelos import ContatoColetado, FatoColetado, PerfilColetado, TipoFato
from backend.contratos.simulacoes import FonteSimulada, candidato_simulado
from backend.fontes.perfis import candidato_de_perfil
from backend.fontes.registro import FonteDesconhecida, habilitadas_do_ambiente, montar_fontes

RAIZ = Path(__file__).resolve().parents[2]
HOJE = date(2026, 11, 7)


def _catalogo(criadas: list[str]) -> dict:
    def fabrica(nome: str):
        def criar() -> FonteCandidatos:
            criadas.append(nome)
            return FonteSimulada([candidato_simulado(nome, "empresa-a")])

        return criar

    return {nome: fabrica(nome) for nome in ("github", "documentos", "sites")}


def test_nada_habilitado_por_padrao():
    criadas: list[str] = []

    assert montar_fontes(_catalogo(criadas)) == []
    assert criadas == []


def test_so_cria_o_que_foi_habilitado_na_ordem_da_configuracao():
    criadas: list[str] = []

    fontes = montar_fontes(_catalogo(criadas), ["sites", "github"])

    assert criadas == ["sites", "github"]
    assert all(isinstance(f, FonteCandidatos) for f in fontes)


def test_fonte_desconhecida_e_erro_e_nao_silencio():
    with pytest.raises(FonteDesconhecida):
        montar_fontes(_catalogo([]), ["github", "linkedin"])


def test_fonte_repetida_entra_uma_vez():
    criadas: list[str] = []

    assert len(montar_fontes(_catalogo(criadas), ["github", "github"])) == 1


def test_objeto_que_nao_e_fonte_e_recusado():
    with pytest.raises(TypeError):
        montar_fontes({"ruim": lambda: object()}, ["ruim"])


def test_habilitadas_vem_do_ambiente(monkeypatch):
    monkeypatch.delenv("FONTES_HABILITADAS", raising=False)
    assert habilitadas_do_ambiente() == []

    monkeypatch.setenv("FONTES_HABILITADAS", " github, sites ,")
    assert habilitadas_do_ambiente() == ["github", "sites"]


def _perfil(fonte: str = "documento_enviado") -> PerfilColetado:
    origem = {"fonte": fonte, "documento": "cv.pdf", "coletado_em": HOJE}
    return PerfilColetado(
        empresa_id="empresa-a",
        candidato_id="c1",
        simulado=True,
        coletado_em=HOJE,
        nome="Zulmira Ficticia",
        fatos=[
            FatoColetado(**origem, texto="Faz APIs.", trecho="Faz APIs.", tipo=TipoFato.DECLARADO),
            FatoColetado(**origem, texto="Usa Go.", trecho="Usa Go.", tipo=TipoFato.COMPROVADO),
            FatoColetado(**origem, texto="Talvez SRE.", trecho="SRE", tipo=TipoFato.INFERIDO),
        ],
        contatos=[
            ContatoColetado(
                **origem,
                tipo="email",
                valor="z@example.invalid",
                publicado_pela_pessoa=True,
            ),
            ContatoColetado(
                **origem,
                tipo="telefone",
                valor="(00) 90000-0000",
                publicado_pela_pessoa=False,
            ),
        ],
    )


def test_fato_inferido_nao_entra_no_texto_do_candidato():
    candidato = candidato_de_perfil(_perfil(), origem="cv.pdf")

    assert "Faz APIs." in candidato.perfil_texto
    assert "Usa Go." in candidato.perfil_texto
    assert "SRE" not in candidato.perfil_texto


def test_fonte_verificavel_so_leva_fato_comprovado():
    candidato = candidato_de_perfil(_perfil("github"), origem="cv.pdf")

    assert candidato.perfil_texto == "Usa Go."


def test_contato_nao_publicado_pela_pessoa_nao_vira_atributo():
    candidato = candidato_de_perfil(_perfil(), origem="cv.pdf")

    assert candidato.atributos["email"] == "z@example.invalid"
    assert "telefone" not in candidato.atributos


@pytest.mark.parametrize(
    "arquivo",
    ["documentos.py", "github_teste.py", "site_publico.py", "registro.py", "perfis.py"],
)
def test_novos_modulos_nao_importam_nada_privado(arquivo):
    arvore = ast.parse((RAIZ / "backend" / "fontes" / arquivo).read_text(encoding="utf-8"))

    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            assert not any(nome.name.startswith("_") for nome in no.names), no.names


def test_nenhuma_fonte_tem_alvo_do_linkedin():
    for arquivo in ("github_teste.py", "documentos.py", "registro.py", "perfis.py"):
        texto = (RAIZ / "backend" / "fontes" / arquivo).read_text(encoding="utf-8")
        assert "linkedin.com/" not in texto
