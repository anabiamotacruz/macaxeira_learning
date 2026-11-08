"""Dossiê para o recrutador: o documento de ingestão em HTML, com a marca da CORA, para PDF."""

import re

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.documento import AVISO_DADO
from backend.agente.documento_html import POLITICA_DE_CONTEUDO, documento_html
from backend.agente.montagem import montar_demo
from backend.contratos.modelos import Evidencia, Experiencia, PontoExplorar
from tests.agente.apoio import vaga_exemplo
from tests.agente.test_documento import INJECAO, SESSAO, _duvida, _pacote, _vaga_entregue


def _ponto(**campos) -> PontoExplorar:
    dados = {
        "tipo": "afirmacao_sem_exemplo",
        "criterio": "backend",
        "descricao": "Liderou a migração de um monólito.",
        "trecho": "migrei o monólito para serviços",
        "fonte": "banco",
        "verificado": True,
    }
    dados.update(campos)
    return PontoExplorar(**dados)


def test_dossie_traz_a_marca_e_o_contexto_com_trecho_e_fonte():
    texto = documento_html(_pacote(), vaga_exemplo(titulo="Pessoa Backend"))

    assert texto.startswith("<!doctype html>")
    assert "<title>CORA · Pessoa Backend</title>" in texto
    assert "CORA" in texto and "Conexão de Oportunidade" in texto
    assert 'src="data:image/png;base64,' in texto
    for esperado in (
        "Construiu APIs em Python por cinco anos.",
        "Construiu APIs em Python",
        "Sem experiência declarada com AWS.",
        "Escala dos sistemas que operou.",
        "Evidência de cloud é de Azure, não de AWS.",
        "contato autorizado, válido até 07/11/2027",
        "execucao:v1:c1",
    ):
        assert esperado in texto


def test_dossie_esta_pronto_para_imprimir_em_a4():
    texto = documento_html(_pacote(), vaga_exemplo())

    assert "@page" in texto and "A4" in texto
    assert "@media print" in texto
    assert "break-inside: avoid" in texto


def test_simulacao_e_aviso_de_dado_aparecem_antes_do_conteudo():
    texto = documento_html(_pacote(), vaga_exemplo())
    antes_do_conteudo = texto.split("Por que segue", 1)[0]

    assert "SIMULAÇÃO" in antes_do_conteudo
    assert AVISO_DADO in antes_do_conteudo


def test_dossie_real_nao_leva_o_selo_de_simulacao():
    texto = documento_html(_pacote(simulado=False), vaga_exemplo())

    assert "SIMULAÇÃO" not in texto
    assert AVISO_DADO in texto


def test_evidencia_fica_junto_do_criterio_que_ela_sustenta():
    texto = documento_html(_pacote(), vaga_exemplo())
    cartao = texto.split('data-criterio="backend"', 1)[1].split("</article>", 1)[0]

    assert "Construiu APIs em Python por cinco anos." in cartao
    assert "Construiu APIs em Python" in cartao and "banco" in cartao


def test_criterio_aparece_legivel_e_motivo_igual_ao_trecho_nao_se_repete():
    pacote = _pacote(
        motivo_por_criterio={"presencial_sp": "Moro em São Paulo."},
        evidencias=[
            Evidencia(criterio="presencial_sp", trecho="Moro em São Paulo.", fonte="banco")
        ],
    )

    texto = documento_html(pacote, vaga_exemplo())

    assert "<h3>Presencial sp</h3>" in texto
    assert texto.count("Moro em São Paulo.") == 1


def test_trajetoria_e_roteiro_de_entrevista_entram_com_fonte():
    from datetime import date

    pacote = _pacote(
        historico=[
            Experiencia(
                empresa="Loja Exemplo",
                cargo="Pessoa Backend",
                inicio=date(2021, 3, 1),
                fim=None,
                descricao="APIs de pagamento.",
            )
        ],
        pontos_a_explorar=[_ponto()],
    )

    texto = documento_html(pacote, vaga_exemplo())

    assert "Loja Exemplo" in texto and "mar/2021" in texto and "hoje" in texto
    assert "Liderou a migração de um monólito." in texto
    assert "Verificado" in texto and "migrei o monólito para serviços" in texto


