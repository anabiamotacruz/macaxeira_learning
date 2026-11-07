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

from backend.contratos.modelos import Contrato, Decisao, EventoFluxo, Texto, Vaga

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
    estado TEXT NOT NULL DEFAULT 'pendente',
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

CREATE TABLE IF NOT EXISTS progressos (
    empresa_id TEXT NOT NULL,
    vaga_id TEXT NOT NULL,
    dados TEXT NOT NULL,
    PRIMARY KEY (empresa_id, vaga_id)
);

CREATE TABLE IF NOT EXISTS vagas (
    ordem INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id TEXT NOT NULL,
    vaga_id TEXT NOT NULL,
    dados TEXT NOT NULL,
    UNIQUE (empresa_id, vaga_id)
);

CREATE TABLE IF NOT EXISTS respostas_idempotentes (
    empresa_id TEXT NOT NULL,
    escopo TEXT NOT NULL,
    resumo_pedido TEXT NOT NULL,
    resposta TEXT NOT NULL,
    PRIMARY KEY (empresa_id, escopo)
);
"""

TABELAS_DA_EMPRESA = (
    "execucoes",
    "eventos",
    "chaves_idempotencia",
    "decisoes",
    "mandatos",
    "progressos",
    "vagas",
    "respostas_idempotentes",
)
"""Nomes fixos, nunca vindos de fora: toda tabela com dados de uma empresa entra aqui."""


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

    def trocar_estado(
        self,
        empresa_id: str,
        vaga_id: str,
        de: str,
        para: str,
        cursor: int,
        motivo: str | None = None,
        estado_anterior: str | None = None,
    ) -> bool:
        """Muda o estado só se ele ainda for `de`, para quem parou a vaga não ser sobrescrito."""
        registro = EstadoExecucao(
            empresa_id=_exigir_texto(empresa_id, "empresa_id"),
            vaga_id=vaga_id,
            estado=para,
            cursor=cursor,
            motivo=motivo,
            estado_anterior=estado_anterior,
        )
        with self._transacao() as conexao:
            alterado = conexao.execute(
                """
                UPDATE execucoes SET estado = ?, cursor = ?, motivo = ?, estado_anterior = ?
                WHERE empresa_id = ? AND vaga_id = ? AND estado = ?
                """,
                (
                    registro.estado,
                    registro.cursor,
                    registro.motivo,
                    registro.estado_anterior,
                    registro.empresa_id,
                    registro.vaga_id,
                    de,
                ),
            )
            return alterado.rowcount == 1

    def atualizar_cursor(self, empresa_id: str, vaga_id: str, cursor: int) -> None:
        """Avança o cursor sem tocar no estado: o candidato em curso conta mesmo com a parada."""
        if cursor < 0:
            raise ValueError("cursor não pode ser negativo")
        with self._transacao() as conexao:
            conexao.execute(
                "UPDATE execucoes SET cursor = ? WHERE empresa_id = ? AND vaga_id = ?",
                (
                    cursor,
                    _exigir_texto(empresa_id, "empresa_id"),
                    _exigir_texto(vaga_id, "vaga_id"),
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

        A chave nasce pendente. Quem chama faz a ação e depois usa `concluir_chave`. Se cair
        no meio, a chave segue pendente e a ação pode ser repetida, com a mesma chave, para
        o destino descartar a duplicata: não duplica e não se perde.
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

    def concluir_chave(self, empresa_id: str, chave: str) -> None:
        """Marca a ação como feita. Depois disso, ela nunca mais é repetida."""
        with self._transacao() as conexao:
            cursor = conexao.execute(
                """
                UPDATE chaves_idempotencia SET estado = 'concluida'
                WHERE empresa_id = ? AND chave = ?
                """,
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(chave, "chave")),
            )
            if cursor.rowcount != 1:
                raise ValueError("chave ainda não foi registrada nesta empresa")

    def chave_concluida(self, empresa_id: str, chave: str) -> bool:
        with self._transacao() as conexao:
            linha = conexao.execute(
                """
                SELECT 1 FROM chaves_idempotencia
                WHERE empresa_id = ? AND chave = ? AND estado = 'concluida'
                """,
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(chave, "chave")),
            ).fetchone()
        return linha is not None

    def chaves_pendentes(self, empresa_id: str) -> list[str]:
        with self._transacao() as conexao:
            linhas = conexao.execute(
                """
                SELECT chave FROM chaves_idempotencia
                WHERE empresa_id = ? AND estado = 'pendente' ORDER BY chave
                """,
                (_exigir_texto(empresa_id, "empresa_id"),),
            ).fetchall()
        return [chave for (chave,) in linhas]

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

    def salvar_progresso(self, empresa_id: str, vaga_id: str, progresso_json: str) -> None:
        """Guarda o trabalho da execução como JSON opaco, substituindo o anterior."""
        empresa_id = _exigir_texto(empresa_id, "empresa_id")
        vaga_id = _exigir_texto(vaga_id, "vaga_id")
        json.loads(progresso_json)
        with self._transacao() as conexao:
            conexao.execute(
                """
                INSERT INTO progressos (empresa_id, vaga_id, dados) VALUES (?, ?, ?)
                ON CONFLICT (empresa_id, vaga_id) DO UPDATE SET dados = excluded.dados
                """,
                (empresa_id, vaga_id, progresso_json),
            )

    def carregar_progresso(self, empresa_id: str, vaga_id: str) -> str | None:
        with self._transacao() as conexao:
            linha = conexao.execute(
                "SELECT dados FROM progressos WHERE empresa_id = ? AND vaga_id = ?",
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(vaga_id, "vaga_id")),
            ).fetchone()
        return linha[0] if linha is not None else None

    def salvar_vaga(self, vaga: Vaga) -> None:
        """Grava a vaga ou a substitui, mantendo a ordem de criação."""
        valida = _revalidar(vaga)
        with self._transacao() as conexao:
            conexao.execute(
                """
                INSERT INTO vagas (empresa_id, vaga_id, dados) VALUES (?, ?, ?)
                ON CONFLICT (empresa_id, vaga_id) DO UPDATE SET dados = excluded.dados
                """,
                (valida.empresa_id, valida.id, valida.model_dump_json()),
            )

    def carregar_vaga(self, empresa_id: str, vaga_id: str) -> Vaga | None:
        with self._transacao() as conexao:
            linha = conexao.execute(
                "SELECT dados FROM vagas WHERE empresa_id = ? AND vaga_id = ?",
                (_exigir_texto(empresa_id, "empresa_id"), vaga_id),
            ).fetchone()
        return None if linha is None else Vaga.model_validate_json(linha[0])

    def listar_vagas(self, empresa_id: str) -> list[Vaga]:
        """Vagas da empresa, na ordem em que foram criadas."""
        with self._transacao() as conexao:
            linhas = conexao.execute(
                "SELECT dados FROM vagas WHERE empresa_id = ? ORDER BY ordem",
                (_exigir_texto(empresa_id, "empresa_id"),),
            ).fetchall()
        return [Vaga.model_validate_json(dados) for (dados,) in linhas]

    def guardar_resposta(
        self, empresa_id: str, escopo: str, resumo_pedido: str, resposta_json: str
    ) -> tuple[str, str]:
        """Guarda a resposta de uma ação repetível. Devolve a primeira gravada para o escopo."""
        empresa_id = _exigir_texto(empresa_id, "empresa_id")
        escopo = _exigir_texto(escopo, "escopo")
        json.loads(resposta_json)
        with self._transacao() as conexao:
            conexao.execute(
                """
                INSERT INTO respostas_idempotentes (empresa_id, escopo, resumo_pedido, resposta)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (empresa_id, escopo) DO NOTHING
                """,
                (empresa_id, escopo, resumo_pedido, resposta_json),
            )
            return conexao.execute(
                """
                SELECT resumo_pedido, resposta FROM respostas_idempotentes
                WHERE empresa_id = ? AND escopo = ?
                """,
                (empresa_id, escopo),
            ).fetchone()

    def carregar_resposta(self, empresa_id: str, escopo: str) -> tuple[str, str] | None:
        with self._transacao() as conexao:
            return conexao.execute(
                """
                SELECT resumo_pedido, resposta FROM respostas_idempotentes
                WHERE empresa_id = ? AND escopo = ?
                """,
                (_exigir_texto(empresa_id, "empresa_id"), _exigir_texto(escopo, "escopo")),
            ).fetchone()

    def apagar_empresa(self, empresa_id: str) -> None:
        """Apaga tudo da empresa. Serve ao reinício dos dados sintéticos de demonstração."""
        empresa_id = _exigir_texto(empresa_id, "empresa_id")
        with self._transacao() as conexao:
            for tabela in TABELAS_DA_EMPRESA:
                conexao.execute(f"DELETE FROM {tabela} WHERE empresa_id = ?", (empresa_id,))
