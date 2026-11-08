"""Recontato de quem está no banco de talentos (T3.6; spec 002, história 7; FR-C024).

Quando surge uma vaga, o agente olha o banco antes do hunting e pode chamar de novo
quem autorizou. A decisão é determinística: no máximo um contato a cada 90 dias,
só com autorização válida e nunca para quem recusou, saiu ou está na lista de
supressão. O modelo só redige a abertura, a partir do motivo dado pelo código.

`RegistroContato` é um tipo local até o `Contato` do #50 entrar nos contratos (#9).
"""

import logging
import re
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from backend.contato.conversa import contem_instrucao
from backend.contato.mensageiro import chave_convite
from backend.contato.prompts import (
    AVISO_SIMULACAO,
    MARCADOR_NOME,
    PALAVRA_SAIDA,
    SISTEMA_RECONTATO,
    montar_pedido_recontato,
)
from backend.contato.supressao import ListaSupressao
from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import (
    Candidato,
    Convite,
    EstadoBanco,
    TipoConvite,
    TipoResposta,
    Vaga,
)

logger = logging.getLogger(__name__)

ETAPA_RECONTATO = "redigir_recontato"
INTERVALO_RECONTATO = timedelta(days=90)
LIMITE_MENSAGEM = 800
_MARCADOR = re.compile(r"\{[^}]*\}")
_ENDERECO = re.compile(r"https?://|www\.|@")


class RegistroContato(BaseModel):
    """Um contato já feito com a pessoa e a resposta dela, se houve."""

    model_config = ConfigDict(extra="forbid")

    empresa_id: str
    candidato_id: str
    momento: date
    resposta: TipoResposta | None = None


class RedacaoRecontato(BaseModel):
    """Saída esperada do modelo na etapa `redigir_recontato`."""

    mensagem: str


# Decisão


def bloqueio_recontato(
    candidato: Candidato,
    historico: list[RegistroContato],
    hoje: date,
    *,
    lista: ListaSupressao | None = None,
    identidades: list[str] | None = None,
    intervalo: timedelta = INTERVALO_RECONTATO,
) -> str | None:
    """Regra que impede o recontato, ou None se ele pode ser feito."""
    if candidato.opt_out:
        return "saiu"
    if candidato.estado != EstadoBanco.ATIVO:
        return "estado"
    if (
        not candidato.autorizou_contato
        or candidato.autorizacao_valida_ate is None
        or candidato.autorizacao_valida_ate < hoje
    ):
        return "sem_autorizacao"
    if lista is not None and lista.esta_suprimido(candidato.empresa_id, identidades or []):
        return "lista_supressao"

    da_pessoa = [
        r
        for r in historico
        if r.empresa_id == candidato.empresa_id and r.candidato_id == candidato.id
    ]
    respostas = {r.resposta for r in da_pessoa}
    if TipoResposta.OPT_OUT in respostas:
        return "saiu"
    if TipoResposta.RECUSA in respostas:
        return "recusou"
    if da_pessoa and hoje - max(r.momento for r in da_pessoa) < intervalo:
        return "intervalo"
    return None


def pode_recontatar(
    candidato: Candidato,
    historico: list[RegistroContato],
    hoje: date,
    **opcoes,
) -> bool:
    regra = bloqueio_recontato(candidato, historico, hoje, **opcoes)
    if regra:
        logger.info("recontato bloqueado: candidato=%s regra=%s", candidato.id, regra)
    return regra is None


# Mensagem


def _motivo_contaminado(motivo: str) -> bool:
    return bool(contem_instrucao(motivo) or _ENDERECO.search(motivo.lower()))


def _abertura_padrao(motivo: str, nome_empresa: str, vaga: Vaga | None) -> str:
    if _motivo_contaminado(motivo):
        logger.warning("alerta: instrução no motivo do recontato, abertura sem o trecho")
        texto = f"Olá, {MARCADOR_NOME}! A {nome_empresa} lembrou de você."
    else:
        texto = (
            f"Olá, {MARCADOR_NOME}! A {nome_empresa} lembrou de você: "
            f"{motivo.strip().rstrip('.')}."
        )
    if vaga is not None and vaga.titulo.lower() not in texto.lower():
        texto += f" A vaga é de {vaga.titulo}."
    return texto


