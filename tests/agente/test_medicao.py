"""Ciclo de taxa de erro com casos sintéticos criados aqui. Valores conferidos à mão."""

from math import isclose

import pytest
from pydantic import ValidationError

from backend.agente import auditoria, medicao
from backend.agente.medicao import (
    calcular_metricas,
    intervalo_wilson,
    medir_taxa,
    rodar,
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
