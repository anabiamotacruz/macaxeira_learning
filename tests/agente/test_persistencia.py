import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agente.persistencia import EstadoExecucao, Repositorio
from backend.contratos.modelos import Decisao, EventoFluxo, Evidencia, TipoDecisao

FUSO_BRASILIA = timezone(timedelta(hours=-3))
MOMENTO = datetime(2026, 11, 7, 12, 0, tzinfo=FUSO_BRASILIA)
INJECAO_SQL = "x' OR '1'='1"


@pytest.fixture
def caminho(tmp_path: Path) -> Path:
    return tmp_path / "agente.db"


@pytest.fixture
def repo(caminho: Path) -> Repositorio:
    return Repositorio(caminho)


def _evento(mensagem: str = "busca iniciada", **campos) -> EventoFluxo:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "etapa": "busca",
        "mensagem": mensagem,
        "momento": MOMENTO,
    }
    dados.update(campos)
    return EventoFluxo(**dados)


def _decisao(**campos) -> Decisao:
    dados = {
        "empresa_id": "empresa-a",
        "vaga_id": "vaga-1",
        "candidato_id": "c1",
        "tipo": TipoDecisao.INDICAR,
        "regra": "requisitos_ok",
        "motivo": "atende aos requisitos",
        "responsavel": "agente; mandato v1",
        "rastro_id": "rastro-1",
        "entrada": {"nota": "0.8"},
        "evidencias": [Evidencia(criterio="python", trecho="5 anos", fonte="banco")],
        "momento": MOMENTO,
    }
    dados.update(campos)
    return Decisao(**dados)


# T1.8a: estado e eventos


def test_estado_sobrevive_a_reinicio(repo: Repositorio, caminho: Path) -> None:
    repo.salvar_estado(
        "empresa-a",
        "vaga-1",
        estado="PAUSADA",
        cursor=2,
        motivo="LIMITE_GASTO",
        estado_anterior="ANALISANDO",
    )

    reaberto = Repositorio(caminho)

    assert reaberto.carregar_estado("empresa-a", "vaga-1") == EstadoExecucao(
        empresa_id="empresa-a",
        vaga_id="vaga-1",
        estado="PAUSADA",
        cursor=2,
        motivo="LIMITE_GASTO",
        estado_anterior="ANALISANDO",
    )


def test_estado_inexistente_devolve_none(repo: Repositorio) -> None:
    assert repo.carregar_estado("empresa-a", "vaga-1") is None


def test_salvar_estado_de_novo_substitui_o_anterior(repo: Repositorio) -> None:
    repo.salvar_estado(
        "empresa-a", "vaga-1", estado="PAUSADA", cursor=2, motivo="X", estado_anterior="BUSCANDO"
    )
    repo.salvar_estado("empresa-a", "vaga-1", estado="ANALISANDO", cursor=3)

    estado = repo.carregar_estado("empresa-a", "vaga-1")

    assert estado is not None
    assert (estado.estado, estado.cursor, estado.motivo, estado.estado_anterior) == (
        "ANALISANDO",
        3,
        None,
        None,
    )


@pytest.mark.parametrize(
    "campos", [{"estado": "", "cursor": 0}, {"estado": "BUSCANDO", "cursor": -1}]
)
def test_estado_invalido_e_recusado(repo: Repositorio, campos: dict) -> None:
    with pytest.raises(ValueError):
        repo.salvar_estado("empresa-a", "vaga-1", **campos)

    assert repo.carregar_estado("empresa-a", "vaga-1") is None


def test_eventos_voltam_em_ordem_estavel_depois_de_reabrir(
    repo: Repositorio, caminho: Path
) -> None:
    # Momentos fora de ordem e empatados: quem manda é a ordem de registro.
    eventos = [
        _evento("primeiro", momento=MOMENTO + timedelta(minutes=5)),
        _evento("segundo", momento=MOMENTO),
        _evento("terceiro", momento=MOMENTO),
    ]
    for evento in eventos:
        repo.registrar_evento(evento)

    assert Repositorio(caminho).listar_eventos("empresa-a", "vaga-1") == eventos


