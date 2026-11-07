import asyncio
import json
import logging
import random
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.agente import auditoria as modulo_auditoria
from backend.agente.auditoria import (
    MOTIVO_AUDITORIA_REPROVADA,
    NAO_MEDIDO,
    RASTRO_LOCAL,
    Auditoria,
    AuditoriaInvalida,
    DecisaoIncompleta,
    DecisoesAutomaticasPausadas,
    ExplicacaoInexistente,
    RastroLangfuse,
    RastroLocal,
    RegistroRastro,
    configurar_destino_externo,
    contexto_rastro,
    destino_do_ambiente,
    metricas_autonomia,
    rastreado,
    responsavel_do_mandato,
    selecionar_amostra,
)
from backend.agente.fluxo import EstadoFluxo
from backend.agente.mandato import Mandato, Politica
from backend.agente.persistencia import Repositorio
from backend.contratos.erros import ModeloIndisponivel
from backend.contratos.modelos import Decisao, EventoFluxo, Evidencia, TipoDecisao

FUSO_BRASILIA = timezone(timedelta(hours=-3))
MOMENTO = datetime(2026, 11, 7, 12, 0, tzinfo=FUSO_BRASILIA)


def _mandato(**campos) -> Mandato:
    dados = {
        "id": "mandato-1",
        "versao": 2,
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "hash_vaga": "hash",
        "assinante": "Ana Souza",
        "limite_gasto_usd": 5.0,
        "politica": Politica(limiar_verde=0.7, piso_nota=0.3, max_indicacoes=5, max_ampliacoes=1),
        "assinado_em": MOMENTO,
    }
    dados.update(campos)
    return Mandato(**dados)


def _decisao(**campos) -> Decisao:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "candidato_id": "cand-1",
        "tipo": TipoDecisao.INDICAR,
        "regra": "faixa_verde_v1",
        "motivo": "requisitos comprovados",
        "responsavel": responsavel_do_mandato(_mandato()),
        "rastro_id": "exec-1:vaga-1:cand-1",
        "entrada": {"nota": "0.9"},
        "evidencias": [Evidencia(criterio="r1", trecho="Python há 5 anos", fonte="github")],
        "momento": MOMENTO,
    }
    dados.update(campos)
    return Decisao(**dados)


@pytest.fixture
def repo(tmp_path: Path) -> Repositorio:
    repositorio = Repositorio(tmp_path / "agente.db")
    repositorio.salvar_mandato("empresa-a", "vaga-1", _mandato().model_dump_json())
    return repositorio


@pytest.fixture
def rastro() -> RastroLocal:
    return RastroLocal()


@pytest.fixture
def auditoria(repo: Repositorio, rastro: RastroLocal) -> Auditoria:
    return Auditoria(repo, rastro)


def test_toda_decisao_tem_entrada_regra_evidencias_e_responsavel(auditoria, repo):
    decisao = _decisao()

    auditoria.registrar_decisao(decisao)

    assert repo.listar_decisoes("empresa-a", "vaga-1") == [decisao]


@pytest.mark.parametrize(
    "campos, faltando",
    [
        ({"entrada": {}}, "entrada"),
        ({"entrada": {"nota": " "}}, "entrada"),
        ({"evidencias": []}, "evidencias"),
        ({"evidencias": [Evidencia(criterio="r1", trecho=" ", fonte="github")]}, "evidencias"),
        ({"evidencias": [Evidencia(criterio="r1", trecho="x", fonte="")]}, "evidencias"),
        ({"evidencias": [Evidencia(criterio="", trecho="x", fonte="f")]}, "evidencias"),
        ({"motivo": " "}, "motivo"),
        ({"rastro_id": ""}, "rastro_id"),
        ({"vaga_id": ""}, "vaga_id"),
        ({"candidato_id": " "}, "candidato_id"),
    ],
)
def test_decisao_incompleta_e_recusada_e_nada_e_salvo(auditoria, repo, campos, faltando):
    with pytest.raises(DecisaoIncompleta, match=faltando):
        auditoria.registrar_decisao(_decisao(**campos))

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


@pytest.mark.parametrize("campo", ["regra", "responsavel", "empresa_id"])
def test_campo_vazio_que_escapou_do_contrato_e_recusado(auditoria, repo, campo):
    with pytest.raises(DecisaoIncompleta, match=campo):
        auditoria.registrar_decisao(_decisao().model_copy(update={campo: " "}))

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


