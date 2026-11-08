"""Resolução de identidade: só sinal forte une, e na dúvida o registro fica separado."""

from random import Random

import pytest

from backend.contratos.simulacoes import candidato_simulado
from backend.fontes.identidade import (
    DOMINIOS_LINKEDIN,
    Resolucao,
    SinaisIdentidade,
    normalizar_email,
    normalizar_perfil,
    resolver,
    sinais_de_candidato,
)
from dados.gerador import QUANTIDADE_DEMO, SEMENTE_DEMO, gerar


def sinal(registro_id, *, emails=(), perfis=(), nome="", local="", escopo="", fonte="teste"):
    return SinaisIdentidade(
        registro_id=registro_id,
        fonte=fonte,
        emails=frozenset(emails),
        perfis=frozenset(perfis),
        nome=nome,
        local=local,
        escopo=escopo,
    )


def candidato_com(identificador, **atributos):
    return candidato_simulado(identificador, "empresa-1", atributos=atributos)


def test_conjunto_vazio_nao_tem_grupo_nem_sugestao():
    assert resolver([]) == Resolucao(grupos=(), sugestoes=())


def test_um_registro_sozinho_vira_um_grupo_sem_chave_forte():
    [grupo] = resolver([sinal("a", emails=["ana@exemplo.invalid"])]).grupos

    assert grupo.id_grupo == "a"
    assert grupo.registros == ("a",)
    assert grupo.chaves_fortes == ()
    assert grupo.conflito_de_nome is False


def test_dois_registros_sem_sinal_em_comum_ficam_separados():
    resolucao = resolver(
        [
            sinal("a", emails=["ana@exemplo.invalid"], perfis=["https://github.com/ana"]),
            sinal("b", emails=["bruno@exemplo.invalid"], perfis=["https://github.com/bruno"]),
        ]
    )

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",)]
    assert resolucao.sugestoes == ()


def test_mesmo_email_une_e_guarda_a_chave_que_uniu():
    [grupo] = resolver(
        [
            sinal("b", emails=["  Ana@Exemplo.invalid "]),
            sinal("a", emails=["ana@exemplo.invalid"], perfis=["https://anasilva.dev"]),
        ]
    ).grupos

    assert grupo.registros == ("a", "b")
    assert grupo.id_grupo == "a"
    assert grupo.chaves_fortes == ("email:ana@exemplo.invalid",)


def test_mesma_url_de_perfil_une_apesar_de_esquema_www_barra_consulta_e_fragmento():
    [grupo] = resolver(
        [
            sinal("a", perfis=["https://github.com/ana"]),
            sinal("b", perfis=["http://www.github.com/ana/"]),
            sinal("c", perfis=["GitHub.com/ana?tab=repositories#topo"]),
        ]
    ).grupos

    assert grupo.registros == ("a", "b", "c")
    assert grupo.chaves_fortes == ("perfil:github.com/ana",)


def test_mesmo_par_de_host_e_usuario_une_perfis_com_caminho_diferente():
    [grupo] = resolver(
        [
            sinal("a", perfis=["https://github.com/ana"]),
            sinal("b", perfis=["https://github.com/ana/projeto-aurora"]),
        ]
    ).grupos

    assert grupo.registros == ("a", "b")
    assert grupo.chaves_fortes == ("perfil:github.com/ana",)


def test_usuarios_diferentes_no_mesmo_host_nao_se_juntam():
    resolucao = resolver(
        [
            sinal("a", perfis=["https://github.com/ana"]),
            sinal("b", perfis=["https://github.com/bruno"]),
        ]
    )

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",)]


@pytest.mark.parametrize(
    ("um", "outro"),
    [
        ("https://sites.google.com/view/ana-silva", "https://sites.google.com/view/joao-souza"),
        ("https://ufpe.br/docentes/ana", "https://ufpe.br/docentes/joao"),
        ("https://exemplo.dev/blog/post-1", "https://exemplo.dev/blog/post-2"),
    ],
)
def test_primeiro_segmento_fora_das_plataformas_nao_vira_usuario(um, outro):
    """Em site qualquer, o primeiro segmento é seção, não pessoa: só a URL inteira une."""
    resolucao = resolver([sinal("a", perfis=[um]), sinal("b", perfis=[outro])])

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",)]


def test_pagina_reservada_da_plataforma_nao_vira_usuario():
    resolucao = resolver(
        [
            sinal("a", perfis=["https://github.com/orgs/aurora"]),
            sinal("b", perfis=["https://github.com/orgs/boreal"]),
        ]
    )

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",)]


def test_mesma_url_inteira_em_site_qualquer_ainda_une():
    [grupo] = resolver(
        [
            sinal("a", perfis=["https://sites.google.com/view/ana-silva"]),
            sinal("b", perfis=["sites.google.com/view/ana-silva/"]),
        ]
    ).grupos

    assert grupo.registros == ("a", "b")


