from math import sqrt

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import LIMITE_MAXIMO, app, criar_app
from backend.agente.auditoria import Auditoria
from backend.agente.servico import MetricasVaga
from backend.contratos.erros import ModeloIndisponivel
from backend.contratos.modelos import Candidato, DestinoPessoa, TaxaMedida, TipoDecisao, TipoErro
from tests.agente.apoio import (
    PEDIDO_VAGA,
    AnalisadorComEvidencias,
    Relogio,
    pedido_mandato,
    servico_de_teste,
)

SESSAO = {"X-Empresa-Id": "empresa-a"}
OUTRA_EMPRESA = {"X-Empresa-Id": "empresa-outra"}
PESSOA = "Pessoa Responsável Fictícia"

PEDIDO_MANDATO = pedido_mandato()
PEDIDO_CONTROLE = {"responsavel": PESSOA, "chave_idempotencia": "k1"}
PEDIDO_REVERSAO = {"motivo": "Revisão humana", "responsavel": PESSOA, "chave_idempotencia": "k2"}
PEDIDO_DESTINO = {"destino": "banco", "responsavel": PESSOA, "chave_idempotencia": "k3"}

ROTAS = [
    ("post", "/vagas", PEDIDO_VAGA, 201),
    ("post", "/vagas/{vaga}/mandato", PEDIDO_MANDATO, 201),
    ("get", "/vagas/{vaga}", None, 200),
    ("get", "/vagas/{vaga}/candidatos", None, 200),
    ("get", "/vagas/{vaga}/eventos", None, 200),
    ("get", "/vagas/{vaga}/entrega", None, 200),
    ("get", "/vagas/{vaga}/resumo", None, 200),
    ("get", "/vagas/{vaga}/metricas", None, 200),
    ("get", "/candidatos/verde/decisao", None, 200),
    ("post", "/vagas/{vaga}/parar", PEDIDO_CONTROLE, 200),
    ("post", "/vagas/{vaga}/retomar", PEDIDO_CONTROLE, 200),
    ("post", "/candidatos/verde/reverter", PEDIDO_REVERSAO, 200),
    ("post", "/candidatos/verde/destino", PEDIDO_DESTINO, 200),
    ("post", "/sessoes/reiniciar", None, 200),
]
ROTAS_COM_RECURSO = [rota for rota in ROTAS if rota[1] not in {"/vagas", "/sessoes/reiniciar"}]
ROTAS_DE_ANDAMENTO = [rota for rota in ROTAS_COM_RECURSO if not rota[1].endswith("/mandato")]


def _ids(rota: tuple) -> str:
    return f"{rota[0]} {rota[1]}"


@pytest.fixture
def servico(tmp_path):
    return servico_de_teste(tmp_path / "agente.db")


@pytest.fixture
def cliente(servico) -> TestClient:
    return TestClient(criar_app(servico))


def _criar_vaga(cliente: TestClient, cabecalhos: dict = SESSAO) -> str:
    resposta = cliente.post("/vagas", headers=cabecalhos, json=PEDIDO_VAGA)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["vaga"]["id"]


def _vaga_executada(cliente: TestClient, **politica) -> str:
    vaga = _criar_vaga(cliente)
    resposta = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json=pedido_mandato(**politica)
    )
    assert resposta.status_code == 201, resposta.text
    return vaga


@pytest.fixture
def vaga(cliente) -> str:
    return _vaga_executada(cliente)


def _corpo_com_vaga(caminho: str, corpo: dict | None, vaga: str) -> dict | None:
    if corpo is not None and caminho.startswith("/candidatos"):
        return {**corpo, "vaga_id": vaga}
    return corpo


def _chamar(cliente: TestClient, rota: tuple, vaga: str, cabecalhos: dict):
    metodo, caminho, corpo, _ = rota
    argumentos = {"headers": cabecalhos}
    corpo = _corpo_com_vaga(caminho, corpo, vaga)
    if corpo is not None:
        argumentos["json"] = corpo
    return cliente.request(metodo, caminho.format(vaga=vaga), **argumentos)


def _erro_padrao(resposta) -> dict:
    corpo = resposta.json()
    assert set(corpo) == {"erro", "simulado"}
    assert set(corpo["erro"]) == {"codigo", "mensagem"}
    assert corpo["simulado"] is True
    return corpo["erro"]


def _wilson(erros: int, casos: int, z: float = 1.959964) -> tuple[float, float]:
    p = erros / casos
    divisor = 1 + z**2 / casos
    centro = (p + z**2 / (2 * casos)) / divisor
    margem = z * sqrt(p * (1 - p) / casos + z**2 / (4 * casos**2)) / divisor
    return round(max(0.0, centro - margem), 4), round(min(1.0, centro + margem), 4)


def _estado(cliente: TestClient, vaga: str) -> str:
    return cliente.get(f"/vagas/{vaga}", headers=SESSAO).json()["estado"]


# Rotas e identificação da simulação


