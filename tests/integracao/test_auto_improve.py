"""Integração do ciclo de auto-improve, com as peças reais e um modelo simulado.

Peças reais: dados sintéticos, analisador, revisor, faixa verde, medição, limiar, portão e prova.
Só o modelo é simulado, e ele reage ao texto do prompt, para que um prompt candidato mude o
resultado. Sem chave, sem internet e sem custo. As métricas valem para este simulado: mostram se o
ciclo funciona, não a qualidade do agente.

Os testes marcados com `xfail` descrevem o que a spec 005 (História 6) pede e ainda não existe.
São estritos: quando a lacuna for fechada, o teste passa a acusar e a marca deve sair.
"""

import importlib
import inspect
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

import pytest

from backend.agente import regras
from backend.agente.mandato import assinar
from backend.agente.medicao import (
    RegistroProvas,
    aplicar_limiar,
    calcular_metricas,
    escolher_limiar,
    ler_casos,
    passa_no_portao,
    resumir_casos,
    rodar,
    rodar_prova,
    versionar_prompt,
)
from backend.agente.regras import classificar_faixa
from backend.contratos.modelos import (
    Candidato,
    MetricasMedicao,
    Particao,
    Politica,
    RespostaAgente,
    ResultadoCaso,
    TipoDecisao,
    TipoErro,
    Vaga,
    VersaoPrompt,
)
from backend.fontes import analisador as modulo_analisador
from backend.fontes import revisor as modulo_revisor
from backend.fontes.analisador import AnalisadorPorModelo, RespostaAnalise
from backend.fontes.prompts import SISTEMA_ANALISE, SISTEMA_REVISAO
from backend.fontes.revisor import RespostaRevisao, RevisorIndependente

DADOS = Path(__file__).resolve().parents[2] / "dados" / "sinteticos"
HOJE = date(2026, 11, 7)
AGORA = datetime(2026, 11, 7, 12, tzinfo=UTC)
META = 0.15
"""Com 27 indicáveis no ajuste, 0 erros dão teto de Wilson de 12,46%: meta menor não é viável."""

AJUSTE_SINONIMOS = "Considere microsserviços e filas como evidência de sistemas distribuídos."
AJUSTE_SEM_RESSALVAS = "Não registre ressalvas: confie no que a pessoa declara."

PALAVRAS = {
    "producao": ["produção"],
    "presencial_sp": ["presencial"],
    "negocio_3_anos": ["negócio"],
    "lideranca_tecnica": ["lider", "liderei"],
    "sistemas distribuídos": ["distribuíd"],
    "cloud (AWS preferencial)": ["aws", "azure", "gcp", "nuvens"],
    "testes e code review": ["testes"],
    "transformação de processos": ["processos"],
    "comunicação com clientes": ["clientes"],
    "capacidade analítica": ["dados", "analis", "análise"],
    "arquitetura distribuída": ["distribuíd"],
    "liderança técnica": ["lider"],
}
GENERICO = "sem exemplos"


def _secao(texto: str, marca: str) -> str:
    return re.search(rf"<{marca}>\n(.*?)\n</{marca}>", texto, re.S).group(1)


class ModeloReagente:
    """Responde conforme o prompt recebido. Sem marcador, lê literalmente e faz ressalvas."""

    custo_total_usd = 0.0

    def __init__(self) -> None:
        self.pedidos: list[tuple[str, str]] = []

    def completar(self, sistema, usuario, esquema, etapa):
        self.pedidos.append((sistema, usuario))
        perfil = _secao(usuario, "perfil_candidato")
        frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", perfil) if f.strip()]
        if esquema is RespostaRevisao:
            return self._revisar(sistema, usuario, frases)
        return self._analisar(sistema, usuario, frases)

    def _analisar(self, sistema, usuario, frases) -> RespostaAnalise:
        vaga = _secao(usuario, "vaga")
        requisitos = re.findall(r"^- ([^:\n]+): ", vaga, re.M)
        competencias = [
            linha[2:] for linha in vaga.splitlines() if linha.startswith("- ") and ": " not in linha
        ]
        evidencias, notas = [], {}
        for criterio in [*requisitos, *competencias]:
            palavras = list(PALAVRAS.get(criterio, [criterio.casefold()]))
            if "distribuída" in criterio or "distribuídos" in criterio:
                palavras += ["microsserviços", "filas"] if AJUSTE_SINONIMOS in sistema else []
            frase = next((f for f in frases if any(p in f.casefold() for p in palavras)), None)
            if frase is None:
                continue
            evidencias.append({"criterio": criterio, "trecho": frase})
            if criterio in competencias:
                notas[criterio] = 0.3 if GENERICO in frase else 0.9
        return RespostaAnalise(notas=notas, evidencias=evidencias)

    def _revisar(self, sistema, usuario, frases) -> RespostaRevisao:
        if AJUSTE_SEM_RESSALVAS in sistema:
            return RespostaRevisao(ressalvas=[])
        ressalvas = [
            {
                "criterio": "cloud (AWS preferencial)",
                "problema": "Afirmação genérica, sem exemplo.",
                "trecho": frase,
            }
            for frase in frases
            if GENERICO in frase
        ]
        return RespostaRevisao(ressalvas=ressalvas)


