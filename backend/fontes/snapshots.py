"""Snapshots de perfil com validade, isolados por empresa (#50, seção 6).

Cada coleta grava uma versão do perfil com `versao_esquema`, os hashes das fontes
e um hash canônico do conteúdo. O histórico fica: vencer não é apagar, e só
`apagar` remove o que a pessoa pediu para remover.

Gravar de novo o mesmo conteúdo, com as mesmas fontes e a mesma versão de esquema,
não cria versão nova. É o que permite a caça incremental: perfis já conhecidos e
inalterados não são reprocessados nem pagos de novo ao provedor externo.

O conteúdo do perfil é dado, nunca instrução, e nunca entra em log.
"""

import hashlib
import json
import logging
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)

VALIDADE_PADRAO = timedelta(days=30)
"""Prazo de validade de um snapshot.

Trinta dias é o prazo da regra de atualidade da seção 6 de #50. Passado ele, o
perfil não conta como atual e a coleta precisa confirmá-lo antes do contato.
"""

_SEM_LIMITE = -1

_COLUNAS = (
    "empresa_id, candidato_id, versao_esquema, coletado_em, valido_ate, "
    "hash_conteudo, hashes_fontes, conteudo, simulado"
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ordem INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id TEXT NOT NULL,
    candidato_id TEXT NOT NULL,
    versao_esquema TEXT NOT NULL,
    coletado_em TEXT NOT NULL,
    valido_ate TEXT NOT NULL,
    hash_conteudo TEXT NOT NULL,
    hashes_fontes TEXT NOT NULL,
    conteudo TEXT NOT NULL,
    simulado INTEGER NOT NULL,
    UNIQUE (empresa_id, candidato_id, versao_esquema, hash_conteudo, hashes_fontes, simulado)
);

CREATE INDEX IF NOT EXISTS snapshots_por_candidato
    ON snapshots (empresa_id, candidato_id, coletado_em);