def test_evento_preserva_o_fuso_do_momento(repo: Repositorio) -> None:
    repo.registrar_evento(_evento())

    [evento] = repo.listar_eventos("empresa-a", "vaga-1")

    assert evento.momento.utcoffset() == timedelta(hours=-3)


def test_eventos_de_outra_vaga_ficam_de_fora(repo: Repositorio) -> None:
    repo.registrar_evento(_evento(vaga_id="vaga-2"))

    assert repo.listar_eventos("empresa-a", "vaga-1") == []


def test_texto_de_candidato_com_sql_e_guardado_como_dado(repo: Repositorio) -> None:
    repo.registrar_evento(_evento(INJECAO_SQL))

    assert repo.listar_eventos("empresa-a", "vaga-1")[0].mensagem == INJECAO_SQL


def test_estado_rejeita_campo_desconhecido() -> None:
    with pytest.raises(ValidationError):
        EstadoExecucao(empresa_id="a", vaga_id="v", estado="BUSCANDO", cursor=0, extra="x")


# T1.8b: idempotência


def test_chave_repetida_nao_duplica_acao(repo: Repositorio, caminho: Path) -> None:
    assert repo.chave_ja_usada("empresa-a", "convite-1") is False

    assert repo.registrar_chave("empresa-a", "convite-1") is True
    assert repo.registrar_chave("empresa-a", "convite-1") is False

    assert repo.chave_ja_usada("empresa-a", "convite-1") is True
    assert Repositorio(caminho).registrar_chave("empresa-a", "convite-1") is False


def test_mesma_chave_em_outra_empresa_nao_colide(repo: Repositorio) -> None:
    assert repo.registrar_chave("empresa-a", "convite-1") is True

    assert repo.chave_ja_usada("empresa-b", "convite-1") is False
    assert repo.registrar_chave("empresa-b", "convite-1") is True


def test_registro_concorrente_da_chave_so_vence_uma_vez(repo: Repositorio) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        resultados = list(
            executor.map(lambda _: repo.registrar_chave("empresa-a", "convite-1"), range(32))
        )

    assert resultados.count(True) == 1


def test_unicidade_da_chave_vem_de_restricao_do_banco(repo: Repositorio, caminho: Path) -> None:
    repo.registrar_chave("empresa-a", "convite-1")

    with closing(sqlite3.connect(caminho)) as conexao, pytest.raises(sqlite3.IntegrityError):
        conexao.execute(
            "INSERT INTO chaves_idempotencia (empresa_id, chave) VALUES (?, ?)",
            ("empresa-a", "convite-1"),
        )


@pytest.mark.parametrize("chave", ["", "   "])
def test_chave_vazia_e_recusada(repo: Repositorio, chave: str) -> None:
    with pytest.raises(ValueError):
        repo.registrar_chave("empresa-a", chave)
    with pytest.raises(ValueError):
        repo.chave_ja_usada("empresa-a", chave)


# T1.8c: isolamento, decisões e mandato


def test_empresa_so_le_os_proprios_dados(repo: Repositorio) -> None:
    # As duas empresas usam o mesmo id de vaga: só o empresa_id separa os dados.
    for empresa_id, cursor in (("empresa-a", 1), ("empresa-b", 2)):
        repo.salvar_estado(empresa_id, "vaga-1", estado="BUSCANDO", cursor=cursor)
        repo.registrar_evento(_evento(empresa_id, empresa_id=empresa_id))
        repo.salvar_decisao(_decisao(empresa_id=empresa_id, motivo=empresa_id))
        repo.salvar_mandato(empresa_id, "vaga-1", json.dumps({"assinante": empresa_id}))

    for empresa_id, cursor in (("empresa-a", 1), ("empresa-b", 2)):
        estado = repo.carregar_estado(empresa_id, "vaga-1")
        assert estado is not None and estado.cursor == cursor
        assert [e.mensagem for e in repo.listar_eventos(empresa_id, "vaga-1")] == [empresa_id]
        assert [d.motivo for d in repo.listar_decisoes(empresa_id, "vaga-1")] == [empresa_id]
        mandato = repo.carregar_mandato(empresa_id, "vaga-1")
        assert mandato is not None and json.loads(mandato) == {"assinante": empresa_id}


