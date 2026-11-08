"""Da criação da vaga à entrega, pela API, com o funil e o banco reais e simulações no resto."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import consultas_por_modelo, montar_demo, priorizador_do_funil
from backend.agente.persistencia import Repositorio
from backend.agente.servico import DependenciasFluxo, ServicoVagas
from backend.contratos.modelos import RespostaCandidato, TipoResposta
from backend.contratos.simulacoes import (
    AnalisadorSimulado,
    ClienteModeloSimulado,
    ClienteNaraSimulado,
    FonteSimulada,
    MensageiroSimulado,
    RevisorSimulado,
)
from backend.fontes.banco_talentos import BancoTalentos
from backend.fontes.consultas import ETAPA_GERAR
from backend.modelos.resiliencia import Resiliencia
from tests.agente.apoio import PEDIDO_VAGA, Relogio, candidato_exemplo

SESSAO = {"X-Empresa-Id": "empresa-a"}
OUTRA_EMPRESA = {"X-Empresa-Id": "empresa-b"}
PESSOA = "Pessoa Responsável Fictícia"
PERFIL = "Cinco anos de Python em APIs"


def _mandato(**politica) -> dict:
    return {
        "assinante": PESSOA,
        "limite_gasto_usd": 5.0,
        "politica": {
            "limiar_verde": 0.5,
            "piso_nota": 0.3,
            "max_indicacoes": 2,
            "max_ampliacoes": 1,
            **politica,
        },
    }


def _pessoa(candidato_id: str, **campos):
    dados = {
        "nome": f"Pessoa Fictícia {candidato_id}",
        "perfil_texto": PERFIL,
        "atributos": {"linguagem": "python"},
    }
    return candidato_exemplo(candidato_id, **{**dados, **campos})


class Cenario:
    def __init__(self, caminho, destino=None, fonte=None) -> None:
        self.banco = BancoTalentos(hoje=date(2026, 11, 7), confiar_autorizacao_sintetica=True)
        self.fonte = fonte or FonteSimulada(
            [
                _pessoa("verde"),
                _pessoa("java", atributos={"linguagem": "java"}),
                _pessoa("saiu", opt_out=True),
            ]
        )
        self.mensageiro = MensageiroSimulado()
        self.destino = destino or ClienteNaraSimulado()
        self.modelo = ClienteModeloSimulado({ETAPA_GERAR: {"consultas": ["python"]}})
        self.relogio = Relogio()
        self.servico = ServicoVagas(
            DependenciasFluxo(
                repositorio=Repositorio(caminho),
                banco=self.banco,
                fontes=[self.fonte],
                analisador=AnalisadorSimulado(),
                revisor=RevisorSimulado(),
                mensageiro=self.mensageiro,
                destino=self.destino,
                relogio=self.relogio,
                medidor_gasto=lambda: 0.0,
                consultas=consultas_por_modelo(self.modelo),
                priorizador=priorizador_do_funil(),
                resiliencia=Resiliencia(dormir=lambda _: None),
            )
        )
        self.cliente = TestClient(criar_app(self.servico))

    def criar(self, **pedido) -> str:
        resposta = self.cliente.post("/vagas", headers=SESSAO, json={**PEDIDO_VAGA, **pedido})
        assert resposta.status_code == 201, resposta.text
        return resposta.json()["vaga"]["id"]

    def assinar(self, vaga: str, **politica) -> dict:
        resposta = self.cliente.post(
            f"/vagas/{vaga}/mandato", headers=SESSAO, json=_mandato(**politica)
        )
        assert resposta.status_code == 201, resposta.text
        return resposta.json()

    def obter(self, caminho: str, **parametros) -> dict:
        resposta = self.cliente.get(caminho, headers=SESSAO, params=parametros)
        assert resposta.status_code == 200, resposta.text
        return resposta.json()


@pytest.fixture
def cenario(tmp_path) -> Cenario:
    return Cenario(tmp_path / "agente.db")


def test_vaga_vai_da_criacao_a_entrega_na_decisao(cenario):
    vaga = cenario.criar()
    assert cenario.obter(f"/vagas/{vaga}")["estado"] == "aguardando_mandato"

    assinatura = cenario.assinar(vaga, modo_entrega="na_decisao")
    assert assinatura["estado"] == "buscando"

    situacao = cenario.obter(f"/vagas/{vaga}")
    assert situacao["estado"] == "concluida"
    assert situacao["vaga"]["aprovada"] is True

    itens = cenario.obter(f"/vagas/{vaga}/candidatos")["itens"]
    assert {i["candidato"]["id"]: i["decisao"] for i in itens} == {
        "verde": "indicar",
        "java": "descartar",
        "saiu": "descartar",
    }
    assert all(i["candidato"]["simulado"] is True for i in itens)

    saida = cenario.obter(f"/vagas/{vaga}/entrega")["saida"]
    assert saida["simulado"] is True
    assert [p["candidato_id"] for p in saida["pacotes"]] == ["verde"]
    pacote = saida["pacotes"][0]
    assert pacote["simulado"] is True
    assert pacote["evidencias"]
    assert [p.candidato_id for p in cenario.destino.entregues.values()] == ["verde"]
    assert (
        pacote["chave_idempotencia"]
        == next(iter(cenario.destino.entregues.values())).chave_idempotencia
    )

    decisao = cenario.obter("/candidatos/verde/decisao", vaga_id=vaga)["decisao"]
    assert decisao["regra"] == "faixa_verde_v1"
    assert decisao["rastro_id"] == pacote["rastro_id"]
    assert ":assinante:" in decisao["responsavel"]

    descarte = cenario.obter("/candidatos/java/decisao", vaga_id=vaga)["decisao"]
    assert descarte["regra"] == "funil:requisito_nao_atendido"
    assert "python" in descarte["motivo"]

    resumo = cenario.obter(f"/vagas/{vaga}/resumo")["resumo"]
    assert (resumo["analisados"], resumo["indicados"], resumo["descartados"]) == (1, 1, 2)
    assert resumo["estado"] == "concluida"

    etapas = [e["etapa"] for e in cenario.obter(f"/vagas/{vaga}/eventos", limite=100)["itens"]]
    for etapa in ("buscando", "analisando", "revisando", "decidindo", "entregando", "concluida"):
        assert etapa in etapas


def test_entrega_depois_do_aceite_passa_pelo_convite_simulado(cenario):
    vaga = cenario.criar()
    cenario.assinar(vaga)

    assert cenario.obter(f"/vagas/{vaga}")["estado"] == "convidando"
    assert cenario.destino.entregues == {}
    convite = next(iter(cenario.mensageiro.enviados.values()))
    assert convite.simulado is True
    assert cenario.obter(f"/vagas/{vaga}/entrega")["saida"]["pacotes"] == []

    cenario.servico.registrar_resposta(
        "empresa-a",
        vaga,
        RespostaCandidato(convite_id=convite.id, tipo=TipoResposta.ACEITE),
    )

    assert cenario.obter(f"/vagas/{vaga}")["estado"] == "concluida"
    assert [
        p["candidato_id"] for p in cenario.obter(f"/vagas/{vaga}/entrega")["saida"]["pacotes"]
    ] == ["verde"]


def test_outra_empresa_nao_ve_nada_da_vaga(cenario):
    vaga = cenario.criar()
    cenario.assinar(vaga, modo_entrega="na_decisao")

    for caminho in (
        f"/vagas/{vaga}",
        f"/vagas/{vaga}/candidatos",
        f"/vagas/{vaga}/eventos",
        f"/vagas/{vaga}/entrega",
        f"/vagas/{vaga}/resumo",
        "/candidatos/verde/decisao",
    ):
        assert cenario.cliente.get(caminho, headers=OUTRA_EMPRESA).status_code == 404


def test_destino_fora_do_ar_pausa_e_retomar_entrega_uma_vez(tmp_path):
    class DestinoInstavel(ClienteNaraSimulado):
        fora = True

        def entregar(self, pacote):
            if self.fora:
                return False
            return super().entregar(pacote)

    destino = DestinoInstavel()
    cenario = Cenario(tmp_path / "agente.db", destino=destino)
    vaga = cenario.criar()
    cenario.assinar(vaga, modo_entrega="na_decisao")
    assert cenario.obter(f"/vagas/{vaga}")["estado"] == "pausada"
    assert cenario.obter(f"/vagas/{vaga}/entrega")["saida"]["pacotes"] == []

    destino.fora = False
    resposta = cenario.cliente.post(
        f"/vagas/{vaga}/retomar",
        headers=SESSAO,
        json={"responsavel": PESSOA, "chave_idempotencia": "retomar-1"},
    )

    assert resposta.json()["estado"] == "entregando"
    assert cenario.obter(f"/vagas/{vaga}")["estado"] == "concluida"
    assert len(destino.entregues) == 1


def test_fonte_fora_do_ar_nao_impede_o_banco_e_fica_na_cobertura(tmp_path):
    fonte = FonteSimulada([])
    fonte.falhar = True
    cenario = Cenario(tmp_path / "agente.db", fonte=fonte)
    registros = [
        {
            "id": "do-banco",
            "nome": "Pessoa Fictícia do banco",
            "fonte": "banco",
            "simulado": True,
            "origem": "importacao",
            "atualizado_em": "2026-11-01",
            "autorizacao_valida_ate": "2027-11-01",
            "estado": "ativo",
            "perfil_texto": PERFIL,
            "atributos": {"linguagem": "python"},
            "historico": [],
            "autorizou_contato": True,
        }
    ]
    cenario.banco.importar("empresa-a", registros)
    vaga = cenario.criar()

    cenario.assinar(vaga, aceitar_declarada=True, modo_entrega="na_decisao")

    eventos = cenario.obter(f"/vagas/{vaga}/eventos", limite=100)["itens"]
    assert any("cobertura parcial" in e["mensagem"] for e in eventos)
    assert cenario.obter(f"/vagas/{vaga}")["estado"] == "concluida"
    assert [p.candidato_id for p in cenario.destino.entregues.values()] == ["do-banco"]


def test_aplicacao_de_demonstracao_funciona_sem_nenhuma_chave(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    cliente = TestClient(criar_app(montar_demo(tmp_path / "demo.db")))

    # A demo usa as vagas e os perfis sintéticos da Frente 2. O banco é autodeclarado, então o
    # mandato precisa aceitar evidência declarada para alguém entrar na faixa verde.
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    criada = cliente.post("/vagas", headers=SESSAO, json={**modelo, "meta_candidatos": 2}).json()
    vaga = criada["vaga"]["id"]
    assinada = cliente.post(
        f"/vagas/{vaga}/mandato",
        headers=SESSAO,
        json=_mandato(limiar_verde=0.8, modo_entrega="na_decisao", aceitar_declarada=True),
    )

    assert assinada.status_code == 201, assinada.text
    consulta = cliente.get(f"/vagas/{vaga}", headers=SESSAO).json()
    assert consulta["simulado"] is True
    assert consulta["estado"] == "concluida"
    entrega = cliente.get(f"/vagas/{vaga}/entrega", headers=SESSAO).json()["saida"]
    assert entrega["simulado"] is True
    assert entrega["pacotes"]
    assert all(p["simulado"] is True for p in entrega["pacotes"])


def test_demonstracao_reinicia_so_a_empresa_da_sessao_e_recarrega(tmp_path):
    cliente = TestClient(criar_app(montar_demo(tmp_path / "demo.db")))
    daqui = cliente.post("/vagas", headers=SESSAO, json=PEDIDO_VAGA).json()["vaga"]["id"]
    de_la = cliente.post("/vagas", headers=OUTRA_EMPRESA, json=PEDIDO_VAGA).json()["vaga"]["id"]

    corpo = cliente.post("/sessoes/reiniciar", headers=SESSAO).json()

    assert corpo["dados_recarregados"] is True
    assert corpo["exemplo_fixo"] is False
    assert cliente.get(f"/vagas/{daqui}", headers=SESSAO).status_code == 404
    assert cliente.get(f"/vagas/{de_la}", headers=OUTRA_EMPRESA).status_code == 200
    nova = cliente.post("/vagas", headers=SESSAO, json=PEDIDO_VAGA).json()["vaga"]["id"]
    assinada = cliente.post(f"/vagas/{nova}/mandato", headers=SESSAO, json=_mandato())
    assert assinada.status_code == 201
    assert cliente.get(f"/vagas/{nova}/candidatos", headers=SESSAO).json()["total"] > 0