def test_momento_sem_fuso_e_recusado(auditoria, repo):
    sem_fuso = _decisao().model_copy(update={"momento": datetime(2026, 11, 7, 12, 0)})

    with pytest.raises(DecisaoIncompleta, match="momento"):
        auditoria.registrar_decisao(sem_fuso)

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_erro_de_contrato_nao_copia_os_dados_da_decisao(auditoria):
    decisao = _decisao().model_copy(update={"momento": "dado-do-perfil-sintetico"})

    with pytest.raises(DecisaoIncompleta) as erro:
        auditoria.registrar_decisao(decisao)

    assert "dado-do-perfil-sintetico" not in str(erro.value)


def test_responsavel_identifica_assinante_e_versao_do_mandato():
    responsavel = responsavel_do_mandato(_mandato())

    assert "Ana Souza" in responsavel
    assert "v2" in responsavel
    assert "mandato-1" in responsavel


@pytest.mark.parametrize(
    "responsavel",
    [
        "regras",
        "agente",
        "agente:mandato:mandato-1:v2",
        "agente:mandato:mandato-1:assinante:Ana Souza",
        "humano:",
        "rh",
    ],
)
def test_responsavel_sem_identificacao_e_recusado(auditoria, repo, responsavel):
    with pytest.raises(DecisaoIncompleta, match="responsavel"):
        auditoria.registrar_decisao(_decisao(responsavel=responsavel))

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


@pytest.mark.parametrize(
    "mandato_citado",
    [
        _mandato(id="mandato-falso"),
        _mandato(versao=1),
        _mandato(assinante="Outra Pessoa"),
    ],
)
def test_decisao_do_agente_precisa_citar_o_mandato_assinado(auditoria, repo, mandato_citado):
    decisao = _decisao(responsavel=responsavel_do_mandato(mandato_citado))

    with pytest.raises(DecisaoIncompleta, match="mandato"):
        auditoria.registrar_decisao(decisao)

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []


def test_mandato_de_outra_empresa_nao_vale(auditoria, repo):
    decisao = _decisao(empresa_id="empresa-b")

    with pytest.raises(DecisaoIncompleta, match="mandato"):
        auditoria.registrar_decisao(decisao)

    assert repo.listar_decisoes("empresa-b", "vaga-1") == []


def test_decisao_humana_identifica_a_pessoa_e_nao_exige_mandato(tmp_path):
    repositorio = Repositorio(tmp_path / "sem_mandato.db")
    decisao = _decisao(tipo=TipoDecisao.DESCARTAR, responsavel="humano:Carla Lima")

    Auditoria(repositorio).registrar_decisao(decisao)

    assert repositorio.listar_decisoes("empresa-a", "vaga-1") == [decisao]


def _registro(**campos) -> RegistroRastro:
    dados = {
        "rastro_id": "exec-1:vaga-1:cand-1",
        "execucao_id": "exec-1",
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "candidato_id": "cand-1",
        "etapa": "analise",
        "funcao": "analisar",
        "sucesso": True,
        "duracao_ms": 12.5,
        "momento": MOMENTO,
    }
    dados.update(campos)
    return RegistroRastro(**dados)


def _evento(mensagem: str, **campos) -> EventoFluxo:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "etapa": "decidindo",
        "mensagem": mensagem,
        "candidato_id": "cand-1",
        "momento": MOMENTO,
    }
    dados.update(campos)
    return EventoFluxo(**dados)


def test_explicacao_liga_decisao_eventos_e_rastro(auditoria, repo, rastro):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    repo.registrar_evento(_evento("analisado"))
    repo.registrar_evento(_evento("vaga em busca", candidato_id=None))
    repo.registrar_evento(_evento("de outra pessoa", candidato_id="cand-2"))
    registro = _registro()
    rastro.registrar(registro)
    rastro.registrar(_registro(rastro_id="exec-1:vaga-1:cand-2", candidato_id="cand-2"))

    explicacao = auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")

    assert explicacao["decisoes"] == [decisao.model_dump(mode="json")]
    assert explicacao["mandato"] == _mandato().model_dump(mode="json")
    assert explicacao["mandatos_citados"] == [
        {"id": "mandato-1", "versao": 2, "assinante": "Ana Souza"}
    ]
    assert [e["mensagem"] for e in explicacao["eventos"]] == ["analisado", "vaga em busca"]
    assert explicacao["rastro_ids"] == [decisao.rastro_id]
    assert explicacao["rastro"] == [registro.model_dump(mode="json")]


def test_explicacao_ignora_decisoes_de_outro_candidato(auditoria):
    auditoria.registrar_decisao(_decisao())
    auditoria.registrar_decisao(_decisao(candidato_id="cand-2", rastro_id="outro"))

    explicacao = auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")

    assert [d["candidato_id"] for d in explicacao["decisoes"]] == ["cand-1"]
    assert explicacao["rastro_ids"] == ["exec-1:vaga-1:cand-1"]


