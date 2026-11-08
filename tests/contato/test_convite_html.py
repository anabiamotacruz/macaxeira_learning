"""Convite em HTML com a identidade da CORA (decisão de 8/11): mesmo conteúdo do texto."""

from backend.contato.convite_html import (
    CID_LOGO,
    LOGO,
    ROTULO_BOTAO,
    ConteudoConvite,
    destaques,
    html_convite,
    texto_convite,
)
from backend.contato.prompts import AVISO_SIMULACAO, PALAVRA_SAIDA
from backend.contratos.modelos import Analise

LINK = "https://agenda.exemplo.invalid/marcar?vaga=v1&pessoa=ext"
ORIGEM = "https://www.linkedin.com/in/pessoa-exemplo/"
SAIDA = "mailto:convites@exemplo.invalid?subject=SAIR"


def conteudo(**campos) -> ConteudoConvite:
    dados = {
        "empresa": "CORA",
        "titulo_vaga": "Pessoa Desenvolvedora Python",
        "nome": "Pessoa Exemplo",
        "destaques": ["Python", "APIs"],
        "link": LINK,
        "descricao_origem": "seu perfil público do LinkedIn",
        "url_origem": ORIGEM,
        "data_coleta": "08/11/2026",
        "simulado": False,
    }
    dados.update(campos)
    return ConteudoConvite(**dados)


def analise(notas: dict[str, float]) -> Analise:
    return Analise(
        empresa_id="empresa-a",
        vaga_id="v1",
        candidato_id="ext",
        requisitos_ok={"r1": True},
        notas=notas,
        evidencias=[],
        lacunas=[],
        pontos_a_aprofundar=[],
        alertas=[],
    )


def test_html_tem_o_botao_com_o_link_escapado_e_as_cores_da_marca():
    html = html_convite(conteudo(), SAIDA)

    assert 'href="https://agenda.exemplo.invalid/marcar?vaga=v1&amp;pessoa=ext"' in html
    assert ROTULO_BOTAO in html
    assert "#fb3c0d" in html
    assert "#0b3038" in html


def test_html_usa_o_logo_por_cid_e_o_cabecalho_da_cora():
    html = html_convite(conteudo(), SAIDA)

    assert f'src="cid:{CID_LOGO}"' in html
    assert "Conexão de Oportunidade de Recrutamento Ativo" in html
    assert LOGO.is_file()
    assert LOGO.read_bytes().startswith(b"\x89PNG")


def test_html_escapa_o_nome_com_script():
    html = html_convite(conteudo(nome="<script>alert(1)</script>"), SAIDA)

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_html_escapa_vaga_destaques_e_origem():
    html = html_convite(
        conteudo(titulo_vaga="<b>vaga</b>", destaques=['"><img src=x>'], url_origem=ORIGEM + '"x'),
        SAIDA,
    )

    assert "<b>vaga</b>" not in html
    assert "<img src=x>" not in html
    assert ORIGEM + '"x' not in html


def test_html_diz_por_que_recebeu_e_como_sair():
    html = html_convite(conteudo(), SAIDA)

    assert "Por que você recebeu este e-mail" in html
    assert ORIGEM in html
    assert "Não quero mais contato" in html
    assert f'href="{SAIDA}"' in html
    assert PALAVRA_SAIDA in html


def test_texto_e_html_trazem_o_mesmo_conteudo():
    item = conteudo()
    texto = texto_convite(item)
    html = html_convite(item, SAIDA)

    for parte in ("Pessoa Exemplo", "Pessoa Desenvolvedora Python", "Python", "APIs", ORIGEM):
        assert parte in texto
        assert parte in html
    assert LINK in texto
    assert "Por que você recebeu este e-mail" in texto
    assert "Não quero mais contato" in texto


def test_envio_real_nao_leva_o_aviso_de_simulacao():
    item = conteudo(simulado=False)

    assert AVISO_SIMULACAO not in texto_convite(item)
    assert AVISO_SIMULACAO not in html_convite(item, SAIDA)


def test_simulacao_continua_identificada_no_texto_e_no_html():
    item = conteudo(simulado=True)

    assert AVISO_SIMULACAO in texto_convite(item)
    assert AVISO_SIMULACAO in html_convite(item, SAIDA)


def test_destaques_ficam_so_com_nota_de_0_6_para_cima_em_ordem():
    assert destaques(analise({"cloud": 0.4, "APIs": 0.8, "Python": 1.0, "SQL": 0.6})) == [
        "Python",
        "APIs",
        "SQL",
    ]


def test_sem_destaque_a_frase_e_neutra_e_sem_lista():
    item = conteudo(destaques=destaques(analise({"cloud": 0.4})))

    assert item.destaques == []
    assert "chamou nossa atenção por" not in texto_convite(item)
    assert "chamou a nossa atenção por" not in html_convite(item, SAIDA)
    assert destaques(None) == []


def test_sem_link_nao_ha_botao_e_a_pessoa_responde_o_email():
    item = conteudo(link=None)

    assert ROTULO_BOTAO not in html_convite(item, SAIDA)
    assert "responda este e-mail" in texto_convite(item)


def test_link_que_nao_e_http_nao_vira_href():
    html = html_convite(conteudo(link="javascript:alert(1)"), SAIDA)

    assert "javascript:" not in html