def vaga_assinavel(vaga: Vaga) -> Vaga:
    """Tira a frase da vaga staff que a validação recusa. Ver a lacuna correspondente, abaixo."""
    if regras.validar_criterios(vaga):
        texto = re.sub(r"O anúncio de referência[^.]*\. ", "", vaga.descricao)
        vaga = vaga.model_copy(update={"descricao": texto})
    assert not regras.validar_criterios(vaga)
    return vaga


def _politica(aceitar_declarada: bool = True) -> Politica:
    return Politica(
        limiar_verde=0.0,
        piso_nota=0.0,
        max_indicacoes=1000,
        max_ampliacoes=0,
        aceitar_declarada=aceitar_declarada,
    )


def agente_real(modelo: ModeloReagente, aceitar_declarada: bool = True):
    """Analisador, revisor e faixa verde reais. Limiar zero: quem corta é `aplicar_limiar`."""
    analisador = AnalisadorPorModelo(modelo)
    revisor = RevisorIndependente(modelo)

    def agente(perfil: Candidato, vaga: Vaga) -> RespostaAgente:
        vaga = vaga_assinavel(vaga)
        analise = revisor.revisar(vaga, perfil, analisador.analisar(vaga, perfil))
        mandato = assinar(
            vaga,
            "pessoa.responsavel",
            5.0,
            _politica(aceitar_declarada),
            AGORA,
            validar_criterios=regras.validar_criterios,
        )
        faixa = classificar_faixa(vaga, perfil, analise, mandato, HOJE, AGORA)
        return RespostaAgente(
            decisao=faixa.tipo, regra=faixa.regra, nota=faixa.nota, evidencias=analise.evidencias
        )

    return agente


@contextmanager
def prompts(analise: str = SISTEMA_ANALISE, revisao: str = SISTEMA_REVISAO) -> Iterator[None]:
    """Troca os prompts por fora: hoje os módulos não aceitam prompt por parâmetro."""
    with (
        mock.patch.object(modulo_analisador, "SISTEMA_ANALISE", analise),
        mock.patch.object(modulo_revisor, "SISTEMA_REVISAO", revisao),
    ):
        yield


def versao_de(analise: str, revisao: str = SISTEMA_REVISAO) -> VersaoPrompt:
    return versionar_prompt("analise+revisao", analise + "\n---\n" + revisao, "modelo-simulado")


def rodada(casos, analise=SISTEMA_ANALISE, revisao=SISTEMA_REVISAO) -> list[ResultadoCaso]:
    with prompts(analise, revisao):
        return rodar(casos, agente_real(ModeloReagente()), versao_de(analise, revisao))


@pytest.fixture(scope="module")
def casos():
    return ler_casos(DADOS)


@pytest.fixture(scope="module")
def ajuste(casos):
    return [c for c in casos if c.particao == Particao.AJUSTE]


@pytest.fixture(scope="module")
def validacao(casos):
    return [c for c in casos if c.particao == Particao.VALIDACAO]


@pytest.fixture(scope="module")
def prova(casos):
    return [c for c in casos if c.particao == Particao.PROVA]


def _candidato_melhor() -> str:
    return SISTEMA_ANALISE + "\n" + AJUSTE_SINONIMOS