def test_explicacao_mantem_o_id_do_rastro_mesmo_sem_registro_local(auditoria):
    auditoria.registrar_decisao(_decisao())

    explicacao = auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")

    assert explicacao["rastro_ids"] == ["exec-1:vaga-1:cand-1"]
    assert explicacao["rastro"] == []


def test_explicacao_acha_rastro_citado_pela_decisao_sem_candidato_no_contexto(auditoria, rastro):
    auditoria.registrar_decisao(_decisao())
    registro = _registro(candidato_id=None)
    rastro.registrar(registro)

    explicacao = auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")

    assert explicacao["rastro"] == [registro.model_dump(mode="json")]


def test_explicacao_de_outra_empresa_nao_existe(auditoria, repo, rastro):
    auditoria.registrar_decisao(_decisao())
    repo.registrar_evento(_evento("analisado"))
    rastro.registrar(_registro())

    with pytest.raises(ExplicacaoInexistente) as de_outra_empresa:
        auditoria.explicar_candidato("empresa-b", "cand-1", "vaga-1")
    with pytest.raises(ExplicacaoInexistente) as inexistente:
        auditoria.explicar_candidato("empresa-a", "cand-9", "vaga-1")

    assert str(de_outra_empresa.value) == str(inexistente.value)


def test_rastro_de_outra_empresa_com_o_mesmo_id_nao_aparece(auditoria, rastro):
    auditoria.registrar_decisao(_decisao())
    rastro.registrar(_registro(empresa_id="empresa-b"))

    explicacao = auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")

    assert explicacao["rastro"] == []


def test_so_o_mandato_da_vaga_nao_faz_um_candidato_existir(auditoria):
    with pytest.raises(ExplicacaoInexistente):
        auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")


def test_candidato_ainda_sem_decisao_e_explicado_pelos_eventos(auditoria, repo):
    repo.registrar_evento(_evento("analisado"))

    explicacao = auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")

    assert explicacao["decisoes"] == []
    assert [e["mensagem"] for e in explicacao["eventos"]] == ["analisado"]


@pytest.mark.parametrize("empresa_id", ["", "  "])
def test_explicacao_exige_empresa(auditoria, empresa_id):
    with pytest.raises(ValueError, match="empresa_id"):
        auditoria.explicar_candidato(empresa_id, "cand-1", "vaga-1")


CHAVE = "sk-teste-sintetica-0123456789"


class DestinoEmMemoria:
    def __init__(self) -> None:
        self.registros: list[RegistroRastro] = []

    def registrar(self, registro: RegistroRastro) -> None:
        self.registros.append(registro)


class DestinoQuebrado:
    def registrar(self, registro: RegistroRastro) -> None:
        raise ConnectionError(f"falhou com {CHAVE}")


def _listar_local(candidato_id: str = "cand-1") -> list[RegistroRastro]:
    return RASTRO_LOCAL.listar("empresa-a", "vaga-1", candidato_id)


@rastreado("modelo")
def _completar(sistema: str, api_key: str = "") -> str:
    return f"resposta com {api_key}"


def test_rastro_traz_execucao_vaga_e_candidato_do_contexto():
    with contexto_rastro(empresa_id="empresa-a", execucao_id="exec-1", vaga_id="vaga-1"):
        with contexto_rastro(candidato_id="cand-1") as contexto:
            assert _completar("sistema") == "resposta com "

    registro = _listar_local()[0]
    assert registro.execucao_id == "exec-1"
    assert registro.empresa_id == "empresa-a"
    assert registro.vaga_id == "vaga-1"
    assert registro.candidato_id == "cand-1"
    assert registro.rastro_id == contexto.rastro_id
    assert registro.etapa == "modelo"
    assert registro.funcao.endswith("_completar")
    assert registro.sucesso is True
    assert registro.erro_tipo is None
    assert registro.duracao_ms >= 0
    assert registro.momento.tzinfo is not None


def test_contexto_e_desfeito_ao_sair():
    with contexto_rastro(empresa_id="empresa-a", vaga_id="vaga-1"):
        with contexto_rastro(candidato_id="cand-1"):
            pass
        with contexto_rastro(candidato_id="cand-2"):
            _completar("sistema")

    assert _listar_local("cand-1") == []
    assert len(_listar_local("cand-2")) == 1
    assert modulo_auditoria.contexto_atual() is None


