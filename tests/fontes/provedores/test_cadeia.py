import json
import logging
import threading

import pytest

from backend.agente.auditoria import contexto_rastro
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.cadeia import CadeiaProvedores, ModoDados
from backend.fontes.provedores.controles import (
    CacheConsultas,
    MetricasProvedores,
    OrcamentoProvedores,
)
from backend.fontes.provedores.erros import ErroProvedor, MotivoTroca, UrlRecusada
from backend.fontes.provedores.modelos import (
    ConfiancaDado,
    ConsultaProvedor,
    ContatoColetado,
    IdentidadeConsulta,
    ItemColetado,
    ProvedorDados,
    RespostaProvedor,
    SituacaoConsulta,
    id_externo_de_email,
    id_externo_de_url,
)
from tests.fontes.provedores.apoio import MOMENTO

EMPRESA = "empresa-a"
EMAIL = "pessoa@exemplo-ficticio.com.br"
URL = "https://site-ficticio.com.br/portfolio"
POR_URL = ConsultaProvedor(url=URL)
POR_TEXTO = ConsultaProvedor(texto="python recife")
POR_EMAIL = ConsultaProvedor(identidade=IdentidadeConsulta(email=EMAIL))


def item(provedor: str = "p1", **campos) -> ItemColetado:
    return ItemColetado(
        **{
            "provedor": provedor,
            "fonte": f"{provedor}:teste",
            "coletado_em": MOMENTO,
            "url": URL,
            "confianca": ConfiancaDado.INFERIDO,
            "texto": "Perfil fictício.",
            **campos,
        }
    )


def achou(provedor: str = "p1", custo: float = 0.1, **campos) -> RespostaProvedor:
    return RespostaProvedor(itens=[item(provedor, **campos)], custo_usd=custo)


NADA = RespostaProvedor()


class ProvedorFalso:
    def __init__(self, nome, *respostas, aceita=True, custo=0.1):
        self.nome = nome
        self.respostas = list(respostas)
        self.consultas = []
        self._aceita = aceita
        self._custo = custo

    def aceita(self, consulta):
        return self._aceita

    def custo_maximo(self, consulta):
        return self._custo

    def consultar(self, consulta):
        self.consultas.append(consulta)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class SupressaoFalsa:
    def __init__(self, *ids, emails=()):
        self.ids = set(ids)
        self.emails = set(emails)

    def suprimida(self, empresa_id, candidato_id, email):
        return candidato_id in self.ids or email in self.emails


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


def cadeia_com(*provedores, **opcoes) -> CadeiaProvedores:
    return CadeiaProvedores(
        list(provedores),
        **{
            "supressao": SupressaoFalsa(),
            "orcamento": OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=100),
            "dormir": lambda _: None,
            "tentativas": 2,
            "limite_falhas": 3,
            **opcoes,
        },
    )


def test_o_falso_cumpre_a_interface():
    assert isinstance(ProvedorFalso("p"), ProvedorDados)


def test_ordem_primeiro_provedor_responde_e_o_segundo_nao_e_chamado():
    p1, p2 = ProvedorFalso("p1", achou("p1")), ProvedorFalso("p2", achou("p2"))
    resultado = cadeia_com(p1, p2).consultar(EMPRESA, POR_URL)
    assert resultado.situacao == SituacaoConsulta.ENCONTRADO
    assert resultado.provedor == "p1"
    assert resultado.trocas == []
    assert p2.consultas == []


def test_troca_por_nao_encontrado_registra_o_motivo():
    p1, p2 = ProvedorFalso("p1", NADA), ProvedorFalso("p2", achou("p2"))
    resultado = cadeia_com(p1, p2).consultar(EMPRESA, POR_URL)
    assert resultado.provedor == "p2"
    assert [(t.de, t.para, t.motivo) for t in resultado.trocas] == [
        ("p1", "p2", MotivoTroca.NAO_ENCONTRADO)
    ]
    assert resultado.cobertura_parcial is False


def test_troca_por_falha_repete_antes_e_registra_o_motivo():
    falha = FonteIndisponivel("fora do ar")
    p1, p2 = ProvedorFalso("p1", falha, falha), ProvedorFalso("p2", achou("p2"))
    resultado = cadeia_com(p1, p2).consultar(EMPRESA, POR_URL)
    assert len(p1.consultas) == 2
    assert resultado.provedor == "p2"
    assert resultado.trocas[0].motivo == MotivoTroca.FALHA_TEMPORARIA
    assert resultado.cobertura_parcial is True


