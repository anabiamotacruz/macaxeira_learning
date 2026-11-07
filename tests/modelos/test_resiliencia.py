"""Testes de resiliência. Espera e relógio são injetados: nada depende do tempo real."""

import pytest

from backend.contratos.erros import (
    FonteIndisponivel,
    LimiteGastoAtingido,
    ModeloIndisponivel,
    RespostaInvalida,
)
from backend.modelos.resiliencia import (
    TEMPO_LIMITE_PADRAO_S,
    DisjuntorFonte,
    EstadoDisjuntor,
    TempoLimiteExcedido,
    com_tentativas,
)


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
    [{"tentativas": 0}, {"espera": -1.0}, {"tempo_limite": 0.0}],
)
def test_parametros_invalidos_sao_recusados(opcoes):
    funcao = Instavel()

    with pytest.raises(ValueError):
        com_tentativas(funcao, **opcoes)

    assert funcao.chamadas == 0


class Relogio:
    def __init__(self) -> None:
        self.agora = 100.0

    def __call__(self) -> float:
        return self.agora


def funcao_lenta(relogio: Relogio, segundos: float, resultado: str = "ok"):
    def executar() -> str:
        relogio.agora += segundos
        return resultado

    return executar


def test_tempo_limite_gera_erro_claro():
    relogio = Relogio()

    with pytest.raises(TempoLimiteExcedido) as erro:
        com_tentativas(
            funcao_lenta(relogio, 31.0),
            tentativas=1,
            etapa="busca_github",
            relogio=relogio,
        )

    assert TEMPO_LIMITE_PADRAO_S == 30.0
    assert "busca_github" in str(erro.value)
    assert "30" in str(erro.value)


def test_dentro_do_limite_devolve_o_resultado():
    relogio = Relogio()

    assert com_tentativas(funcao_lenta(relogio, 30.0), relogio=relogio) == "ok"


def test_tempo_esgotado_no_cliente_http_vira_erro_claro():
    funcao, espera = Instavel(TimeoutError("httpx"), TimeoutError("httpx")), Espera()

    with pytest.raises(TempoLimiteExcedido) as erro:
        com_tentativas(funcao, tentativas=2, tempo_limite=5.0, etapa="analise", dormir=espera)

    assert funcao.chamadas == 2
    assert "analise" in str(erro.value)
    assert "5" in str(erro.value)
    assert erro.value.__context__ is None


def test_tempo_limite_e_temporario_e_repete():
    relogio, espera = Relogio(), Espera()
    atrasos = iter([31.0, 1.0])

    def as_vezes_lenta() -> str:
        relogio.agora += next(atrasos)
        return "ok"

    assert com_tentativas(as_vezes_lenta, relogio=relogio, dormir=espera) == "ok"
    assert espera.pedidas == [1.0]


def test_tempo_esgotado_repete_mesmo_fora_da_lista_de_temporarios():
    class ErroDaFonte(Exception):
        pass

    funcao, espera = Instavel(TimeoutError()), Espera()

    assert com_tentativas(funcao, temporarios=(ErroDaFonte,), dormir=espera) == "ok"


def disjuntor_com(relogio: Relogio, limite_falhas: int = 2, espera: float = 60.0) -> DisjuntorFonte:
    return DisjuntorFonte("github", limite_falhas=limite_falhas, espera=espera, relogio=relogio)


def derrubar(disjuntor: DisjuntorFonte, vezes: int = 2) -> None:
    for _ in range(vezes):
        with pytest.raises(ConnectionError):
            disjuntor.chamar(Instavel(ConnectionError("queda")))


def test_disjuntor_abre_e_fecha():
    relogio = Relogio()
    disjuntor = disjuntor_com(relogio)
    assert disjuntor.estado is EstadoDisjuntor.FECHADO

    derrubar(disjuntor, vezes=1)
    assert disjuntor.estado is EstadoDisjuntor.FECHADO

    derrubar(disjuntor, vezes=1)
    assert disjuntor.estado is EstadoDisjuntor.ABERTO

    relogio.agora += 60.0
    assert disjuntor.estado is EstadoDisjuntor.MEIO_ABERTO

    assert disjuntor.chamar(Instavel()) == "ok"
    assert disjuntor.estado is EstadoDisjuntor.FECHADO


