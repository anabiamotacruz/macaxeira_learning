"""Busca real atrás de opt-in: soma-se aos perfis sintéticos.

Decisão de 8/11: quem chega sem autorização é analisado, e o convite só sai pelo e-mail que a
pessoa publicou.
"""

from fastapi.testclient import TestClient

from backend.agente.api import criar_app
from backend.agente.montagem import BUSCA_REAL, busca_real, montar_servico
from backend.contratos.modelos import EstadoBanco
from backend.contratos.simulacoes import FonteSimulada, candidato_simulado
from backend.fontes.provedores.fonte import FonteProvedores
from backend.fontes.provedores.modelos import CONTATO_NAO_PUBLICADO
from tests.agente.apoio import pedido_mandato

SESSAO = {"X-Empresa-Id": "empresa-real"}
COLETADO = "coletado-1"


def _coletado(**atributos):
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
        atributos={"producao": "sim", "presencial_sp": "sim", **atributos},
    )


class Criador:
    def __init__(self, **atributos) -> None:
        self.pedidos = []
        self.atributos = atributos

    def __call__(self, ambiente):
        def criar(banco, repositorio):
            self.pedidos.append((banco, repositorio))
            return FonteSimulada([_coletado(**self.atributos)])

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


def _eventos_do_coletado(servico, vaga: str) -> list:
    """Todos os eventos, sem a paginação da API."""
    return [e for e in servico.eventos("empresa-real", vaga) if e.candidato_id == COLETADO]


def test_quem_vem_da_busca_real_sem_autorizacao_e_analisado(tmp_path):
    servico = montar_servico(tmp_path / "a.db", ambiente={BUSCA_REAL: "1"}, criar_busca=Criador())

    cliente, vaga = _rodar(servico)

    eventos = _eventos_do_coletado(servico, vaga)
    decisoes = [e.mensagem for e in eventos if e.etapa == "decisao"]
    assert decisoes, "a pessoa da busca real passou pela análise e tem decisão"
    assert not any("funil:" in d for d in decisoes)


def test_quem_vem_da_busca_real_sem_email_publicado_nao_recebe_convite(tmp_path):
    servico = montar_servico(tmp_path / "a.db", ambiente={BUSCA_REAL: "1"}, criar_busca=Criador())

    cliente, vaga = _rodar(servico)

    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    assert COLETADO not in {c["candidato_id"] for c in convites}
    assert convites, "os perfis sintéticos seguem na vaga"


def test_email_de_provedor_nao_publicado_pela_pessoa_nao_recebe_convite(tmp_path):
    criador = Criador(email="pessoa@exemplo.invalid", contato_origem=CONTATO_NAO_PUBLICADO)
    servico = montar_servico(tmp_path / "a.db", ambiente={BUSCA_REAL: "1"}, criar_busca=criador)

    cliente, vaga = _rodar(servico)

    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    assert COLETADO not in {c["candidato_id"] for c in convites}
    assert all("pessoa@exemplo.invalid" not in c["mensagem"] for c in convites)


def test_busca_real_padrao_usa_a_fonte_da_frente_2_sem_provedor_sem_chave(tmp_path):
    from backend.agente.persistencia import Repositorio
    from backend.contratos.simulacoes import BancoTalentosSimulado

    fonte = busca_real({})(BancoTalentosSimulado(), Repositorio(tmp_path / "a.db"))

    assert isinstance(fonte, FonteProvedores)
    assert not fonte.cadeia.provedores


PERFIL_ADERENTE = (
    "Desenvolvi serviços Python em produção por quatro anos. Implementei microsserviços e filas "
    "com testes e revisão de código. Operei serviços em Azure com monitoramento e recuperação de "
    "falhas. Tenho disponibilidade para trabalhar presencialmente em São Paulo."
)


def test_com_email_publicado_o_convite_sai_pelo_mensageiro_simulado_com_origem(tmp_path):
    def criar_busca(ambiente):
        def criar(banco, repositorio):
            coletado = _coletado(email="pessoa@exemplo.invalid")
            return FonteSimulada([coletado.model_copy(update={"perfil_texto": PERFIL_ADERENTE})])

        return criar

    servico = montar_servico(tmp_path / "a.db", ambiente={BUSCA_REAL: "1"}, criar_busca=criar_busca)

    cliente, vaga = _rodar(servico)

    convites = cliente.get(f"/vagas/{vaga}/convites", headers=SESSAO).json()["itens"]
    [convite] = [c for c in convites if c["candidato_id"] == COLETADO]
    assert convite["simulado"]
    assert convite["estado"] == "aguardando"
    assert "https://exemplo.invalid/perfil" in convite["mensagem"]
    assert "Não quero mais contato" in convite["mensagem"]
