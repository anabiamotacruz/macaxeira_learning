"""Lista de supressão e link de exclusão (T3.10).

Quem pede para sair vira um conjunto de hashes por empresa, consultado antes de
cada contato (#50, seção 5; FR-C020). A lista não guarda e-mail, telefone nem
perfil, só o HMAC de cada identidade normalizada. O link de exclusão funciona em
um clique, sem login, e não leva dados pessoais na URL.
"""

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

BASE_EXCLUSAO = "https://contato.simulado.local/sair"
_SO_TELEFONE = re.compile(r"^[\d\s()+.-]+$")
_ESQUEMA = re.compile(r"^https?://")


def normalizar_identidade(valor: str) -> str:
    """Põe e-mail, telefone ou URL de perfil numa forma única antes do hash."""
    texto = valor.strip().lower()
    if not texto:
        return ""
    if _SO_TELEFONE.match(texto):
        return re.sub(r"\D", "", texto)
    texto = _ESQUEMA.sub("", texto)
    texto = texto.removeprefix("www.")
    return texto.rstrip("/")


@dataclass(frozen=True)
class PedidoExclusao:
    """Pedido aplicado por um link de exclusão. Não contém dados pessoais."""

    empresa_id: str
    candidato_id: str
    aplicado_em: datetime


@dataclass
class _LinkPendente:
    empresa_id: str
    candidato_id: str
    hashes: frozenset[str]
    pedido: PedidoExclusao | None = None


class ListaSupressao:
    """Lista de supressão em memória, isolada por empresa.

    O `segredo` assina os hashes e os tokens. Ele vem da configuração e nunca é
    gravado nem impresso. Sem ele, um hash de e-mail seria reversível por dicionário.
    """

    def __init__(self, segredo: bytes) -> None:
        if not segredo:
            raise ValueError("a lista de supressão precisa de um segredo")
        self._segredo = segredo
        self._hashes: dict[str, set[str]] = {}
        self._links: dict[str, _LinkPendente] = {}

    def _hash(self, empresa_id: str, identidade: str) -> str:
        mensagem = f"{empresa_id}\x00{identidade}".encode()
        return hmac.new(self._segredo, mensagem, hashlib.sha256).hexdigest()

    def _hashes_de(self, empresa_id: str, identidades: list[str]) -> set[str]:
        normalizadas = {normalizar_identidade(i) for i in identidades}
        return {self._hash(empresa_id, n) for n in normalizadas if n}

    def suprimir(self, empresa_id: str, identidades: list[str]) -> None:
        """Bloqueia as identidades para todas as vagas da empresa. É idempotente."""
        novos = self._hashes_de(empresa_id, identidades)
        if not novos:
            return
        self._hashes.setdefault(empresa_id, set()).update(novos)
        logger.info("supressão registrada: empresa=%s identidades=%d", empresa_id, len(novos))

    def esta_suprimido(self, empresa_id: str, identidades: list[str]) -> bool:
        """Verdadeiro se qualquer uma das identidades está na lista da empresa."""
        bloqueados = self._hashes.get(empresa_id, set())
        return not bloqueados.isdisjoint(self._hashes_de(empresa_id, identidades))

    def hashes(self, empresa_id: str) -> list[str]:
        return sorted(self._hashes.get(empresa_id, set()))

    def link_exclusao(self, empresa_id: str, candidato_id: str, identidades: list[str]) -> str:
        """Gera o link de exclusão do candidato, sempre o mesmo para a mesma pessoa."""
        hashes = self._hashes_de(empresa_id, identidades)
        if not hashes:
            raise ValueError("o link de exclusão precisa de ao menos uma identidade")
        token = self._token(empresa_id, candidato_id)
        pendente = self._links.get(token)
        if pendente is None:
            self._links[token] = _LinkPendente(empresa_id, candidato_id, frozenset(hashes))
        else:
            pendente.hashes = pendente.hashes | hashes
        return f"{BASE_EXCLUSAO}/{token}"

    def _token(self, empresa_id: str, candidato_id: str) -> str:
        mensagem = f"exclusao\x00{empresa_id}\x00{candidato_id}".encode()
        return hmac.new(self._segredo, mensagem, hashlib.sha256).hexdigest()[:32]

    def aplicar_exclusao(self, token: str) -> PedidoExclusao | None:
        """Aplica o clique no link. Devolve o pedido, ou None se o token não existe.

        Quem chama usa o pedido para apagar os dados do candidato (FR-C020).
        """
        pendente = self._links.get(token)
        if pendente is None:
            logger.warning("link de exclusão desconhecido")
            return None
        if pendente.pedido is None:
            self._hashes.setdefault(pendente.empresa_id, set()).update(pendente.hashes)
            pendente.pedido = PedidoExclusao(
                pendente.empresa_id, pendente.candidato_id, datetime.now(UTC)
            )
            logger.info(
                "exclusão aplicada: empresa=%s candidato=%s",
                pendente.empresa_id,
                pendente.candidato_id,
            )
        return pendente.pedido

    @staticmethod
    def cabecalhos_exclusao(link: str) -> dict[str, str]:
        """Cabeçalhos de saída em um clique (RFC 8058) para o e-mail."""
        return {
            "List-Unsubscribe": f"<{link}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