def _candidato_pior() -> str:
    return SISTEMA_REVISAO + "\n" + AJUSTE_SEM_RESSALVAS


def resumo(metricas: MetricasMedicao) -> dict[str, float | None]:
    return {
        "casos": metricas.casos,
        "cobertura": metricas.cobertura.valor,
        "revisao": metricas.revisao.valor,
        "falhas": metricas.falhas.valor,
        "indicacao_errada": metricas.erros[TipoErro.INDICACAO_ERRADA].valor,
        "teto_indicacao": metricas.erros[TipoErro.INDICACAO_ERRADA].wilson_superior,
        "descarte_errado": metricas.erros[TipoErro.DESCARTE_ERRADO].valor,
        "violacao": metricas.erros[TipoErro.VIOLACAO_ELIMINATORIA].valor,
        "opt_out": metricas.erros[TipoErro.CONTATO_OPT_OUT].valor,
        "vies": metricas.erros[TipoErro.MUDANCA_NOME_GENERO].valor,
        "sem_evidencia": metricas.erros[TipoErro.AFIRMACAO_SEM_EVIDENCIA].valor,
    }


# Etapa 1: medir, com as peças reais.


def test_modelo_nao_recebe_gabarito_nem_identidade(ajuste):
    modelo = ModeloReagente()
    with prompts():
        rodar(ajuste[:20], agente_real(modelo), versao_de(SISTEMA_ANALISE))
    enviado = "\n".join(usuario for _, usuario in modelo.pedidos)

    assert modelo.pedidos
    assert "gabarito" not in enviado.casefold()
    for caso in ajuste[:20]:
        assert caso.motivo_gabarito not in enviado
        assert caso.perfil.nome not in enviado
        assert caso.perfil.atributos.get("email", "@@") not in enviado


def test_rodada_de_ajuste_com_pecas_reais_nao_falha(ajuste):
    resultados = rodada(ajuste)

    assert Counter(r.falha for r in resultados) == {None: len(ajuste)}
    metricas = calcular_metricas(resultados)
    print("\nbase/ajuste", resumo(metricas))
    print(Counter((r.armadilha, r.gabarito.value, r.decisao.value) for r in resultados))
    assert metricas.erros[TipoErro.VIOLACAO_ELIMINATORIA].valor in (None, 0)
    assert metricas.erros[TipoErro.CONTATO_OPT_OUT].valor in (None, 0)


def test_erros_de_ajuste_agrupam_por_armadilha_sem_texto(ajuste):
    """O erro vem do candidato pior: o simulado base não erra neste conjunto."""
    resultados = rodada(ajuste, revisao=_candidato_pior())
    erros = Counter(r.armadilha for r in resultados if r.decisao != r.gabarito)

    print("\nerros por armadilha", erros)
    assert set(erros) == {"exagero"}


# Etapa 2: o limiar sai só do ajuste e é conferido na validação.


def test_limiar_sai_do_ajuste_e_e_conferido_na_validacao(ajuste, validacao):
    limiar = escolher_limiar(rodada(ajuste, _candidato_melhor()), META)
    metricas = calcular_metricas(aplicar_limiar(rodada(validacao, _candidato_melhor()), limiar))

    print("\nlimiar", limiar, "validacao", resumo(metricas))
    assert limiar is not None
    assert metricas.erros[TipoErro.INDICACAO_ERRADA].wilson_superior <= META


def test_limiar_recusa_resultados_de_outra_particao(validacao):
    with pytest.raises(ValueError, match="ajuste"):
        escolher_limiar(rodada(validacao[:5]), META)


# Etapa 3: o candidato muda o resultado, e o portão decide na validação.


def test_candidato_melhor_aumenta_a_cobertura_na_validacao(validacao):
    antes = calcular_metricas(rodada(validacao))
    depois = calcular_metricas(rodada(validacao, _candidato_melhor()))

    print("\nbase", resumo(antes), "\nmelhor", resumo(depois))
    assert depois.cobertura.valor > antes.cobertura.valor
    assert depois.falhas.valor == 0