def test_repeticao_com_sucesso_nao_troca():
    p1 = ProvedorFalso("p1", ConnectionError("queda"), achou("p1"))
    resultado = cadeia_com(p1, ProvedorFalso("p2")).consultar(EMPRESA, POR_URL)
    assert resultado.provedor == "p1"
    assert resultado.trocas == []


def test_erro_permanente_troca_sem_repetir():
    p1 = ProvedorFalso("p1", ErroProvedor(MotivoTroca.AUTENTICACAO))
    p2 = ProvedorFalso("p2", achou("p2"))
    resultado = cadeia_com(p1, p2).consultar(EMPRESA, POR_URL)
    assert len(p1.consultas) == 1
    assert resultado.trocas[0].motivo == MotivoTroca.AUTENTICACAO


def test_provedor_que_nao_aceita_a_consulta_fica_registrado_e_nao_e_chamado():
    p1 = ProvedorFalso("p1", aceita=False)
    p2 = ProvedorFalso("p2", achou("p2"))
    resultado = cadeia_com(p1, p2).consultar(EMPRESA, POR_EMAIL)
    assert p1.consultas == []
    assert resultado.trocas[0].motivo == MotivoTroca.CONSULTA_NAO_SUPORTADA


def test_nenhum_provedor_aceita_devolve_situacao_propria():
    resultado = cadeia_com(ProvedorFalso("p1", aceita=False)).consultar(EMPRESA, POR_TEXTO)
    assert resultado.situacao == SituacaoConsulta.NAO_SUPORTADA


def test_nenhum_encontra():
    resultado = cadeia_com(ProvedorFalso("p1", NADA), ProvedorFalso("p2", NADA)).consultar(
        EMPRESA, POR_URL
    )
    assert resultado.situacao == SituacaoConsulta.NAO_ENCONTRADO
    assert resultado.provedor is None
    assert [t.para for t in resultado.trocas] == ["p2", None]


def test_falha_de_ambos_vira_fonte_indisponivel_com_os_motivos():
    falha = FonteIndisponivel("fora do ar")
    cadeia = cadeia_com(
        ProvedorFalso("p1", falha, falha),
        ProvedorFalso("p2", ErroProvedor(MotivoTroca.SEM_CREDITOS)),
    )
    with pytest.raises(FonteIndisponivel) as erro:
        cadeia.consultar(EMPRESA, POR_URL)
    assert "p1=falha_temporaria" in str(erro.value)
    assert "p2=sem_creditos" in str(erro.value)


def test_falha_de_um_e_nao_encontrado_do_outro_e_cobertura_parcial():
    falha = FonteIndisponivel("fora do ar")
    cadeia = cadeia_com(ProvedorFalso("p1", falha, falha), ProvedorFalso("p2", NADA))
    resultado = cadeia.consultar(EMPRESA, POR_URL)
    assert resultado.situacao == SituacaoConsulta.NAO_ENCONTRADO
    assert resultado.cobertura_parcial is True


def test_disjuntor_abre_e_o_provedor_para_de_ser_chamado():
    relogio = Relogio()
    falhas = [FonteIndisponivel("x") for _ in range(2)]
    p1 = ProvedorFalso("p1", *falhas, achou("p1"))
    p2 = ProvedorFalso("p2", NADA, NADA)
    cadeia = cadeia_com(p1, p2, limite_falhas=1, espera_disjuntor=60, relogio_disjuntor=relogio)

    cadeia.consultar(EMPRESA, POR_URL)
    chamadas = len(p1.consultas)
    segunda = cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/2"))
    assert len(p1.consultas) == chamadas
    assert segunda.trocas[0].motivo == MotivoTroca.DISJUNTOR_ABERTO

    relogio.agora = 61
    terceira = cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/3"))
    assert terceira.provedor == "p1"


def test_erro_permanente_nao_abre_o_disjuntor():
    respostas = [ErroProvedor(MotivoTroca.AUTENTICACAO) for _ in range(3)]
    p1 = ProvedorFalso("p1", *respostas)
    p2 = ProvedorFalso("p2", NADA, NADA, NADA)
    cadeia = cadeia_com(p1, p2, limite_falhas=1)
    for indice in range(3):
        cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/{indice}"))
    assert len(p1.consultas) == 3


def test_orcamento_da_execucao_barra_antes_de_chamar():
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=0.05)
    p1 = ProvedorFalso("p1", achou("p1"), custo=0.1)
    with pytest.raises(FonteIndisponivel) as erro:
        cadeia_com(p1, orcamento=orcamento).consultar(EMPRESA, POR_URL)
    assert p1.consultas == []
    assert "orcamento_esgotado" in str(erro.value)