def test_expoe_exatamente_as_rotas_combinadas():
    rotas = {
        (metodo, caminho)
        for caminho, operacoes in app.openapi()["paths"].items()
        for metodo in operacoes
    }
    assert rotas == {
        ("post", "/vagas"),
        ("get", "/vagas/modelos"),
        ("post", "/vagas/{id}/mandato"),
        ("get", "/vagas/{id}"),
        ("get", "/vagas/{id}/candidatos"),
        ("get", "/vagas/{id}/eventos"),
        ("get", "/vagas/{id}/entrega"),
        ("get", "/vagas/{id}/convites"),
        ("post", "/vagas/{id}/retornos"),
        ("get", "/vagas/{id}/resumo"),
        ("get", "/vagas/{id}/metricas"),
        ("get", "/candidatos/{id}/decisao"),
        ("post", "/vagas/{id}/parar"),
        ("post", "/vagas/{id}/retomar"),
        ("post", "/candidatos/{id}/reverter"),
        ("post", "/candidatos/{id}/destino"),
        ("post", "/convites/{id}/resposta"),
        ("post", "/sessoes/reiniciar"),
    }


@pytest.mark.parametrize("rota", ROTAS_DE_ANDAMENTO, ids=_ids)
def test_respostas_identificam_simulacao_e_so_as_metricas_seguem_fixas(cliente, vaga, rota):
    resposta = _chamar(cliente, rota, vaga, SESSAO)
    assert resposta.status_code == rota[3], resposta.text
    assert resposta.json()["simulado"] is True
    assert resposta.json()["exemplo_fixo"] is rota[1].endswith("/metricas")


def test_criar_e_assinar_nao_sao_exemplo_fixo(cliente):
    criada = cliente.post("/vagas", headers=SESSAO, json=PEDIDO_VAGA).json()
    assinada = cliente.post(
        f"/vagas/{criada['vaga']['id']}/mandato", headers=SESSAO, json=PEDIDO_MANDATO
    ).json()
    assert criada["exemplo_fixo"] is False
    assert assinada["exemplo_fixo"] is False
    assert criada["simulado"] is assinada["simulado"] is True


@pytest.mark.parametrize(
    "metodo, caminho, cabecalhos",
    [
        ("get", "/vagas/qualquer", {}),
        ("get", "/vagas/nao-existe", SESSAO),
        ("get", "/rota-que-nao-existe", SESSAO),
        ("delete", "/vagas/qualquer", SESSAO),
        ("get", "/vagas/qualquer/candidatos?limite=0", SESSAO),
    ],
)
def test_erros_tambem_identificam_simulacao(cliente, metodo, caminho, cabecalhos):
    _erro_padrao(cliente.request(metodo, caminho, headers=cabecalhos))


def test_dados_de_candidato_sao_sinteticos_e_marcados(cliente, vaga):
    itens = cliente.get(f"/vagas/{vaga}/candidatos", headers=SESSAO).json()["itens"]
    assert itens
    for item in itens:
        assert item["candidato"]["simulado"] is True


def test_saida_vazia_antes_da_entrega_tambem_e_identificada(cliente, vaga):
    saida = cliente.get(f"/vagas/{vaga}/entrega", headers=SESSAO).json()["saida"]
    assert saida["pacotes"] == []
    assert saida["simulado"] is True


# Sessão e isolamento


@pytest.mark.parametrize("rota", ROTAS, ids=_ids)
def test_sem_sessao_recebe_401(cliente, rota):
    resposta = _chamar(cliente, rota, "qualquer", {})
    assert resposta.status_code == 401
    assert _erro_padrao(resposta)["codigo"] == "sessao_ausente"


@pytest.mark.parametrize("valor", ["   ", "empresa com espacos", "a" * 65, "<script>"])
def test_sessao_invalida_recebe_401(cliente, valor):
    resposta = cliente.get("/vagas/qualquer", headers={"X-Empresa-Id": valor})
    assert resposta.status_code == 401
    assert _erro_padrao(resposta)["codigo"] == "sessao_ausente"
    assert valor not in resposta.text


@pytest.mark.parametrize("rota", ROTAS_COM_RECURSO, ids=_ids)
def test_outra_empresa_recebe_404(cliente, vaga, rota):
    resposta = _chamar(cliente, rota, vaga, OUTRA_EMPRESA)
    assert resposta.status_code == 404
    _erro_padrao(resposta)
    assert "empresa-a" not in resposta.text
    assert "Fictícia" not in resposta.text


def test_recurso_de_outra_empresa_e_inexistente_tem_a_mesma_resposta(cliente, vaga):
    de_outra_empresa = cliente.get(f"/vagas/{vaga}", headers=OUTRA_EMPRESA)
    inexistente = cliente.get("/vagas/nao-existe", headers=OUTRA_EMPRESA)
    assert de_outra_empresa.json() == inexistente.json()


def test_acao_de_outra_empresa_nao_muda_a_vaga(cliente, vaga):
    antes = _estado(cliente, vaga)
    cliente.post(f"/vagas/{vaga}/parar", headers=OUTRA_EMPRESA, json=PEDIDO_CONTROLE)
    assert _estado(cliente, vaga) == antes


def test_empresa_no_corpo_e_rejeitada(cliente):
    resposta = cliente.post("/vagas", headers=SESSAO, json={**PEDIDO_VAGA, "empresa_id": "outra"})
    assert resposta.status_code == 422
    _erro_padrao(resposta)


