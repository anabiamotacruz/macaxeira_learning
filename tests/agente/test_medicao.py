"""Ciclo de taxa de erro com casos sintéticos criados aqui. Valores conferidos à mão."""

from datetime import UTC, datetime
from math import isclose

import pytest
from pydantic import ValidationError

from backend.agente import auditoria, medicao
from backend.agente.medicao import (
    ProvaJaAberta,
    RegistroProvas,
    aplicar_limiar,
    calcular_metricas,
    escolher_limiar,
    intervalo_wilson,
    medir_taxa,
    passa_no_portao,
    rodar,
    rodar_prova,
    versionar_prompt,
)
from backend.contratos.modelos import (
    CasoAvaliacao,
    Evidencia,
    MetricasMedicao,
    Particao,
    RespostaAgente,
    ResultadoCaso,
    TipoDecisao,
    TipoErro,
)
from tests.agente.apoio import PERFIL_EXEMPLO, TRECHO_REQUISITO, candidato_exemplo, vaga_exemplo

INDICAR = TipoDecisao.INDICAR
DESCARTAR = TipoDecisao.DESCARTAR
PEDIR = TipoDecisao.PEDIR_HUMANO
VERSAO = versionar_prompt("analise", "Prompt sintético", "modelo-teste")
EVIDENCIA = Evidencia(criterio="r1", trecho=TRECHO_REQUISITO, fonte="rede_simulada")


def _caso(numero: int = 0, **campos) -> CasoAvaliacao:
    candidato_id = campos.pop("candidato_id", f"pessoa-{numero}")
    dados = {
        "id": f"caso-{numero}",
        "perfil": candidato_exemplo(candidato_id),
        "vaga": vaga_exemplo(),
        "gabarito": INDICAR,
        "motivo_gabarito": "requisitos_atendidos_sem_ressalva",
        "requisitos_atendidos": ["r1"],
        "particao": Particao.AJUSTE,
        "semente": 42,
        "versao_gerador": "1",
    }
    dados.update(campos)
    return CasoAvaliacao(**dados)


def _resultado(
    decisao: TipoDecisao | None = INDICAR,
    gabarito: TipoDecisao = INDICAR,
    numero: int = 0,
    **campos,
) -> ResultadoCaso:
    dados = {
        "caso_id": f"caso-{numero}",
        "particao": Particao.AJUSTE,
        "versao_hash": VERSAO.hash,
        "gabarito": gabarito,
        "decisao": decisao,
        "regra": None if decisao is None else "regra-teste",
        "falha": "resposta_invalida" if decisao is None else None,
    }
    dados.update(campos)
    return ResultadoCaso(**dados)


def _resultados(*grupos: tuple[int, TipoDecisao | None, TipoDecisao]) -> list[ResultadoCaso]:
    """Cada grupo é (quantidade, decisão do agente, gabarito)."""
    lista: list[ResultadoCaso] = []
    for quantidade, decisao, gabarito in grupos:
        for _ in range(quantidade):
            lista.append(_resultado(decisao, gabarito, numero=len(lista)))
    return lista


def _resposta(decisao: TipoDecisao = INDICAR, **campos) -> RespostaAgente:
    dados = {"decisao": decisao, "regra": "regra-teste", "nota": 0.9, "evidencias": [EVIDENCIA]}
    dados.update(campos)
    return RespostaAgente(**dados)


class AgenteEspiao:
    """Anota o que recebe e responde sempre o mesmo, ou falha se receber uma exceção."""

    def __init__(self, resposta=None) -> None:
        self.resposta = _resposta() if resposta is None else resposta
        self.chamadas: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.chamadas.append((args, kwargs))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


# M1: formato do caso


def test_caso_exige_gabarito_e_particao():
    for campo in ("gabarito", "particao"):
        dados = _caso().model_dump()
        dados.pop(campo)
        with pytest.raises(ValidationError):
            CasoAvaliacao(**dados)


def test_caso_guarda_dados_para_separar_erros_e_reproduzir():
    caso = _caso(armadilha="exagero", dificuldade="dificil", par_vies="par-1")
    assert (caso.armadilha, caso.dificuldade, caso.par_vies) == ("exagero", "dificil", "par-1")
    assert (caso.semente, caso.versao_gerador) == (42, "1")


def test_caso_e_imutavel():
    with pytest.raises(ValidationError):
        _caso().gabarito = DESCARTAR