def test_orcamento_usa_a_execucao_do_contexto_de_rastro():
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=0.15)
    p1 = ProvedorFalso("p1", *[achou("p1") for _ in range(3)])
    cadeia = cadeia_com(p1, orcamento=orcamento)
    with contexto_rastro(empresa_id=EMPRESA, execucao_id="x1"):
        cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/1"))
        with pytest.raises(FonteIndisponivel):
            cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/2"))
    with contexto_rastro(empresa_id=EMPRESA, execucao_id="x2"):
        assert cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/3")).provedor == "p1"
    assert orcamento.gasto_execucao(EMPRESA, "x1") == pytest.approx(0.1)


def test_orcamento_da_empresa_barra_entre_execucoes():
    orcamento = OrcamentoProvedores(limite_empresa_usd=0.15, limite_execucao_usd=100)
    p1 = ProvedorFalso("p1", achou("p1"), achou("p1"))
    cadeia = cadeia_com(p1, orcamento=orcamento)
    with contexto_rastro(empresa_id=EMPRESA, execucao_id="x1"):
        cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/1"))
    with contexto_rastro(empresa_id=EMPRESA, execucao_id="x2"), pytest.raises(FonteIndisponivel):
        cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/2"))


def test_orcamento_esgotado_num_provedor_tenta_o_mais_barato():
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=0.05)
    caro = ProvedorFalso("p1", custo=0.28)
    barato = ProvedorFalso("p2", achou("p2", custo=0.001), custo=0.001)
    resultado = cadeia_com(caro, barato, orcamento=orcamento).consultar(EMPRESA, POR_URL)
    assert resultado.provedor == "p2"
    assert resultado.trocas[0].motivo == MotivoTroca.ORCAMENTO_ESGOTADO


def test_falha_devolve_a_reserva_e_custo_real_vale_no_orcamento():
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=100)
    falha = FonteIndisponivel("x")
    p1 = ProvedorFalso("p1", falha, falha)
    p2 = ProvedorFalso("p2", achou("p2", custo=0.03), custo=0.5)
    resultado = cadeia_com(p1, p2, orcamento=orcamento).consultar(EMPRESA, POR_URL)
    assert orcamento.gasto_empresa(EMPRESA) == pytest.approx(0.03)
    assert resultado.custo_usd == pytest.approx(0.03)


def test_cobranca_ate_a_falha_permanente_vale_no_orcamento():
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=100)
    p1 = ProvedorFalso("p1", ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA, 0.28))
    resultado = cadeia_com(p1, ProvedorFalso("p2", NADA), orcamento=orcamento).consultar(
        EMPRESA, POR_URL
    )
    assert orcamento.gasto_empresa(EMPRESA) == pytest.approx(0.28)
    assert resultado.custo_usd == pytest.approx(0.28)


def test_cache_nao_paga_duas_vezes_e_indica_a_origem():
    p1 = ProvedorFalso("p1", achou("p1"))
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=100)
    metricas = MetricasProvedores()
    cadeia = cadeia_com(p1, orcamento=orcamento, metricas=metricas)
    cadeia.consultar(EMPRESA, POR_URL)
    segundo = cadeia.consultar(EMPRESA, POR_URL)
    assert len(p1.consultas) == 1
    assert segundo.do_cache is True
    assert segundo.custo_usd == 0
    assert segundo.provedor == "p1"
    assert orcamento.gasto_empresa(EMPRESA) == pytest.approx(0.1)
    assert metricas.fotografia()["cache_acertos"] == 1


def test_cache_guarda_nao_encontrado_de_todos():
    p1 = ProvedorFalso("p1", NADA)
    cadeia = cadeia_com(p1)
    cadeia.consultar(EMPRESA, POR_URL)
    assert cadeia.consultar(EMPRESA, POR_URL).situacao == SituacaoConsulta.NAO_ENCONTRADO
    assert len(p1.consultas) == 1


def test_cache_nao_guarda_falha_nem_vazio_com_cobertura_parcial():
    falha = FonteIndisponivel("x")
    p1 = ProvedorFalso("p1", falha, falha, achou("p1"))
    p2 = ProvedorFalso("p2", NADA)
    cadeia = cadeia_com(p1, p2)
    assert cadeia.consultar(EMPRESA, POR_URL).cobertura_parcial
    assert cadeia.consultar(EMPRESA, POR_URL).provedor == "p1"


def test_cache_nao_cruza_empresas():
    p1 = ProvedorFalso("p1", achou("p1"), achou("p1"))
    cadeia = cadeia_com(p1)
    cadeia.consultar("empresa-a", POR_URL)
    assert cadeia.consultar("empresa-b", POR_URL).do_cache is False
    assert len(p1.consultas) == 2