def test_empresa_na_consulta_nao_substitui_a_sessao(cliente, vaga):
    resposta = cliente.get(f"/vagas/{vaga}?empresa_id=empresa-a", headers=OUTRA_EMPRESA)
    assert resposta.status_code == 404


def test_vaga_nova_pertence_a_empresa_da_sessao_e_fica_gravada(cliente):
    resposta = cliente.post("/vagas", headers=OUTRA_EMPRESA, json=PEDIDO_VAGA)
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["vaga"]["empresa_id"] == "empresa-outra"
    assert corpo["estado"] == "aguardando_mandato"
    assert corpo["mandato"] is None
    salva = cliente.get(f"/vagas/{corpo['vaga']['id']}", headers=OUTRA_EMPRESA)
    assert salva.json()["vaga"] == corpo["vaga"]


def test_duas_vagas_iguais_recebem_ids_diferentes(cliente):
    assert _criar_vaga(cliente) != _criar_vaga(cliente)


# Criação e mandato


@pytest.mark.parametrize(
    "criterio",
    [
        {"requisitos": [{"id": "r", "descricao": "Gênero", "campo": "g", "valor_esperado": "f"}]},
        {"competencias": [{"nome": "Religião", "peso": 1.0}]},
    ],
)
def test_criterio_sensivel_e_recusado_e_nada_e_gravado(cliente, servico, criterio):
    resposta = cliente.post("/vagas", headers=SESSAO, json={**PEDIDO_VAGA, **criterio})
    assert resposta.status_code == 422
    assert _erro_padrao(resposta)["codigo"] == "criterio_sensivel"
    assert servico.vagas("empresa-a") == []


def test_requisito_sem_valor_esperado_e_recusado_e_nada_e_gravado(cliente, servico):
    requisito = {"id": "r1", "descricao": "CNH", "campo": "cnh", "valor_esperado": " "}

    resposta = cliente.post(
        "/vagas", headers=SESSAO, json={**PEDIDO_VAGA, "requisitos": [requisito]}
    )

    assert resposta.status_code == 422
    assert _erro_padrao(resposta)["codigo"] == "requisito_incompleto"
    assert servico.vagas("empresa-a") == []


def test_mandato_inicia_a_busca_em_segundo_plano_e_a_resposta_nao_espera(cliente):
    vaga = _criar_vaga(cliente)
    corpo = cliente.post(f"/vagas/{vaga}/mandato", headers=SESSAO, json=PEDIDO_MANDATO).json()

    assert corpo["estado"] == "buscando"
    assert corpo["mandato"]["vaga_id"] == vaga
    assert corpo["mandato"]["assinante"] == PESSOA
    assert corpo["mandato"]["empresa_id"] == "empresa-a"
    assert _estado(cliente, vaga) == "convidando"


def test_vaga_consultada_mostra_mandato_e_aprovacao(cliente, vaga):
    corpo = cliente.get(f"/vagas/{vaga}", headers=SESSAO).json()
    assert corpo["vaga"]["aprovada"] is True
    assert corpo["mandato"]["versao"] == 1


def test_mandato_repetido_e_conflito(cliente, vaga):
    resposta = cliente.post(f"/vagas/{vaga}/mandato", headers=SESSAO, json=PEDIDO_MANDATO)
    assert resposta.status_code == 409
    assert _erro_padrao(resposta)["codigo"] == "transicao_invalida"


def test_mandato_assinado_pelo_agente_e_recusado(cliente):
    vaga = _criar_vaga(cliente)
    resposta = cliente.post(
        f"/vagas/{vaga}/mandato",
        headers=SESSAO,
        json={**PEDIDO_MANDATO, "assinante": "agente:mandato:m:v1"},
    )
    assert resposta.status_code == 422
    assert _erro_padrao(resposta)["codigo"] == "responsavel_invalido"
    assert _estado(cliente, vaga) == "aguardando_mandato"


def test_aditivo_em_vaga_pausada_nao_retoma_sozinho(cliente, vaga):
    cliente.post(f"/vagas/{vaga}/parar", headers=SESSAO, json=PEDIDO_CONTROLE)

    corpo = cliente.post(f"/vagas/{vaga}/mandato", headers=SESSAO, json=PEDIDO_MANDATO).json()

    assert corpo["mandato"]["versao"] == 2
    assert corpo["estado"] == "pausada"
    assert _estado(cliente, vaga) == "pausada"


def test_falha_previsivel_na_execucao_pausa_sem_derrubar_a_api(tmp_path):
    class ModeloFora(AnalisadorComEvidencias):
        def analisar(self, vaga, candidato: Candidato):
            raise ModeloIndisponivel("fora do ar")

    cliente = TestClient(
        criar_app(servico_de_teste(tmp_path / "agente.db", analisador=ModeloFora()))
    )
    vaga = _vaga_executada(cliente)

    assert _estado(cliente, vaga) == "pausada"
    assert cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]["estado"] == (
        "pausada"
    )