def test_caso_recusa_perfil_que_nao_e_sintetico():
    with pytest.raises(ValidationError, match="sintético"):
        _caso(perfil=candidato_exemplo("p", simulado=False))


def test_caso_recusa_vaga_de_outra_empresa():
    with pytest.raises(ValidationError, match="empresa"):
        _caso(perfil=candidato_exemplo("p", empresa_id="empresa-b"))


def test_caso_recusa_requisito_que_a_vaga_nao_tem():
    with pytest.raises(ValidationError, match="requisito"):
        _caso(requisitos_atendidos=["r1", "inventado"])


def test_caso_recusa_indicar_sem_todos_os_requisitos():
    with pytest.raises(ValidationError, match="indicar"):
        _caso(requisitos_atendidos=[])


# M4: intervalo de Wilson, com valores calculados à mão


@pytest.mark.parametrize(
    ("erros", "total", "inferior", "superior"),
    [
        (16, 20, 0.5840, 0.9193),
        (32, 40, 0.6524, 0.8950),
        (1, 10, 0.0179, 0.4042),
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
    ],
)
def test_intervalo_bate_com_valores_calculados_a_mao(erros, total, inferior, superior):
    limites = intervalo_wilson(erros, total)
    assert isclose(limites[0], inferior, abs_tol=5e-5)
    assert isclose(limites[1], superior, abs_tol=5e-5)


def test_intervalo_com_poucos_casos_e_largo():
    pequeno = intervalo_wilson(0, 5)
    grande = intervalo_wilson(0, 500)
    assert pequeno[1] > 0.4
    assert grande[1] < 0.01


def test_intervalo_sem_casos_e_nulo_nunca_zero():
    assert intervalo_wilson(0, 0) == (None, None)


@pytest.mark.parametrize(("erros", "total"), [(-1, 5), (6, 5), (0, -1), (True, 5), (0.5, 5)])
def test_intervalo_recusa_contagem_invalida(erros, total):
    with pytest.raises(ValueError):
        intervalo_wilson(erros, total)


def test_medir_taxa_traz_valor_casos_e_intervalo():
    taxa = medir_taxa(1, 10)
    assert (taxa.valor, taxa.casos) == (0.1, 10)
    assert isclose(taxa.wilson_superior, 0.4042, abs_tol=5e-5)


def test_medir_taxa_sem_casos_e_nula():
    taxa = medir_taxa(0, 0)
    assert (taxa.valor, taxa.casos, taxa.wilson_inferior, taxa.wilson_superior) == (
        None,
        0,
        None,
        None,
    )


def test_o_metodo_da_margem_esta_documentado_no_arquivo():
    assert "Wilson" in (medicao.__doc__ or "")
    assert "1,96" in (medicao.__doc__ or "")


# M3: métricas


def test_calcula_tipos_de_erro():
    resultados = _resultados(
        (8, INDICAR, INDICAR),
        (1, INDICAR, DESCARTAR),
        (1, INDICAR, PEDIR),
        (3, DESCARTAR, DESCARTAR),
        (1, DESCARTAR, INDICAR),
        (4, PEDIR, PEDIR),
        (2, None, INDICAR),
    )
    metricas = calcular_metricas(resultados)

    assert metricas.casos == 20
    assert metricas.erros[TipoErro.INDICACAO_ERRADA].valor == 2 / 10
    assert metricas.erros[TipoErro.INDICACAO_ERRADA].casos == 10
    assert metricas.erros[TipoErro.DESCARTE_ERRADO].valor == 1 / 4
    assert metricas.erros[TipoErro.DESCARTE_ERRADO].casos == 4
    assert metricas.revisao.valor == 4 / 20
    assert metricas.cobertura.valor == 14 / 20
    assert metricas.falhas.valor == 2 / 20


def test_cobertura_revisao_e_falhas_somam_um():
    metricas = calcular_metricas(
        _resultados(
            (3, INDICAR, INDICAR), (2, DESCARTAR, DESCARTAR), (4, PEDIR, PEDIR), (1, None, PEDIR)
        )
    )
    soma = metricas.cobertura.valor + metricas.revisao.valor + metricas.falhas.valor
    assert isclose(soma, 1.0)


