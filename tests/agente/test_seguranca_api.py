"""Segurança do link público (T4.5): sessão, limite de requisições, erro sem segredo e gasto."""

from fastapi.testclient import TestClient

from backend.agente.api import LimiteRequisicoes, criar_app
from tests.agente.apoio import PEDIDO_VAGA, pedido_mandato, servico_de_teste

SESSAO = {"X-Empresa-Id": "empresa-a"}
OUTRA = {"X-Empresa-Id": "empresa-b"}


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


def _vaga(cliente: TestClient) -> str:
    resposta = cliente.post("/vagas", headers=SESSAO, json=PEDIDO_VAGA)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["vaga"]["id"]


def test_sessao_nao_acessa_dados_de_outra_empresa(tmp_path):
    cliente = TestClient(criar_app(servico_de_teste(tmp_path / "a.db")))
    vaga = _vaga(cliente)

    for caminho in (f"/vagas/{vaga}", f"/vagas/{vaga}/candidatos", f"/vagas/{vaga}/eventos"):
        resposta = cliente.get(caminho, headers=OUTRA)
        assert resposta.status_code == 404, caminho
        assert vaga not in resposta.text


def test_limite_de_requisicoes_por_sessao(tmp_path):
    relogio = Relogio()
    limite = LimiteRequisicoes(maximo=3, janela_s=60, relogio=relogio)
    cliente = TestClient(criar_app(servico_de_teste(tmp_path / "a.db"), limite=limite))

    for _ in range(3):
        assert cliente.get("/vagas/modelos", headers=SESSAO).status_code == 200
    bloqueada = cliente.get("/vagas/modelos", headers=SESSAO)

    assert bloqueada.status_code == 429
    assert bloqueada.json()["erro"]["codigo"] == "muitas_requisicoes"
    assert int(bloqueada.headers["Retry-After"]) >= 1
    assert cliente.get("/vagas/modelos", headers=OUTRA).status_code == 200
    relogio.agora += 61
    assert cliente.get("/vagas/modelos", headers=SESSAO).status_code == 200


def test_preflight_do_navegador_nao_conta_no_limite(tmp_path):
    limite = LimiteRequisicoes(maximo=1, janela_s=60, relogio=Relogio())
    cliente = TestClient(criar_app(servico_de_teste(tmp_path / "a.db"), limite=limite))
    origem = {"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}

    for _ in range(3):
        cliente.options("/vagas/modelos", headers=origem)

    assert cliente.get("/vagas/modelos", headers=SESSAO).status_code == 200


def test_erros_nao_expoem_chave_nem_stack_trace(tmp_path):
    servico = servico_de_teste(tmp_path / "a.db")
    segredo = "FEATHERLESS_API_KEY=sk-segredo-que-nao-pode-vazar"

    def falha(*_args, **_kwargs):
        raise RuntimeError(f"falha interna com {segredo}")

    servico.consultar = falha
    cliente = TestClient(criar_app(servico), raise_server_exceptions=False)

    resposta = cliente.get("/vagas/qualquer", headers=SESSAO)

    assert resposta.status_code == 500
    assert resposta.json()["erro"] == {"codigo": "erro_interno", "mensagem": "Erro interno."}
    assert "sk-segredo" not in resposta.text
    assert "Traceback" not in resposta.text
    assert "RuntimeError" not in resposta.text


def test_limite_de_gasto_por_sessao_bloqueia_novas_execucoes(tmp_path):
    cliente = TestClient(
        criar_app(servico_de_teste(tmp_path / "a.db", medidor_gasto=lambda: 999.0))
    )
    vaga = _vaga(cliente)

    assinado = cliente.post(f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato())

    assert assinado.status_code == 201, assinado.text
    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]
    assert resumo["estado"] == "pausada"
    assert resumo["analisados"] == 0
