import pytest

from backend.fontes.provedores.erros import MotivoTroca, UrlRecusada
from backend.fontes.provedores.url_segura import (
    remover_links_proibidos,
    validar_forma,
    validar_url_publica,
)
from tests.fontes.provedores.apoio import IP_PUBLICO, resolver_publico


@pytest.mark.parametrize(
    "url",
    [
        "https://linkedin.com/in/pessoa-ficticia",
        "https://www.linkedin.com/in/pessoa-ficticia",
        "https://br.linkedin.com/in/pessoa-ficticia",
        "https://LINKEDIN.COM./in/pessoa-ficticia",
        "http://media.licdn.com/foto.png",
        "https://linkedin.cn/in/pessoa",
        "https://ⅼinkedin.com/in/pessoa",
        "https://linkedin。com/in/pessoa",
        "https://www-linkedin-com.translate.goog/in/pessoa",
        "https://web.archive.org/web/2024/https://www.linkedin.com/in/pessoa",
        "https://site-ficticio.com.br/ir?para=https%3A%2F%2Fwww.linkedin.com%2Fin%2Fpessoa",
        "https://site-ficticio.com.br/ir?para=https%253A%252F%252Fwww.linkedin.com",
        "https://site-ficticio.com.br/#https://linkedin.com/in/pessoa",
    ],
)
def test_recusa_linkedin_em_qualquer_forma(url):
    with pytest.raises(UrlRecusada) as erro:
        validar_forma(url)
    assert erro.value.motivo == MotivoTroca.DOMINIO_RECUSADO


@pytest.mark.parametrize(
    "url",
    [
        "https://lnkd.in/abc",
        "https://bit.ly/abc",
        "https://www.bit.ly/abc",
        "https://t.co/abc",
        "https://tinyurl.com/abc",
        "https://goo.gl/abc",
        "https://ow.ly/abc",
    ],
)
def test_recusa_encurtadores_porque_escondem_o_destino(url):
    with pytest.raises(UrlRecusada) as erro:
        validar_forma(url)
    assert erro.value.motivo == MotivoTroca.DOMINIO_RECUSADO


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://servico.localhost/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://192.168.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://2130706433/",
        "http://0x7f.0.0.1/",
        "http://127.1/",
        "http://017700000001/",
        "http://metadata.google.internal/",
        "http://impressora.local/",
        "http://intranet/",
        "http://8.8.8.8/",
    ],
)
def test_recusa_enderecos_internos_e_ip_literal(url):
    with pytest.raises(UrlRecusada) as erro:
        validar_url_publica(url, resolver_publico)
    assert erro.value.motivo == MotivoTroca.ENDERECO_NAO_PUBLICO


@pytest.mark.parametrize(
    "url",
    [
        "ftp://site-ficticio.com.br/arquivo",
        "file:///etc/passwd",
        "gopher://site-ficticio.com.br/",
        "javascript:alert(1)",
        "https://usuario:senha@site-ficticio.com.br/",
        "https://site-ficticio.com.br:8080/",
        "https://site ficticio.com.br/",
        "https://site-ficticio.com.br\\@interno/",
        "https://site-ficticio.com.br/\nHost: interno",
        "https://%6cocalhost/",
        "https:///sem-host",
        "http://[::1",
        "https://site-ficticio.com.br/" + "a" * 3000,
        "",
    ],
)
def test_recusa_forma_invalida(url):
    with pytest.raises(UrlRecusada):
        validar_url_publica(url, resolver_publico)


@pytest.mark.parametrize(
    "endereco",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:10.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
    ],
)
def test_recusa_nome_que_resolve_para_endereco_interno(endereco):
    with pytest.raises(UrlRecusada) as erro:
        validar_url_publica("https://parece-publico.com.br/", lambda _: [endereco])
    assert erro.value.motivo == MotivoTroca.ENDERECO_NAO_PUBLICO


def test_recusa_quando_apenas_um_dos_enderecos_e_interno():
    with pytest.raises(UrlRecusada):
        validar_url_publica("https://parece-publico.com.br/", lambda _: [IP_PUBLICO, "10.0.0.1"])


def test_recusa_quando_o_nome_nao_resolve():
    def falha(_host: str) -> list[str]:
        raise OSError("sem resposta")

    with pytest.raises(UrlRecusada) as erro:
        validar_url_publica("https://parece-publico.com.br/", falha)
    assert erro.value.motivo == MotivoTroca.ENDERECO_NAO_PUBLICO

    with pytest.raises(UrlRecusada):
        validar_url_publica("https://parece-publico.com.br/", lambda _: [])


@pytest.mark.parametrize(
    "url",
    [
        "https://site-ficticio.com.br/portfolio",
        "http://site-ficticio.com.br:80/",
        "https://site-ficticio.com.br:443/projetos?id=1",
        "https://github.com/pessoa-ficticia",
    ],
)
def test_aceita_pagina_publica(url):
    assert validar_url_publica(url, resolver_publico) == url


def test_mensagem_de_recusa_nao_copia_a_url():
    with pytest.raises(UrlRecusada) as erro:
        validar_forma("https://www.linkedin.com/in/pessoa-ficticia")
    assert "pessoa-ficticia" not in str(erro.value)


def test_remove_links_proibidos_de_texto_externo():
    texto = "Veja https://www.linkedin.com/in/pessoa e LNKD.IN/abc ou linkedin.com/in/x. Fim."
    limpo = remover_links_proibidos(texto)
    assert "linkedin" not in limpo.casefold()
    assert "lnkd" not in limpo.casefold()
    assert limpo.endswith("Fim.")