def test_o_que_a_conversa_apurou_entra_como_dado():
    duvidas = [
        _duvida("A vaga é presencial?", "Sim, em São Paulo."),
        _duvida("Tem plano odontológico?", None),
    ]

    texto = documento_html(_pacote(), vaga_exemplo(), duvidas)

    assert "A vaga é presencial?" in texto and "Sim, em São Paulo." in texto
    assert "Tem plano odontológico?" in texto
    assert "encaminhada a uma pessoa" in texto


def test_texto_da_pessoa_nao_vira_html():
    pacote = _pacote(
        motivo_por_criterio={"backend": INJECAO},
        lacunas=['"><img src=x onerror=alert(1)>'],
    )

    texto = documento_html(pacote, vaga_exemplo(titulo="<b>Vaga</b>"), [_duvida(INJECAO, None)])

    assert "<script>alert" not in texto
    assert "<img src=x" not in texto
    assert "<b>Vaga</b>" not in texto
    assert "&lt;script&gt;" in texto


def test_o_unico_script_e_o_botao_de_imprimir_e_a_politica_o_fixa():
    texto = documento_html(_pacote(), vaga_exemplo())

    scripts = re.findall(r"<script[^>]*>(.*?)</script>", texto, flags=re.S)
    assert len(scripts) == 1 and "print()" in scripts[0]
    assert "default-src 'none'" in POLITICA_DE_CONTEUDO
    assert "script-src 'sha256-" in POLITICA_DE_CONTEUDO


def test_dossie_nao_tem_nota_nem_ranking():
    pagina = re.sub(
        r"<style>.*?</style>", " ", documento_html(_pacote(), vaga_exemplo()), flags=re.S
    )
    texto = re.sub(r"<[^>]+>", " ", pagina).casefold()

    for proibido in ("nota", "score", "ranking", "faixa"):
        assert proibido not in texto


@pytest.fixture
def demo(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    return TestClient(criar_app(montar_demo(tmp_path / "demo.db")))


def test_api_devolve_o_dossie_em_html_identificado_como_simulacao(demo):
    vaga, candidato = _vaga_entregue(demo)

    resposta = demo.get(f"/vagas/{vaga}/entrega/{candidato}/documento?formato=html", headers=SESSAO)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["simulado"] is True
    assert corpo["formato"] == "html"
    assert corpo["documento"].startswith("<!doctype html>")
    assert "SIMULAÇÃO" in corpo["documento"] and "Por que segue" in corpo["documento"]


def test_sem_formato_o_documento_segue_em_markdown(demo):
    vaga, candidato = _vaga_entregue(demo)

    corpo = demo.get(f"/vagas/{vaga}/entrega/{candidato}/documento", headers=SESSAO).json()

    assert corpo["formato"] == "markdown"
    assert corpo["documento"].startswith("# Contexto para entrevista")


def test_formato_desconhecido_e_recusado(demo):
    vaga, candidato = _vaga_entregue(demo)

    resposta = demo.get(f"/vagas/{vaga}/entrega/{candidato}/documento?formato=pdf", headers=SESSAO)

    assert resposta.status_code == 422


def test_politica_tambem_vai_no_documento_para_valer_fora_da_api():
    texto = documento_html(_pacote(), vaga_exemplo())

    assert f'<meta http-equiv="Content-Security-Policy" content="{POLITICA_DE_CONTEUDO}">' in texto


def test_api_recusa_dossie_de_quem_nao_foi_entregue(demo):
    vaga, _ = _vaga_entregue(demo)
    itens = demo.get(f"/vagas/{vaga}/candidatos?limite=100", headers=SESSAO).json()["itens"]
    descartado = next(i["candidato"]["id"] for i in itens if i["decisao"] == "descartar")

    resposta = demo.get(
        f"/vagas/{vaga}/entrega/{descartado}/documento?formato=html", headers=SESSAO
    )

    assert resposta.status_code == 404


def test_outra_empresa_nao_le_o_dossie(demo):
    vaga, candidato = _vaga_entregue(demo)

    resposta = demo.get(
        f"/vagas/{vaga}/entrega/{candidato}/documento?formato=html",
        headers={"X-Empresa-Id": "outra"},
    )

    assert resposta.status_code == 404
    assert candidato not in resposta.text


def test_sem_empresa_o_dossie_nao_abre(demo):
    vaga, candidato = _vaga_entregue(demo)

    resposta = demo.get(f"/vagas/{vaga}/entrega/{candidato}/documento?formato=html")

    assert resposta.status_code == 401
