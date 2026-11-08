"""Análise e revisão em paralelo: mesma ordem, mesmo limite de gasto e nada refeito ao retomar."""

import random
import threading
import time
from pathlib import Path

import pytest

from backend.agente.auditoria import _contexto
from backend.agente.fluxo import FluxoVaga, concorrencia_do_ambiente
from backend.agente.persistencia import Repositorio
from backend.contratos.erros import (
    LimiteGastoAtingido,
    ModeloIndisponivel,
    RespostaInvalida,
)
from backend.contratos.modelos import EstadoFluxo
from tests.agente.apoio import (
    AnalisadorComEvidencias,
    RevisorSemRessalva,
    candidato_exemplo,
    servico_de_teste,
    vaga_exemplo,
)
from tests.agente.test_fluxo import Montagem, _assinar_fluxo, _decisoes

TEMPO_MAXIMO_S = 5


def _pessoas(quantas: int) -> list:
    return [candidato_exemplo(f"c{i:02d}") for i in range(quantas)]


class _Medidor:
    """Conta quantas chamadas estão em andamento e qual foi o maior número ao mesmo tempo."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self.agora = 0
        self.maximo = 0

    def __enter__(self):
        with self._trava:
            self.agora += 1
            self.maximo = max(self.maximo, self.agora)

    def __exit__(self, *_):
        with self._trava:
            self.agora -= 1


class _AnalisadorEmParalelo(AnalisadorComEvidencias):
    """Espera até `juntos` chamadas estarem em andamento, para provar que elas se sobrepõem."""

    def __init__(self, juntos: int = 1, atraso=lambda: 0.0, **campos) -> None:
        super().__init__(**campos)
        self.medidor = _Medidor()
        self.barreira = threading.Barrier(juntos) if juntos > 1 else None
        self.atraso = atraso
        self.contextos: dict[str, str | None] = {}
        self.trava = threading.Lock()

    def analisar(self, vaga, candidato):
        with self.medidor:
            if self.barreira is not None:
                try:
                    self.barreira.wait(TEMPO_MAXIMO_S)
                except threading.BrokenBarrierError:
                    pass
            time.sleep(self.atraso())
            with self.trava:
                contexto = _contexto.get()
                self.contextos[candidato.id] = contexto.candidato_id if contexto else None
                return super().analisar(vaga, candidato)


class _RevisorEmParalelo(RevisorSemRessalva):
    def __init__(self, atraso=lambda: 0.0) -> None:
        super().__init__()
        self.atraso = atraso
        self.trava = threading.Lock()

    def revisar(self, vaga, candidato, analise):
        time.sleep(self.atraso())
        with self.trava:
            return super().revisar(vaga, candidato, analise)


def test_analises_acontecem_ao_mesmo_tempo_sem_passar_do_limite(tmp_path: Path) -> None:
    analisador = _AnalisadorEmParalelo(juntos=3)
    m = Montagem(tmp_path, _pessoas(9), analisador=analisador, concorrencia=3)

    _assinar_fluxo(m.fluxo(), max_indicacoes=9)

    assert analisador.medidor.maximo == 3
    assert sorted(analisador.analisados) == [f"c{i:02d}" for i in range(9)]


def test_concorrencia_um_nao_sobrepoe_chamadas(tmp_path: Path) -> None:
    analisador = _AnalisadorEmParalelo()
    m = Montagem(tmp_path, _pessoas(4), analisador=analisador)

    _assinar_fluxo(m.fluxo(), max_indicacoes=4)

    assert analisador.medidor.maximo == 1
    assert analisador.analisados == [f"c{i:02d}" for i in range(4)]


@pytest.mark.parametrize("valor", [0, -1])
def test_concorrencia_invalida_e_recusada(tmp_path: Path, valor: int) -> None:
    m = Montagem(tmp_path, [], concorrencia=valor)

    with pytest.raises(ValueError, match="concorrencia"):
        m.fluxo()


@pytest.mark.parametrize(
    ("valor", "esperado"), [(None, 1), ("", 1), ("6", 6)]
)
def test_concorrencia_vem_do_ambiente(monkeypatch, valor, esperado) -> None:
    monkeypatch.delenv("CONCORRENCIA_MODELO", raising=False)
    if valor is not None:
        monkeypatch.setenv("CONCORRENCIA_MODELO", valor)

    assert concorrencia_do_ambiente() == esperado


@pytest.mark.parametrize("valor", ["0", "-2", "muitos"])
def test_concorrencia_invalida_no_ambiente_e_recusada(monkeypatch, valor) -> None:
    monkeypatch.setenv("CONCORRENCIA_MODELO", valor)

    with pytest.raises(ValueError, match="CONCORRENCIA_MODELO"):
        concorrencia_do_ambiente()


def _resultado(tmp_path: Path, nome: str, concorrencia: int, semente: int) -> tuple:
    sorteio = random.Random(semente)
    pasta = tmp_path / nome
    pasta.mkdir()
    notas = {f"c{i:02d}": 0.7 + (i % 4) * 0.1 for i in range(12)}
    analisador = _AnalisadorEmParalelo(atraso=lambda: sorteio.random() / 100, notas=notas)
    m = Montagem(
        pasta,
        _pessoas(12),
        analisador=analisador,
        revisor=_RevisorEmParalelo(lambda: sorteio.random() / 100),
        concorrencia=concorrencia,
    )
    fluxo = m.fluxo()
    _assinar_fluxo(fluxo, max_indicacoes=3)
    decisoes = Repositorio(m.caminho).listar_decisoes("empresa-a", "v1")
    return (
        [(d.candidato_id, d.tipo, d.regra, d.motivo) for d in decisoes],
        list(fluxo._progresso().analises),
        [e.candidato_id for e in fluxo.eventos if e.etapa == "decisao"],
    )


def test_ordem_das_decisoes_nao_depende_da_concorrencia(tmp_path: Path) -> None:
    sequencial = _resultado(tmp_path, "um", 1, 1)

    assert _resultado(tmp_path, "tres", 3, 2) == sequencial
    assert _resultado(tmp_path, "oito", 8, 3) == sequencial


def test_contexto_do_rastro_chega_a_thread_certa(tmp_path: Path) -> None:
    analisador = _AnalisadorEmParalelo(juntos=2)
    m = Montagem(tmp_path, _pessoas(4), analisador=analisador, concorrencia=2)

    _assinar_fluxo(m.fluxo(), max_indicacoes=4)

    assert analisador.contextos == {f"c{i:02d}": f"c{i:02d}" for i in range(4)}


class _GastoPorChamada(_AnalisadorEmParalelo):
    def __init__(self, custo: float, **campos) -> None:
        super().__init__(**campos)
        self.custo = custo
        self.gasto = 0.0

    def analisar(self, vaga, candidato):
        resposta = super().analisar(vaga, candidato)
        with self.trava:
            self.gasto += self.custo
        return resposta


def test_vaga_pausa_no_limite_de_gasto_e_nao_inicia_mais_analises(tmp_path: Path) -> None:
    analisador = _GastoPorChamada(custo=2.0, atraso=lambda: 0.01)
    m = Montagem(
        tmp_path,
        _pessoas(8),
        analisador=analisador,
        concorrencia=2,
        medidor_gasto=lambda: analisador.gasto,
    )
    fluxo = m.fluxo()

    _assinar_fluxo(fluxo)

    assert fluxo.estado is EstadoFluxo.PAUSADA
    assert fluxo._repo.carregar_estado("empresa-a", "v1").motivo == "LIMITE_GASTO"
    assert len(analisador.analisados) <= 4
    assert len(fluxo._progresso().analises) == len(analisador.analisados)


class _FalhaUmaVez(_AnalisadorEmParalelo):
    """Falha na pessoa pedida, uma vez, depois de quem veio depois dela já ter terminado."""

    def __init__(self, alvo: str, erro: Exception, **campos) -> None:
        super().__init__(**campos)
        self.alvo = alvo
        self.erro = erro
        self.terminaram = threading.Event()

    def analisar(self, vaga, candidato):
        if candidato.id == self.alvo and self.erro is not None:
            assert self.terminaram.wait(TEMPO_MAXIMO_S)
            erro, self.erro = self.erro, None
            raise erro
        resposta = super().analisar(vaga, candidato)
        if candidato.id > self.alvo:
            self.terminaram.set()
        return resposta


@pytest.mark.parametrize(
    "erro", [LimiteGastoAtingido("limite"), ModeloIndisponivel("fora do ar")]
)
def test_retomar_nao_paga_de_novo_quem_ja_terminou(tmp_path: Path, erro: Exception) -> None:
    analisador = _FalhaUmaVez("c00", erro)
    m = Montagem(tmp_path, _pessoas(3), analisador=analisador, concorrencia=2)
    fluxo = m.fluxo()

    _assinar_fluxo(fluxo, max_indicacoes=3)

    assert fluxo.estado is EstadoFluxo.PAUSADA
    if isinstance(erro, LimiteGastoAtingido):
        fluxo.assinar_mandato(
            "Pessoa Recrutadora", 9.0, fluxo.mandato.politica, executar=False
        )
    fluxo.retomar()

    assert sorted(analisador.analisados) == ["c00", "c01", "c02"]
    assert sorted(_decisoes(m)) == ["c00", "c01", "c02"]


class _Queda(Exception):
    """Falha fora do previsto, como uma queda do processo no meio da etapa."""


class _RevisorQueCai(_RevisorEmParalelo):
    def __init__(self) -> None:
        super().__init__()
        self.caiu = False

    def revisar(self, vaga, candidato, analise):
        if candidato.id == "c00" and not self.caiu:
            self.caiu = True
            time.sleep(0.05)
            raise _Queda
        return super().revisar(vaga, candidato, analise)


def test_queda_na_revisao_nao_revisa_duas_vezes_quem_ja_terminou(tmp_path: Path) -> None:
    revisor = _RevisorQueCai()
    m = Montagem(tmp_path, _pessoas(3), revisor=revisor, concorrencia=3)
    fluxo = m.fluxo()

    with pytest.raises(_Queda):
        _assinar_fluxo(fluxo, max_indicacoes=3)
    m.fluxo().continuar()

    assert sorted(revisor.revisados) == ["c00", "c01", "c02"]


class _AnalisadorInvalido(_AnalisadorEmParalelo):
    def __init__(self, invalidos: set[str], **campos) -> None:
        super().__init__(**campos)
        self.invalidos = invalidos

    def analisar(self, vaga, candidato):
        if candidato.id in self.invalidos:
            raise RespostaInvalida("resposta fora do esquema")
        return super().analisar(vaga, candidato)


def test_tres_invalidas_seguidas_pausam_na_mesma_pessoa_em_qualquer_concorrencia(
    tmp_path: Path,
) -> None:
    motivos = []
    for concorrencia in (1, 4):
        pasta = tmp_path / str(concorrencia)
        pasta.mkdir()
        analisador = _AnalisadorInvalido({"c01", "c02", "c03"})
        m = Montagem(pasta, _pessoas(6), analisador=analisador, concorrencia=concorrencia)
        fluxo = m.fluxo()
        _assinar_fluxo(fluxo)
        estado = fluxo._repo.carregar_estado("empresa-a", "v1")
        motivos.append((estado.motivo, estado.cursor))

    assert motivos == [("RESPOSTAS_INVALIDAS", 4), ("RESPOSTAS_INVALIDAS", 4)]


def test_parar_no_meio_nao_inicia_as_proximas(tmp_path: Path) -> None:
    fluxos: list[FluxoVaga] = []

    class _Paradora(_AnalisadorEmParalelo):
        def analisar(self, vaga, candidato):
            if candidato.id == "c00":
                fluxos[0].parar()
            return super().analisar(vaga, candidato)

    analisador = _Paradora()
    m = Montagem(tmp_path, _pessoas(8), analisador=analisador, concorrencia=2)
    fluxo = m.fluxo()
    fluxos.append(fluxo)

    _assinar_fluxo(fluxo)

    assert fluxo.estado is EstadoFluxo.PAUSADA
    assert len(analisador.analisados) <= 3


def test_servico_entrega_a_concorrencia_ao_fluxo(tmp_path: Path) -> None:
    servico = servico_de_teste(tmp_path / "agente.db", concorrencia=5)

    assert servico._novo_fluxo(vaga_exemplo())._concorrencia == 5
