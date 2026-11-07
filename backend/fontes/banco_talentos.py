"""Banco de talentos em SQLite, isolado por empresa.

Remover apaga os dados da pessoa e guarda só resumos irreversíveis do id e do e-mail,
para ela não voltar por uma nova importação. Texto de candidato é sempre tratado como dado.
"""

import hashlib
import re
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import date
from pathlib import Path
from threading import RLock

from backend.contratos.modelos import Candidato, EstadoBanco

POR_PAGINA = 20
ESTADOS_BUSCAVEIS = frozenset({EstadoBanco.ATIVO, EstadoBanco.DESATUALIZADO})
CAMPOS_DE_CONTATO = frozenset({"email", "telefone", "whatsapp"})

ESQUEMA = """
CREATE TABLE IF NOT EXISTS perfis (
    empresa_id TEXT NOT NULL,
    candidato_id TEXT NOT NULL,
    email TEXT,
    dados TEXT NOT NULL,
    PRIMARY KEY (empresa_id, candidato_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS perfis_por_email ON perfis (empresa_id, email)
    WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS origens (
    empresa_id TEXT NOT NULL,
    candidato_id TEXT NOT NULL,
    ordem INTEGER PRIMARY KEY AUTOINCREMENT,
    origem TEXT NOT NULL,
    UNIQUE (empresa_id, candidato_id, origem)
);

CREATE TABLE IF NOT EXISTS bloqueios (
    empresa_id TEXT NOT NULL,
    resumo TEXT NOT NULL,
    PRIMARY KEY (empresa_id, resumo)
);
"""


def _exigir_empresa(empresa_id: str) -> str:
    if not isinstance(empresa_id, str) or not empresa_id.strip():
        raise ValueError("empresa_id é obrigatório em toda leitura e escrita")
    return empresa_id.strip()


def _email(candidato: Candidato) -> str | None:
    return candidato.atributos.get("email", "").strip().casefold() or None


def _resumos(empresa_id: str, candidato_id: str, email: str | None) -> list[str]:
    valores = [f"id:{candidato_id}"] + ([f"email:{email}"] if email else [])
    return [hashlib.sha256(f"{empresa_id}:{v}".encode()).hexdigest() for v in valores]


def _termos(texto: str) -> set[str]:
    return set(re.findall(r"\w+", texto.casefold()))


def _combina(candidato: Candidato, consulta: str) -> bool:
    """Compara palavras inteiras do perfil. Nome e contato ficam de fora da busca."""
    atributos = (v for k, v in candidato.atributos.items() if k not in CAMPOS_DE_CONTATO)
    return _termos(consulta) <= _termos(" ".join([candidato.perfil_texto, *atributos]))