def test_cada_taxa_traz_intervalo():
    metricas = calcular_metricas(_resultados((9, INDICAR, INDICAR), (1, INDICAR, DESCARTAR)))
    assert isclose(metricas.erros[TipoErro.INDICACAO_ERRADA].wilson_superior, 0.4042, abs_tol=5e-5)
    assert metricas.cobertura.wilson_inferior is not None
    assert metricas.revisao.wilson_superior is not None


def test_sem_resultados_as_taxas_sao_nulas_nunca_zero():
    metricas = calcular_metricas([])
    assert metricas.casos == 0
    assert metricas.particao is None
    assert metricas.versao_hash is None
    assert set(metricas.erros) == set(TipoErro)
    for taxa in (*metricas.erros.values(), metricas.revisao, metricas.cobertura, metricas.falhas):
        assert taxa.valor is None


def test_sem_indicacao_a_taxa_de_indicacao_errada_e_nula():
    metricas = calcular_metricas(_resultados((3, PEDIR, INDICAR)))
    assert metricas.erros[TipoErro.INDICACAO_ERRADA].valor is None
    assert metricas.erros[TipoErro.VIOLACAO_ELIMINATORIA].valor is None
    assert metricas.erros[TipoErro.DESCARTE_ERRADO].valor is None


def test_so_falhas_nao_viram_acerto():
    metricas = calcular_metricas(_resultados((4, None, INDICAR)))
    assert metricas.falhas.valor == 1.0
    assert metricas.cobertura.valor == 0.0
    assert metricas.erros[TipoErro.INDICACAO_ERRADA].valor is None


def test_violacao_conta_requisito_faltante_e_autorizacao_bloqueada():
    resultados = [
        _resultado(INDICAR, numero=0),
        _resultado(INDICAR, DESCARTAR, numero=1, requisitos_cumpridos=False),
        _resultado(INDICAR, DESCARTAR, numero=2, autorizacao_bloqueada=True),
        _resultado(DESCARTAR, DESCARTAR, numero=3, requisitos_cumpridos=False),
    ]
    taxa = calcular_metricas(resultados).erros[TipoErro.VIOLACAO_ELIMINATORIA]
    assert (taxa.valor, taxa.casos) == (2 / 3, 3)


def test_opt_out_conta_entre_quem_pediu_para_sair():
    resultados = [
        _resultado(INDICAR, DESCARTAR, numero=0, opt_out=True, autorizacao_bloqueada=True),
        _resultado(DESCARTAR, DESCARTAR, numero=1, opt_out=True, autorizacao_bloqueada=True),
        _resultado(INDICAR, numero=2),
    ]
    taxa = calcular_metricas(resultados).erros[TipoErro.CONTATO_OPT_OUT]
    assert (taxa.valor, taxa.casos) == (1 / 2, 2)


def test_sem_opt_out_a_taxa_de_opt_out_e_nula():
    assert (
        calcular_metricas(_resultados((2, INDICAR, INDICAR))).erros[TipoErro.CONTATO_OPT_OUT].valor
        is None
    )


def test_afirmacao_sem_evidencia_conta_entre_indicados():
    resultados = [
        _resultado(INDICAR, numero=0),
        _resultado(INDICAR, numero=1, afirmacao_sem_evidencia=True),
        _resultado(PEDIR, numero=2, afirmacao_sem_evidencia=True),
    ]
    taxa = calcular_metricas(resultados).erros[TipoErro.AFIRMACAO_SEM_EVIDENCIA]
    assert (taxa.valor, taxa.casos) == (1 / 2, 2)


def test_mudanca_de_nome_ou_genero_conta_por_par():
    resultados = [
        _resultado(INDICAR, numero=0, par_vies="a"),
        _resultado(INDICAR, numero=1, par_vies="a"),
        _resultado(INDICAR, numero=2, par_vies="b"),
        _resultado(PEDIR, numero=3, par_vies="b"),
    ]
    taxa = calcular_metricas(resultados).erros[TipoErro.MUDANCA_NOME_GENERO]
    assert (taxa.valor, taxa.casos) == (1 / 2, 2)


def test_par_com_falha_nao_conta_como_par_medido():
    resultados = [
        _resultado(INDICAR, numero=0, par_vies="a"),
        _resultado(None, numero=1, par_vies="a"),
    ]
    assert calcular_metricas(resultados).erros[TipoErro.MUDANCA_NOME_GENERO].valor is None