def test_falha_inesperada_na_execucao_fica_registrada_sem_o_texto(tmp_path):
    class Quebrado(AnalisadorComEvidencias):
        def analisar(self, vaga, candidato: Candidato):
            raise RuntimeError("sk-segredo-de-teste")

    cliente = TestClient(
        criar_app(servico_de_teste(tmp_path / "agente.db", analisador=Quebrado())),
        raise_server_exceptions=False,
    )
    vaga = _vaga_executada(cliente)

    eventos = cliente.get(f"/vagas/{vaga}/eventos", headers=SESSAO, params={"limite": 100}).text
    assert "falha_execucao" in eventos
    assert "RuntimeError" in eventos
    assert "sk-segredo-de-teste" not in eventos


# Reinício


def test_sem_recarga_injetada_reiniciar_nao_apaga_nem_finge(cliente, vaga):
    corpo = cliente.post("/sessoes/reiniciar", headers=SESSAO).json()
    assert corpo["empresa_id"] == "empresa-a"
    assert corpo["dados_recarregados"] is False
    assert corpo["exemplo_fixo"] is True
    assert cliente.get(f"/vagas/{vaga}", headers=SESSAO).status_code == 200


def test_reiniciar_recarrega_so_a_empresa_da_sessao(tmp_path):
    recarregadas: list[str] = []
    cliente = TestClient(
        criar_app(servico_de_teste(tmp_path / "agente.db", recarregar=recarregadas.append))
    )
    daqui = _vaga_executada(cliente)
    de_la = _criar_vaga(cliente, OUTRA_EMPRESA)

    corpo = cliente.post("/sessoes/reiniciar", headers=SESSAO).json()

    assert corpo["dados_recarregados"] is True
    assert corpo["exemplo_fixo"] is False
    assert recarregadas == ["empresa-a"]
    assert cliente.get(f"/vagas/{daqui}", headers=SESSAO).status_code == 404
    assert cliente.get(f"/vagas/{de_la}", headers=OUTRA_EMPRESA).status_code == 200


# Validação e formato de erro


@pytest.mark.parametrize(
    "ajuste",
    [
        {"limite_gasto_usd": 0},
        {"limite_gasto_usd": -1},
        {"assinante": "   "},
        {
            "politica": {
                "limiar_verde": 0.4,
                "piso_nota": 0.5,
                "max_indicacoes": 1,
                "max_ampliacoes": 0,
            }
        },
        {"hash_vaga": "forjado"},
        {"versao": 9},
    ],
)
def test_mandato_invalido_devolve_422_no_formato_padrao(cliente, ajuste):
    vaga = _criar_vaga(cliente)
    resposta = cliente.post(
        f"/vagas/{vaga}/mandato", headers=SESSAO, json={**PEDIDO_MANDATO, **ajuste}
    )
    assert resposta.status_code == 422
    assert _erro_padrao(resposta)["codigo"] == "dados_invalidos"


def test_corpo_que_nao_e_json_devolve_422_no_formato_padrao(cliente):
    resposta = cliente.post(
        "/vagas",
        headers={**SESSAO, "Content-Type": "application/json"},
        content="{quebrado",
    )
    assert resposta.status_code == 422
    assert "quebrado" not in resposta.text
    _erro_padrao(resposta)


def test_erro_de_validacao_nao_ecoa_entrada(cliente):
    segredo = "sk-segredo-de-teste"
    vaga = _criar_vaga(cliente)
    resposta = cliente.post(
        f"/vagas/{vaga}/mandato",
        headers=SESSAO,
        json={**PEDIDO_MANDATO, "assinante": 1, "limite_gasto_usd": segredo, segredo: segredo},
    )
    assert resposta.status_code == 422
    assert segredo not in resposta.text


def test_erro_nao_expoe_stack_trace_nem_chave(servico):
    aplicacao = criar_app(servico)

    @aplicacao.get("/falha")
    def falha() -> None:
        raise RuntimeError("sk-segredo-de-teste")

    resposta = TestClient(aplicacao, raise_server_exceptions=False).get("/falha")
    assert resposta.status_code == 500
    assert _erro_padrao(resposta)["codigo"] == "erro_interno"
    assert "sk-segredo-de-teste" not in resposta.text
    assert "Traceback" not in resposta.text
    assert "RuntimeError" not in resposta.text


def test_id_malicioso_nao_e_ecoado(cliente):
    resposta = cliente.get("/vagas/%3Cscript%3Ealert(1)%3C%2Fscript%3E", headers=SESSAO)
    assert resposta.status_code == 404
    assert "script" not in resposta.text


# Paginação


@pytest.mark.parametrize("recurso", ["candidatos", "eventos"])
def test_lista_pagina_com_limite(cliente, vaga, recurso):
    corpo = cliente.get(
        f"/vagas/{vaga}/{recurso}", params={"pagina": 2, "limite": 1}, headers=SESSAO
    ).json()
    assert (corpo["pagina"], corpo["limite"]) == (2, 1)
    assert len(corpo["itens"]) == 1
    assert corpo["total"] >= 2