def test_cache_expira():
    momento = [0.0]
    p1 = ProvedorFalso("p1", achou("p1"), achou("p1"))
    cadeia = cadeia_com(p1, cache=CacheConsultas(ttl_s=10, relogio=lambda: momento[0]))
    cadeia.consultar(EMPRESA, POR_URL)
    momento[0] = 11
    cadeia.consultar(EMPRESA, POR_URL)
    assert len(p1.consultas) == 2


def test_chamadas_simultaneas_da_mesma_consulta_pagam_uma_vez():
    entrou = threading.Event()
    soltar = threading.Event()

    class Lento(ProvedorFalso):
        def consultar(self, consulta):
            entrou.set()
            soltar.wait(5)
            return super().consultar(consulta)

    p1 = Lento("p1", achou("p1"))
    cadeia = cadeia_com(p1)
    resultados = []
    linhas = [
        threading.Thread(target=lambda: resultados.append(cadeia.consultar(EMPRESA, POR_URL)))
        for _ in range(2)
    ]
    linhas[0].start()
    entrou.wait(5)
    linhas[1].start()
    soltar.set()
    for linha in linhas:
        linha.join(5)
    assert len(p1.consultas) == 1
    assert len(resultados) == 2


@pytest.mark.parametrize(
    "consulta",
    [
        POR_EMAIL,
        ConsultaProvedor(identidade=IdentidadeConsulta(candidato_id="c-1", nome="N", empresa="E")),
        POR_URL,
    ],
)
def test_supressao_antes_de_consultar_nao_chama_nem_gasta(consulta):
    supressao = SupressaoFalsa("c-1", id_externo_de_url(URL), emails=[EMAIL])
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=100)
    p1 = ProvedorFalso("p1")
    resultado = cadeia_com(p1, supressao=supressao, orcamento=orcamento).consultar(
        EMPRESA, consulta
    )
    assert resultado.situacao == SituacaoConsulta.SUPRIMIDO
    assert p1.consultas == []
    assert orcamento.gasto_empresa(EMPRESA) == 0


def test_supressao_ao_receber_retira_a_pessoa_e_conta_sem_identificar():
    p1 = ProvedorFalso(
        "p1",
        RespostaProvedor(
            itens=[
                item(url="https://bloqueada.com.br/", contatos=[contato(EMAIL)]),
                item(url="https://livre.com.br/"),
            ]
        ),
    )
    resultado = cadeia_com(p1, supressao=SupressaoFalsa(emails=[EMAIL])).consultar(
        EMPRESA, POR_TEXTO
    )
    assert [i.url for i in resultado.itens] == ["https://livre.com.br/"]
    assert resultado.suprimidos == 1


def contato(email: str) -> ContatoColetado:
    return ContatoColetado(tipo="email", valor=email)


def test_item_suprimido_por_id_derivado_de_email_ou_url():
    por_email = achou("p1", contatos=[contato(EMAIL)])
    resultado = cadeia_com(
        ProvedorFalso("p1", por_email), supressao=SupressaoFalsa(id_externo_de_email(EMAIL))
    ).consultar(EMPRESA, POR_TEXTO)
    assert resultado.situacao == SituacaoConsulta.SUPRIMIDO

    por_url = achou("p1", contatos=[contato("outro@ficticio.com.br")])
    resultado = cadeia_com(
        ProvedorFalso("p1", por_url), supressao=SupressaoFalsa(id_externo_de_url(URL))
    ).consultar(EMPRESA, POR_TEXTO)
    assert resultado.situacao == SituacaoConsulta.SUPRIMIDO


def test_todos_suprimidos_nao_paga_o_proximo_provedor():
    p2 = ProvedorFalso("p2")
    resultado = cadeia_com(
        ProvedorFalso("p1", achou("p1", contatos=[contato(EMAIL)])),
        p2,
        supressao=SupressaoFalsa(emails=[EMAIL]),
    ).consultar(EMPRESA, ConsultaProvedor(identidade=IdentidadeConsulta(nome="N", empresa="E")))
    assert resultado.situacao == SituacaoConsulta.SUPRIMIDO
    assert p2.consultas == []


def test_supressao_nova_vale_para_o_que_esta_no_cache():
    supressao = SupressaoFalsa()
    p1 = ProvedorFalso("p1", achou("p1", contatos=[contato(EMAIL)]))
    cadeia = cadeia_com(p1, supressao=supressao)
    consulta = ConsultaProvedor(texto="python")
    assert cadeia.consultar(EMPRESA, consulta).situacao == SituacaoConsulta.ENCONTRADO
    supressao.emails.add(EMAIL)
    assert cadeia.consultar(EMPRESA, consulta).situacao == SituacaoConsulta.SUPRIMIDO


