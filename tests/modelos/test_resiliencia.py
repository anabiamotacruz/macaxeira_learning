"""Testes de resiliência. Espera e relógio são injetados: nada depende do tempo real."""

import pytest

from backend.contratos.erros import (
    FonteIndisponivel,
    LimiteGastoAtingido,
    ModeloIndisponivel,
    RespostaInvalida,
)
from backend.modelos.resiliencia import com_tentativas


class Instavel:
    """Falha com os erros dados, na ordem, e depois devolve `resultado`."""

    def __init__(self, *erros: Exception, resultado: str = "ok") -> None:
        self.erros = list(erros)
        self.resultado = resultado
        self.chamadas = 0

    def __call__(self) -> str:
        self.chamadas += 1
        if self.erros:
            raise self.erros.pop(0)
        return self.resultado


class Espera:
    def __init__(self) -> None:
        self.pedidas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.pedidas.append(segundos)


def test_repete_erro_temporario_com_espera():
    funcao = Instavel(ConnectionError("queda"), FonteIndisponivel("fora do ar"))
    espera = Espera()

    resultado = com_tentativas(funcao, tentativas=3, espera=1.0, dormir=espera)

    assert resultado == "ok"
    assert funcao.chamadas == 3
    assert espera.pedidas == [1.0, 2.0]


def test_sucesso_de_primeira_nao_espera():
    funcao, espera = Instavel(), Espera()

    assert com_tentativas(funcao, dormir=espera) == "ok"
    assert espera.pedidas == []


def test_esgotadas_as_tentativas_levanta_o_ultimo_erro():
    ultimo = FonteIndisponivel("segunda falha")
    funcao, espera = Instavel(FonteIndisponivel("primeira falha"), ultimo), Espera()

    with pytest.raises(FonteIndisponivel) as erro:
        com_tentativas(funcao, tentativas=2, espera=1.0, dormir=espera)

    assert erro.value is ultimo
    assert funcao.chamadas == 2
    assert espera.pedidas == [1.0]


@pytest.mark.parametrize(
    "permanente",
    [
        ValueError("dado errado"),
        RespostaInvalida("fora do esquema"),
        LimiteGastoAtingido("sem verba"),
        ModeloIndisponivel("sem modelo"),
    ],
)
def test_nao_repete_erro_permanente(permanente):
    funcao, espera = Instavel(permanente), Espera()

    with pytest.raises(type(permanente)):
        com_tentativas(funcao, tentativas=3, dormir=espera)

    assert funcao.chamadas == 1
    assert espera.pedidas == []


def test_lista_de_erros_temporarios_pode_ser_trocada():
    class ErroDaFonte(Exception):
        pass

    funcao, espera = Instavel(ErroDaFonte()), Espera()

    assert com_tentativas(funcao, temporarios=(ErroDaFonte,), dormir=espera) == "ok"

    with pytest.raises(ConnectionError):
        com_tentativas(Instavel(ConnectionError()), temporarios=(ErroDaFonte,), dormir=espera)


@pytest.mark.parametrize(
    "opcoes",
    [{"tentativas": 0}, {"espera": -1.0}],
)
def test_parametros_invalidos_sao_recusados(opcoes):
    funcao = Instavel()

    with pytest.raises(ValueError):
        com_tentativas(funcao, **opcoes)

    assert funcao.chamadas == 0