@pytest.mark.parametrize("recurso", ["candidatos", "eventos"])
def test_pagina_alem_do_fim_vem_vazia(cliente, vaga, recurso):
    corpo = cliente.get(f"/vagas/{vaga}/{recurso}", params={"pagina": 99}, headers=SESSAO).json()
    assert corpo["itens"] == []
    assert corpo["total"] > 0


@pytest.mark.parametrize("recurso", ["candidatos", "eventos"])
@pytest.mark.parametrize(
    "parametros", [{"limite": LIMITE_MAXIMO + 1}, {"limite": 0}, {"pagina": 0}, {"pagina": "x"}]
)
def test_paginacao_fora_do_limite_devolve_422(cliente, vaga, recurso, parametros):
    resposta = cliente.get(f"/vagas/{vaga}/{recurso}", params=parametros, headers=SESSAO)
    assert resposta.status_code == 422
    _erro_padrao(resposta)


# Controle depois da ação


def test_parar_e_idempotente_com_a_mesma_chave(cliente, vaga):
    primeira = cliente.post(f"/vagas/{vaga}/parar", headers=SESSAO, json=PEDIDO_CONTROLE)
    segunda = cliente.post(f"/vagas/{vaga}/parar", headers=SESSAO, json=PEDIDO_CONTROLE)
    assert primeira.json() == segunda.json()
    assert primeira.json()["estado"] == "pausada"
    assert primeira.json()["estado_anterior"] == "convidando"
    eventos = cliente.get(f"/vagas/{vaga}/eventos", headers=SESSAO, params={"limite": 100}).json()
    assert len([e for e in eventos["itens"] if e["etapa"] == "controle"]) == 1


def test_mesma_chave_com_outro_pedido_e_conflito(cliente, vaga):
    cliente.post(f"/vagas/{vaga}/parar", headers=SESSAO, json=PEDIDO_CONTROLE)
    resposta = cliente.post(
        f"/vagas/{vaga}/parar", headers=SESSAO, json={**PEDIDO_CONTROLE, "motivo": "Outro"}
    )
    assert resposta.status_code == 409
    assert _erro_padrao(resposta)["codigo"] == "chave_reutilizada"


def test_a_mesma_chave_em_acoes_diferentes_nao_se_confunde(cliente, vaga):
    parada = cliente.post(f"/vagas/{vaga}/parar", headers=SESSAO, json=PEDIDO_CONTROLE).json()
    retomada = cliente.post(f"/vagas/{vaga}/retomar", headers=SESSAO, json=PEDIDO_CONTROLE).json()
    assert parada["estado"] == "pausada"
    assert retomada["estado"] == "convidando"


def test_retomar_volta_ao_estado_anterior(cliente, vaga):
    parada = cliente.post(f"/vagas/{vaga}/parar", headers=SESSAO, json=PEDIDO_CONTROLE).json()
    retomada = cliente.post(f"/vagas/{vaga}/retomar", headers=SESSAO, json=PEDIDO_CONTROLE).json()
    assert retomada["estado"] == parada["estado_anterior"]
    assert retomada["estado_anterior"] == "pausada"


def test_parar_vaga_sem_execucao_e_conflito(cliente):
    vaga = _criar_vaga(cliente)
    resposta = cliente.post(f"/vagas/{vaga}/parar", headers=SESSAO, json=PEDIDO_CONTROLE)
    assert resposta.status_code == 409
    assert _erro_padrao(resposta)["codigo"] == "transicao_invalida"


def test_retomar_vaga_sem_execucao_e_conflito(cliente):
    vaga = _criar_vaga(cliente)
    resposta = cliente.post(f"/vagas/{vaga}/retomar", headers=SESSAO, json=PEDIDO_CONTROLE)
    assert resposta.status_code == 409


@pytest.mark.parametrize("acao", ["parar", "retomar"])
def test_controle_pelo_agente_e_recusado(cliente, vaga, acao):
    corpo = {**PEDIDO_CONTROLE, "responsavel": "agente:mandato:m:v1"}
    resposta = cliente.post(f"/vagas/{vaga}/{acao}", headers=SESSAO, json=corpo)
    assert resposta.status_code == 422
    assert _erro_padrao(resposta)["codigo"] == "responsavel_invalido"


def test_retomar_com_barreira_da_auditoria_e_conflito(cliente, servico, vaga):
    auditoria = Auditoria(servico.repositorio)
    decisao = next(
        d
        for d in servico.repositorio.listar_decisoes("empresa-a", vaga)
        if d.candidato_id == "verde"
    )
    auditoria.registrar_auditoria(
        decisao, correta=False, auditor="humano:Pessoa", momento=Relogio()()
    )
    assert _estado(cliente, vaga) == "pausada"

    resposta = cliente.post(f"/vagas/{vaga}/retomar", headers=SESSAO, json=PEDIDO_CONTROLE)
    assert resposta.status_code == 409
    assert _erro_padrao(resposta)["codigo"] == "auditoria_pendente"

    auditoria.liberar_decisoes_automaticas("empresa-a", vaga, "humano:Pessoa", "ok", Relogio()())
    novamente = cliente.post(f"/vagas/{vaga}/retomar", headers=SESSAO, json=PEDIDO_CONTROLE)
    assert novamente.status_code == 200
    assert novamente.json()["estado"] == "convidando"