def test_disjuntor_aberto_nao_chama_a_fonte():
    relogio = Relogio()
    disjuntor = disjuntor_com(relogio)
    derrubar(disjuntor)
    funcao = Instavel()

    with pytest.raises(FonteIndisponivel) as erro:
        disjuntor.chamar(funcao)

    assert funcao.chamadas == 0
    assert "github" in str(erro.value)


def test_falha_no_meio_aberto_reabre_e_recomeca_a_espera():
    relogio = Relogio()
    disjuntor = disjuntor_com(relogio, limite_falhas=3)
    derrubar(disjuntor, vezes=3)
    relogio.agora += 60.0

    derrubar(disjuntor, vezes=1)

    assert disjuntor.estado is EstadoDisjuntor.ABERTO
    relogio.agora += 59.0
    assert disjuntor.estado is EstadoDisjuntor.ABERTO
    relogio.agora += 1.0
    assert disjuntor.estado is EstadoDisjuntor.MEIO_ABERTO


def test_meio_aberto_deixa_passar_um_teste_por_vez():
    relogio = Relogio()
    disjuntor = disjuntor_com(relogio)
    derrubar(disjuntor)
    relogio.agora += 60.0
    outra = Instavel()

    def teste_em_andamento() -> str:
        with pytest.raises(FonteIndisponivel):
            disjuntor.chamar(outra)
        return "ok"

    assert disjuntor.chamar(teste_em_andamento) == "ok"
    assert outra.chamadas == 0


def test_sucesso_zera_as_falhas_seguidas():
    disjuntor = disjuntor_com(Relogio())

    derrubar(disjuntor, vezes=1)
    disjuntor.chamar(Instavel())
    derrubar(disjuntor, vezes=1)

    assert disjuntor.estado is EstadoDisjuntor.FECHADO


def test_erro_permanente_nao_abre_o_disjuntor():
    disjuntor = disjuntor_com(Relogio(), limite_falhas=1)

    with pytest.raises(ValueError):
        disjuntor.chamar(Instavel(ValueError("dado errado")))

    assert disjuntor.estado is EstadoDisjuntor.FECHADO


def test_erro_permanente_no_meio_aberto_libera_novo_teste():
    relogio = Relogio()
    disjuntor = disjuntor_com(relogio)
    derrubar(disjuntor)
    relogio.agora += 60.0

    with pytest.raises(ValueError):
        disjuntor.chamar(Instavel(ValueError("dado errado")))

    assert disjuntor.estado is EstadoDisjuntor.MEIO_ABERTO
    assert disjuntor.chamar(Instavel()) == "ok"
    assert disjuntor.estado is EstadoDisjuntor.FECHADO


def test_tempo_limite_conta_como_falha_e_repeticoes_contam_uma_vez():
    relogio, espera = Relogio(), Espera()
    disjuntor = disjuntor_com(relogio)

    def chamar(funcao: Instavel) -> str:
        return disjuntor.chamar(lambda: com_tentativas(funcao, tentativas=2, dormir=espera))

    with pytest.raises(TempoLimiteExcedido):
        chamar(Instavel(TimeoutError(), TimeoutError()))
    assert disjuntor.estado is EstadoDisjuntor.FECHADO

    with pytest.raises(TempoLimiteExcedido):
        chamar(Instavel(TimeoutError(), TimeoutError()))
    assert disjuntor.estado is EstadoDisjuntor.ABERTO


@pytest.mark.parametrize(
    "opcoes",
    [{"limite_falhas": 0}, {"espera": 0.0}, {"fonte": " "}],
)
def test_disjuntor_recusa_parametros_invalidos(opcoes):
    with pytest.raises(ValueError):
        DisjuntorFonte(**{"fonte": "github", **opcoes})