class BancoTalentos:
    """Implementação de `backend.contratos.interfaces.BancoTalentos`."""

    def __init__(
        self,
        caminho: str | Path = ":memory:",
        *,
        hoje: date,
        confiar_autorizacao_sintetica: bool = False,
    ) -> None:
        """`confiar_autorizacao_sintetica` serve só a cargas sintéticas de confiança.

        Sem ele, a autorização declarada no registro é ignorada: a pessoa entra como pendente
        e só autoriza por `registrar_autorizacao`.
        """
        self.hoje = hoje
        self._confiar_autorizacao_sintetica = confiar_autorizacao_sintetica
        self._trava = RLock()
        self._conexao = sqlite3.connect(caminho, check_same_thread=False)
        with self._trava, self._conexao:
            self._conexao.execute("PRAGMA secure_delete = ON")
            self._conexao.executescript(ESQUEMA)

    def fechar(self) -> None:
        with self._trava:
            self._conexao.close()

    def _listar(self, empresa_id: str) -> Iterable[Candidato]:
        with self._trava, closing(self._conexao.cursor()) as cursor:
            linhas = cursor.execute(
                "SELECT dados FROM perfis WHERE empresa_id = ? ORDER BY candidato_id",
                (_exigir_empresa(empresa_id),),
            ).fetchall()
        return [Candidato.model_validate_json(dados) for (dados,) in linhas]

    def _obter(self, empresa_id: str, candidato_id: str) -> Candidato:
        with self._trava:
            linha = self._conexao.execute(
                "SELECT dados FROM perfis WHERE empresa_id = ? AND candidato_id = ?",
                (_exigir_empresa(empresa_id), candidato_id),
            ).fetchone()
        if linha is None:
            raise KeyError(candidato_id)
        return Candidato.model_validate_json(linha[0])

    def _salvar(self, candidato: Candidato) -> Candidato:
        valido = Candidato.model_validate(candidato.model_dump())
        try:
            with self._trava, self._conexao:
                self._conexao.execute(
                    "UPDATE perfis SET email = ?, dados = ? "
                    "WHERE empresa_id = ? AND candidato_id = ?",
                    (_email(valido), valido.model_dump_json(), valido.empresa_id, valido.id),
                )
        except sqlite3.IntegrityError as erro:
            raise ValueError("e-mail já pertence a outra pessoa desta empresa") from erro
        return valido

    def _apto(self, candidato: Candidato) -> bool:
        validade = candidato.autorizacao_valida_ate
        return (
            candidato.estado in ESTADOS_BUSCAVEIS
            and candidato.autorizou_contato
            and not candidato.opt_out
            and validade is not None
            and validade >= self.hoje
        )

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        if pagina < 1:
            raise ValueError("pagina deve ser maior ou igual a 1")
        aptos = [c for c in self._listar(empresa_id) if self._apto(c) and _combina(c, consulta)]
        inicio = (pagina - 1) * POR_PAGINA
        return aptos[inicio : inicio + POR_PAGINA]

    def importar(self, empresa_id: str, registros: list[dict]) -> list[Candidato]:
        """Grava tudo ou nada. Duplicata mantém o perfil atual e só acrescenta a origem."""
        empresa_id = _exigir_empresa(empresa_id)
        candidatos = []
        for registro in registros:
            candidato = Candidato.model_validate({"empresa_id": empresa_id, **registro})
            if candidato.empresa_id != empresa_id:
                raise ValueError("registro pertence a outra empresa")
            candidatos.append(self._sem_autorizacao_declarada(candidato))

        importados: dict[str, Candidato] = {}
        with self._trava, self._conexao:
            for candidato in candidatos:
                atual = self._importar_um(candidato)
                if atual is not None:
                    importados.setdefault(atual.id, atual)
        return list(importados.values())

    def _sem_autorizacao_declarada(self, candidato: Candidato) -> Candidato:
        """Autorização de arquivo não tem consentimento registrado. Remoção e opt-out valem."""
        if self._confiar_autorizacao_sintetica and candidato.simulado:
            return candidato
        removido = candidato.estado == EstadoBanco.REMOVIDO
        return candidato.model_copy(
            update={
                "autorizou_contato": False,
                "autorizacao_valida_ate": None,
                "estado": EstadoBanco.REMOVIDO if removido else EstadoBanco.PENDENTE,
            }
        )

    def _importar_um(self, candidato: Candidato) -> Candidato | None:
        empresa_id, email = candidato.empresa_id, _email(candidato)
        for resumo in _resumos(empresa_id, candidato.id, email):
            bloqueado = self._conexao.execute(
                "SELECT 1 FROM bloqueios WHERE empresa_id = ? AND resumo = ?",
                (empresa_id, resumo),
            ).fetchone()
            if bloqueado:
                return None

        linha = self._conexao.execute(
            """
            SELECT dados FROM perfis
            WHERE empresa_id = ? AND (candidato_id = ? OR (email IS NOT NULL AND email = ?))
            ORDER BY candidato_id LIMIT 1
            """,
            (empresa_id, candidato.id, email),
        ).fetchone()
        if linha is None:
            atual = candidato
            self._conexao.execute(
                "INSERT INTO perfis (empresa_id, candidato_id, email, dados) VALUES (?, ?, ?, ?)",
                (empresa_id, candidato.id, email, candidato.model_dump_json()),
            )
        else:
            atual = Candidato.model_validate_json(linha[0])
            if candidato.opt_out and not atual.opt_out:
                atual = atual.model_copy(update={"opt_out": True})
                self._conexao.execute(
                    "UPDATE perfis SET dados = ? WHERE empresa_id = ? AND candidato_id = ?",
                    (atual.model_dump_json(), empresa_id, atual.id),
                )
        self._conexao.execute(
            """
            INSERT INTO origens (empresa_id, candidato_id, origem) VALUES (?, ?, ?)
            ON CONFLICT (empresa_id, candidato_id, origem) DO NOTHING
            """,
            (empresa_id, atual.id, candidato.origem),
        )
        return atual

    def origens(self, empresa_id: str, candidato_id: str) -> list[str]:
        """Origens registradas para a pessoa, na ordem em que chegaram."""
        self._obter(empresa_id, candidato_id)
        with self._trava:
            linhas = self._conexao.execute(
                "SELECT origem FROM origens "
                "WHERE empresa_id = ? AND candidato_id = ? ORDER BY ordem",
                (empresa_id.strip(), candidato_id),
            ).fetchall()
        return [origem for (origem,) in linhas]

    def registrar_autorizacao(
        self, empresa_id: str, candidato_id: str, valida_ate: date
    ) -> Candidato:
        """Registra a autorização. Um opt-out anterior continua valendo, e removido não volta."""
        if valida_ate < self.hoje:
            raise ValueError("a validade da autorização já passou")
        atual = self._obter(empresa_id, candidato_id)
        if atual.estado == EstadoBanco.REMOVIDO:
            raise ValueError("pessoa removida não pode voltar por autorização")
        return self._salvar(
            atual.model_copy(
                update={
                    "autorizou_contato": True,
                    "autorizacao_valida_ate": valida_ate,
                    "estado": EstadoBanco.ATIVO,
                }
            )
        )

    def atualizar(self, empresa_id: str, candidato_id: str, dados: dict[str, str]) -> Candidato:
        atual = self._obter(empresa_id, candidato_id)
        estado = EstadoBanco.ATIVO if atual.estado == EstadoBanco.DESATUALIZADO else atual.estado
        return self._salvar(
            atual.model_copy(
                update={
                    "atributos": {**atual.atributos, **dados},
                    "atualizado_em": self.hoje,
                    "estado": estado,
                }
            )
        )

    def registrar_opt_out(self, empresa_id: str, candidato_id: str) -> Candidato:
        atual = self._obter(empresa_id, candidato_id)
        return self._salvar(atual.model_copy(update={"opt_out": True}))

    def remover(self, empresa_id: str, candidato_id: str) -> None:
        empresa_id = _exigir_empresa(empresa_id)
        atual = self._obter(empresa_id, candidato_id)
        with self._trava, self._conexao:
            self._conexao.execute(
                "DELETE FROM perfis WHERE empresa_id = ? AND candidato_id = ?",
                (empresa_id, candidato_id),
            )
            self._conexao.execute(
                "DELETE FROM origens WHERE empresa_id = ? AND candidato_id = ?",
                (empresa_id, candidato_id),
            )
            self._conexao.executemany(
                "INSERT OR IGNORE INTO bloqueios (empresa_id, resumo) VALUES (?, ?)",
                [(empresa_id, r) for r in _resumos(empresa_id, candidato_id, _email(atual))],
            )

    def vencendo(self, empresa_id: str, ate: date) -> list[Candidato]:
        """Quem tem autorização até `ate`, sem quem saiu ou foi removido."""
        return [
            c
            for c in self._listar(empresa_id)
            if c.autorizacao_valida_ate is not None
            and c.autorizacao_valida_ate <= ate
            and not c.opt_out
            and c.estado != EstadoBanco.REMOVIDO
        ]