def test_portao_barra_candidato_pior(validacao):
    antes = calcular_metricas(rodada(validacao, _candidato_melhor()))
    depois = calcular_metricas(rodada(validacao, _candidato_melhor(), _candidato_pior()))
    decisao = passa_no_portao(antes, depois)

    print("\npior", resumo(depois), decisao.motivos)
    assert not decisao.passou
    assert any("indicacao_errada" in motivo for motivo in decisao.motivos)


def test_portao_recusa_comparar_conjuntos_diferentes(ajuste, validacao):
    decisao = passa_no_portao(
        calcular_metricas(rodada(ajuste[:10])), calcular_metricas(rodada(validacao[:10]))
    )

    assert not decisao.passou
    assert any("conjunto" in motivo for motivo in decisao.motivos)


def test_portao_aceita_melhor_quando_ha_pares_de_vies(validacao):
    """Com pares de nome e gênero medidos, o ciclo fecha. Ver a lacuna dos dados, abaixo."""

    # Mesma decisão nos dois lados do par: duas cópias por caso.
    def dobrar(resultados):
        return [
            r.model_copy(update={"par_vies": f"par-{i}", "caso_id": f"{r.caso_id}-{lado}"})
            for i, r in enumerate(resultados)
            for lado in "ab"
        ]

    antes = calcular_metricas(dobrar(rodada(validacao)))
    depois = calcular_metricas(dobrar(rodada(validacao, _candidato_melhor())))
    decisao = passa_no_portao(antes, depois)

    print("\nportao com pares", decisao)
    assert decisao.passou, decisao.motivos


# Etapa 4: a prova abre uma vez e o cache respeita a versão.


def test_prova_abre_uma_vez_e_rodar_a_recusa(prova, tmp_path):
    versao = versao_de(_candidato_melhor())
    registro = RegistroProvas(tmp_path / "provas.db")

    with pytest.raises(ValueError, match="prova"):
        rodar(prova[:2], agente_real(ModeloReagente()), versao)
    with prompts(_candidato_melhor()):
        resultado = rodar_prova(prova, agente_real(ModeloReagente()), versao, 0.5, registro, AGORA)
        print("\nprova", resumo(resultado.metricas), "aberturas", resultado.aberturas_do_conjunto)
        with pytest.raises(Exception, match="(?i)prova|abert"):
            rodar_prova(prova, agente_real(ModeloReagente()), versao, 0.5, registro, AGORA)


def test_candidato_novo_reabre_a_prova_e_o_registro_conta(prova, tmp_path):
    registro = RegistroProvas(tmp_path / "provas.db")
    uma = rodar_prova(
        prova[:5], agente_real(ModeloReagente()), versao_de("a"), 0.5, registro, AGORA
    )
    outra = rodar_prova(
        prova[:5], agente_real(ModeloReagente()), versao_de("b"), 0.5, registro, AGORA
    )

    assert (uma.aberturas_do_conjunto, outra.aberturas_do_conjunto) == (1, 2)


def test_cache_nao_reaproveita_resposta_de_outro_prompt(ajuste):
    cache = {}
    modelo = ModeloReagente()
    with prompts():
        rodar(ajuste[:5], agente_real(modelo), versao_de(SISTEMA_ANALISE), cache)
    chamadas = len(modelo.pedidos)
    with prompts(_candidato_melhor()):
        rodar(ajuste[:5], agente_real(modelo), versao_de(_candidato_melhor()), cache)

    assert len(modelo.pedidos) == 2 * chamadas


# Lacunas: o que a spec 005 pede e o código ainda não tem.


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="vaga staff recusada na assinatura")
def test_vagas_dos_dados_podem_ser_assinadas(casos):
    vagas = {c.vaga.id: c.vaga for c in casos}

    assert {
        i: regras.validar_criterios(v) for i, v in vagas.items() if regras.validar_criterios(v)
    } == {}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T015: uma função por partição")
def test_cada_particao_tem_mais_de_uma_funcao(casos):
    por_particao = {p: {c.vaga.titulo for c in casos if c.particao == p} for p in Particao}

    print("\nfuncoes por particao", por_particao)
    assert all(len(titulos) > 1 for titulos in por_particao.values())


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T016: os dados não têm pares")
def test_dados_medem_troca_de_nome_e_genero(casos):
    assert any(c.par_vies for c in casos)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T016: sem pares, barra sempre")
