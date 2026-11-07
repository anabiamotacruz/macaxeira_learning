"""Persistência do agente em SQLite, acessada somente pelo `Repositorio`.

O esquema inteiro fica em `ESQUEMA`, neste arquivo. Toda leitura e escrita é
escopada por `empresa_id`, e o que entra passa de novo pelos contratos.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from pydantic import NonNegativeInt

from backend.contratos.modelos import Contrato, Decisao, EventoFluxo, Texto

ESQUEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    empresa_id TEXT NOT NULL,
    vaga_id TEXT NOT NULL,
    estado TEXT NOT NULL,
    cursor INTEGER NOT NULL,
    motivo TEXT,
    estado_anterior TEXT,
    PRIMARY KEY (empresa_id, vaga_id)
);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id TEXT NOT NULL,
    vaga_id TEXT NOT NULL,
    dados TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS eventos_por_vaga ON eventos (empresa_id, vaga_id, id);

CREATE TABLE IF NOT EXISTS chaves_idempotencia (
    empresa_id TEXT NOT NULL,
    chave TEXT NOT NULL,
    PRIMARY KEY (empresa_id, chave)
);

CREATE TABLE IF NOT EXISTS decisoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id TEXT NOT NULL,
    vaga_id TEXT NOT NULL,
    dados TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisoes_por_vaga ON decisoes (empresa_id, vaga_id, id);

CREATE TABLE IF NOT EXISTS mandatos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id TEXT NOT NULL,
    vaga_id TEXT NOT NULL,
    dados TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mandatos_por_vaga ON mandatos (empresa_id, vaga_id, id);
"""


class EstadoExecucao(Contrato):
    """Onde a execução de uma vaga parou. Modelo local: não cruza frentes."""

    empresa_id: Texto
    vaga_id: Texto
    estado: Texto
    cursor: NonNegativeInt
    motivo: str | None = None
    estado_anterior: Texto | None = None