def test_metricas_nao_misturam_particoes_nem_versoes():
    with pytest.raises(ValueError, match="partição"):
        calcular_metricas([_resultado(numero=0), _resultado(numero=1, particao=Particao.VALIDACAO)])
    with pytest.raises(ValueError, match="versão"):
        calcular_metricas([_resultado(numero=0), _resultado(numero=1, versao_hash="outra")])


def test_metricas_exigem_os_seis_tipos_de_erro():
    dados = calcular_metricas([]).model_dump()
    dados["erros"].pop(TipoErro.CONTATO_OPT_OUT)
    with pytest.raises(ValidationError, match="tipo"):
        MetricasMedicao(**dados)


def test_metricas_nao_guardam_caso_a_caso():
    metricas = calcular_metricas(_resultados((1, INDICAR, INDICAR)))
    assert "caso-0" not in metricas.model_dump_json()


# M2: rodada


def test_rodada_nao_entrega_gabarito_ao_agente():
    caso = _caso(motivo_gabarito="marca-do-gabarito", armadilha="marca-da-armadilha")
    agente = AgenteEspiao()

    rodar([caso], agente, VERSAO)

    assert len(agente.chamadas) == 1
    args, kwargs = agente.chamadas[0]
    assert kwargs == {}
    assert [type(arg) for arg in args] == [type(caso.perfil), type(caso.vaga)]
    assert args == (caso.perfil, caso.vaga)
    entrega = " ".join(arg.model_dump_json() for arg in args)
    assert "marca-do-gabarito" not in entrega
    assert "marca-da-armadilha" not in entrega


def test_rodada_entrega_copias_ao_agente():
    caso = _caso()

    def agente_que_altera(perfil, vaga):
        perfil.atributos["python"] = "alterado"
        vaga.requisitos.clear()
        return _resposta()

    rodar([caso], agente_que_altera, VERSAO)

    assert caso.perfil.atributos["python"] == "sim"
    assert caso.vaga.requisitos


def test_rodada_junta_gabarito_e_resposta_e_registra_a_versao():
    caso = _caso(gabarito=DESCARTAR, requisitos_atendidos=[], armadilha="sem_requisito")
    [resultado] = rodar([caso], AgenteEspiao(), VERSAO)

    assert resultado.versao_hash == VERSAO.hash
    assert (resultado.decisao, resultado.gabarito) == (INDICAR, DESCARTAR)
    assert resultado.requisitos_cumpridos is False
    assert resultado.armadilha == "sem_requisito"
    assert resultado.regra == "regra-teste"
    assert resultado.nota == 0.9
    assert resultado.rastro_id


def test_rodada_conta_excecao_como_falha_e_continua():
    casos = [_caso(0), _caso(1)]
    chamadas = iter([RuntimeError("chave-secreta"), _resposta()])

    def agente(_perfil, _vaga):
        saida = next(chamadas)
        if isinstance(saida, Exception):
            raise saida
        return saida

    resultados = rodar(casos, agente, VERSAO)

    assert [r.falha for r in resultados] == ["RuntimeError", None]
    assert resultados[0].decisao is None
    assert "chave-secreta" not in resultados[0].model_dump_json()
    assert calcular_metricas(resultados).falhas.valor == 1 / 2


def test_rodada_conta_resposta_invalida_como_falha():
    [resultado] = rodar([_caso()], lambda _p, _v: {"decisao": "indicar"}, VERSAO)
    assert resultado.falha == "resposta_invalida"
    assert resultado.decisao is None


def test_rodada_gera_rastro_de_cada_chamada_e_de_cada_falha():
    casos = [_caso(0), _caso(1)]
    rodar(casos[:1], AgenteEspiao(), VERSAO)
    rodar(casos[1:], AgenteEspiao(RuntimeError("x")), VERSAO)

    ok = auditoria.RASTRO_LOCAL.listar("empresa-a", "v1", "pessoa-0")
    falha = auditoria.RASTRO_LOCAL.listar("empresa-a", "v1", "pessoa-1")
    assert [r.sucesso for r in ok] == [True]
    assert [(r.sucesso, r.erro_tipo) for r in falha] == [(False, "RuntimeError")]