def test_empresa_sem_dados_nao_le_nada_de_outra(repo: Repositorio) -> None:
    repo.salvar_estado("empresa-a", "vaga-1", estado="BUSCANDO", cursor=1)
    repo.registrar_evento(_evento())
    repo.salvar_decisao(_decisao())
    repo.salvar_mandato("empresa-a", "vaga-1", "{}")

    assert repo.carregar_estado("empresa-b", "vaga-1") is None
    assert repo.listar_eventos("empresa-b", "vaga-1") == []
    assert repo.listar_decisoes("empresa-b", "vaga-1") == []
    assert repo.carregar_mandato("empresa-b", "vaga-1") is None


def test_injecao_sql_no_escopo_nao_vaza_dados(repo: Repositorio) -> None:
    repo.salvar_estado("empresa-a", "vaga-1", estado="BUSCANDO", cursor=1)
    repo.registrar_evento(_evento())
    repo.salvar_decisao(_decisao())
    repo.salvar_mandato("empresa-a", "vaga-1", "{}")
    repo.registrar_chave("empresa-a", "convite-1")

    assert repo.carregar_estado(INJECAO_SQL, "vaga-1") is None
    assert repo.carregar_estado("empresa-a", INJECAO_SQL) is None
    assert repo.listar_eventos(INJECAO_SQL, "vaga-1") == []
    assert repo.listar_eventos("empresa-a", INJECAO_SQL) == []
    assert repo.listar_decisoes(INJECAO_SQL, "vaga-1") == []
    assert repo.listar_decisoes("empresa-a", INJECAO_SQL) == []
    assert repo.carregar_mandato(INJECAO_SQL, "vaga-1") is None
    assert repo.carregar_mandato("empresa-a", INJECAO_SQL) is None
    assert repo.chave_ja_usada(INJECAO_SQL, "convite-1") is False
    assert repo.chave_ja_usada("empresa-a", INJECAO_SQL) is False


OPERACOES_COM_EMPRESA = {
    "salvar_estado": lambda repo, e: repo.salvar_estado(e, "vaga-1", estado="BUSCANDO", cursor=0),
    "carregar_estado": lambda repo, e: repo.carregar_estado(e, "vaga-1"),
    "registrar_evento": lambda repo, e: repo.registrar_evento(
        _evento().model_copy(update={"empresa_id": e})
    ),
    "listar_eventos": lambda repo, e: repo.listar_eventos(e, "vaga-1"),
    "registrar_chave": lambda repo, e: repo.registrar_chave(e, "convite-1"),
    "chave_ja_usada": lambda repo, e: repo.chave_ja_usada(e, "convite-1"),
    "salvar_decisao": lambda repo, e: repo.salvar_decisao(
        _decisao().model_copy(update={"empresa_id": e})
    ),
    "listar_decisoes": lambda repo, e: repo.listar_decisoes(e, "vaga-1"),
    "salvar_mandato": lambda repo, e: repo.salvar_mandato(e, "vaga-1", "{}"),
    "carregar_mandato": lambda repo, e: repo.carregar_mandato(e, "vaga-1"),
    "chave_concluida": lambda repo, e: repo.chave_concluida(e, "convite-1"),
    "concluir_chave": lambda repo, e: repo.concluir_chave(e, "convite-1"),
    "chaves_pendentes": lambda repo, e: repo.chaves_pendentes(e),
    "trocar_estado": lambda repo, e: repo.trocar_estado(e, "vaga-1", "a", "b", 0),
    "atualizar_cursor": lambda repo, e: repo.atualizar_cursor(e, "vaga-1", 1),
    "salvar_progresso": lambda repo, e: repo.salvar_progresso(e, "vaga-1", "{}"),
    "carregar_progresso": lambda repo, e: repo.carregar_progresso(e, "vaga-1"),
}