def test_contexto_gera_execucao_e_a_mantem_nos_aninhados():
    with contexto_rastro(empresa_id="empresa-a") as externo:
        with contexto_rastro(vaga_id="vaga-1") as interno:
            assert interno.execucao_id == externo.execucao_id
            assert interno.execucao_id


def test_contexto_nao_troca_de_empresa():
    with contexto_rastro(empresa_id="empresa-a"):
        with pytest.raises(ValueError, match="empresa"):
            with contexto_rastro(empresa_id="empresa-b"):
                pass


@pytest.mark.parametrize("empresa_id", [None, "", " "])
def test_contexto_externo_exige_empresa(empresa_id):
    with pytest.raises(ValueError, match="empresa"):
        with contexto_rastro(empresa_id=empresa_id):
            pass


def test_rastro_nao_contem_chave(monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", CHAVE)
    externo = DestinoEmMemoria()
    configurar_destino_externo(externo)

    @rastreado("modelo")
    def chamar(sistema: str, api_key: str, cabecalhos: dict) -> str:
        if sistema == "falhar":
            raise ModeloIndisponivel(f"recusado: {api_key}")
        return api_key

    with contexto_rastro(empresa_id="empresa-a", vaga_id="vaga-1", candidato_id="cand-1"):
        chamar("sistema", CHAVE, {"Authorization": f"Bearer {CHAVE}"})
        with pytest.raises(ModeloIndisponivel):
            chamar("falhar", api_key=CHAVE, cabecalhos={})

    registros = _listar_local()
    assert len(registros) == 2
    assert registros == externo.registros
    assert CHAVE not in json.dumps([r.model_dump(mode="json") for r in registros])


def test_falha_e_registrada_e_relancada():
    erro = ModeloIndisponivel("fora do ar")

    @rastreado("modelo")
    def chamar() -> None:
        raise erro

    with contexto_rastro(empresa_id="empresa-a", vaga_id="vaga-1", candidato_id="cand-1"):
        with pytest.raises(ModeloIndisponivel) as capturado:
            chamar()

    assert capturado.value is erro
    registro = _listar_local()[0]
    assert registro.sucesso is False
    assert registro.erro_tipo == "ModeloIndisponivel"


def test_etapa_vazia_e_recusada_ao_decorar():
    with pytest.raises(ValueError, match="etapa"):
        rastreado(" ")


def test_sem_contexto_o_rastro_nao_quebra_a_funcao():
    assert _completar("sistema", api_key="x") == "resposta com x"


def test_funcao_assincrona_e_medida_ate_terminar():
    @rastreado("ferramenta")
    async def buscar() -> str:
        await asyncio.sleep(0)
        return "ok"

    @rastreado("ferramenta")
    async def falhar() -> None:
        await asyncio.sleep(0)
        raise ModeloIndisponivel("fora do ar")

    async def executar() -> str:
        with contexto_rastro(empresa_id="empresa-a", vaga_id="vaga-1", candidato_id="cand-1"):
            with pytest.raises(ModeloIndisponivel):
                await falhar()
            return await buscar()

    assert asyncio.run(executar()) == "ok"
    assert [r.sucesso for r in _listar_local()] == [False, True]


def test_destino_externo_quebrado_nao_quebra_o_fluxo_nem_loga_a_chave(caplog):
    configurar_destino_externo(DestinoQuebrado())

    with caplog.at_level(logging.WARNING, logger="backend.agente.auditoria"):
        with contexto_rastro(empresa_id="empresa-a", vaga_id="vaga-1", candidato_id="cand-1"):
            assert _completar("sistema") == "resposta com "

    assert len(_listar_local()) == 1
    assert "ConnectionError" in caplog.text
    assert CHAVE not in caplog.text


def test_erro_real_nao_e_trocado_por_falha_do_destino():
    configurar_destino_externo(DestinoQuebrado())

    @rastreado("modelo")
    def chamar() -> None:
        raise ModeloIndisponivel("fora do ar")

    with pytest.raises(ModeloIndisponivel):
        chamar()


def test_explicacao_acha_o_rastro_de_uma_funcao_decorada(auditoria):
    with contexto_rastro(
        empresa_id="empresa-a", execucao_id="exec-1", vaga_id="vaga-1", candidato_id="cand-1"
    ) as contexto:
        _completar("sistema")
        auditoria.registrar_decisao(_decisao(rastro_id=contexto.rastro_id))

    explicacao = Auditoria(auditoria._repositorio).explicar_candidato(
        "empresa-a", "cand-1", "vaga-1"
    )

    assert explicacao["rastro_ids"] == [contexto.rastro_id]
    assert [r["etapa"] for r in explicacao["rastro"]] == ["modelo"]


class ClienteLangfuseFalso:
    def __init__(self, **argumentos) -> None:
        self.argumentos = argumentos
        self.eventos: list[dict] = []

    @staticmethod
    def create_trace_id(*, seed: str) -> str:
        return f"trace-{seed}"

    def create_event(self, **campos) -> None:
        self.eventos.append(campos)


def test_rastro_langfuse_envia_metadados_no_trace_do_rastro():
    cliente = ClienteLangfuseFalso()

    RastroLangfuse(cliente).registrar(_registro(sucesso=False, erro_tipo="ModeloIndisponivel"))

    evento = cliente.eventos[0]
    assert evento["name"] == "analise"
    assert evento["trace_context"] == {"trace_id": "trace-exec-1:vaga-1:cand-1"}
    assert evento["level"] == "ERROR"
    assert evento["metadata"]["empresa_id"] == "empresa-a"
    assert evento["metadata"]["candidato_id"] == "cand-1"
    assert not {"input", "output"} & set(evento)


def test_rastro_langfuse_aceita_o_sdk_real_sem_rede():
    from langfuse import Langfuse

    cliente = Langfuse(public_key="pk-teste", secret_key="sk-teste", tracing_enabled=False)

    RastroLangfuse(cliente).registrar(_registro())


def _simular_sdk(monkeypatch, classe) -> None:
    monkeypatch.setitem(sys.modules, "langfuse", types.SimpleNamespace(Langfuse=classe))


@pytest.mark.parametrize(
    "ambiente",
    [{}, {"LANGFUSE_PUBLIC_KEY": "pk"}, {"LANGFUSE_SECRET_KEY": "sk"}],
)
def test_sem_chaves_do_langfuse_nao_ha_destino_externo(monkeypatch, ambiente):
    def nao_deveria_criar(**_argumentos):
        raise AssertionError("não deveria criar o cliente")

    _simular_sdk(monkeypatch, nao_deveria_criar)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    for nome, valor in ambiente.items():
        monkeypatch.setenv(nome, valor)

    assert destino_do_ambiente() is None


def test_com_chaves_do_langfuse_usa_o_destino_externo(monkeypatch):
    _simular_sdk(monkeypatch, ClienteLangfuseFalso)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    assert isinstance(destino_do_ambiente(), RastroLangfuse)


def test_falha_ao_criar_o_langfuse_vira_rastro_local(monkeypatch, caplog):
    def falhar(**_argumentos):
        raise RuntimeError(f"erro com {CHAVE}")

    _simular_sdk(monkeypatch, falhar)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(modulo_auditoria, "_externo_resolvido", False)

    with caplog.at_level(logging.WARNING, logger="backend.agente.auditoria"):
        with contexto_rastro(empresa_id="empresa-a", vaga_id="vaga-1", candidato_id="cand-1"):
            assert _completar("sistema") == "resposta com "

    assert len(_listar_local()) == 1
    assert "RuntimeError" in caplog.text
    assert CHAVE not in caplog.text


def _automaticas(indicar: int, descartar: int = 0, vaga_id: str = "vaga-1") -> list[Decisao]:
    tipos = [TipoDecisao.INDICAR] * indicar + [TipoDecisao.DESCARTAR] * descartar
    return [
        _decisao(tipo=tipo, candidato_id=f"cand-{i}", vaga_id=vaga_id, rastro_id=f"r-{i}")
        for i, tipo in enumerate(tipos)
    ]


def test_amostra_auditada_e_reproduzivel():
    decisoes = _automaticas(150, 50)
    embaralhadas = random.Random(7).sample(decisoes, len(decisoes))

    amostra = selecionar_amostra(decisoes, 0.1, semente="mandato-1")

    assert amostra == selecionar_amostra(embaralhadas, 0.1, semente="mandato-1")
    assert len(amostra) == 20
    assert amostra != selecionar_amostra(decisoes, 0.1, semente="mandato-2")


def test_amostra_tem_pelo_menos_uma_decisao():
    assert len(selecionar_amostra(_automaticas(1), 0.01, semente="s")) == 1


def test_amostra_inclui_descartes_mesmo_raros():
    amostra = selecionar_amostra(_automaticas(99, 1), 0.01, semente="s")

    assert sorted(decisao.tipo for decisao in amostra) == [
        TipoDecisao.DESCARTAR,
        TipoDecisao.INDICAR,
    ]


def test_amostra_e_proporcional_em_cada_grupo():
    amostra = selecionar_amostra(_automaticas(100, 200), 0.07, semente="s")

    assert sum(d.tipo == TipoDecisao.INDICAR for d in amostra) == 7
    assert sum(d.tipo == TipoDecisao.DESCARTAR for d in amostra) == 14


def test_amostra_cobre_cada_vaga():
    decisoes = _automaticas(50, vaga_id="vaga-1") + _automaticas(1, vaga_id="vaga-2")

    amostra = selecionar_amostra(decisoes, 0.01, semente="s")

    assert sorted(decisao.vaga_id for decisao in amostra) == ["vaga-1", "vaga-2"]


def test_amostra_so_considera_decisoes_automaticas():
    fora = [
        _decisao(tipo=TipoDecisao.PEDIR_HUMANO),
        _decisao(tipo=TipoDecisao.DESCARTAR, responsavel="humano:Carla Lima"),
    ]

    assert selecionar_amostra(fora, 1, semente="s") == []
    assert selecionar_amostra([], 0.5, semente="s") == []


@pytest.mark.parametrize("percentual", [0, -0.1, 1.5, float("nan")])
def test_percentual_invalido_nao_desliga_a_auditoria(percentual):
    with pytest.raises(ValueError, match="percentual"):
        selecionar_amostra(_automaticas(3), percentual, semente="s")


def test_amostra_nao_mistura_empresas():
    decisoes = [_decisao(), _decisao(empresa_id="empresa-b")]

    with pytest.raises(ValueError, match="empresa"):
        selecionar_amostra(decisoes, 0.5, semente="s")


def _auditar(auditoria: Auditoria, decisao: Decisao, correta: bool = False, **campos):
    dados = {"correta": correta, "auditor": "humano:Carla Lima", "momento": MOMENTO}
    dados.update(campos)
    return auditoria.registrar_auditoria(decisao, **dados)


def test_erro_na_amostra_pausa_decisoes_automaticas(auditoria, repo):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    repo.salvar_estado("empresa-a", "vaga-1", EstadoFluxo.DECIDINDO, 7)

    _auditar(auditoria, decisao, comentario="trecho não sustenta o requisito")

    estado = repo.carregar_estado("empresa-a", "vaga-1")
    assert estado.estado == EstadoFluxo.PAUSADA
    assert estado.cursor == 7
    assert estado.estado_anterior == EstadoFluxo.DECIDINDO
    assert estado.motivo == MOTIVO_AUDITORIA_REPROVADA
    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is True
    with pytest.raises(DecisoesAutomaticasPausadas):
        auditoria.registrar_decisao(_decisao(candidato_id="cand-2"))
    with pytest.raises(DecisoesAutomaticasPausadas):
        auditoria.registrar_decisao(_decisao(candidato_id="cand-3", tipo=TipoDecisao.DESCARTAR))
    assert [d.candidato_id for d in repo.listar_decisoes("empresa-a", "vaga-1")] == ["cand-1"]
    assert any(
        evento.etapa == EstadoFluxo.PAUSADA for evento in repo.listar_eventos("empresa-a", "vaga-1")
    )


def test_pausa_nao_impede_mandar_para_humano(auditoria, repo):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    _auditar(auditoria, decisao)

    auditoria.registrar_decisao(_decisao(candidato_id="cand-2", tipo=TipoDecisao.PEDIR_HUMANO))
    auditoria.registrar_decisao(
        _decisao(candidato_id="cand-3", tipo=TipoDecisao.DESCARTAR, responsavel="humano:Carla Lima")
    )

    assert len(repo.listar_decisoes("empresa-a", "vaga-1")) == 3


def test_auditoria_correta_nao_pausa(auditoria, repo):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    repo.salvar_estado("empresa-a", "vaga-1", EstadoFluxo.DECIDINDO, 7)

    resultado = _auditar(auditoria, decisao, correta=True)

    assert auditoria.listar_auditorias("empresa-a", "vaga-1") == [resultado]
    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is False
    assert repo.carregar_estado("empresa-a", "vaga-1").estado == EstadoFluxo.DECIDINDO


def test_pausa_anterior_mantem_estado_e_motivo_e_a_barreira_vale(auditoria, repo):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    repo.salvar_estado(
        "empresa-a",
        "vaga-1",
        EstadoFluxo.PAUSADA,
        3,
        motivo="limite_gasto",
        estado_anterior=EstadoFluxo.ANALISANDO,
    )

    _auditar(auditoria, decisao)

    estado = repo.carregar_estado("empresa-a", "vaga-1")
    assert estado.motivo == "limite_gasto"
    assert estado.estado_anterior == EstadoFluxo.ANALISANDO
    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is True


@pytest.mark.parametrize("com_estado", [True, False])
def test_vaga_concluida_ou_sem_execucao_nao_muda_de_estado_mas_a_barreira_vale(
    auditoria, repo, com_estado
):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    if com_estado:
        repo.salvar_estado("empresa-a", "vaga-1", EstadoFluxo.CONCLUIDA, 9)

    _auditar(auditoria, decisao)

    estado = repo.carregar_estado("empresa-a", "vaga-1")
    assert (estado.estado if estado else None) == (EstadoFluxo.CONCLUIDA if com_estado else None)
    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is True


def test_so_uma_pessoa_libera_e_novo_erro_pausa_de_novo(auditoria, repo):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    _auditar(auditoria, decisao)

    with pytest.raises(AuditoriaInvalida, match="responsavel"):
        auditoria.liberar_decisoes_automaticas(
            "empresa-a", "vaga-1", "agente:mandato:m:v1:assinante:A", "revisto", MOMENTO
        )
    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is True

    auditoria.liberar_decisoes_automaticas(
        "empresa-a", "vaga-1", "humano:Ana Souza", "faixa verde revista", MOMENTO
    )
    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is False
    outra = _decisao(candidato_id="cand-2")
    auditoria.registrar_decisao(outra)

    _auditar(auditoria, outra)
    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is True


def test_pausa_vale_so_para_a_vaga_e_a_empresa_auditadas(auditoria, repo):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    repo.salvar_mandato("empresa-a", "vaga-2", _mandato(vaga_id="vaga-2").model_dump_json())
    repo.salvar_mandato("empresa-b", "vaga-1", _mandato(empresa_id="empresa-b").model_dump_json())

    _auditar(auditoria, decisao)

    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-2") is False
    assert auditoria.decisoes_automaticas_pausadas("empresa-b", "vaga-1") is False
    auditoria.registrar_decisao(_decisao(vaga_id="vaga-2"))
    auditoria.registrar_decisao(_decisao(empresa_id="empresa-b"))


def test_auditoria_exige_decisao_automatica_registrada(auditoria):
    automatica = _decisao()
    para_humano = _decisao(candidato_id="cand-2", tipo=TipoDecisao.PEDIR_HUMANO)
    humana = _decisao(candidato_id="cand-3", responsavel="humano:Carla Lima")
    auditoria.registrar_decisao(para_humano)
    auditoria.registrar_decisao(humana)

    for decisao in (automatica, para_humano, humana):
        with pytest.raises(AuditoriaInvalida, match="decisão"):
            _auditar(auditoria, decisao)

    assert auditoria.listar_auditorias("empresa-a", "vaga-1") == []


@pytest.mark.parametrize("auditor", ["", "agente:mandato:m:v1:assinante:A", "humano: ", "Carla"])
def test_auditoria_exige_pessoa_identificada(auditoria, auditor):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)

    with pytest.raises(AuditoriaInvalida, match="auditor"):
        _auditar(auditoria, decisao, auditor=auditor)

    assert auditoria.decisoes_automaticas_pausadas("empresa-a", "vaga-1") is False