def test_rodada_marca_indicacao_sem_trecho_no_perfil():
    casos = [_caso(0), _caso(1), _caso(2)]
    respostas = iter(
        [
            _resposta(),
            _resposta(evidencias=[]),
            _resposta(evidencias=[Evidencia(criterio="r1", trecho="Inventado", fonte="x")]),
        ]
    )
    resultados = rodar(casos, lambda _p, _v: next(respostas), VERSAO)
    assert PERFIL_EXEMPLO.startswith(TRECHO_REQUISITO)
    assert [r.afirmacao_sem_evidencia for r in resultados] == [False, True, True]


def test_rodada_sem_casos_devolve_lista_vazia():
    assert rodar([], AgenteEspiao(), VERSAO) == []


def test_rodada_recusa_casos_de_prova():
    agente = AgenteEspiao()
    with pytest.raises(ValueError, match="prova"):
        rodar([_caso(particao=Particao.PROVA)], agente, VERSAO)
    assert agente.chamadas == []


# M5: limiar


def _indicados(quantidade: int, nota: float, gabarito: TipoDecisao, inicio: int, **campos):
    return [
        _resultado(INDICAR, gabarito, numero=inicio + i, nota=nota, **campos)
        for i in range(quantidade)
    ]


def test_aplicar_limiar_manda_indicacao_abaixo_para_revisao():
    resultados = [
        _resultado(INDICAR, numero=0, nota=0.8),
        _resultado(INDICAR, numero=1, nota=0.79),
        _resultado(INDICAR, numero=2, nota=None),
        _resultado(DESCARTAR, DESCARTAR, numero=3, nota=0.1),
        _resultado(None, numero=4),
    ]
    novos = aplicar_limiar(resultados, 0.8)
    assert [r.decisao for r in novos] == [INDICAR, PEDIR, PEDIR, DESCARTAR, None]
    assert novos[1].regra == "abaixo_do_limiar"
    assert resultados[1].decisao == INDICAR


def test_limiar_nulo_nao_deixa_ninguem_na_faixa_verde():
    novos = aplicar_limiar([_resultado(INDICAR, nota=1.0)], None)
    assert [r.decisao for r in novos] == [PEDIR]


def test_escolhe_limiar_com_maior_cobertura_dentro_da_meta():
    resultados = [
        *_indicados(10, 0.95, INDICAR, 0),
        *_indicados(40, 0.9, INDICAR, 10),
        *_indicados(5, 0.5, DESCARTAR, 50),
    ]
    # 0 em 10 dá teto de 27,75%; 0 em 50, de 7,13%; 5 em 55, de 19,58%.
    assert escolher_limiar(resultados, 0.10) == 0.9
    assert escolher_limiar(resultados, 0.25) == 0.5
    assert escolher_limiar(resultados, 0.20) == 0.5
    assert escolher_limiar(resultados, 0.19) == 0.9


def test_sem_limiar_viavel_devolve_nulo_nunca_o_menos_pior():
    resultados = [*_indicados(9, 0.9, INDICAR, 0), *_indicados(1, 0.9, DESCARTAR, 9)]
    assert escolher_limiar(resultados, 0.05) is None


def test_poucos_casos_sem_erro_nao_bastam_para_a_meta():
    assert escolher_limiar(_indicados(5, 0.9, INDICAR, 0), 0.10) is None


def test_sem_resultados_ou_sem_indicacao_nao_ha_limiar():
    assert escolher_limiar([], 0.10) is None
    assert escolher_limiar([_resultado(PEDIR, PEDIR, nota=0.9)], 0.10) is None
    assert escolher_limiar([_resultado(INDICAR, nota=None)], 0.99) is None


@pytest.mark.parametrize(
    "marca",
    [{"requisitos_cumpridos": False}, {"opt_out": True}, {"afirmacao_sem_evidencia": True}],
)
def test_limiar_com_violacao_nao_e_viavel_mesmo_dentro_da_meta(marca):
    resultados = [
        *_indicados(100, 0.9, INDICAR, 0),
        *_indicados(1, 0.5, DESCARTAR, 100, **marca),
    ]
    assert escolher_limiar(resultados, 0.20) == 0.9


def test_limiar_com_par_que_muda_nao_e_viavel():
    resultados = [
        *_indicados(100, 0.9, INDICAR, 0),
        _resultado(INDICAR, numero=100, nota=0.9, par_vies="a"),
        _resultado(PEDIR, numero=101, nota=0.5, par_vies="a"),
    ]
    assert escolher_limiar(resultados, 0.20) is None


