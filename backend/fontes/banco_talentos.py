"""Banco de talentos em SQLite, isolado por empresa.

Remover apaga os dados da pessoa e guarda só resumos irreversíveis do id e do e-mail,
para ela não voltar por uma nova importação. Texto de candidato é sempre tratado como dado.
"""

import hashlib
import re
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from threading import RLock

from backend.contratos.modelos import Candidato, EstadoBanco

POR_PAGINA = 20
ESTADOS_BUSCAVEIS = frozenset({EstadoBanco.ATIVO, EstadoBanco.DESATUALIZADO})
ATRIBUTOS_PESQUISAVEIS = frozenset(
    {
        "area",
        "cargo",
        "certificacao",
        "certificacoes",
        "competencia",
        "competencias",
        "ferramentas",
        "formacao",
        "habilidade",
        "habilidades",
        "linguagem",
        "linguagens",
        "senioridade",
        "skill",
        "skills",
        "stack",
        "tecnologia",
        "tecnologias",
    }
)
"""Só estes atributos entram na busca. Sensível, contato ou campo novo ficam de fora por padrão."""

_SUFIXOS_DE_GENERO = (("doras", "dores"), ("dora", "dor"), ("eiras", "eiros"), ("eira", "eiro"))
_MENOR_PALAVRA_COM_SUFIXO = 6
_MASCULINOS_EM_OR = (
    "assessor auditor autor consultor diretor doutor editor gestor inspetor instrutor mentor "
    "professor redator revisor supervisor tutor"
).split()
_MASCULINOS_EM_O = (
    "arquiteto estagiario estagiário especializado formado graduado pleno tecnico técnico"
).split()
_FEMININOS = {
    **{f"{m}a": m for m in _MASCULINOS_EM_OR},
    **{f"{m}as": f"{m}es" for m in _MASCULINOS_EM_OR},
    **{f"{m[:-1]}a": m for m in _MASCULINOS_EM_O},
    **{f"{m[:-1]}as": f"{m}s" for m in _MASCULINOS_EM_O},
}

PERFIL_POR_ID = "SELECT dados FROM perfis WHERE empresa_id = ? AND candidato_id = ?"
PERFIL_POR_EMAIL = "SELECT dados FROM perfis WHERE empresa_id = ? AND email = ?"

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


def _identidade_segura(
    por_id: Candidato | None, por_email: Candidato | None, email: str | None
) -> bool:
    """Falso quando o id e o e-mail do registro apontam para pessoas que podem ser diferentes."""
    if por_id is None or email is None:
        return True
    if por_email is not None:
        return por_email.id == por_id.id
    return _email(por_id) is None


def sem_genero(palavra: str) -> str:
    """Leva o feminino ao masculino, por lista fechada e pelos sufixos `-dora` e `-eira`.

    Trocar `-a` por `-o` em qualquer palavra não é seguro: misturaria `banco` e `banca`, `for`
    e `fora`. Palavra fora da lista e dos sufixos, como `advogada`, continua diferente.
    """
    if palavra in _FEMININOS:
        return _FEMININOS[palavra]
    if len(palavra) >= _MENOR_PALAVRA_COM_SUFIXO:
        for feminino, masculino in _SUFIXOS_DE_GENERO:
            if palavra.endswith(feminino):
                return palavra.removesuffix(feminino) + masculino
    return palavra


def _termos(texto: str) -> set[str]:
    sem_marcador = re.sub(r"\((?:a|as|o|os)\)", "", texto.casefold())
    return {sem_genero(termo) for termo in re.findall(r"\w+", sem_marcador)}


def _combina(candidato: Candidato, consulta: str) -> bool:
    """Compara palavras inteiras do perfil e de atributos profissionais. O nome fica de fora."""
    atributos = (
        v for k, v in candidato.atributos.items() if k.strip().casefold() in ATRIBUTOS_PESQUISAVEIS
    )
    return _termos(consulta) <= _termos(" ".join([candidato.perfil_texto, *atributos]))


class BancoTalentos:
    """Implementação de `backend.contratos.interfaces.BancoTalentos`."""

    def __init__(
        self,
        caminho: str | Path = ":memory:",
        *,
        hoje: date | Callable[[], date],
        confiar_autorizacao_sintetica: bool = False,
    ) -> None:
        """Em processo de longa duração, `hoje` deve ser uma função, lida a cada operação.

        `confiar_autorizacao_sintetica` serve só a cargas sintéticas de confiança. Sem ele, a
        autorização declarada no registro é ignorada: a pessoa entra como pendente e só autoriza
        por `registrar_autorizacao`.
        """
        self._hoje = hoje
        self._confiar_autorizacao_sintetica = confiar_autorizacao_sintetica
        self._trava = RLock()
        self._conexao = sqlite3.connect(caminho, check_same_thread=False)
        with self._trava, self._conexao:
            self._conexao.execute("PRAGMA secure_delete = ON")
            self._conexao.executescript(ESQUEMA)

    @property
    def hoje(self) -> date:
        """A data da operação. Aceita também o relógio do fluxo, que devolve data e hora."""
        valor = self._hoje() if callable(self._hoje) else self._hoje
        return valor.date() if isinstance(valor, datetime) else valor

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
            perfil = self._perfil(PERFIL_POR_ID, _exigir_empresa(empresa_id), candidato_id)
        if perfil is None:
            raise KeyError(candidato_id)
        return perfil

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

    def _bloqueado(self, empresa_id: str, candidato_id: str, email: str | None) -> bool:
        return any(
            self._conexao.execute(
                "SELECT 1 FROM bloqueios WHERE empresa_id = ? AND resumo = ?",
                (empresa_id, resumo),
            ).fetchone()
            for resumo in _resumos(empresa_id, candidato_id, email)
        )

    def _perfil(self, consulta: str, empresa_id: str, valor: str | None) -> Candidato | None:
        linha = self._conexao.execute(consulta, (empresa_id, valor)).fetchone()
        return Candidato.model_validate_json(linha[0]) if linha else None

    def _importar_um(self, candidato: Candidato) -> Candidato | None:
        empresa_id, email = candidato.empresa_id, _email(candidato)
        if self._bloqueado(empresa_id, candidato.id, email):
            return None

        por_id = self._perfil(PERFIL_POR_ID, empresa_id, candidato.id)
        por_email = self._perfil(PERFIL_POR_EMAIL, empresa_id, email)
        if candidato.opt_out and not _identidade_segura(por_id, por_email, email):
            raise ValueError(f"opt-out não aplicado: identidade em conflito em {candidato.id}")

        atual = por_id or por_email
        if atual is None:
            atual = candidato
            self._conexao.execute(
                "INSERT INTO perfis (empresa_id, candidato_id, email, dados) VALUES (?, ?, ?, ?)",
                (empresa_id, candidato.id, email, candidato.model_dump_json()),
            )
        elif candidato.opt_out and not atual.opt_out:
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
        novo_email = _email(atual.model_copy(update={"atributos": dados}))
        with self._trava:
            if novo_email and self._bloqueado(atual.empresa_id, atual.id, novo_email):
                raise ValueError("e-mail bloqueado por uma remoção anterior")
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