def test_retomar_pausa_por_gasto_exige_aditivo(tmp_path):
    cliente = TestClient(
        criar_app(servico_de_teste(tmp_path / "agente.db", medidor_gasto=lambda: 99.0))
    )
    vaga = _vaga_executada(cliente)
    assert _estado(cliente, vaga) == "pausada"

    resposta = cliente.post(f"/vagas/{vaga}/retomar", headers=SESSAO, json=PEDIDO_CONTROLE)

    assert resposta.status_code == 409
    assert _erro_padrao(resposta)["codigo"] == "aditivo_necessario"


@pytest.mark.parametrize(
    "caminho, pedido, campo",
    [
        ("/vagas/{vaga}/parar", PEDIDO_CONTROLE, "chave_idempotencia"),
        ("/vagas/{vaga}/parar", PEDIDO_CONTROLE, "responsavel"),
        ("/vagas/{vaga}/retomar", PEDIDO_CONTROLE, "chave_idempotencia"),
        ("/candidatos/verde/reverter", PEDIDO_REVERSAO, "chave_idempotencia"),
        ("/candidatos/verde/reverter", PEDIDO_REVERSAO, "responsavel"),
        ("/candidatos/verde/reverter", PEDIDO_REVERSAO, "motivo"),
        ("/candidatos/verde/destino", PEDIDO_DESTINO, "chave_idempotencia"),
        ("/candidatos/verde/destino", PEDIDO_DESTINO, "responsavel"),
    ],
)
def test_acao_repetivel_exige_campos_obrigatorios(cliente, vaga, caminho, pedido, campo):
    corpo = {"vaga_id": vaga, **pedido}
    if caminho.startswith("/vagas"):
        corpo.pop("vaga_id")
    corpo.pop(campo)
    resposta = cliente.post(caminho.format(vaga=vaga), headers=SESSAO, json=corpo)
    assert resposta.status_code == 422
    _erro_padrao(resposta)


def test_reverter_preserva_decisao_original(cliente, vaga):
    atual = cliente.get("/candidatos/verde/decisao", headers=SESSAO).json()["decisao"]
    reversao = cliente.post(
        "/candidatos/verde/reverter", headers=SESSAO, json={**PEDIDO_REVERSAO, "vaga_id": vaga}
    ).json()
    assert reversao["decisao_original"] == atual
    assert reversao["decisao_nova"]["regra"] == "reversao_humana"
    assert reversao["decisao_nova"]["responsavel"] == f"humano:{PESSOA}"
    assert reversao["decisao_nova"]["entrada"]["rastro_revertido"] == atual["rastro_id"]
    agora = cliente.get("/candidatos/verde/decisao", headers=SESSAO).json()["decisao"]
    assert agora == reversao["decisao_nova"]


def test_reverter_de_novo_com_outra_chave_mantem_a_original(cliente, vaga):
    corpo = {**PEDIDO_REVERSAO, "vaga_id": vaga}
    primeira = cliente.post("/candidatos/verde/reverter", headers=SESSAO, json=corpo).json()
    segunda = cliente.post(
        "/candidatos/verde/reverter", headers=SESSAO, json={**corpo, "chave_idempotencia": "k9"}
    ).json()
    assert segunda["decisao_original"] == primeira["decisao_original"]
    assert segunda["decisao_nova"] == primeira["decisao_nova"]


def test_reverter_quem_ja_esta_na_fila_e_conflito(cliente, vaga):
    resposta = cliente.post(
        "/candidatos/fila/reverter", headers=SESSAO, json={**PEDIDO_REVERSAO, "vaga_id": vaga}
    )
    assert resposta.status_code == 409
    assert _erro_padrao(resposta)["codigo"] == "acao_recusada"


def test_reverter_pelo_agente_e_recusado(cliente, vaga):
    resposta = cliente.post(
        "/candidatos/verde/reverter",
        headers=SESSAO,
        json={**PEDIDO_REVERSAO, "vaga_id": vaga, "responsavel": "agente"},
    )
    assert resposta.status_code == 422
    assert _erro_padrao(resposta)["codigo"] == "responsavel_invalido"


def test_reverter_em_vaga_que_nao_e_da_empresa_recebe_404(cliente, vaga):
    resposta = cliente.post(
        "/candidatos/verde/reverter",
        headers=SESSAO,
        json={**PEDIDO_REVERSAO, "vaga_id": "vaga-de-outra-empresa"},
    )
    assert resposta.status_code == 404


def test_candidato_que_nao_passou_pela_vaga_recebe_404(cliente, vaga):
    resposta = cliente.post(
        "/candidatos/nao-existe/reverter",
        headers=SESSAO,
        json={**PEDIDO_REVERSAO, "vaga_id": vaga},
    )
    assert resposta.status_code == 404
    assert _erro_padrao(resposta)["codigo"] == "candidato_nao_encontrado"
    assert "nao-existe" not in resposta.text


def test_decisao_filtra_por_vaga(cliente, vaga):
    caminho = "/candidatos/verde/decisao"
    assert cliente.get(caminho, params={"vaga_id": vaga}, headers=SESSAO).status_code == 200
    assert cliente.get(caminho, params={"vaga_id": "outra"}, headers=SESSAO).status_code == 404