@pytest.mark.parametrize("particao", [Particao.VALIDACAO, Particao.PROVA])
def test_limiar_so_se_escolhe_no_ajuste(particao):
    with pytest.raises(ValueError, match="ajuste"):
        escolher_limiar(_indicados(50, 0.9, INDICAR, 0, particao=particao), 0.10)


@pytest.mark.parametrize("meta", [0, 1, -0.1, 1.5])
def test_meta_precisa_estar_entre_zero_e_um(meta):
    with pytest.raises(ValueError, match="meta"):
        escolher_limiar([], meta)


# M6: versão do prompt


def test_prompt_tem_versao_e_hash():
    versao = versionar_prompt("analise", "Texto", "modelo-a")
    assert (versao.etapa, versao.modelo) == ("analise", "modelo-a")
    assert len(versao.hash) == 64
    assert versao == versionar_prompt("analise", "Texto", "modelo-a")


def test_outro_texto_ou_outro_modelo_geram_outro_hash():
    base = versionar_prompt("analise", "Texto", "modelo-a").hash
    assert versionar_prompt("analise", "Texto.", "modelo-a").hash != base
    assert versionar_prompt("analise", "Texto", "modelo-b").hash != base


def test_versao_do_prompt_e_imutavel():
    with pytest.raises(ValidationError):
        VERSAO.hash = "outro"


def test_prompt_vazio_nao_tem_versao():
    with pytest.raises(ValueError):
        versionar_prompt("analise", "  ", "modelo-a")


# M7: cache


def test_mesma_versao_e_caso_nao_chama_o_modelo_de_novo():
    agente = AgenteEspiao()
    cache = {}
    primeira = rodar([_caso()], agente, VERSAO, cache)
    segunda = rodar([_caso()], agente, VERSAO, cache)
    assert len(agente.chamadas) == 1
    assert primeira == segunda


def test_prompt_novo_invalida_o_cache():
    agente = AgenteEspiao()
    cache = {}
    rodar([_caso()], agente, VERSAO, cache)
    novo = versionar_prompt("analise", "Outro prompt", "modelo-teste")
    [resultado] = rodar([_caso()], agente, novo, cache)
    assert len(agente.chamadas) == 2
    assert resultado.versao_hash == novo.hash


def test_entrada_diferente_nao_usa_o_cache():
    agente = AgenteEspiao()
    cache = {}
    rodar([_caso()], agente, VERSAO, cache)
    alterado = candidato_exemplo("pessoa-0", perfil_texto=f"{PERFIL_EXEMPLO} Mais um fato.")
    rodar([_caso(perfil=alterado)], agente, VERSAO, cache)
    assert len(agente.chamadas) == 2


def test_cache_vale_pela_entrada_e_nao_guarda_o_gabarito():
    agente = AgenteEspiao()
    cache = {}
    rodar([_caso()], agente, VERSAO, cache)
    [resultado] = rodar(
        [_caso(gabarito=PEDIR, motivo_gabarito="outro", requisitos_atendidos=[])],
        agente,
        VERSAO,
        cache,
    )
    assert len(agente.chamadas) == 1
    assert resultado.gabarito == PEDIR
    assert all(isinstance(valor, RespostaAgente) for valor in cache.values())


def test_falha_nao_entra_no_cache():
    agente = AgenteEspiao(RuntimeError("fora do ar"))
    cache = {}
    rodar([_caso()], agente, VERSAO, cache)
    assert cache == {}
    agente.resposta = _resposta()
    [resultado] = rodar([_caso()], agente, VERSAO, cache)
    assert resultado.falha is None
    assert len(agente.chamadas) == 2


def test_sem_cache_cada_rodada_chama_o_agente():
    agente = AgenteEspiao()
    rodar([_caso()], agente, VERSAO)
    rodar([_caso()], agente, VERSAO)
    assert len(agente.chamadas) == 2


# M8: portão


def _base() -> MetricasMedicao:
    """Oito indicações certas, 1 de 2 erradas no descarte: tudo que precisa ser zero está medido."""
    return calcular_metricas(
        [
            _resultado(INDICAR, numero=0, par_vies="a"),
            _resultado(INDICAR, numero=1, par_vies="a"),
            *[_resultado(INDICAR, numero=i) for i in range(2, 8)],
            _resultado(DESCARTAR, DESCARTAR, numero=8, opt_out=True, autorizacao_bloqueada=True),
            _resultado(DESCARTAR, PEDIR, numero=9),
            _resultado(PEDIR, PEDIR, numero=10),
            _resultado(None, PEDIR, numero=11),
        ]
    )


