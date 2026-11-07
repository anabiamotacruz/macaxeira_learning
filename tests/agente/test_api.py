from math import sqrt

import pytest
from fastapi.testclient import TestClient

from backend.agente.api import LIMITE_MAXIMO, app, criar_app
from backend.contratos.modelos import DestinoPessoa, TipoDecisao, TipoErro

SESSAO = {"X-Empresa-Id": "empresa-exemplo"}
OUTRA_EMPRESA = {"X-Empresa-Id": "empresa-outra"}
VAGA = "vaga-exemplo-1"
CANDIDATO = "candidato-exemplo-1"

PEDIDO_VAGA = {
    "titulo": "Pessoa Desenvolvedora (fictícia)",
    "descricao": "Vaga sintética",
    "requisitos": [
        {
            "id": "python",
            "descricao": "Experiência com Python",
            "campo": "linguagem",
            "valor_esperado": "python",
        }
    ],
    "competencias": [{"nome": "APIs", "peso": 1.0}],
    "meta_candidatos": 2,
    "prazo_dias": 14,
    "max_tentativas_contato": 2,
}
PEDIDO_MANDATO = {
    "assinante": "Pessoa Responsável Fictícia",
    "limite_gasto_usd": 5.0,
    "politica": {
        "limiar_verde": 0.8,
        "piso_nota": 0.5,
        "max_indicacoes": 2,
        "max_ampliacoes": 1,
    },
}
PEDIDO_CONTROLE = {"responsavel": "Pessoa Responsável Fictícia", "chave_idempotencia": "k1"}
PEDIDO_REVERSAO = {
    "vaga_id": VAGA,
    "motivo": "Revisão humana",
    "responsavel": "Pessoa Responsável Fictícia",
    "chave_idempotencia": "k2",
}
PEDIDO_DESTINO = {
    "vaga_id": VAGA,
    "destino": "banco",
    "responsavel": "Pessoa Responsável Fictícia",
    "chave_idempotencia": "k3",
}

ROTAS = [
    ("post", "/vagas", PEDIDO_VAGA, 201),
    ("post", f"/vagas/{VAGA}/mandato", PEDIDO_MANDATO, 201),
    ("get", f"/vagas/{VAGA}", None, 200),
    ("get", f"/vagas/{VAGA}/candidatos", None, 200),
    ("get", f"/vagas/{VAGA}/eventos", None, 200),
    ("get", f"/vagas/{VAGA}/entrega", None, 200),
    ("get", f"/vagas/{VAGA}/resumo", None, 200),
    ("get", f"/vagas/{VAGA}/metricas", None, 200),
    ("get", f"/candidatos/{CANDIDATO}/decisao", None, 200),
    ("post", f"/vagas/{VAGA}/parar", PEDIDO_CONTROLE, 200),
    ("post", f"/vagas/{VAGA}/retomar", PEDIDO_CONTROLE, 200),
    ("post", f"/candidatos/{CANDIDATO}/reverter", PEDIDO_REVERSAO, 200),
    ("post", f"/candidatos/{CANDIDATO}/destino", PEDIDO_DESTINO, 200),
    ("post", "/sessoes/reiniciar", None, 200),
]
ROTAS_COM_RECURSO = [rota for rota in ROTAS if rota[1] not in {"/vagas", "/sessoes/reiniciar"}]


@pytest.fixture
def cliente() -> TestClient:
    return TestClient(app)


def _chamar(cliente: TestClient, metodo: str, caminho: str, corpo: dict | None, cabecalhos: dict):
    argumentos = {"headers": cabecalhos}
    if corpo is not None:
        argumentos["json"] = corpo
    return cliente.request(metodo, caminho, **argumentos)


def _ids(rota: tuple) -> str:
    return f"{rota[0]} {rota[1]}"


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


# Rotas e identificação da simulação


def test_expoe_exatamente_as_rotas_combinadas():
    rotas = {
        (metodo, caminho)
        for caminho, operacoes in app.openapi()["paths"].items()
        for metodo in operacoes
    }
    assert rotas == {
        ("post", "/vagas"),
        ("post", "/vagas/{id}/mandato"),
        ("get", "/vagas/{id}"),
        ("get", "/vagas/{id}/candidatos"),
        ("get", "/vagas/{id}/eventos"),
        ("get", "/vagas/{id}/entrega"),
        ("get", "/vagas/{id}/resumo"),
        ("get", "/vagas/{id}/metricas"),
        ("get", "/candidatos/{id}/decisao"),
        ("post", "/vagas/{id}/parar"),
        ("post", "/vagas/{id}/retomar"),
        ("post", "/candidatos/{id}/reverter"),
        ("post", "/candidatos/{id}/destino"),
        ("post", "/sessoes/reiniciar"),
    }