@pytest.mark.parametrize("operacao", OPERACOES_COM_EMPRESA.values(), ids=OPERACOES_COM_EMPRESA)
@pytest.mark.parametrize("empresa_id", ["", "   "])
def test_empresa_vazia_levanta_erro_em_toda_leitura_e_escrita(
    repo: Repositorio, operacao, empresa_id: str
) -> None:
    with pytest.raises(ValueError):
        operacao(repo, empresa_id)


def test_data_sem_fuso_e_recusada(repo: Repositorio) -> None:
    sem_fuso = datetime(2026, 11, 7, 12, 0)

    # O contrato recusa na criação; o repositório recusa o que escapou por model_copy.
    with pytest.raises(ValidationError):
        _decisao(momento=sem_fuso)
    with pytest.raises(ValidationError):
        _evento(momento=sem_fuso)
    with pytest.raises(ValueError):
        repo.salvar_decisao(_decisao().model_copy(update={"momento": sem_fuso}))
    with pytest.raises(ValueError):
        repo.registrar_evento(_evento().model_copy(update={"momento": sem_fuso}))

    assert repo.listar_decisoes("empresa-a", "vaga-1") == []
    assert repo.listar_eventos("empresa-a", "vaga-1") == []


def test_decisoes_voltam_inteiras_e_em_ordem(repo: Repositorio, caminho: Path) -> None:
    # A decisão original nunca é apagada: reverter acrescenta, não substitui.
    original = _decisao()
    revertida = _decisao(tipo=TipoDecisao.DESCARTAR, regra="reversao_humana", responsavel="rh")

    repo.salvar_decisao(original)
    repo.salvar_decisao(revertida)

    decisoes = Repositorio(caminho).listar_decisoes("empresa-a", "vaga-1")
    assert decisoes == [original, revertida]
    assert decisoes[0].momento.utcoffset() == timedelta(hours=-3)


def test_mandato_e_guardado_como_json_opaco(repo: Repositorio, caminho: Path) -> None:
    # Espaços e ordem das chaves preservados: o repositório não interpreta o conteúdo.
    mandato = '{"z": 1,  "assinante": "Ana", "limite_usd": 5.0}'

    repo.salvar_mandato("empresa-a", "vaga-1", mandato)

    assert Repositorio(caminho).carregar_mandato("empresa-a", "vaga-1") == mandato


def test_mandato_inexistente_devolve_none(repo: Repositorio) -> None:
    assert repo.carregar_mandato("empresa-a", "vaga-1") is None


def test_nova_assinatura_vale_sem_apagar_o_mandato_anterior(
    repo: Repositorio, caminho: Path
) -> None:
    repo.salvar_mandato("empresa-a", "vaga-1", '{"versao": 1}')
    repo.salvar_mandato("empresa-a", "vaga-1", '{"versao": 2}')

    assert repo.carregar_mandato("empresa-a", "vaga-1") == '{"versao": 2}'
    with closing(sqlite3.connect(caminho)) as conexao:
        [(quantidade,)] = conexao.execute("SELECT COUNT(*) FROM mandatos").fetchall()
    assert quantidade == 2


@pytest.mark.parametrize("mandato", ["", "{nao e json"])
def test_mandato_que_nao_e_json_e_recusado(repo: Repositorio, mandato: str) -> None:
    with pytest.raises(ValueError):
        repo.salvar_mandato("empresa-a", "vaga-1", mandato)

    assert repo.carregar_mandato("empresa-a", "vaga-1") is None


@pytest.mark.parametrize("vaga_id", ["", "   "])
def test_mandato_exige_vaga(repo: Repositorio, vaga_id: str) -> None:
    with pytest.raises(ValueError):
        repo.salvar_mandato("empresa-a", vaga_id, "{}")
    with pytest.raises(ValueError):
        repo.carregar_mandato("empresa-a", vaga_id)


def test_progresso_sobrevive_a_reinicio_e_substitui_o_anterior(
    repo: Repositorio, caminho: Path
) -> None:
    assert repo.carregar_progresso("empresa-a", "vaga-1") is None

    repo.salvar_progresso("empresa-a", "vaga-1", '{"rodada": 0}')
    repo.salvar_progresso("empresa-a", "vaga-1", '{"rodada": 1}')

    assert Repositorio(caminho).carregar_progresso("empresa-a", "vaga-1") == '{"rodada": 1}'