def _com_erro(metricas: MetricasMedicao, tipo: TipoErro, erros: int, total: int):
    return metricas.model_copy(update={"erros": {**metricas.erros, tipo: medir_taxa(erros, total)}})


def test_portao_passa_quando_nada_piora():
    decisao = passa_no_portao(_base(), _base())
    assert decisao.passou is True
    assert decisao.motivos == []


@pytest.mark.parametrize(
    "regua",
    [
        {"revisao": medir_taxa(2, 12)},
        {"cobertura": medir_taxa(9, 12)},
        {"falhas": medir_taxa(2, 12)},
    ],
    ids=["revisao", "cobertura", "falhas"],
)
def test_portao_barra_piora_em_qualquer_regua(regua):
    depois = _base().model_copy(update=regua)
    decisao = passa_no_portao(_base(), depois)
    assert decisao.passou is False
    assert next(iter(regua)) in decisao.motivos[0]


@pytest.mark.parametrize(
    ("tipo", "erros", "total"),
    [(TipoErro.INDICACAO_ERRADA, 1, 8), (TipoErro.DESCARTE_ERRADO, 2, 2)],
)
def test_portao_barra_mais_erro(tipo, erros, total):
    decisao = passa_no_portao(_base(), _com_erro(_base(), tipo, erros, total))
    assert decisao.passou is False
    assert tipo.value in decisao.motivos[0]


@pytest.mark.parametrize(
    "tipo",
    [
        TipoErro.VIOLACAO_ELIMINATORIA,
        TipoErro.CONTATO_OPT_OUT,
        TipoErro.MUDANCA_NOME_GENERO,
        TipoErro.AFIRMACAO_SEM_EVIDENCIA,
    ],
)
def test_qualquer_violacao_que_precisa_ser_zero_barra(tipo):
    antes = _com_erro(_base(), tipo, 1, 8)
    decisao = passa_no_portao(antes, antes)
    assert decisao.passou is False
    assert tipo.value in decisao.motivos[0]


def test_regua_que_precisa_ser_zero_sem_medida_barra():
    depois = _com_erro(_base(), TipoErro.MUDANCA_NOME_GENERO, 0, 0)
    decisao = passa_no_portao(_base(), depois)
    assert decisao.passou is False
    assert "não foi medida" in decisao.motivos[0]


def test_deixar_de_medir_uma_regua_barra():
    depois = _com_erro(_base(), TipoErro.INDICACAO_ERRADA, 0, 0)
    assert passa_no_portao(_base(), depois).passou is False


def test_regua_sem_base_so_barra_com_erro():
    antes = _com_erro(_base(), TipoErro.DESCARTE_ERRADO, 0, 0)
    assert passa_no_portao(antes, _com_erro(antes, TipoErro.DESCARTE_ERRADO, 0, 3)).passou is True
    assert passa_no_portao(antes, _com_erro(antes, TipoErro.DESCARTE_ERRADO, 1, 3)).passou is False
    assert passa_no_portao(antes, antes).passou is True


def test_portao_nao_compara_conjuntos_diferentes():
    depois = _base().model_copy(update={"conjunto_hash": "outro"})
    decisao = passa_no_portao(_base(), depois)
    assert decisao.passou is False
    assert "conjunto" in decisao.motivos[0]


def test_portao_lista_todos_os_motivos():
    depois = _com_erro(_base(), TipoErro.INDICACAO_ERRADA, 1, 8).model_copy(
        update={"falhas": medir_taxa(2, 12)}
    )
    assert len(passa_no_portao(_base(), depois).motivos) == 2


def test_melhora_passa_no_portao():
    antes = _com_erro(_base(), TipoErro.INDICACAO_ERRADA, 1, 8)
    assert passa_no_portao(antes, _base()).passou is True


# M9: prova


AGORA_PROVA = datetime(2026, 11, 8, 8, 0, tzinfo=UTC)


def _prova(numero: int = 0, **campos) -> CasoAvaliacao:
    return _caso(numero, particao=Particao.PROVA, **campos)