def test_decisao_sem_filtro_traz_a_mais_recente_entre_as_vagas(tmp_path):
    relogio = Relogio()
    cliente = TestClient(criar_app(servico_de_teste(tmp_path / "agente.db", relogio=relogio)))
    _vaga_executada(cliente)
    relogio.avancar(hours=1)
    segunda = _vaga_executada(cliente)

    decisao = cliente.get("/candidatos/verde/decisao", headers=SESSAO).json()["decisao"]

    assert decisao["vaga_id"] == segunda


def test_decisao_explica_regra_evidencia_e_rastro(cliente, vaga):
    decisao = cliente.get("/candidatos/java/decisao", headers=SESSAO).json()["decisao"]
    assert decisao["tipo"] == "descartar"
    assert decisao["regra"] == "funil:requisito_nao_atendido"
    assert decisao["evidencias"]
    assert decisao["rastro_id"].endswith(f":{vaga}:java")


@pytest.mark.parametrize("destino", list(DestinoPessoa))
def test_destino_guarda_quem_decidiu(cliente, vaga, destino):
    corpo = cliente.post(
        "/candidatos/verde/destino",
        headers=SESSAO,
        json={**PEDIDO_DESTINO, "vaga_id": vaga, "destino": destino.value},
    ).json()
    assert corpo["destino"] == destino.value
    assert corpo["responsavel"] == PEDIDO_DESTINO["responsavel"]
    itens = cliente.get(f"/vagas/{vaga}/candidatos", headers=SESSAO).json()["itens"]
    assert next(i for i in itens if i["candidato"]["id"] == "verde")["destino"] == destino.value


def test_destino_pelo_agente_e_recusado(cliente, vaga):
    resposta = cliente.post(
        "/candidatos/verde/destino",
        headers=SESSAO,
        json={**PEDIDO_DESTINO, "vaga_id": vaga, "responsavel": "agente:mandato:m:v1"},
    )
    assert resposta.status_code == 422


def test_destino_de_quem_pediu_para_sair_e_conflito(cliente, vaga):
    resposta = cliente.post(
        "/candidatos/saiu/destino", headers=SESSAO, json={**PEDIDO_DESTINO, "vaga_id": vaga}
    )
    assert resposta.status_code == 409
    assert _erro_padrao(resposta)["codigo"] == "acao_recusada"


def test_destino_fora_da_lista_e_recusado(cliente, vaga):
    resposta = cliente.post(
        "/candidatos/verde/destino",
        headers=SESSAO,
        json={**PEDIDO_DESTINO, "vaga_id": vaga, "destino": "entrevista"},
    )
    assert resposta.status_code == 422


# Coerência das respostas


def test_candidatos_trazem_a_decisao_de_quem_foi_e_de_quem_saiu(cliente, vaga):
    itens = cliente.get(f"/vagas/{vaga}/candidatos", headers=SESSAO).json()["itens"]
    decisoes = {item["candidato"]["id"]: item["decisao"] for item in itens}
    assert decisoes == {
        "verde": TipoDecisao.INDICAR.value,
        "fila": TipoDecisao.PEDIR_HUMANO.value,
        "java": TipoDecisao.DESCARTAR.value,
        "saiu": TipoDecisao.DESCARTAR.value,
    }


def test_perfil_de_quem_pediu_para_sair_nao_volta_pela_api(cliente, vaga):
    itens = cliente.get(f"/vagas/{vaga}/candidatos", headers=SESSAO).json()["itens"]
    saiu = next(i["candidato"] for i in itens if i["candidato"]["id"] == "saiu")
    assert (saiu["nome"], saiu["perfil_texto"], saiu["atributos"]) == ("", "", {})


def test_resumo_bate_com_a_lista_de_candidatos(cliente, vaga):
    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]
    itens = cliente.get(f"/vagas/{vaga}/candidatos", headers=SESSAO).json()["itens"]
    decisoes = [item["decisao"] for item in itens]
    assert resumo["estado"] == "convidando"
    assert resumo["analisados"] == 2
    assert resumo["indicados"] == decisoes.count(TipoDecisao.INDICAR.value)
    assert resumo["descartados"] == decisoes.count(TipoDecisao.DESCARTAR.value)
    assert resumo["na_fila_humana"] == decisoes.count(TipoDecisao.PEDIR_HUMANO.value)
    assert resumo["revertidos"] == 0
    assert resumo["limite_gasto_usd"] == PEDIDO_MANDATO["limite_gasto_usd"]
    assert resumo["simulado"] is True


def test_resumo_conta_reversoes_e_gasto_do_medidor(tmp_path):
    cliente = TestClient(
        criar_app(servico_de_teste(tmp_path / "agente.db", medidor_gasto=lambda: 0.25))
    )
    vaga = _vaga_executada(cliente)
    cliente.post(
        "/candidatos/verde/reverter", headers=SESSAO, json={**PEDIDO_REVERSAO, "vaga_id": vaga}
    )

    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]

    assert resumo["revertidos"] == 1
    assert resumo["gasto_usd"] == 0.25