def test_progresso_de_outra_empresa_nao_aparece(repo: Repositorio) -> None:
    repo.salvar_progresso("empresa-a", "vaga-1", '{"rodada": 1}')

    assert repo.carregar_progresso("empresa-b", "vaga-1") is None


def test_progresso_invalido_e_recusado(repo: Repositorio) -> None:
    with pytest.raises(ValueError):
        repo.salvar_progresso("empresa-a", "vaga-1", "isto não é json")


def test_chave_registrada_fica_pendente_ate_concluir(repo: Repositorio, caminho: Path) -> None:
    repo.registrar_chave("empresa-a", "entrega-1")

    assert repo.chave_ja_usada("empresa-a", "entrega-1") is True
    assert repo.chave_concluida("empresa-a", "entrega-1") is False
    assert Repositorio(caminho).chaves_pendentes("empresa-a") == ["entrega-1"]

    repo.concluir_chave("empresa-a", "entrega-1")

    assert repo.chave_concluida("empresa-a", "entrega-1") is True
    assert Repositorio(caminho).chaves_pendentes("empresa-a") == []
    assert repo.registrar_chave("empresa-a", "entrega-1") is False
    assert repo.chave_concluida("empresa-a", "entrega-1") is True


def test_chave_desconhecida_nao_conclui_nem_conta_como_concluida(repo: Repositorio) -> None:
    assert repo.chave_concluida("empresa-a", "entrega-1") is False
    with pytest.raises(ValueError, match="registrada"):
        repo.concluir_chave("empresa-a", "entrega-1")


def test_chave_pendente_nao_cruza_empresas(repo: Repositorio) -> None:
    repo.registrar_chave("empresa-a", "entrega-1")

    assert repo.chaves_pendentes("empresa-b") == []
    with pytest.raises(ValueError, match="registrada"):
        repo.concluir_chave("empresa-b", "entrega-1")
    assert repo.chave_concluida("empresa-a", "entrega-1") is False


def test_trocar_estado_so_vale_a_partir_do_esperado(repo: Repositorio) -> None:
    repo.salvar_estado("empresa-a", "vaga-1", "analisando", 2)

    assert repo.trocar_estado("empresa-a", "vaga-1", "buscando", "pausada", 2) is False
    assert repo.carregar_estado("empresa-a", "vaga-1").estado == "analisando"

    trocou = repo.trocar_estado(
        "empresa-a", "vaga-1", "analisando", "pausada", 3, "LIMITE_GASTO", "analisando"
    )

    assert trocou is True
    salvo = repo.carregar_estado("empresa-a", "vaga-1")
    assert (salvo.estado, salvo.cursor, salvo.motivo, salvo.estado_anterior) == (
        "pausada",
        3,
        "LIMITE_GASTO",
        "analisando",
    )


def test_trocar_estado_nao_cruza_empresas(repo: Repositorio) -> None:
    repo.salvar_estado("empresa-a", "vaga-1", "analisando", 2)

    assert repo.trocar_estado("empresa-b", "vaga-1", "analisando", "pausada", 2) is False


def test_atualizar_cursor_nao_muda_o_estado(repo: Repositorio) -> None:
    repo.salvar_estado("empresa-a", "vaga-1", "pausada", 2, "PARADA_PELO_RH", "analisando")

    repo.atualizar_cursor("empresa-a", "vaga-1", 3)
    repo.atualizar_cursor("empresa-b", "vaga-1", 9)

    salvo = repo.carregar_estado("empresa-a", "vaga-1")
    assert (salvo.estado, salvo.cursor, salvo.motivo) == ("pausada", 3, "PARADA_PELO_RH")


def test_atualizar_cursor_recusa_valor_negativo(repo: Repositorio) -> None:
    repo.salvar_estado("empresa-a", "vaga-1", "analisando", 2)

    with pytest.raises(ValueError):
        repo.atualizar_cursor("empresa-a", "vaga-1", -1)