def test_uniao_e_transitiva_entre_email_e_perfil():
    resolucao = resolver(
        [
            sinal("a", emails=["ana@exemplo.invalid"]),
            sinal("b", emails=["ana@exemplo.invalid"], perfis=["https://github.com/ana"]),
            sinal("c", perfis=["https://www.github.com/ana/"]),
        ]
    )

    [grupo] = resolucao.grupos
    assert grupo.registros == ("a", "b", "c")
    assert grupo.chaves_fortes == ("email:ana@exemplo.invalid", "perfil:github.com/ana")


def test_nome_e_local_parecidos_nunca_unem_e_viram_sugestao():
    resolucao = resolver(
        [
            sinal("a", nome="Ana Silva", local="Recife", emails=["ana@um.invalid"]),
            sinal("b", nome="Ana Silva", local="Recife - PE", emails=["ana@dois.invalid"]),
        ]
    )

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",)]
    [sugestao] = resolucao.sugestoes
    assert (sugestao.id_grupo_a, sugestao.id_grupo_b) == ("a", "b")
    assert "Ana Silva" in sugestao.motivo and "Recife" in sugestao.motivo


def test_sugestao_exige_nome_e_local_parecidos():
    resolucao = resolver(
        [
            sinal("a", nome="Ana Silva", local="Recife"),
            sinal("b", nome="Ana Silva", local="Curitiba"),
            sinal("c", nome="Bruno Souza", local="Recife"),
            sinal("d", nome="Ana Silva"),
        ]
    )

    assert resolucao.sugestoes == ()


def test_registros_ja_unidos_nao_viram_sugestao():
    resolucao = resolver(
        [
            sinal("a", nome="Ana Silva", local="Recife", emails=["ana@exemplo.invalid"]),
            sinal("b", nome="Ana Silva", local="Recife", emails=["ana@exemplo.invalid"]),
        ]
    )

    assert len(resolucao.grupos) == 1
    assert resolucao.sugestoes == ()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/in/ana",
        "https://br.linkedin.com/in/ana/",
        "http://linkedin.cn/in/ana",
        "https://linked.in/ana",
        "https://media.licdn.com/perfil/ana",
        "https://lnkd.in/abc123",
        "linkedin.com/in/ana",
    ],
)
def test_url_do_linkedin_nunca_e_chave_de_juncao(url):
    assert normalizar_perfil(url) is None

    resolucao = resolver([sinal("a", perfis=[url]), sinal("b", perfis=[url])])

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",)]


def test_dominios_do_linkedin_sao_os_mesmos_que_o_coletor_recusa():
    assert DOMINIOS_LINKEDIN == ("linkedin.com", "linkedin.cn", "linked.in", "licdn.com", "lnkd.in")


@pytest.mark.parametrize("vazio", ["", "   ", "\t\n"])
def test_valor_vazio_ou_so_espaco_nunca_une(vazio):
    assert normalizar_email(vazio) is None
    assert normalizar_perfil(vazio) is None

    resolucao = resolver(
        [
            sinal("a", emails=[vazio], perfis=[vazio]),
            sinal("b", emails=[vazio], perfis=[vazio]),
            sinal("c", emails=[vazio, "ana@exemplo.invalid"]),
        ]
    )

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",), ("c",)]


@pytest.mark.parametrize("texto", ["ana", "ana@", "@exemplo.invalid", "ana@exemplo invalid"])
def test_texto_que_nao_e_endereco_de_email_nao_vira_chave(texto):
    assert normalizar_email(texto) is None

    resolucao = resolver([sinal("a", emails=[texto]), sinal("b", emails=[texto])])

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",)]


def test_nao_usa_truque_de_provedor_no_email():
    resolucao = resolver(
        [
            sinal("a", emails=["ana.silva@exemplo.invalid"]),
            sinal("b", emails=["anasilva@exemplo.invalid"]),
            sinal("c", emails=["ana.silva+vaga@exemplo.invalid"]),
        ]
    )

    assert [g.registros for g in resolucao.grupos] == [("a",), ("b",), ("c",)]


def test_conflito_de_nome_nao_separa_mas_sinaliza():
    [grupo] = resolver(
        [
            sinal("a", nome="Ana Silva", emails=["contato@exemplo.invalid"]),
            sinal("b", nome="Bruno Souza", emails=["contato@exemplo.invalid"]),
        ]
    ).grupos

    assert grupo.registros == ("a", "b")
    assert grupo.conflito_de_nome is True


