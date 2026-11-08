"""Busca real atrás de opt-in: soma-se aos perfis sintéticos, e quem chega sem autorização para."""

from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import BUSCA_REAL, busca_real, montar_servico
from backend.contratos.modelos import EstadoBanco
from backend.contratos.simulacoes import FonteSimulada, candidato_simulado
from backend.fontes.provedores.fonte import FonteProvedores
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-real"}
COLETADO = "coletado-1"


def _coletado():
    """Como a Frente 2 entrega quem vem de provedor: sem autorização e pendente."""
    return candidato_simulado(
        COLETADO,
        "empresa-real",
        nome="Pessoa Coletada",
        fonte="brave",
        simulado=False,
        origem="https://exemplo.invalid/perfil",
        autorizacao_valida_ate=None,
        autorizou_contato=False,
        estado=EstadoBanco.PENDENTE,
        perfil_texto="Desenvolve em python há oito anos.",
    )


class Criador:
    def __init__(self) -> None:
        self.pedidos = []

    def __call__(self, ambiente):
        def criar(banco, repositorio):
            self.pedidos.append((banco, repositorio))
            return FonteSimulada([_coletado()])

        return criar


def _rodar(servico) -> tuple[TestClient, str]:
    cliente = TestClient(criar_app(servico))
    modelo = cliente.get("/vagas/modelos", headers=SESSAO).json()["itens"][0]
    vaga = cliente.post("/vagas", headers=SESSAO, json=modelo).json()["vaga"]["id"]
    assinado = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(aceitar_declarada=True)
    )
    assert assinado.status_code == 201, assinado.text
    return cliente, vaga


def test_sem_opt_in_nao_ha_busca_real(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    criador = Criador()

    servico = montar_servico(tmp_path / "a.db", ambiente={}, criar_busca=criador)
    _rodar(servico)

    assert criador.pedidos == []


def test_com_opt_in_a_busca_real_recebe_banco_e_repositorio(tmp_path):
    criador = Criador()

    servico = montar_servico(tmp_path / "a.db", ambiente={BUSCA_REAL: "1"}, criar_busca=criador)
    _rodar(servico)

    [(banco, repositorio)] = criador.pedidos
    assert banco is not None
    assert repositorio is not None


def test_quem_vem_da_busca_real_sem_autorizacao_nao_recebe_convite(tmp_path):
    servico = montar_servico(tmp_path / "a.db", ambiente={BUSCA_REAL: "1"}, criar_busca=Criador())

    cliente, vaga = _rodar(servico)

    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    assert COLETADO not in {c["candidato_id"] for c in convites}
    assert convites, "os perfis sintéticos seguem na vaga"


def test_busca_real_padrao_usa_a_fonte_da_frente_2_sem_provedor_sem_chave(tmp_path):
    from backend.agente.persistencia import Repositorio
    from backend.contratos.simulacoes import BancoTalentosSimulado

    fonte = busca_real({})(BancoTalentosSimulado(), Repositorio(tmp_path / "a.db"))

    assert isinstance(fonte, FonteProvedores)
    assert not fonte.cadeia.provedores
