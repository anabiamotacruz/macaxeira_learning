"""Entrada de novos candidatos por link de cadastro e por indicação (T3.5).

O link de cadastro leva um token assinado com a empresa, a origem e a validade.
Cadastro sem autorização não entra no banco. O indicado recebe só o pedido de
autorização (T3.4) e fica pendente, fora da busca, até autorizar.

A mesma pessoa tem o mesmo id na empresa, venha por cadastro ou por indicação:
o id é um HMAC do contato, sem expor o e-mail. Os contatos ficam num registro
local até o `Candidato` ganhar campo de contato nos contratos (#9).
"""

import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta

from backend.contato.cadastro import CAMPOS_ATUALIZAVEIS, VALIDADE_PADRAO, pedir_autorizacao
from backend.contato.email_inicial import ContatoBloqueado
from backend.contato.pacote import CRITERIOS_SENSIVEIS
from backend.contato.supressao import ListaSupressao, normalizar_identidade
from backend.contratos.interfaces import BancoTalentos
from backend.contratos.modelos import Candidato, Convite

logger = logging.getLogger(__name__)

BASE_CADASTRO = "https://cadastro.simulado.local"
VALIDADE_LINK = timedelta(days=30)
LIMITE_TEXTO = 5000
LIMITE_CAMPO = 200
_ORIGEM = re.compile(r"^[\w-]{1,40}$")
_CONTATOS = ("email", "telefone")


class TokenInvalido(Exception):
    """Token de cadastro adulterado, vencido ou de outra empresa."""


class CadastroRecusado(Exception):
    """Cadastro que não pode entrar no banco. `regra` diz por quê."""

    def __init__(self, regra: str) -> None:
        super().__init__(regra)
        self.regra = regra


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode().rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


