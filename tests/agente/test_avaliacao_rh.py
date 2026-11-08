"""Avaliação às cegas pela pessoa de RH (T1.13; spec 005, T047 a T049). Sem modelo."""

from collections import Counter
from pathlib import Path

import pytest

from backend.agente.avaliacao_rh import (
    PERGUNTA,
    SEM_TIPO,
    AvaliacaoHumana,
    DecisaoHumana,
    Ficha,
    RespostaIncompleta,
    gerar_fichas,
    importar_avaliacoes,
    medir_concordancia,
    sortear,
)
from backend.agente.medicao import ler_casos
from backend.contratos.modelos import Particao, TipoDecisao

DADOS = Path(__file__).resolve().parents[2] / "dados" / "sinteticos"
SEMENTE = 7
EQUIVALENTE = {
    TipoDecisao.INDICAR: DecisaoHumana.ENCAMINHAR,
    TipoDecisao.PEDIR_HUMANO: DecisaoHumana.MAIS_INFORMACAO,
    TipoDecisao.DESCARTAR: DecisaoHumana.NAO_ENCAMINHAR,
}


@pytest.fixture(scope="module")
def casos():
    return ler_casos(DADOS)


def _resposta(codigo: str, decisao: DecisaoHumana, **campos) -> dict:
    dados = {
        "codigo": codigo,
        "decisao": decisao.value,
        "seguranca": 4,
        "criterio_decisivo": "requisito eliminatório",
        "motivo": "requisito_atendido",
        "comentario": "",
        "tempo_s": 95.0,
    }
    dados.update(campos)
    return dados


def _concorda_com_tudo(sessao) -> list[AvaliacaoHumana]:
    return importar_avaliacoes(
        [_resposta(item.codigo, EQUIVALENTE[item.gabarito]) for item in sessao]
    )


def test_ficha_nao_mostra_gabarito_nem_resposta_do_agente(casos):
    sessao = sortear(casos, SEMENTE)
    fichas = gerar_fichas(casos, SEMENTE)
    por_id = {caso.id: caso for caso in casos}

    assert set(Ficha.model_fields) == {
        "codigo",
        "pergunta",
        "vaga_titulo",
        "requisitos",
        "competencias",
        "perfil",
    }
    for ficha, item in zip(fichas, sessao, strict=True):
        assert ficha.pergunta == PERGUNTA
        texto = ficha.model_dump_json().casefold()
        caso = por_id[item.caso_id]
        assert caso.perfil.nome.casefold() not in texto
        assert caso.id.casefold() not in texto
        assert caso.perfil.id.casefold() not in texto
        for proibido in ("indicar", "pedir_humano", "descartar", "ajuste", "prova", "validacao"):
            assert f'"{proibido}"' not in texto
        assert caso.motivo_gabarito.casefold() not in texto


def test_selecao_e_reproduzivel_e_respeita_as_particoes(casos):
    sessao = sortear(casos, SEMENTE)
    particao = {caso.id: caso.particao for caso in casos}

    assert sortear(casos, SEMENTE) == sessao
    assert gerar_fichas(casos, SEMENTE) == gerar_fichas(casos, SEMENTE)
    assert sortear(casos, SEMENTE + 1) != sessao
    assert len(sessao) == 34
    originais = [item for item in sessao if item.duplicata_de is None]
    duplicatas = [item for item in sessao if item.duplicata_de is not None]
    assert Counter(item.particao for item in originais) == {Particao.AJUSTE: 12, Particao.PROVA: 18}
    assert len(duplicatas) == 4
    assert all(particao[item.caso_id] == item.particao for item in sessao)
    assert Particao.VALIDACAO not in {item.particao for item in sessao}
    assert len({item.codigo for item in sessao}) == 34
    codigos = {item.codigo: item.caso_id for item in originais}
    assert all(codigos[item.duplicata_de] == item.caso_id for item in duplicatas)


def test_sorteio_recusa_casos_insuficientes(casos):
    poucos = [caso for caso in casos if caso.particao == Particao.AJUSTE][:5]

    with pytest.raises(ValueError):
        sortear(poucos, SEMENTE)


def test_importacao_guarda_decisao_e_motivo():
    [avaliacao] = importar_avaliacoes(
        [
            _resposta(
                "F01",
                DecisaoHumana.MAIS_INFORMACAO,
                seguranca=2,
                criterio_decisivo="experiência em produção",
                motivo="dado_ausente",
                comentario="Não diz por quanto tempo.",
                tempo_s=130,
            )
        ]
    )

    assert avaliacao.codigo == "F01"
    assert avaliacao.decisao == DecisaoHumana.MAIS_INFORMACAO
    assert avaliacao.seguranca == 2
    assert avaliacao.criterio_decisivo == "experiência em produção"
    assert avaliacao.motivo == "dado_ausente"
    assert avaliacao.comentario == "Não diz por quanto tempo."
    assert avaliacao.tempo_s == 130