def _problema(mensagem: str, vaga: Vaga | None) -> str | None:
    if not mensagem.strip() or len(mensagem) > LIMITE_MENSAGEM:
        return "vazia ou longa demais"
    if _ENDERECO.search(mensagem.lower()):
        return "com endereço escrito pelo modelo"
    if set(_MARCADOR.findall(mensagem)) - {MARCADOR_NOME}:
        return "com marcador desconhecido"
    if vaga is not None and vaga.titulo.lower() not in mensagem.lower():
        return "sem o título da vaga"
    return None


def _redigir(
    motivo: str, nome_empresa: str, vaga: Vaga | None, cliente_modelo: ClienteModelo
) -> str | None:
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_RECONTATO,
            montar_pedido_recontato(motivo, nome_empresa, vaga),
            RedacaoRecontato,
            ETAPA_RECONTATO,
        )
        mensagem = RedacaoRecontato.model_validate(resposta.model_dump()).mensagem
    except (ModeloIndisponivel, RespostaInvalida) as erro:
        logger.warning("recontato usou a mensagem padrão: %s", erro)
        return None
    problema = _problema(mensagem, vaga)
    if problema:
        logger.warning("recontato usou a mensagem padrão: redação %s", problema)
        return None
    return mensagem.strip()


def montar_recontato(
    candidato: Candidato,
    motivo: str,
    cliente_modelo: ClienteModelo,
    *,
    nome_empresa: str,
    link_exclusao: str,
    hoje: date,
    vaga: Vaga | None = None,
    personalizar: bool = True,
    canal: str = "email",
) -> Convite:
    """Mensagem de recontato. Quem decide se pode enviar é `pode_recontatar`.

    `motivo` vem do código (por exemplo, do casamento da vaga com o perfil) e diz
    por que a pessoa foi lembrada. Com `vaga`, o convite é da vaga; sem ela, é para
    manter o banco atual.
    """
    regra = bloqueio_recontato(candidato, [], hoje)
    if regra:
        raise ValueError(f"recontato não permitido: {regra}")
    if vaga is not None and vaga.empresa_id != candidato.empresa_id:
        raise ValueError("vaga e candidato precisam ser da mesma empresa")

    abertura = None
    if personalizar:
        abertura = _redigir(motivo, nome_empresa, vaga, cliente_modelo)
    if abertura is None:
        abertura = _abertura_padrao(motivo, nome_empresa, vaga)
    abertura = abertura.replace(MARCADOR_NOME, candidato.nome)

    validade = candidato.autorizacao_valida_ate.strftime("%d/%m/%Y")
    mensagem = "\n\n".join(
        [
            abertura,
            f"Você recebe esta mensagem porque autorizou a {nome_empresa} a guardar seu perfil "
            f"no banco de talentos, com validade até {validade}.",
            f"Para sair do banco e não receber mais contatos, use este link: {link_exclusao}\n"
            f"Você também pode responder {PALAVRA_SAIDA}.",
            AVISO_SIMULACAO,
        ]
    )

    if vaga is not None:
        tipo, escopo = TipoConvite.VAGA, vaga.id
    else:
        tipo, escopo = TipoConvite.AUTORIZACAO, f"recontato-{hoje.isoformat()}"
    chave = chave_convite(candidato.empresa_id, escopo, candidato.id, tipo, 1)
    return Convite(
        id=chave,
        empresa_id=candidato.empresa_id,
        tipo=tipo,
        canal=canal,
        vaga_id=vaga.id if vaga is not None else None,
        candidato_id=candidato.id,
        mensagem=mensagem,
        link_agendamento=None,
        chave_idempotencia=chave,
        simulado=True,
    )