"""


@dataclass(frozen=True)
class Snapshot:
    """Uma versão do perfil, com a validade e a procedência dela."""

    empresa_id: str
    candidato_id: str
    versao_esquema: str
    coletado_em: date
    valido_ate: date
    hash_conteudo: str
    hashes_fontes: dict[str, str]
    conteudo: dict[str, object]
    simulado: bool

    def esta_valido(self, hoje: date) -> bool:
        """Vale até o dia de `valido_ate`, inclusive."""
        return hoje <= self.valido_ate


def _canonico(valor: object) -> str:
    return json.dumps(valor, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _exigir_texto(valor: str, campo: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{campo} é obrigatório em toda leitura e escrita")
    return valor.strip()


def _exigir_data(valor: date, campo: str) -> date:
    if not isinstance(valor, date) or isinstance(valor, datetime):
        raise ValueError(f"{campo} precisa ser uma data sem hora, para o resultado ser estável")
    return valor


def _conteudo_canonico(conteudo: Mapping[str, object]) -> str:
    if not isinstance(conteudo, Mapping) or any(not isinstance(c, str) for c in conteudo):
        raise ValueError("conteudo precisa ser um mapa com chaves de texto")
    try:
        return _canonico(dict(conteudo))
    except (TypeError, ValueError) as erro:
        raise ValueError("conteudo do snapshot precisa ser serializável em JSON") from erro


def _fontes_canonicas(fontes: Mapping[str, str]) -> str:
    if not isinstance(fontes, Mapping):
        raise ValueError("fontes precisa ser um mapa de nome da fonte para hash")
    if any(not isinstance(nome, str) or not isinstance(h, str) for nome, h in fontes.items()):
        raise ValueError("cada fonte precisa de nome e hash em texto")
    return _canonico(dict(fontes))


def _snapshot_da_linha(linha: tuple) -> Snapshot:
    return Snapshot(
        empresa_id=linha[0],
        candidato_id=linha[1],
        versao_esquema=linha[2],
        coletado_em=date.fromisoformat(linha[3]),
        valido_ate=date.fromisoformat(linha[4]),
        hash_conteudo=linha[5],
        hashes_fontes=json.loads(linha[6]),
        conteudo=json.loads(linha[7]),
        simulado=bool(linha[8]),
    )


class BancoSnapshots:
    """Histórico de versões do perfil em SQLite, escopado por empresa."""

    def __init__(self, caminho: str | Path = ":memory:") -> None:
        self._trava = RLock()
        self._conexao = sqlite3.connect(caminho, check_same_thread=False)
        with self._trava, self._conexao:
            self._conexao.execute("PRAGMA secure_delete = ON")
            self._conexao.executescript(ESQUEMA)

    def fechar(self) -> None:
        with self._trava:
            self._conexao.close()

    def gravar(
        self,
        empresa_id: str,
        candidato_id: str,
        conteudo: Mapping[str, object],
        *,
        fontes: Mapping[str, str],
        coletado_em: date,
        versao_esquema: str,
        simulado: bool,
        validade: timedelta = VALIDADE_PADRAO,
    ) -> Snapshot:
        """Grava uma versão do perfil, ou devolve a que já existia.

        Mesmo conteúdo, mesmas fontes, mesma versão de esquema e mesma procedência
        são a mesma versão. Uma coleta posterior que confirme esse conteúdo renova
        a validade da versão existente, em vez de duplicá-la.

        Grava tudo ou nada: a falha no meio deixa o banco como estava.
        """
        empresa_id = _exigir_texto(empresa_id, "empresa_id")
        candidato_id = _exigir_texto(candidato_id, "candidato_id")
        versao_esquema = _exigir_texto(versao_esquema, "versao_esquema")
        coletado_em = _exigir_data(coletado_em, "coletado_em")
        if not isinstance(validade, timedelta) or validade < timedelta(0):
            raise ValueError("validade precisa ser um prazo não negativo")
        if not isinstance(simulado, bool):
            raise ValueError("simulado precisa dizer se o dado é real ou simulação")

        texto_conteudo = _conteudo_canonico(conteudo)
        texto_fontes = _fontes_canonicas(fontes)
        hash_conteudo = hashlib.sha256(texto_conteudo.encode()).hexdigest()
        valido_ate = coletado_em + validade
        valores = (
            empresa_id, candidato_id, versao_esquema, coletado_em.isoformat(),
            valido_ate.isoformat(), hash_conteudo, texto_fontes, texto_conteudo, int(simulado),
        )

        with self._trava, self._conexao:
            existente = self._conexao.execute(
                "SELECT ordem, coletado_em FROM snapshots "
                "WHERE empresa_id = ? AND candidato_id = ? AND versao_esquema = ? "
                "AND hash_conteudo = ? AND hashes_fontes = ? AND simulado = ?",
                (empresa_id, candidato_id, versao_esquema, hash_conteudo, texto_fontes,
                 int(simulado)),
            ).fetchone()
            if existente is None:
                ordem = self._conexao.execute(
                    f"INSERT INTO snapshots ({_COLUNAS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    valores,
                ).lastrowid
                regra = "versao_nova"
            else:
                ordem, anterior = existente
                regra = "conteudo_identico"
                if coletado_em > date.fromisoformat(anterior):
                    self._conexao.execute(
                        "UPDATE snapshots SET coletado_em = ?, valido_ate = ? WHERE ordem = ?",
                        (coletado_em.isoformat(), valido_ate.isoformat(), ordem),
                    )
                    regra = "validade_renovada"
            gravado = _snapshot_da_linha(self._linha(ordem))

        logger.info(
            "Snapshot gravado",
            extra={
                "empresa_id": empresa_id,
                "candidato_id": candidato_id,
                "etapa": "gravar_snapshot",
                "regra": regra,
                "quantidade": 1,
                "simulado": simulado,
            },
        )
        return gravado

    def _linha(self, ordem: int) -> tuple:
        return self._conexao.execute(
            f"SELECT {_COLUNAS} FROM snapshots WHERE ordem = ?", (ordem,)
        ).fetchone()

    def _versoes(
        self, empresa_id: str, candidato_id: str, limite: int = _SEM_LIMITE
    ) -> list[Snapshot]:
        empresa_id = _exigir_texto(empresa_id, "empresa_id")
        candidato_id = _exigir_texto(candidato_id, "candidato_id")
        with self._trava, closing(self._conexao.cursor()) as cursor:
            linhas = cursor.execute(
                f"SELECT {_COLUNAS} FROM snapshots WHERE empresa_id = ? AND candidato_id = ? "
                "ORDER BY coletado_em DESC, ordem DESC LIMIT ?",
                (empresa_id, candidato_id, limite),
            ).fetchall()
        return [_snapshot_da_linha(linha) for linha in linhas]

    def atual(self, empresa_id: str, candidato_id: str, *, hoje: date) -> Snapshot | None:
        """A versão mais nova do perfil, se ainda estiver dentro da validade.

        Versão vencida não é substituída por uma anterior: o perfil deixa de estar
        atual e a coleta precisa confirmá-lo antes do primeiro contato.
        """
        hoje = _exigir_data(hoje, "hoje")
        versoes = self._versoes(empresa_id, candidato_id, limite=1)
        if not versoes or not versoes[0].esta_valido(hoje):
            return None
        return versoes[0]

    def esta_atual(self, empresa_id: str, candidato_id: str, *, hoje: date) -> bool:
        return self.atual(empresa_id, candidato_id, hoje=hoje) is not None

    def historico(self, empresa_id: str, candidato_id: str) -> list[Snapshot]:
        """Todas as versões, da mais nova para a mais antiga, inclusive as vencidas."""
        return self._versoes(empresa_id, candidato_id)

    def apagar(self, empresa_id: str, candidato_id: str) -> int:
        """Apaga todas as versões da pessoa nesta empresa e diz quantas saíram.

        Atende o direito de eliminação da LGPD. O bloqueio de quem pediu para sair
        continua valendo na lista de supressão, que não vive aqui.
        """
        empresa_id = _exigir_texto(empresa_id, "empresa_id")
        candidato_id = _exigir_texto(candidato_id, "candidato_id")
        with self._trava, self._conexao:
            apagados = self._conexao.execute(
                "DELETE FROM snapshots WHERE empresa_id = ? AND candidato_id = ?",
                (empresa_id, candidato_id),
            ).rowcount
        logger.info(
            "Snapshots apagados",
            extra={
                "empresa_id": empresa_id,
                "candidato_id": candidato_id,
                "etapa": "apagar_snapshots",
                "regra": "direito_de_eliminacao",
                "quantidade": apagados,
            },
        )
        return apagados