@pytest.mark.parametrize("rota", ROTAS, ids=_ids)
def test_respostas_identificam_simulacao(cliente, rota):
    metodo, caminho, corpo, status = rota
    resposta = _chamar(cliente, metodo, caminho, corpo, SESSAO)
    assert resposta.status_code == status, resposta.text
    assert resposta.json()["simulado"] is True
    assert resposta.json()["exemplo_fixo"] is True


@pytest.mark.parametrize(
    "metodo, caminho, cabecalhos",
    [
        ("get", f"/vagas/{VAGA}", {}),
        ("get", "/vagas/nao-existe", SESSAO),
        ("get", "/rota-que-nao-existe", SESSAO),
        ("delete", f"/vagas/{VAGA}", SESSAO),
        ("get", f"/vagas/{VAGA}/candidatos?limite=0", SESSAO),
    ],
)
def test_erros_tambem_identificam_simulacao(cliente, metodo, caminho, cabecalhos):
    _erro_padrao(cliente.request(metodo, caminho, headers=cabecalhos))


def test_dados_de_candidato_sao_sinteticos_e_marcados(cliente):
    itens = cliente.get(f"/vagas/{VAGA}/candidatos", headers=SESSAO).json()["itens"]
    assert itens
    for item in itens:
        assert item["candidato"]["simulado"] is True
        assert "Fictícia" in item["candidato"]["nome"]


def test_saida_personalizada_traz_pacote_identificado(cliente):
    saida = cliente.get(f"/vagas/{VAGA}/entrega", headers=SESSAO).json()["saida"]
    assert saida["simulado"] is True
    assert saida["pacotes"]
    assert all(pacote["simulado"] is True for pacote in saida["pacotes"])


# Sessão e isolamento


@pytest.mark.parametrize("rota", ROTAS, ids=_ids)
def test_sem_sessao_recebe_401(cliente, rota):
    metodo, caminho, corpo, _ = rota
    resposta = _chamar(cliente, metodo, caminho, corpo, {})
    assert resposta.status_code == 401
    assert _erro_padrao(resposta)["codigo"] == "sessao_ausente"


@pytest.mark.parametrize("valor", ["   ", "empresa com espacos", "a" * 65, "<script>"])
def test_sessao_invalida_recebe_401(cliente, valor):
    resposta = cliente.get(f"/vagas/{VAGA}", headers={"X-Empresa-Id": valor})
    assert resposta.status_code == 401
    assert _erro_padrao(resposta)["codigo"] == "sessao_ausente"
    assert valor not in resposta.text


@pytest.mark.parametrize("rota", ROTAS_COM_RECURSO, ids=_ids)
def test_outra_empresa_recebe_404(cliente, rota):
    metodo, caminho, corpo, _ = rota
    resposta = _chamar(cliente, metodo, caminho, corpo, OUTRA_EMPRESA)
    assert resposta.status_code == 404
    _erro_padrao(resposta)
    assert "empresa-exemplo" not in resposta.text
    assert "Fictícia" not in resposta.text


def test_recurso_de_outra_empresa_e_inexistente_tem_a_mesma_resposta(cliente):
    de_outra_empresa = cliente.get(f"/vagas/{VAGA}", headers=OUTRA_EMPRESA)
    inexistente = cliente.get("/vagas/nao-existe", headers=OUTRA_EMPRESA)
    assert de_outra_empresa.json() == inexistente.json()


def test_empresa_no_corpo_e_rejeitada(cliente):
    resposta = cliente.post("/vagas", headers=SESSAO, json={**PEDIDO_VAGA, "empresa_id": "outra"})
    assert resposta.status_code == 422
    _erro_padrao(resposta)


def test_empresa_na_consulta_nao_substitui_a_sessao(cliente):
    resposta = cliente.get(f"/vagas/{VAGA}?empresa_id=empresa-exemplo", headers=OUTRA_EMPRESA)
    assert resposta.status_code == 404


def test_vaga_nova_pertence_a_empresa_da_sessao(cliente):
    resposta = cliente.post("/vagas", headers=OUTRA_EMPRESA, json=PEDIDO_VAGA)
    assert resposta.status_code == 201
    assert resposta.json()["vaga"]["empresa_id"] == "empresa-outra"