def test_auditoria_recusa_momento_sem_fuso(auditoria):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)

    with pytest.raises(AuditoriaInvalida, match="momento"):
        _auditar(auditoria, decisao, momento=datetime(2026, 11, 7, 12, 0))


def test_explicacao_mostra_a_auditoria_do_candidato(auditoria):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    _auditar(auditoria, decisao, correta=True)

    explicacao = auditoria.explicar_candidato("empresa-a", "cand-1", "vaga-1")

    assert [e["etapa"] for e in explicacao["eventos"]] == ["auditoria_amostra"]


def _registrar_lote(auditoria: Auditoria, *decisoes: Decisao) -> None:
    for decisao in decisoes:
        auditoria.registrar_decisao(decisao)


def test_metricas_de_autonomia(auditoria):
    indicada_certa = _decisao(candidato_id="c1")
    indicada_errada = _decisao(candidato_id="c2")
    descartada_certa = _decisao(candidato_id="c3", tipo=TipoDecisao.DESCARTAR)
    para_humano = _decisao(candidato_id="c4", tipo=TipoDecisao.PEDIR_HUMANO)
    _registrar_lote(auditoria, indicada_certa, indicada_errada, descartada_certa, para_humano)
    _auditar(auditoria, indicada_certa, correta=True)
    _auditar(auditoria, descartada_certa, correta=True)
    _auditar(auditoria, indicada_errada, correta=False)

    metricas = metricas_autonomia(
        [indicada_certa, indicada_errada, descartada_certa, para_humano],
        auditoria.listar_auditorias("empresa-a", "vaga-1"),
    )

    assert metricas.candidatos == 4
    assert metricas.sem_revisao == 3
    assert metricas.porcentagem_sem_revisao == 75.0
    assert metricas.tamanho_amostra == 3
    assert metricas.erros == 1
    assert metricas.erro == pytest.approx(33.33, abs=0.01)
    assert metricas.amostra_indicacoes == 2
    assert metricas.erro_indicacoes == 50.0
    assert metricas.amostra_descartes == 1
    assert metricas.erro_descartes == 0.0