def test_prova_so_abre_uma_vez_por_versao(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    agente = AgenteEspiao()

    resultado = rodar_prova([_prova()], agente, VERSAO, 0.5, registro, AGORA_PROVA)
    assert resultado.metricas.casos == 1
    assert resultado.versao == VERSAO
    assert resultado.limiar == 0.5
    assert resultado.aberta_em == AGORA_PROVA

    with pytest.raises(ProvaJaAberta):
        rodar_prova([_prova()], agente, VERSAO, 0.5, registro, AGORA_PROVA)
    assert len(agente.chamadas) == 1


def test_segunda_abertura_e_registrada_e_vale_depois_de_reiniciar(tmp_path):
    caminho = tmp_path / "provas.sqlite"
    rodar_prova([_prova()], AgenteEspiao(), VERSAO, 0.5, RegistroProvas(caminho), AGORA_PROVA)

    reaberto = RegistroProvas(caminho)
    assert reaberto.recusas(VERSAO.hash) == 0
    with pytest.raises(ProvaJaAberta):
        rodar_prova([_prova()], AgenteEspiao(), VERSAO, 0.5, reaberto, AGORA_PROVA)
    assert RegistroProvas(caminho).recusas(VERSAO.hash) == 1


def test_prova_nao_abre_de_novo_com_outro_conjunto(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    rodar_prova([_prova(0)], AgenteEspiao(), VERSAO, 0.5, registro, AGORA_PROVA)
    with pytest.raises(ProvaJaAberta):
        rodar_prova([_prova(1)], AgenteEspiao(), VERSAO, 0.5, registro, AGORA_PROVA)


def test_prova_conta_quantas_versoes_ja_olharam_o_conjunto(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    novo = versionar_prompt("analise", "Outro prompt", "modelo-teste")
    primeira = rodar_prova([_prova()], AgenteEspiao(), VERSAO, 0.5, registro, AGORA_PROVA)
    segunda = rodar_prova([_prova()], AgenteEspiao(), novo, 0.5, registro, AGORA_PROVA)
    assert (primeira.aberturas_do_conjunto, segunda.aberturas_do_conjunto) == (1, 2)


def test_prova_so_devolve_agregados(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    resultado = rodar_prova([_prova()], AgenteEspiao(), VERSAO, 0.5, registro, AGORA_PROVA)
    assert "caso-0" not in resultado.model_dump_json()
    assert "pessoa-0" not in resultado.model_dump_json()


def test_prova_aplica_o_limiar_congelado(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    resultado = rodar_prova([_prova()], AgenteEspiao(), VERSAO, 0.95, registro, AGORA_PROVA)
    assert resultado.metricas.revisao.valor == 1.0
    assert resultado.metricas.erros[TipoErro.INDICACAO_ERRADA].valor is None


def test_prova_sem_limiar_viavel_nao_indica_ninguem(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    resultado = rodar_prova([_prova()], AgenteEspiao(), VERSAO, None, registro, AGORA_PROVA)
    assert resultado.limiar is None
    assert resultado.metricas.revisao.valor == 1.0


def test_prova_recusa_outra_particao_sem_gastar_a_abertura(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    agente = AgenteEspiao()
    with pytest.raises(ValueError, match="prova"):
        rodar_prova([_prova(0), _caso(1)], agente, VERSAO, 0.5, registro, AGORA_PROVA)
    assert agente.chamadas == []
    assert rodar_prova([_prova(0)], agente, VERSAO, 0.5, registro, AGORA_PROVA).metricas.casos == 1


def test_prova_sem_casos_nao_gasta_a_abertura(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    with pytest.raises(ValueError, match="sem casos"):
        rodar_prova([], AgenteEspiao(), VERSAO, 0.5, registro, AGORA_PROVA)
    assert rodar_prova([_prova()], AgenteEspiao(), VERSAO, 0.5, registro, AGORA_PROVA)


def test_falha_na_prova_conta_e_gasta_a_abertura(tmp_path):
    registro = RegistroProvas(tmp_path / "provas.sqlite")
    agente = AgenteEspiao(RuntimeError("fora do ar"))
    resultado = rodar_prova([_prova()], agente, VERSAO, 0.5, registro, AGORA_PROVA)
    assert resultado.metricas.falhas.valor == 1.0
    with pytest.raises(ProvaJaAberta):
        rodar_prova([_prova()], agente, VERSAO, 0.5, registro, AGORA_PROVA)