def test_nome_abreviado_ou_ausente_nao_e_conflito():
    [grupo] = resolver(
        [
            sinal("a", nome="Ana Silva", emails=["ana@exemplo.invalid"]),
            sinal("b", nome="ANA BEATRIZ SILVA", emails=["ana@exemplo.invalid"]),
            sinal("c", nome="", emails=["ana@exemplo.invalid"]),
        ]
    ).grupos

    assert grupo.registros == ("a", "b", "c")
    assert grupo.conflito_de_nome is False


def test_escopos_diferentes_nunca_se_juntam_nem_se_sugerem():
    resolucao = resolver(
        [
            sinal("a", emails=["ana@exemplo.invalid"], nome="Ana Silva", local="Recife"),
            sinal(
                "a",
                emails=["ana@exemplo.invalid"],
                nome="Ana Silva",
                local="Recife",
                escopo="empresa-2",
            ),
        ]
    )

    assert [g.id_grupo for g in resolucao.grupos] == ["a", "empresa-2:a"]
    assert resolucao.sugestoes == ()


def test_registro_repetido_no_mesmo_escopo_e_recusado():
    with pytest.raises(ValueError):
        resolver([sinal("a"), sinal("a")])


@pytest.mark.parametrize("identificador", ["", "   "])
def test_registro_sem_identificador_e_recusado(identificador):
    with pytest.raises(ValueError):
        resolver([sinal(identificador)])


def _vinte_registros() -> list[SinaisIdentidade]:
    registros = []
    for indice in range(20):
        pessoa = indice % 7
        registros.append(
            sinal(
                f"r{indice:02d}",
                emails=[f"pessoa{pessoa}@exemplo.invalid"] if indice % 3 else [],
                perfis=[f"https://github.com/pessoa{pessoa}/projeto-{indice}"],
                nome=f"Pessoa Fictícia {pessoa}",
                local="Recife" if pessoa % 2 else "São Paulo",
            )
        )
    return registros


def test_resultado_nao_depende_da_ordem_de_entrada():
    registros = _vinte_registros()
    esperado = resolver(registros)
    embaralhador = Random(7)

    for _ in range(10):
        embaralhado = registros[:]
        embaralhador.shuffle(embaralhado)
        assert resolver(embaralhado) == esperado

    assert len(esperado.grupos) == 7
    assert all(g.id_grupo == min(g.registros) for g in esperado.grupos)


def test_resolver_nao_altera_a_entrada():
    registros = _vinte_registros()
    copia = list(registros)

    resolver(registros)

    assert registros == copia


def test_sinais_de_candidato_le_email_links_e_perfis():
    candidato = candidato_com(
        "pessoa-1",
        email="Ana@Exemplo.invalid",
        links="https://anasilva.dev , https://github.com/ana",
        perfis="https://gitlab.com/ana",
        cidade="Recife",
    )

    sinais = sinais_de_candidato(candidato)

    assert sinais.registro_id == "pessoa-1:simulada"
    assert sinais.escopo == "empresa-1"
    assert sinais.emails == frozenset({"Ana@Exemplo.invalid"})
    assert sinais.perfis == frozenset(
        {"https://anasilva.dev", "https://github.com/ana", "https://gitlab.com/ana"}
    )
    assert sinais.local == "Recife"


def test_sinais_de_candidato_sem_atributos_nao_gera_chave():
    sinais = sinais_de_candidato(candidato_com("pessoa-1"))

    assert sinais.emails == frozenset()
    assert sinais.perfis == frozenset()
    assert sinais.local == ""
    assert resolver([sinais]).grupos[0].chaves_fortes == ()


def test_duplicata_do_gerador_vira_um_grupo_so():
    candidatos = gerar(SEMENTE_DEMO, 8)
    original, duplicata = candidatos[0], candidatos[7]
    assert original.id == duplicata.id and original.fonte != duplicata.fonte

    resolucao = resolver([sinais_de_candidato(c) for c in (original, duplicata)])

    [grupo] = resolucao.grupos
    assert grupo.registros == ("pessoa-000-00:banco_sintetico", "pessoa-000-00:rede_simulada")
    assert grupo.chaves_fortes == ("email:empresa-demo-1.pessoa-000-00@example.invalid",)
    assert grupo.conflito_de_nome is False


def test_perfis_sinteticos_da_demo_juntam_so_as_duplicatas():
    candidatos = gerar(SEMENTE_DEMO, QUANTIDADE_DEMO)
    duplicatas = sum(1 for indice in range(QUANTIDADE_DEMO) if indice % 12 == 7)

    resolucao = resolver([sinais_de_candidato(c) for c in candidatos])

    assert len(resolucao.grupos) == QUANTIDADE_DEMO - duplicatas
    assert sum(1 for g in resolucao.grupos if len(g.registros) > 1) == duplicatas
    assert [g for g in resolucao.grupos if g.conflito_de_nome] == []
    assert resolucao.sugestoes == ()