def _exigir_texto(valor: str, campo: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{campo} é obrigatório em toda leitura e escrita")
    return valor.strip()


def _revalidar[M: Contrato](modelo: M) -> M:
    """`model_copy` não valida: o banco não aceita o que o contrato recusaria."""
    return type(modelo).model_validate(modelo.model_dump())


class Repositorio:
    """Acesso ao arquivo SQLite. Cada operação abre e fecha a própria conexão."""

    def __init__(self, caminho: str | Path) -> None:
        self._caminho = caminho
        with self._transacao() as conexao:
            conexao.executescript(ESQUEMA)

    @contextmanager
    def _transacao(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._caminho)) as conexao, conexao:
            yield conexao

    def salvar_estado(
        self,
        empresa_id: str,
        vaga_id: str,
        estado: str,
        cursor: int,
        motivo: str | None = None,
        estado_anterior: str | None = None,
    ) -> None:
        """Grava o ponto de retomada, substituindo o anterior da mesma vaga."""
        registro = EstadoExecucao(
            empresa_id=_exigir_texto(empresa_id, "empresa_id"),
            vaga_id=vaga_id,
            estado=estado,
            cursor=cursor,
            motivo=motivo,
            estado_anterior=estado_anterior,
        )
        with self._transacao() as conexao:
            conexao.execute(
                """
                INSERT INTO execucoes
                    (empresa_id, vaga_id, estado, cursor, motivo, estado_anterior)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (empresa_id, vaga_id) DO UPDATE SET
                    estado = excluded.estado,
                    cursor = excluded.cursor,
                    motivo = excluded.motivo,
                    estado_anterior = excluded.estado_anterior
                """,
                (
                    registro.empresa_id,
                    registro.vaga_id,
                    registro.estado,
                    registro.cursor,
                    registro.motivo,
                    registro.estado_anterior,
                ),
            )

    def carregar_estado(self, empresa_id: str, vaga_id: str) -> EstadoExecucao | None:
        with self._transacao() as conexao:
            linha = conexao.execute(
                """
                SELECT estado, cursor, motivo, estado_anterior FROM execucoes
                WHERE empresa_id = ? AND vaga_id = ?
                """,
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(vaga_id, "vaga_id")),
            ).fetchone()
        if linha is None:
            return None
        estado, cursor, motivo, estado_anterior = linha
        return EstadoExecucao(
            empresa_id=empresa_id,
            vaga_id=vaga_id,
            estado=estado,
            cursor=cursor,
            motivo=motivo,
            estado_anterior=estado_anterior,
        )

    def registrar_evento(self, evento: EventoFluxo) -> None:
        valido = _revalidar(evento)
        with self._transacao() as conexao:
            conexao.execute(
                "INSERT INTO eventos (empresa_id, vaga_id, dados) VALUES (?, ?, ?)",
                (valido.empresa_id, valido.vaga_id, valido.model_dump_json()),
            )

    def listar_eventos(self, empresa_id: str, vaga_id: str) -> list[EventoFluxo]:
        """Eventos da vaga na ordem em que foram registrados."""
        with self._transacao() as conexao:
            linhas = conexao.execute(
                "SELECT dados FROM eventos WHERE empresa_id = ? AND vaga_id = ? ORDER BY id",
                (_exigir_texto(empresa_id, "empresa_id"), vaga_id),
            ).fetchall()
        return [EventoFluxo.model_validate_json(dados) for (dados,) in linhas]

    def registrar_chave(self, empresa_id: str, chave: str) -> bool:
        """Devolve `True` só para quem registrou primeiro; a restrição do banco garante a corrida.

        Quem chama faz a ação depois de receber `True`. Se cair entre o registro e a
        ação, a chave fica usada e a ação não acontece: nunca duplica, mas pode faltar.
        """
        with self._transacao() as conexao:
            cursor = conexao.execute(
                """
                INSERT INTO chaves_idempotencia (empresa_id, chave) VALUES (?, ?)
                ON CONFLICT (empresa_id, chave) DO NOTHING
                """,
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(chave, "chave")),
            )
            return cursor.rowcount == 1

    def chave_ja_usada(self, empresa_id: str, chave: str) -> bool:
        with self._transacao() as conexao:
            linha = conexao.execute(
                "SELECT 1 FROM chaves_idempotencia WHERE empresa_id = ? AND chave = ?",
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(chave, "chave")),
            ).fetchone()
        return linha is not None

    def salvar_decisao(self, decisao: Decisao) -> None:
        """Acrescenta a decisão. Decisões anteriores nunca são apagadas nem alteradas."""
        valida = _revalidar(decisao)
        with self._transacao() as conexao:
            conexao.execute(
                "INSERT INTO decisoes (empresa_id, vaga_id, dados) VALUES (?, ?, ?)",
                (valida.empresa_id, valida.vaga_id, valida.model_dump_json()),
            )

    def listar_decisoes(self, empresa_id: str, vaga_id: str) -> list[Decisao]:
        """Decisões da vaga na ordem em que foram registradas."""
        with self._transacao() as conexao:
            linhas = conexao.execute(
                "SELECT dados FROM decisoes WHERE empresa_id = ? AND vaga_id = ? ORDER BY id",
                (_exigir_texto(empresa_id, "empresa_id"), vaga_id),
            ).fetchall()
        return [Decisao.model_validate_json(dados) for (dados,) in linhas]

    def salvar_mandato(self, empresa_id: str, vaga_id: str, mandato_json: str) -> None:
        """Guarda o mandato como JSON opaco, sem conhecer o tipo.

        Cada assinatura vira uma nova linha, para a auditoria não perder a versão
        sob a qual uma decisão antiga foi tomada.
        """
        empresa_id = _exigir_texto(empresa_id, "empresa_id")
        vaga_id = _exigir_texto(vaga_id, "vaga_id")
        json.loads(mandato_json)
        with self._transacao() as conexao:
            conexao.execute(
                "INSERT INTO mandatos (empresa_id, vaga_id, dados) VALUES (?, ?, ?)",
                (empresa_id, vaga_id, mandato_json),
            )

    def carregar_mandato(self, empresa_id: str, vaga_id: str) -> str | None:
        """Devolve o JSON da assinatura mais recente, exatamente como foi salvo."""
        with self._transacao() as conexao:
            linha = conexao.execute(
                """
                SELECT dados FROM mandatos WHERE empresa_id = ? AND vaga_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(vaga_id, "vaga_id")),
            ).fetchone()
        return linha[0] if linha is not None else None