def test_sem_dado_auditado_o_erro_e_nao_medido_nunca_zero():
    metricas = metricas_autonomia(_automaticas(3, 2), [])

    assert metricas.porcentagem_sem_revisao == 100.0
    assert metricas.tamanho_amostra == 0
    assert metricas.erros == 0
    assert metricas.erro == NAO_MEDIDO == "não medido"
    assert metricas.erro_indicacoes == NAO_MEDIDO
    assert metricas.erro_descartes == NAO_MEDIDO


def test_erro_zero_medido_e_numero_e_nao_texto(auditoria):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    resultado = _auditar(auditoria, decisao, correta=True)

    metricas = metricas_autonomia([decisao], [resultado])

    assert metricas.erro == 0.0
    assert metricas.erro != NAO_MEDIDO


def test_grupo_sem_auditoria_nao_herda_o_erro_do_outro(auditoria):
    indicada = _decisao(candidato_id="c1")
    descartada = _decisao(candidato_id="c2", tipo=TipoDecisao.DESCARTAR)
    _registrar_lote(auditoria, indicada, descartada)
    resultado = _auditar(auditoria, indicada, correta=True)

    metricas = metricas_autonomia([indicada, descartada], [resultado])

    assert metricas.erro_indicacoes == 0.0
    assert metricas.erro_descartes == NAO_MEDIDO
    assert metricas.amostra_descartes == 0