@pytest.mark.parametrize(
    "estrago",
    [
        {"seguranca": None},
        {"seguranca": 9},
        {"criterio_decisivo": "  "},
        {"motivo": "porque sim"},
        {"comentario": "x" * 201},
        {"tempo_s": 0},
        {"decisao": "talvez"},
    ],
)
def test_resposta_incompleta_e_recusada(estrago):
    resposta = _resposta("F01", DecisaoHumana.ENCAMINHAR)
    resposta.update(estrago)
    resposta = {chave: valor for chave, valor in resposta.items() if valor is not None}

    with pytest.raises(RespostaIncompleta):
        importar_avaliacoes([resposta])


def test_codigo_repetido_e_recusado():
    resposta = _resposta("F01", DecisaoHumana.ENCAMINHAR)

    with pytest.raises(RespostaIncompleta):
        importar_avaliacoes([resposta, dict(resposta)])


def test_mede_concordancia_por_tipo_de_caso(casos):
    sessao = sortear(casos, SEMENTE)
    avaliacoes = _concorda_com_tudo(sessao)
    alvo = next(
        item
        for item in sessao
        if item.particao == Particao.AJUSTE
        and item.duplicata_de is None
        and all(outro.duplicata_de != item.codigo for outro in sessao)
    )
    trocada = DecisaoHumana.NAO_ENCAMINHAR
    if EQUIVALENTE[alvo.gabarito] == trocada:
        trocada = DecisaoHumana.ENCAMINHAR
    avaliacoes = [
        a.model_copy(update={"decisao": trocada}) if a.codigo == alvo.codigo else a
        for a in avaliacoes
    ]

    resultado = medir_concordancia(avaliacoes, sessao)

    avaliadas = 30
    assert resultado.geral.total == avaliadas
    assert resultado.geral.concordancia == pytest.approx((avaliadas - 1) / avaliadas)
    baixo, alto = resultado.geral.intervalo
    assert baixo < resultado.geral.concordancia < alto
    assert 0 < resultado.kappa < 1
    tipo = alvo.armadilha or SEM_TIPO
    assert resultado.por_tipo[tipo].concordancia < 1
    outros = [t for t in resultado.por_tipo if t != tipo]
    assert all(resultado.por_tipo[t].concordancia == 1 for t in outros)
    assert resultado.discordancias_ajuste == [alvo.codigo]


def test_nao_consigo_avaliar_sai_da_conta_e_e_contado(casos):
    sessao = sortear(casos, SEMENTE)
    avaliacoes = _concorda_com_tudo(sessao)
    primeira = next(item for item in sessao if item.duplicata_de is None)
    avaliacoes = [
        a.model_copy(update={"decisao": DecisaoHumana.NAO_CONSIGO})
        if a.codigo == primeira.codigo
        else a
        for a in avaliacoes
    ]

    resultado = medir_concordancia(avaliacoes, sessao)

    assert resultado.excluidas == 1
    assert resultado.geral.total == 29
    assert resultado.geral.concordancia == 1


def test_duplicatas_medem_consistencia(casos):
    sessao = sortear(casos, SEMENTE)
    avaliacoes = _concorda_com_tudo(sessao)
    duplicata = next(item for item in sessao if item.duplicata_de is not None)
    avaliacoes = [
        a.model_copy(update={"decisao": DecisaoHumana.NAO_CONSIGO})
        if a.codigo == duplicata.codigo
        else a
        for a in avaliacoes
    ]
    outra = next(item for item in sessao if item.duplicata_de is not None and item is not duplicata)
    original = next(a for a in avaliacoes if a.codigo == outra.duplicata_de)
    diferente = next(
        d for d in DecisaoHumana if d not in (original.decisao, DecisaoHumana.NAO_CONSIGO)
    )
    avaliacoes = [
        a.model_copy(update={"decisao": diferente}) if a.codigo == outra.codigo else a
        for a in avaliacoes
    ]

    resultado = medir_concordancia(avaliacoes, sessao)

    assert resultado.consistencia.total == 3
    assert resultado.consistencia.concordancia == pytest.approx(2 / 3)
    assert resultado.geral.total == 30


def test_discordancias_da_prova_nao_saem_caso_a_caso(casos):
    sessao = sortear(casos, SEMENTE)
    da_prova = [
        item for item in sessao if item.particao == Particao.PROVA and not item.duplicata_de
    ]
    erradas = {item.codigo for item in da_prova[:3]}
    avaliacoes = _concorda_com_tudo(sessao)
    trocar = {
        item.codigo: next(
            d
            for d in DecisaoHumana
            if d not in (EQUIVALENTE[item.gabarito], DecisaoHumana.NAO_CONSIGO)
        )
        for item in da_prova[:3]
    }
    avaliacoes = [
        a.model_copy(update={"decisao": trocar[a.codigo]}) if a.codigo in trocar else a
        for a in avaliacoes
    ]

    resultado = medir_concordancia(avaliacoes, sessao)
    texto = resultado.model_dump_json()

    assert resultado.discordancias_ajuste == []
    assert resultado.prova.total == 18
    assert resultado.prova.concordancia == pytest.approx(15 / 18)
    assert not any(codigo in texto for codigo in erradas)


def test_avaliacao_de_codigo_fora_da_sessao_e_recusada(casos):
    sessao = sortear(casos, SEMENTE)
    avaliacoes = importar_avaliacoes([_resposta("X99", DecisaoHumana.ENCAMINHAR)])

    with pytest.raises(RespostaIncompleta):
        medir_concordancia(avaliacoes, sessao)
