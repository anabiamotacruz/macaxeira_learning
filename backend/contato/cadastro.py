"""Autorização para o banco de talentos e atualização por conversa (T3.4).

O pedido de autorização é uma mensagem fixa, sem perguntas sobre o perfil. A
resposta é tratada em código: saída remove do banco e deixa só o hash na lista
de supressão; autorização ganha validade; e só quem tem autorização válida tem o
perfil atualizado pela conversa. O modelo só classifica respostas livres e extrai
os campos, e o código confere cada campo e cada valor.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel

from backend.contato.conversa import classificar_resposta, contem_instrucao, pede_saida
from backend.contato.mensageiro import chave_convite
from backend.contato.pacote import CRITERIOS_SENSIVEIS
from backend.contato.prompts import (
    PALAVRA_SAIDA,
    SISTEMA_ATUALIZACAO,
    montar_pedido_classificacao,
)
from backend.contato.supressao import ListaSupressao
from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import BancoTalentos, ClienteModelo
from backend.contratos.modelos import Candidato, Convite, TipoConvite, TipoResposta

logger = logging.getLogger(__name__)

ETAPA_ATUALIZACAO = "extrair_atualizacao"
VALIDADE_PADRAO = timedelta(days=365)
ESCOPO_BANCO = "banco"
LIMITE_TEXTO = 2000
LIMITE_VALOR = 200

CAMPOS_ATUALIZAVEIS = frozenset(
    {
        "cargo_atual",
        "empresa_atual",
        "cidade",
        "modalidade",
        "disponibilidade",
        "pretensao_salarial",
        "senioridade",
        "competencias",
    }
)

_PALAVRAS_AUTORIZO = {"sim", "autorizo", "pode", "aceito", "claro", "ok", "s", "quero"}
_GATILHO_AUTORIZO = {"sim", "autorizo", "aceito", "pode", "ok", "s"}


class AcaoCadastro(StrEnum):
    AUTORIZOU = "autorizou"
    ATUALIZOU = "atualizou"
    REMOVIDO = "removido"
    SEM_MUDANCA = "sem_mudanca"


@dataclass(frozen=True)
class ResultadoCadastro:
    acao: AcaoCadastro
    candidato: Candidato | None


class CampoExtraido(BaseModel):
    campo: str
    valor: str


class AtualizacaoExtraida(BaseModel):
    """Saída esperada do modelo na etapa `extrair_atualizacao`."""

    campos: list[CampoExtraido]


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


# Pedido


def pedir_autorizacao(
    candidato: Candidato,
    *,
    nome_empresa: str,
    link_exclusao: str | None = None,
    canal: str = "simulado",
    tentativa: int = 1,
) -> Convite:
    """Pedido de autorização para o banco de talentos, sem perguntas sobre o perfil."""
    if candidato.opt_out:
        raise ValueError("quem pediu para sair não recebe pedido de autorização")
    saida = f"Para não receber mais mensagens, responda {PALAVRA_SAIDA}"
    saida += f" ou use este link: {link_exclusao}." if link_exclusao else "."
    mensagem = (
        f"Olá, {candidato.nome}! A {nome_empresa} gostaria de guardar seu perfil profissional "
        "no banco de talentos dela, para te avisar de vagas compatíveis. Você autoriza? "
        "Se sim, responda SIM: a autorização vale por 12 meses e pode ser retirada quando "
        f"quiser. {saida} Mensagem simulada."
    )
    chave = chave_convite(
        candidato.empresa_id, ESCOPO_BANCO, candidato.id, TipoConvite.AUTORIZACAO, tentativa
    )
    return Convite(
        id=chave,
        empresa_id=candidato.empresa_id,
        tipo=TipoConvite.AUTORIZACAO,
        canal=canal,
        vaga_id=None,
        candidato_id=candidato.id,
        mensagem=mensagem,
        link_agendamento=None,
        chave_idempotencia=chave,
        simulado=True,
    )


# Resposta


def _autorizacao_valida(candidato: Candidato, hoje: date) -> bool:
    return (
        candidato.autorizou_contato
        and candidato.autorizacao_valida_ate is not None
        and candidato.autorizacao_valida_ate >= hoje
    )


def _autorizou(texto: str, cliente_modelo: ClienteModelo, convite_id: str) -> bool:
    palavras = set(re.sub(r"[^\w ]", " ", _normalizar(texto)).split())
    if palavras and len(palavras) <= 4 and palavras & _GATILHO_AUTORIZO:
        if palavras <= _PALAVRAS_AUTORIZO:
            return True
    resposta = classificar_resposta(texto, cliente_modelo, convite_id=convite_id)
    return resposta.tipo == TipoResposta.ACEITE


def tratar_resposta_cadastro(
    candidato: Candidato,
    texto: str,
    banco: BancoTalentos,
    cliente_modelo: ClienteModelo,
    *,
    hoje: date,
    lista: ListaSupressao,
    identidades: list[str],
    validade: timedelta = VALIDADE_PADRAO,
) -> ResultadoCadastro:
    """Trata uma mensagem da pessoa sobre o banco de talentos.

    `identidades` são os contatos da pessoa (e-mail, telefone), que viram hash na
    lista de supressão se ela pedir para sair.
    """
    empresa_id = candidato.empresa_id
    if pede_saida(texto):
        lista.suprimir(empresa_id, identidades)
        banco.remover(empresa_id, candidato.id)
        logger.info("saída do banco: empresa=%s candidato=%s", empresa_id, candidato.id)
        return ResultadoCadastro(AcaoCadastro.REMOVIDO, None)

    if not _autorizacao_valida(candidato, hoje):
        convite_id = chave_convite(
            empresa_id, ESCOPO_BANCO, candidato.id, TipoConvite.AUTORIZACAO, 1
        )
        if not _autorizou(texto, cliente_modelo, convite_id):
            return ResultadoCadastro(AcaoCadastro.SEM_MUDANCA, candidato)
        autorizado = banco.registrar_autorizacao(empresa_id, candidato.id, hoje + validade)
        logger.info("autorização registrada: empresa=%s candidato=%s", empresa_id, candidato.id)
        return ResultadoCadastro(AcaoCadastro.AUTORIZOU, autorizado)

    dados = extrair_atualizacao(texto, cliente_modelo)
    if not dados:
        return ResultadoCadastro(AcaoCadastro.SEM_MUDANCA, candidato)
    atualizado = banco.atualizar(empresa_id, candidato.id, dados)
    logger.info("perfil atualizado: candidato=%s campos=%s", candidato.id, sorted(dados))
    return ResultadoCadastro(AcaoCadastro.ATUALIZOU, atualizado)


# Extração


def extrair_atualizacao(texto: str, cliente_modelo: ClienteModelo) -> dict[str, str]:
    """Campos de perfil citados pela pessoa. Cada valor precisa estar no texto."""
    if contem_instrucao(texto):
        logger.warning("alerta: instrução na mensagem de atualização, nada foi extraído")
        return {}
    texto = texto[:LIMITE_TEXTO]
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_ATUALIZACAO,
            montar_pedido_classificacao(texto),
            AtualizacaoExtraida,
            ETAPA_ATUALIZACAO,
        )
        extraida = AtualizacaoExtraida.model_validate(resposta.model_dump())
    except (ModeloIndisponivel, RespostaInvalida) as erro:
        logger.warning("atualização não extraída: %s", erro)
        return {}

    normalizado = _normalizar(texto)
    dados: dict[str, str] = {}
    for item in extraida.campos:
        campo = _normalizar(item.campo)
        valor = item.valor.strip()
        if campo not in CAMPOS_ATUALIZAVEIS or campo in CRITERIOS_SENSIVEIS:
            continue
        if not valor or len(valor) > LIMITE_VALOR or _normalizar(valor) not in normalizado:
            logger.warning("campo %s descartado: valor fora do texto", campo)
            continue
        dados[campo] = valor
    return dados


# Candidato do hunting


def incluir_no_banco(
    banco: BancoTalentos,
    candidato: Candidato,
    *,
    autorizou: bool,
    hoje: date,
    validade: timedelta = VALIDADE_PADRAO,
) -> Candidato:
    """Põe no banco um candidato do hunting, só com autorização explícita (FR-C021)."""
    if not autorizou:
        raise ValueError("candidato do hunting só entra no banco se autorizar")
    importados = banco.importar(
        candidato.empresa_id,
        [
            {
                "id": candidato.id,
                "nome": candidato.nome,
                "perfil_texto": candidato.perfil_texto,
                "origem": candidato.origem,
            }
        ],
    )
    if not importados:
        raise ValueError("candidato removido não volta ao banco")
    return banco.registrar_autorizacao(candidato.empresa_id, candidato.id, hoje + validade)
