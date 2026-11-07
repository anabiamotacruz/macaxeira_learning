"""Testes da lista de supressão e do link de exclusão (T3.10)."""

import pytest

from backend.contato.supressao import ListaSupressao, normalizar_identidade

SEGREDO = b"segredo-de-teste-sintetico"


@pytest.fixture
def lista() -> ListaSupressao:
    return ListaSupressao(SEGREDO)


def test_normaliza_email_telefone_e_url():
    assert normalizar_identidade("  Ana.Souza@Exemplo.COM ") == "ana.souza@exemplo.com"
    assert normalizar_identidade("+55 (81) 99999-0000") == "5581999990000"
    assert normalizar_identidade("https://GitHub.com/ana-dev/") == "github.com/ana-dev"


def test_suprimido_nao_pode_receber_contato(lista):
    lista.suprimir("empresa-a", ["ana@exemplo.com"])

    assert lista.esta_suprimido("empresa-a", ["ANA@exemplo.com"])
    assert not lista.esta_suprimido("empresa-a", ["bia@exemplo.com"])


def test_qualquer_identidade_suprimida_bloqueia(lista):
    lista.suprimir("empresa-a", ["ana@exemplo.com", "github.com/ana-dev"])

    assert lista.esta_suprimido("empresa-a", ["outro@exemplo.com", "https://github.com/ana-dev"])


def test_lista_guarda_so_hash(lista):
    lista.suprimir("empresa-a", ["ana@exemplo.com", "+55 81 99999-0000"])

    guardado = " ".join(lista.hashes("empresa-a"))
    assert "ana" not in guardado
    assert "99999" not in guardado
    assert all(len(h) == 64 for h in lista.hashes("empresa-a"))


def test_supressao_e_por_empresa(lista):
    lista.suprimir("empresa-a", ["ana@exemplo.com"])

    assert not lista.esta_suprimido("empresa-b", ["ana@exemplo.com"])
    assert lista.hashes("empresa-b") == []


def test_mesmo_contato_gera_hash_diferente_por_empresa(lista):
    lista.suprimir("empresa-a", ["ana@exemplo.com"])
    lista.suprimir("empresa-b", ["ana@exemplo.com"])

    assert set(lista.hashes("empresa-a")).isdisjoint(lista.hashes("empresa-b"))


def test_suprimir_duas_vezes_e_idempotente(lista):
    lista.suprimir("empresa-a", ["ana@exemplo.com"])
    lista.suprimir("empresa-a", ["Ana@Exemplo.com"])

    assert len(lista.hashes("empresa-a")) == 1


def test_identidade_vazia_e_ignorada(lista):
    lista.suprimir("empresa-a", ["", "   "])

    assert lista.hashes("empresa-a") == []
    assert not lista.esta_suprimido("empresa-a", [""])


def test_link_de_exclusao_suprime_em_um_clique(lista):
    link = lista.link_exclusao("empresa-a", "cand-1", ["ana@exemplo.com"])
    token = link.rsplit("/", 1)[-1]

    assert link.startswith("https://contato.simulado.local/sair/")
    assert not lista.esta_suprimido("empresa-a", ["ana@exemplo.com"])

    pedido = lista.aplicar_exclusao(token)

    assert pedido is not None
    assert (pedido.empresa_id, pedido.candidato_id) == ("empresa-a", "cand-1")
    assert lista.esta_suprimido("empresa-a", ["ana@exemplo.com"])


def test_link_de_exclusao_nao_expoe_dados(lista):
    link = lista.link_exclusao("empresa-a", "cand-1", ["ana@exemplo.com"])

    assert "ana" not in link
    assert "cand-1" not in link
    assert "empresa-a" not in link


def test_clicar_duas_vezes_e_idempotente(lista):
    token = lista.link_exclusao("empresa-a", "cand-1", ["ana@exemplo.com"]).rsplit("/", 1)[-1]

    primeiro = lista.aplicar_exclusao(token)
    segundo = lista.aplicar_exclusao(token)

    assert primeiro == segundo
    assert len(lista.hashes("empresa-a")) == 1


def test_mesmo_candidato_recebe_o_mesmo_link(lista):
    um = lista.link_exclusao("empresa-a", "cand-1", ["ana@exemplo.com"])
    outro = lista.link_exclusao("empresa-a", "cand-1", ["ana@exemplo.com"])

    assert um == outro


def test_token_desconhecido_nao_suprime_nada(lista):
    assert lista.aplicar_exclusao("token-inventado") is None
    assert lista.hashes("empresa-a") == []


def test_link_de_outra_lista_nao_vale(lista):
    outra = ListaSupressao(b"outro-segredo")
    token = outra.link_exclusao("empresa-a", "cand-1", ["ana@exemplo.com"]).rsplit("/", 1)[-1]

    assert lista.aplicar_exclusao(token) is None


def test_link_exige_ao_menos_uma_identidade(lista):
    with pytest.raises(ValueError):
        lista.link_exclusao("empresa-a", "cand-1", ["  "])


def test_segredo_vazio_e_recusado():
    with pytest.raises(ValueError):
        ListaSupressao(b"")


def test_cabecalho_list_unsubscribe(lista):
    link = lista.link_exclusao("empresa-a", "cand-1", ["ana@exemplo.com"])

    cabecalhos = lista.cabecalhos_exclusao(link)

    assert cabecalhos["List-Unsubscribe"] == f"<{link}>"
    assert cabecalhos["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