def test_resumo_antes_do_mandato_nao_inventa_numero(cliente):
    vaga = _criar_vaga(cliente)
    resumo = cliente.get(f"/vagas/{vaga}/resumo", headers=SESSAO).json()["resumo"]
    assert resumo["estado"] == "aguardando_mandato"
    assert (resumo["analisados"], resumo["indicados"], resumo["gasto_usd"]) == (0, 0, 0.0)
    assert resumo["limite_gasto_usd"] is None


def test_eventos_trazem_o_caminho_da_vaga_sem_texto_do_candidato(cliente, vaga):
    corpo = cliente.get(f"/vagas/{vaga}/eventos", headers=SESSAO, params={"limite": 100}).json()
    etapas = [evento["etapa"] for evento in corpo["itens"]]
    assert etapas[0] == "aguardando_mandato"
    assert "buscando" in etapas
    assert "Cinco anos" not in str(corpo["itens"])


def test_metricas_fixas_cobrem_os_tipos_com_a_vaga_consultada(cliente, vaga):
    corpo = cliente.get(f"/vagas/{vaga}/metricas", headers=SESSAO).json()
    assert corpo["vaga_id"] == vaga
    assert corpo["exemplo_fixo"] is True
    assert set(corpo["erros_por_tipo"]) == {tipo.value for tipo in TipoErro}


def test_metricas_fixas_mostram_nao_medido_como_nulo(cliente, vaga):
    corpo = cliente.get(f"/vagas/{vaga}/metricas", headers=SESSAO).json()
    nao_medidas = [t for t in corpo["erros_por_tipo"].values() if t["casos"] == 0]
    assert nao_medidas
    assert all(taxa["valor"] is None for taxa in nao_medidas)


def test_intervalos_das_metricas_fixas_seguem_wilson(cliente, vaga):
    corpo = cliente.get(f"/vagas/{vaga}/metricas", headers=SESSAO).json()
    taxas = [corpo["sem_revisao"], *corpo["erros_por_tipo"].values()]
    medidas = [taxa for taxa in taxas if taxa["valor"] is not None]
    assert medidas
    for taxa in medidas:
        casos = taxa["casos"]
        assert (taxa["wilson_inferior"], taxa["wilson_superior"]) == _wilson(
            round(taxa["valor"] * casos), casos
        )


def test_metricas_injetadas_deixam_de_ser_exemplo_fixo(tmp_path):
    nao_medida = TaxaMedida(valor=None, casos=0, wilson_inferior=None, wilson_superior=None)
    pedidas: list[tuple[str, str]] = []

    def metricas(empresa_id: str, vaga_id: str) -> MetricasVaga:
        pedidas.append((empresa_id, vaga_id))
        return MetricasVaga(
            sem_revisao=nao_medida, erros_por_tipo={tipo: nao_medida for tipo in TipoErro}
        )

    cliente = TestClient(criar_app(servico_de_teste(tmp_path / "agente.db", metricas=metricas)))
    vaga = _vaga_executada(cliente)

    corpo = cliente.get(f"/vagas/{vaga}/metricas", headers=SESSAO).json()

    assert corpo["exemplo_fixo"] is False
    assert corpo["sem_revisao"]["valor"] is None
    assert pedidas == [("empresa-a", vaga)]


# Limites do agente


def test_api_nao_oferece_agendar_entrevistar_nem_contratar():
    esquema = app.openapi()
    proibidos = ("agend", "entrevist", "contrat", "aprovar", "lote")
    for caminho, operacoes in esquema["paths"].items():
        assert not any(termo in caminho for termo in proibidos), caminho
        for operacao in operacoes.values():
            assert not any(termo in operacao["operationId"] for termo in proibidos)
    for nome, modelo in esquema["components"]["schemas"].items():
        for campo in modelo.get("properties", {}):
            assert not any(termo in campo for termo in ("agend", "entrevist", "contrat")), (
                f"{nome}.{campo}"
            )


def test_contratada_so_aparece_como_destino_registrado_por_pessoa():
    esquemas = app.openapi()["components"]["schemas"]
    com_contratada = {
        nome for nome, modelo in esquemas.items() if "contratada" in modelo.get("enum", [])
    }
    assert com_contratada == {"DestinoPessoa"}
    assert "responsavel" in esquemas["PedidoDestino"]["required"]


def test_descricao_registra_proposta_e_limites_do_agente():
    descricao = app.openapi()["info"]["description"]
    assert "proposta" in descricao.lower()
    assert "acordo das frentes" in descricao
    assert "não agenda" in descricao
    assert "não entrevista" in descricao
    assert "não decide contratações" in descricao
    assert "exemplo_fixo" in descricao


def test_erro_inesperado_de_validacao_nao_vira_mensagem_para_o_cliente(servico):
    aplicacao = criar_app(servico)

    @aplicacao.get("/falha")
    def falha() -> None:
        raise ValueError("sk-segredo-de-teste")

    resposta = TestClient(aplicacao, raise_server_exceptions=False).get("/falha")
    assert resposta.status_code == 500
    assert "sk-segredo-de-teste" not in resposta.text