def test_portao_aceita_candidato_melhor_com_os_dados_atuais(validacao):
    antes = calcular_metricas(rodada(validacao))
    depois = calcular_metricas(rodada(validacao, _candidato_melhor()))

    assert passa_no_portao(antes, depois).passou


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T019: ajuste pequeno para a meta")
def test_ajuste_tem_volume_para_a_meta_de_10_por_cento(ajuste):
    assert escolher_limiar(rodada(ajuste, _candidato_melhor()), 0.10) is not None


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#7: só fonte verificável indica")
def test_politica_padrao_leva_os_indicaveis_a_faixa_verde(ajuste):
    with prompts(_candidato_melhor()):
        resultados = rodar(
            ajuste,
            agente_real(ModeloReagente(), aceitar_declarada=False),
            versao_de(_candidato_melhor()),
        )

    print("\ndecisoes sem declarada", Counter(str(r.decisao) for r in resultados))
    indicaveis = [r for r in resultados if r.gabarito == TipoDecisao.INDICAR]
    assert all(r.decisao == TipoDecisao.INDICAR for r in indicaveis)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T015: textos quase iguais")
def test_casos_independentes_bastam_para_a_meta(casos):
    resumo_ajuste = resumir_casos([c for c in casos if c.particao == Particao.AJUSTE])

    print("\nresumo", resumo_ajuste)
    # 59 aprovações sem erro é o mínimo da #7 para 95% com 95% de confiança.
    assert resumo_ajuste.casos_independentes >= 59


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T066: prompt fixo no módulo")
def test_analisador_e_revisor_recebem_o_prompt_ativo():
    for classe in (AnalisadorPorModelo, RevisorIndependente):
        assert "prompt" in " ".join(inspect.signature(classe.__init__).parameters)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T010: versão sem todos os prompts")
def test_cache_expira_quando_so_o_prompt_do_revisor_muda(validacao):
    """Com a versão montada como a medição sugere, por um só prompt, o cache devolve o antigo."""
    versao = versionar_prompt("analise", SISTEMA_ANALISE, "modelo-simulado")
    cache = {}
    with prompts(_candidato_melhor()):
        antes = rodar(validacao, agente_real(ModeloReagente()), versao, cache)
    with prompts(_candidato_melhor(), _candidato_pior()):
        depois = rodar(validacao, agente_real(ModeloReagente()), versao, cache)

    assert [r.decisao for r in antes] != [r.decisao for r in depois]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="T059: decisão sem versão do prompt")
def test_decisao_guarda_a_versao_avaliada(ajuste):
    caso = ajuste[0].model_copy(update={"vaga": vaga_assinavel(ajuste[0].vaga)})
    mandato = assinar(
        caso.vaga,
        "pessoa.responsavel",
        5.0,
        _politica(),
        AGORA,
        validar_criterios=regras.validar_criterios,
    )
    analise = AnalisadorPorModelo(ModeloReagente()).analisar(caso.vaga, caso.perfil)
    decisao = regras.decidir(caso.vaga, caso.perfil, analise, mandato, HOJE, AGORA, "rastro")

    assert any("versao" in chave and "prompt" in chave for chave in decisao.entrada)


@pytest.mark.xfail(strict=True, raises=ImportError, reason="T067 a T072: módulo não existe")
def test_ciclo_propoe_aprova_e_reverte():
    """A História 6 da spec: propor, barrar ou aguardar aprovação, aplicar e reverter."""
    aprendizado = importlib.import_module("backend.agente.aprendizado")

    for funcao in ("resumir_erros", "propor_prompt", "propor_limiar", "aprovar", "reverter"):
        assert hasattr(aprendizado, funcao)


@pytest.mark.xfail(strict=True, raises=ImportError, reason="T025: agente avaliado só neste teste")
def test_existe_agente_avaliado_de_producao():
    modulo = importlib.import_module("backend.agente.agente_avaliado")

    assert callable(modulo.criar_agente)


@pytest.mark.xfail(strict=True, raises=ImportError, reason="T032: rodada sem comando")
def test_existe_comando_da_medicao():
    importlib.import_module("backend.agente.medicao_cli")