def test_sem_decisoes_nada_e_medido():
    metricas = metricas_autonomia([], [])

    assert metricas.candidatos == 0
    assert metricas.porcentagem_sem_revisao == NAO_MEDIDO
    assert metricas.erro == NAO_MEDIDO


def test_candidato_conta_uma_vez_pela_primeira_decisao():
    automatica = _decisao(candidato_id="c1")
    revertida = _decisao(
        candidato_id="c1",
        tipo=TipoDecisao.DESCARTAR,
        responsavel="humano:Carla Lima",
        momento=MOMENTO + timedelta(hours=1),
    )
    na_fila = _decisao(candidato_id="c2", tipo=TipoDecisao.PEDIR_HUMANO)
    resolvida = _decisao(
        candidato_id="c2",
        tipo=TipoDecisao.INDICAR,
        responsavel="humano:Carla Lima",
        momento=MOMENTO + timedelta(hours=1),
    )

    metricas = metricas_autonomia([revertida, automatica, resolvida, na_fila], [])

    assert metricas.candidatos == 2
    assert metricas.sem_revisao == 1
    assert metricas.porcentagem_sem_revisao == 50.0


def test_mesmo_candidato_em_duas_vagas_conta_duas_vezes():
    decisoes = [_decisao(), _decisao(vaga_id="vaga-2")]

    assert metricas_autonomia(decisoes, []).candidatos == 2


