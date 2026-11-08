"""A coleta aparece enquanto anda: um evento por consulta e o progresso consultável (8/11).

Perfis fictícios e fonte falsa: nenhum teste usa rede.
"""

import re

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.fluxo import EstadoFluxo, FluxoVaga
from backend.agente.mandato import Politica
from backend.agente.montagem import priorizador_do_funil, tamanho_do_funil
from backend.agente.persistencia import Repositorio
from backend.contratos.simulacoes import (
    BancoTalentosSimulado,
    ClienteNaraSimulado,
    MensageiroSimulado,
)
from backend.modelos.resiliencia import Resiliencia
from tests.agente.apoio import (
    AnalisadorComEvidencias,
    Relogio,
    RevisorSemRessalva,
    servico_de_teste,
    vaga_exemplo,
)
from tests.agente.test_api import OUTRA_EMPRESA, SESSAO, _criar_vaga, _vaga_executada
from tests.agente.test_fluxo_contato_publicado import externo

CONSULTAS = ["python", "APIs", "backend"]


class Queda(Exception):
    """Interrupção do processo no meio da busca."""


class FontePorConsulta:
    """Cada consulta devolve as pessoas listadas para ela, só na primeira página."""

    def __init__(self, por_consulta: dict[str, list[str]], ao_buscar=None) -> None:
        self.por_consulta = por_consulta
        self.ao_buscar = ao_buscar
        self.chamadas: list[str] = []
        self.cair_em: str | None = None

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1):
        self.chamadas.append(consulta)
        if consulta == self.cair_em:
            self.cair_em = None
            raise Queda
        if self.ao_buscar is not None:
            self.ao_buscar()
        if pagina > 1:
            return []
        return [
            externo(c, empresa_id=empresa_id, nome=f"Pessoa Fictícia {c}", perfil_texto="SEGREDO")
            for c in self.por_consulta.get(consulta, [])
        ]


class Pecas:
    def __init__(self, tmp_path, fonte: FontePorConsulta) -> None:
        self.caminho = tmp_path / "agente.db"
        self.fonte = fonte
        self.relogio = Relogio()

    def fluxo(self) -> FluxoVaga:
        return FluxoVaga(
            vaga_exemplo(meta_candidatos=2),
            repositorio=Repositorio(self.caminho),
            banco=BancoTalentosSimulado(),
            fontes=[self.fonte],
            analisador=AnalisadorComEvidencias(),
            revisor=RevisorSemRessalva(),
            mensageiro=MensageiroSimulado(),
            destino=ClienteNaraSimulado(),
            relogio=self.relogio,
            medidor_gasto=lambda: 0.0,
            consultas=lambda vaga, rodada, anteriores: list(CONSULTAS),
            priorizador=priorizador_do_funil(),
            resiliencia=Resiliencia(dormir=lambda _: None),
        )

    def rodar(self) -> FluxoVaga:
        fluxo = self.fluxo()
        fluxo.iniciar()
        politica = Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=3, max_ampliacoes=0)
        fluxo.assinar_mandato("Pessoa Recrutadora", 5.0, politica)
        return fluxo


POR_CONSULTA = {"python": ["a", "b"], "APIs": ["b", "c", "d"], "backend": []}


def _eventos_de_consulta(fluxo: FluxoVaga) -> list[str]:
    return [
        e.mensagem
        for e in fluxo.eventos
        if e.etapa == "busca" and e.mensagem.startswith("consulta ")
    ]


def test_um_evento_busca_por_consulta_na_ordem_e_sem_dado_pessoal(tmp_path):
    pecas = Pecas(tmp_path, FontePorConsulta(POR_CONSULTA))

    fluxo = pecas.rodar()

    mensagens = _eventos_de_consulta(fluxo)
    assert mensagens == [
        'consulta 1 de 3 ("python") em FontePorConsulta: 2 pessoas novas · 2 coletadas até agora',
        'consulta 2 de 3 ("APIs") em FontePorConsulta: 2 pessoas novas · 4 coletadas até agora',
        'consulta 3 de 3 ("backend") em FontePorConsulta: 0 pessoas novas · 4 coletadas até agora',
    ]
    texto = " ".join(mensagens)
    assert "SEGREDO" not in texto and "Fictícia" not in texto
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", texto)