class EntradaCandidatos:
    """Links de cadastro, cadastros e indicações de cada empresa."""

    def __init__(
        self,
        segredo: bytes,
        banco: BancoTalentos,
        lista: ListaSupressao,
        *,
        validade_link: timedelta = VALIDADE_LINK,
        validade_autorizacao: timedelta = VALIDADE_PADRAO,
    ) -> None:
        if not segredo:
            raise ValueError("a entrada de candidatos precisa de um segredo")
        self._segredo = segredo
        self.banco = banco
        self.lista = lista
        self.validade_link = validade_link
        self.validade_autorizacao = validade_autorizacao
        self._contatos: dict[tuple[str, str], set[str]] = {}

    # Token

    def _assinar(self, payload: str) -> str:
        return hmac.new(self._segredo, payload.encode(), hashlib.sha256).hexdigest()[:32]

    def gerar_link_cadastro(self, empresa_id: str, origem: str, *, agora: datetime) -> str:
        """Link de cadastro com empresa, origem e validade, assinado."""
        if not empresa_id.strip():
            raise ValueError("empresa_id é obrigatório")
        if not _ORIGEM.match(origem):
            raise ValueError("origem deve ter só letras, números, _ e -")
        expira = int((agora + self.validade_link).timestamp())
        payload = _b64(json.dumps({"e": empresa_id, "o": origem, "x": expira}).encode())
        return f"{BASE_CADASTRO}/{empresa_id}?t={payload}.{self._assinar(payload)}"

    def ler_token(
        self, token: str, *, agora: datetime, empresa_id: str | None = None
    ) -> tuple[str, str]:
        """Confere o token e devolve (empresa_id, origem)."""
        payload, _, assinatura = token.partition(".")
        if not payload or not hmac.compare_digest(assinatura, self._assinar(payload)):
            raise TokenInvalido("token adulterado")
        try:
            dados = json.loads(_de_b64(payload))
            empresa, origem, expira = dados["e"], dados["o"], int(dados["x"])
        except (ValueError, KeyError, TypeError) as erro:
            raise TokenInvalido("token mal formado") from erro
        if agora.timestamp() > expira:
            raise TokenInvalido("token vencido")
        if empresa_id is not None and empresa != empresa_id:
            raise TokenInvalido("token de outra empresa")
        return empresa, origem

    # Pessoa

    def _id_pessoa(self, empresa_id: str, identidade: str) -> str:
        mensagem = f"pessoa\x00{empresa_id}\x00{identidade}".encode()
        return "pessoa-" + hmac.new(self._segredo, mensagem, hashlib.sha256).hexdigest()[:16]

    def contatos(self, empresa_id: str, candidato_id: str) -> list[str]:
        """Contatos que a própria pessoa deu ou que a indicação trouxe."""
        return sorted(self._contatos.get((empresa_id, candidato_id), set()))

    def _guardar_contatos(self, empresa_id: str, candidato_id: str, contatos: list[str]) -> None:
        self._contatos.setdefault((empresa_id, candidato_id), set()).update(contatos)

    # Cadastro

    def registrar_cadastro(
        self,
        token: str,
        dados: dict[str, str],
        autorizacao: bool,
        *,
        agora: datetime,
        empresa_id: str | None = None,
    ) -> Candidato:
        """Põe a pessoa no banco, já autorizada. Sem autorização, nada é guardado."""
        empresa, origem = self.ler_token(token, agora=agora, empresa_id=empresa_id)
        if not autorizacao:
            raise CadastroRecusado("sem_autorizacao")

        nome = dados.get("nome", "").strip()[:LIMITE_CAMPO]
        contatos = [dados[c].strip() for c in _CONTATOS if dados.get(c, "").strip()]
        if not nome or not contatos:
            raise CadastroRecusado("faltam_nome_ou_contato")
        if self.lista.esta_suprimido(empresa, contatos):
            raise CadastroRecusado("lista_supressao")

        candidato_id = self._id_pessoa(empresa, normalizar_identidade(contatos[0]))
        importados = self.banco.importar(
            empresa,
            [
                {
                    "id": candidato_id,
                    "nome": nome,
                    "perfil_texto": dados.get("perfil_texto", "")[:LIMITE_TEXTO],
                    "origem": f"cadastro:{origem}",
                }
            ],
        )
        if not importados:
            raise CadastroRecusado("removido")
        self._guardar_contatos(empresa, candidato_id, contatos)
        hoje = agora.date()
        candidato = self.banco.registrar_autorizacao(
            empresa, candidato_id, hoje + self.validade_autorizacao
        )
        extras = {
            campo: valor.strip()[:LIMITE_CAMPO]
            for campo, valor in dados.items()
            if campo in CAMPOS_ATUALIZAVEIS and campo not in CRITERIOS_SENSIVEIS and valor.strip()
        }
        if extras:
            candidato = self.banco.atualizar(empresa, candidato_id, extras)
        logger.info("cadastro registrado: empresa=%s origem=%s", empresa, origem)
        return candidato

    # Indicação

    def registrar_indicacao(
        self,
        empresa_id: str,
        indicador: str,
        contato: str,
        *,
        nome: str,
        nome_empresa: str,
        agora: datetime,
    ) -> Convite | None:
        """Registra o indicado como pendente e devolve só o pedido de autorização.

        Devolve None se a pessoa já está autorizada no banco.
        """
        identidade = normalizar_identidade(contato)
        if not identidade:
            raise ValueError("a indicação precisa de um contato")
        if self.lista.esta_suprimido(empresa_id, [contato]):
            raise ContatoBloqueado("lista_supressao")
        candidato_id = self._id_pessoa(empresa_id, identidade)
        importados = self.banco.importar(
            empresa_id,
            [{"id": candidato_id, "nome": nome.strip(), "origem": f"indicacao:{indicador}"}],
        )
        if not importados:
            raise ContatoBloqueado("removido")
        [candidato] = importados
        if candidato.autorizou_contato:
            logger.info("indicado já está no banco: empresa=%s", empresa_id)
            return None
        self._guardar_contatos(empresa_id, candidato_id, [contato.strip()])
        link = self.lista.link_exclusao(empresa_id, candidato_id, [contato])
        logger.info("indicação registrada: empresa=%s indicador=%s", empresa_id, indicador)
        return pedir_autorizacao(candidato, nome_empresa=nome_empresa, link_exclusao=link)