def test_reiniciar_vale_para_a_empresa_da_sessao_e_nao_finge_recarga(cliente):
    corpo = cliente.post("/sessoes/reiniciar", headers=OUTRA_EMPRESA).json()
    assert corpo["empresa_id"] == "empresa-outra"
    assert corpo["dados_recarregados"] is False


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
    resposta = cliente.post(
        f"/vagas/{VAGA}/mandato", headers=SESSAO, json={**PEDIDO_MANDATO, **ajuste}
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
    resposta = cliente.post(
        f"/vagas/{VAGA}/mandato",
        headers=SESSAO,
        json={**PEDIDO_MANDATO, "assinante": 1, "limite_gasto_usd": segredo, segredo: segredo},
    )
    assert resposta.status_code == 422
    assert segredo not in resposta.text


def test_erro_nao_expoe_stack_trace_nem_chave():
    aplicacao = criar_app()

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
def test_lista_pagina_com_limite(cliente, recurso):
    corpo = cliente.get(
        f"/vagas/{VAGA}/{recurso}", params={"pagina": 2, "limite": 1}, headers=SESSAO
    ).json()
    assert (corpo["pagina"], corpo["limite"]) == (2, 1)
    assert len(corpo["itens"]) == 1
    assert corpo["total"] >= 2


@pytest.mark.parametrize("recurso", ["candidatos", "eventos"])
def test_pagina_alem_do_fim_vem_vazia(cliente, recurso):
    corpo = cliente.get(f"/vagas/{VAGA}/{recurso}", params={"pagina": 99}, headers=SESSAO).json()
    assert corpo["itens"] == []
    assert corpo["total"] > 0


@pytest.mark.parametrize("recurso", ["candidatos", "eventos"])
@pytest.mark.parametrize(
    "parametros", [{"limite": LIMITE_MAXIMO + 1}, {"limite": 0}, {"pagina": 0}, {"pagina": "x"}]
)
def test_paginacao_fora_do_limite_devolve_422(cliente, recurso, parametros):
    resposta = cliente.get(f"/vagas/{VAGA}/{recurso}", params=parametros, headers=SESSAO)
    assert resposta.status_code == 422
    _erro_padrao(resposta)


# Controle depois da ação


def test_parar_e_idempotente(cliente):
    primeira = cliente.post(f"/vagas/{VAGA}/parar", headers=SESSAO, json=PEDIDO_CONTROLE)
    segunda = cliente.post(f"/vagas/{VAGA}/parar", headers=SESSAO, json=PEDIDO_CONTROLE)
    assert primeira.json() == segunda.json()
    assert primeira.json()["estado"] == "pausada"


def test_retomar_volta_ao_estado_anterior(cliente):
    parada = cliente.post(f"/vagas/{VAGA}/parar", headers=SESSAO, json=PEDIDO_CONTROLE).json()
    retomada = cliente.post(f"/vagas/{VAGA}/retomar", headers=SESSAO, json=PEDIDO_CONTROLE).json()
    assert retomada["estado"] == parada["estado_anterior"]


@pytest.mark.parametrize(
    "caminho, pedido, campo",
    [
        (f"/vagas/{VAGA}/parar", PEDIDO_CONTROLE, "chave_idempotencia"),
        (f"/vagas/{VAGA}/parar", PEDIDO_CONTROLE, "responsavel"),
        (f"/vagas/{VAGA}/retomar", PEDIDO_CONTROLE, "chave_idempotencia"),
        (f"/candidatos/{CANDIDATO}/reverter", PEDIDO_REVERSAO, "chave_idempotencia"),
        (f"/candidatos/{CANDIDATO}/reverter", PEDIDO_REVERSAO, "responsavel"),
        (f"/candidatos/{CANDIDATO}/reverter", PEDIDO_REVERSAO, "motivo"),
        (f"/candidatos/{CANDIDATO}/destino", PEDIDO_DESTINO, "chave_idempotencia"),
        (f"/candidatos/{CANDIDATO}/destino", PEDIDO_DESTINO, "responsavel"),
    ],
)
def test_acao_repetivel_exige_campos_obrigatorios(cliente, caminho, pedido, campo):
    corpo = {chave: valor for chave, valor in pedido.items() if chave != campo}
    resposta = cliente.post(caminho, headers=SESSAO, json=corpo)
    assert resposta.status_code == 422
    _erro_padrao(resposta)


def test_reverter_preserva_decisao_original(cliente):
    atual = cliente.get(f"/candidatos/{CANDIDATO}/decisao", headers=SESSAO).json()["decisao"]
    reversao = cliente.post(
        f"/candidatos/{CANDIDATO}/reverter", headers=SESSAO, json=PEDIDO_REVERSAO
    ).json()
    assert reversao["decisao_original"] == atual
    assert reversao["decisao_nova"]["regra"] == "reversao_humana"
    assert reversao["decisao_nova"]["entrada"]["rastro_revertido"] == atual["rastro_id"]


def test_reverter_em_vaga_que_nao_e_da_empresa_recebe_404(cliente):
    resposta = cliente.post(
        f"/candidatos/{CANDIDATO}/reverter",
        headers=SESSAO,
        json={**PEDIDO_REVERSAO, "vaga_id": "vaga-de-outra-empresa"},
    )
    assert resposta.status_code == 404


def test_decisao_filtra_por_vaga(cliente):
    caminho = f"/candidatos/{CANDIDATO}/decisao"
    assert cliente.get(caminho, params={"vaga_id": VAGA}, headers=SESSAO).status_code == 200
    assert cliente.get(caminho, params={"vaga_id": "outra"}, headers=SESSAO).status_code == 404


@pytest.mark.parametrize("destino", list(DestinoPessoa))
def test_destino_guarda_quem_decidiu(cliente, destino):
    corpo = cliente.post(
        f"/candidatos/{CANDIDATO}/destino",
        headers=SESSAO,
        json={**PEDIDO_DESTINO, "destino": destino.value},
    ).json()
    assert corpo["destino"] == destino.value
    assert corpo["responsavel"] == PEDIDO_DESTINO["responsavel"]


def test_destino_fora_da_lista_e_recusado(cliente):
    resposta = cliente.post(
        f"/candidatos/{CANDIDATO}/destino",
        headers=SESSAO,
        json={**PEDIDO_DESTINO, "destino": "entrevista"},
    )
    assert resposta.status_code == 422


# Coerência dos exemplos


def test_resumo_bate_com_a_lista_de_candidatos(cliente):
    resumo = cliente.get(f"/vagas/{VAGA}/resumo", headers=SESSAO).json()["resumo"]
    itens = cliente.get(f"/vagas/{VAGA}/candidatos", headers=SESSAO).json()["itens"]
    decisoes = [item["decisao"] for item in itens]
    assert resumo["analisados"] == len(itens)
    assert resumo["indicados"] == decisoes.count(TipoDecisao.INDICAR.value)
    assert resumo["descartados"] == decisoes.count(TipoDecisao.DESCARTAR.value)
    assert resumo["na_fila_humana"] == decisoes.count(TipoDecisao.PEDIR_HUMANO.value)


def test_evidencias_dos_exemplos_existem_no_perfil(cliente):
    itens = cliente.get(f"/vagas/{VAGA}/candidatos", headers=SESSAO).json()["itens"]
    for item in itens:
        candidato = item["candidato"]
        decisao = cliente.get(f"/candidatos/{candidato['id']}/decisao", headers=SESSAO).json()
        for evidencia in decisao["decisao"]["evidencias"]:
            assert evidencia["trecho"] in candidato["perfil_texto"]


def test_metricas_cobrem_todos_os_tipos_de_erro(cliente):
    corpo = cliente.get(f"/vagas/{VAGA}/metricas", headers=SESSAO).json()
    assert set(corpo["erros_por_tipo"]) == {tipo.value for tipo in TipoErro}


def test_metricas_mostram_nao_medido_como_nulo(cliente):
    corpo = cliente.get(f"/vagas/{VAGA}/metricas", headers=SESSAO).json()
    nao_medidas = [t for t in corpo["erros_por_tipo"].values() if t["casos"] == 0]
    assert nao_medidas
    assert all(taxa["valor"] is None for taxa in nao_medidas)


def test_intervalos_dos_exemplos_seguem_wilson(cliente):
    corpo = cliente.get(f"/vagas/{VAGA}/metricas", headers=SESSAO).json()
    taxas = [corpo["sem_revisao"], *corpo["erros_por_tipo"].values()]
    medidas = [taxa for taxa in taxas if taxa["valor"] is not None]
    assert medidas
    for taxa in medidas:
        casos = taxa["casos"]
        assert (taxa["wilson_inferior"], taxa["wilson_superior"]) == _wilson(
            round(taxa["valor"] * casos), casos
        )


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