def test_andamento_avanca_a_cada_consulta_e_fica_gravado(tmp_path):
    vistos: list[tuple[int, int, int]] = []
    pecas = Pecas(tmp_path, FontePorConsulta(POR_CONSULTA))

    def olhar() -> None:
        andamento = pecas.fluxo().andamento_da_busca()
        vistos.append((andamento.consultas_feitas, andamento.consultas_total, andamento.coletados))

    pecas.fonte.ao_buscar = olhar
    fluxo = pecas.rodar()

    assert vistos == [(0, 3, 0), (1, 3, 2), (2, 3, 4)]
    final = fluxo.andamento_da_busca()
    assert (final.consultas_feitas, final.consultas_total, final.coletados) == (3, 3, 4)
    assert final.ultima_fonte == "FontePorConsulta"
    assert final.atualizado_em == pecas.relogio()


def test_queda_no_meio_da_busca_nao_duplica_nem_perde_pessoas(tmp_path):
    fonte = FontePorConsulta(POR_CONSULTA)
    fonte.cair_em = "APIs"
    pecas = Pecas(tmp_path, fonte)

    with pytest.raises(Queda):
        pecas.rodar()
    caido = pecas.fluxo()
    assert caido.estado is EstadoFluxo.BUSCANDO
    assert caido.andamento_da_busca().consultas_feitas == 1

    retomado = pecas.fluxo()
    retomado.continuar()

    ids = [c.id for c, _, _ in retomado.situacao_candidatos()]
    assert sorted(ids) == ["a", "b", "c", "d"]
    assert len(ids) == len(set(ids))
    analisados = retomado._progresso().analises
    assert sorted(analisados) == ["a", "b", "c", "d"]
    andamento = retomado.andamento_da_busca()
    assert (andamento.consultas_feitas, andamento.coletados) == (3, 4)


def test_vaga_sem_mandato_tem_andamento_zerado(tmp_path):
    pecas = Pecas(tmp_path, FontePorConsulta(POR_CONSULTA))
    fluxo = pecas.fluxo()
    fluxo.iniciar()

    andamento = fluxo.andamento_da_busca()

    assert (andamento.consultas_feitas, andamento.consultas_total, andamento.coletados) == (
        0,
        0,
        0,
    )
    assert andamento.ultima_fonte is None
    assert andamento.atualizado_em == pecas.relogio()


@pytest.fixture
def cliente(tmp_path) -> TestClient:
    return TestClient(criar_app(servico_de_teste(tmp_path / "agente.db")))


def test_rota_de_progresso_traz_o_andamento_e_o_funil(cliente):
    vaga = _vaga_executada(cliente)

    resposta = cliente.get(f"/vagas/{vaga}/progresso", headers=SESSAO)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["simulado"] is True
    assert corpo["exemplo_fixo"] is False
    progresso = corpo["progresso"]
    assert set(progresso) == {
        "vaga_id",
        "estado",
        "consultas_feitas",
        "consultas_total",
        "coletados",
        "funil",
        "ultima_fonte",
        "atualizado_em",
    }
    assert progresso["vaga_id"] == vaga
    assert progresso["consultas_total"] >= 1
    assert progresso["consultas_feitas"] == progresso["consultas_total"]
    assert progresso["coletados"] >= 1
    assert progresso["funil"] == tamanho_do_funil(1)
    assert progresso["ultima_fonte"] == "FonteSimulada"
    assert progresso["estado"] != "buscando"
    assert progresso["atualizado_em"]


def test_rota_de_progresso_antes_da_busca_vem_zerada(cliente):
    vaga = _criar_vaga(cliente)

    progresso = cliente.get(f"/vagas/{vaga}/progresso", headers=SESSAO).json()["progresso"]

    assert progresso["estado"] == "aguardando_mandato"
    assert (progresso["consultas_feitas"], progresso["coletados"]) == (0, 0)
    assert progresso["ultima_fonte"] is None


def test_rota_de_progresso_e_isolada_por_empresa(cliente):
    vaga = _vaga_executada(cliente)

    resposta = cliente.get(f"/vagas/{vaga}/progresso", headers=OUTRA_EMPRESA)

    assert resposta.status_code == 404
    assert "progresso" not in resposta.json()