def test_falha_ao_conferir_supressao_nao_consulta():
    class Quebrada:
        def suprimida(self, empresa_id, candidato_id, email):
            raise RuntimeError(f"banco fora {EMAIL}")

    p1 = ProvedorFalso("p1")
    with pytest.raises(FonteIndisponivel) as erro:
        cadeia_com(p1, supressao=Quebrada()).consultar(EMPRESA, POR_URL)
    assert p1.consultas == []
    assert EMAIL not in str(erro.value)


@pytest.mark.parametrize(
    "consulta",
    [
        ConsultaProvedor(url="https://www.linkedin.com/in/pessoa"),
        ConsultaProvedor(url="https://lnkd.in/abc"),
        ConsultaProvedor(url="http://localhost/"),
        ConsultaProvedor(texto="python site:linkedin.com"),
        ConsultaProvedor(identidade=IdentidadeConsulta(perfil="linkedin.com/in/pessoa")),
    ],
)
def test_consulta_proibida_nao_chega_a_nenhum_provedor(consulta):
    p1, p2 = ProvedorFalso("p1"), ProvedorFalso("p2")
    resultado = cadeia_com(p1, p2).consultar(EMPRESA, consulta)
    assert resultado.situacao == SituacaoConsulta.RECUSADA
    assert resultado.motivo_recusa is not None
    assert p1.consultas == p2.consultas == []


def test_recusa_no_meio_do_caminho_para_a_cadeia_e_guarda_o_custo():
    orcamento = OrcamentoProvedores(limite_empresa_usd=100, limite_execucao_usd=100)
    p1 = ProvedorFalso("p1", UrlRecusada(MotivoTroca.DOMINIO_RECUSADO, 0.0015))
    p2 = ProvedorFalso("p2")
    resultado = cadeia_com(p1, p2, orcamento=orcamento).consultar(EMPRESA, POR_URL)
    assert resultado.situacao == SituacaoConsulta.RECUSADA
    assert resultado.motivo_recusa == MotivoTroca.DOMINIO_RECUSADO
    assert p2.consultas == []
    assert orcamento.gasto_empresa(EMPRESA) == pytest.approx(0.0015)


def test_modo_sintetico_nao_chama_nenhum_provedor():
    p1 = ProvedorFalso("p1")
    resultado = cadeia_com(p1, modo=ModoDados.SINTETICOS).consultar(EMPRESA, POR_URL)
    assert resultado.situacao == SituacaoConsulta.SOMENTE_SINTETICOS
    assert p1.consultas == []


def test_sem_provedor_avisa_e_nao_levanta(caplog):
    caplog.set_level(logging.WARNING)
    resultado = cadeia_com().consultar(EMPRESA, POR_URL)
    assert resultado.situacao == SituacaoConsulta.SEM_FONTES_EXTERNAS
    assert "sem fontes externas" in caplog.text


def test_empresa_e_obrigatoria():
    with pytest.raises(ValueError):
        cadeia_com(ProvedorFalso("p1")).consultar("  ", POR_URL)


def test_metricas_de_custo_acertos_e_trocas_por_provedor():
    metricas = MetricasProvedores()
    falha = FonteIndisponivel("x")
    cadeia = cadeia_com(
        ProvedorFalso("p1", NADA, falha, falha),
        ProvedorFalso("p2", achou("p2", custo=0.3), achou("p2", custo=0.3)),
        metricas=metricas,
    )
    cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/1"))
    cadeia.consultar(EMPRESA, ConsultaProvedor(url=f"{URL}/2"))
    foto = metricas.fotografia()["provedores"]
    assert foto["p1"]["nao_encontrados"] == 1
    assert foto["p1"]["falhas"] == 1
    assert foto["p1"]["trocas"] == {"nao_encontrado": 1, "falha_temporaria": 1}
    assert foto["p2"]["acertos"] == 2
    assert foto["p2"]["custo_usd"] == pytest.approx(0.6)


def test_logs_nao_trazem_chave_nem_dado_pessoal(caplog):
    caplog.set_level(logging.DEBUG)
    falha = FonteIndisponivel("x")
    cadeia = cadeia_com(ProvedorFalso("p1", falha, falha), ProvedorFalso("p2", achou("p2")))
    resultado = cadeia.consultar(EMPRESA, POR_EMAIL)
    assert resultado.provedor == "p2"
    gravado = caplog.text + json.dumps(cadeia.metricas.fotografia())
    assert EMAIL not in gravado
    assert "site-ficticio" not in gravado