def test_segunda_auditoria_substitui_a_primeira_e_nao_infla_a_amostra(auditoria):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    primeira = _auditar(auditoria, decisao, correta=False)
    segunda = _auditar(auditoria, decisao, correta=True, momento=MOMENTO + timedelta(hours=1))

    metricas = metricas_autonomia([decisao], [segunda, primeira])

    assert metricas.tamanho_amostra == 1
    assert metricas.erros == 0


def test_auditoria_sem_decisao_correspondente_nao_conta(auditoria):
    decisao = _decisao(candidato_id="cand-fora-da-lista")
    auditoria.registrar_decisao(decisao)
    resultado = _auditar(auditoria, decisao, correta=False)

    metricas = metricas_autonomia(_automaticas(2), [resultado])

    assert metricas.tamanho_amostra == 0
    assert metricas.erro == NAO_MEDIDO


def test_metricas_nao_misturam_empresas(auditoria):
    decisao = _decisao()
    auditoria.registrar_decisao(decisao)
    resultado = _auditar(auditoria, decisao, correta=True)

    with pytest.raises(ValueError, match="empresa"):
        metricas_autonomia([decisao, _decisao(empresa_id="empresa-b")], [])
    with pytest.raises(ValueError, match="empresa"):
        metricas_autonomia(
            [_decisao(empresa_id="empresa-b")],
            [resultado],
        )
