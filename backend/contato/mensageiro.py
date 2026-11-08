"""Convite para a vaga e mensageiro simulado (T3.1).

O modelo redige o convite inteiro a partir dos fits da análise, sem receber o nome
nem atributos da pessoa. O código confere os itens obrigatórios e, se faltar algo
ou o modelo falhar, usa a mensagem padrão, montada sem modelo.
"""

import logging
import re

from pydantic import BaseModel

from backend.contato.prompts import (
    MARCADOR_LINK,
    MARCADOR_NOME,
    PALAVRA_SAIDA,
    SISTEMA_CONVITE,
    montar_pedido_convite,
)
from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Convite, TipoConvite, Vaga

logger = logging.getLogger(__name__)

ETAPA_CONVITE = "redigir_convite"
AVISO_SIMULACAO = "Mensagem simulada, enviada em ambiente de demonstração."
_MARCADOR = re.compile(r"\{[^}]*\}")


class PreferenciasContato(BaseModel):
    """Preferências de contato da empresa. `personalizar=False` dispensa o modelo."""

    personalizar: bool = True
    canal: str = "simulado"


class RedacaoConvite(BaseModel):
    """Saída esperada do modelo na etapa `redigir_convite`."""

    mensagem: str
    criterios_citados: list[str]


def chave_convite(
    empresa_id: str, vaga_id: str, candidato_id: str, tipo: TipoConvite, tentativa: int
) -> str:
    return f"{empresa_id}:{vaga_id}:{candidato_id}:{tipo.value}:{tentativa}"


def _conferir_ids(vaga: Vaga, candidato: Candidato, analise: Analise) -> None:
    if candidato.empresa_id != vaga.empresa_id or analise.empresa_id != vaga.empresa_id:
        raise ValueError("vaga, candidato e análise precisam ser da mesma empresa")
    if analise.vaga_id != vaga.id or analise.candidato_id != candidato.id:
        raise ValueError("a análise não corresponde à vaga e ao candidato")


def _sem_nome(texto: str, nome: str) -> str:
    """Troca o nome da pessoa, inteiro ou por partes, pelo marcador."""
    texto = texto.replace(nome, MARCADOR_NOME)
    for parte in nome.split():
        if len(parte) >= 3:
            texto = re.sub(rf"\b{re.escape(parte)}\b", MARCADOR_NOME, texto)
    return texto


def _fits(analise: Analise, nome: str) -> list[tuple[str, str]]:
    return [
        (evidencia.criterio, _sem_nome(evidencia.trecho, nome))
        for evidencia in analise.evidencias
        if evidencia.trecho.strip()
    ]


def _criterios_atendidos(vaga: Vaga, analise: Analise) -> list[str]:
    """Critérios com evidência ou requisito cumprido, pela descrição e sem repetir."""
    descricoes = {r.id: r.descricao for r in vaga.requisitos}
    ids = [e.criterio for e in analise.evidencias if e.trecho.strip()]
    ids += [rid for rid, ok in analise.requisitos_ok.items() if ok]
    return list(dict.fromkeys(descricoes.get(i, i) for i in ids))


def mensagem_padrao(vaga: Vaga, analise: Analise, tem_link: bool) -> str:
    """Convite determinístico, usado quando a empresa desliga a personalização."""
    criterios = ", ".join(_criterios_atendidos(vaga, analise))
    motivo = f" Seu perfil chamou nossa atenção por: {criterios}." if criterios else ""
    if tem_link:
        proximo = f"Se tiver interesse, agende uma conversa por aqui: {MARCADOR_LINK}."
    else:
        proximo = "Se tiver interesse, responda esta mensagem e a equipe combina a entrevista."
    return (
        f"Olá, {MARCADOR_NOME}! Temos uma vaga de {vaga.titulo}.{motivo} {proximo} "
        f"Se não quiser mais receber mensagens, responda {PALAVRA_SAIDA}."
    )


def rodape(candidato: Candidato) -> str:
    """Origem do contato e aviso de simulação, montados pelo código e nunca pelo modelo."""
    return (
        f"Encontramos seu perfil em: {candidato.fonte} ({candidato.origem}). "
        f"{AVISO_SIMULACAO}"
    )


def _problema_na_redacao(
    redacao: RedacaoConvite, vaga: Vaga, fits: list[tuple[str, str]], tem_link: bool
) -> str | None:
    texto = redacao.mensagem
    if vaga.titulo.lower() not in texto.lower():
        return "sem o título da vaga"
    if PALAVRA_SAIDA not in texto:
        return "sem a forma de sair"
    if tem_link and MARCADOR_LINK not in texto:
        return "sem o link de agendamento"
    if "http" in texto.lower() or "www." in texto.lower():
        return "com endereço escrito pelo modelo"
    permitidos = {MARCADOR_NOME, MARCADOR_LINK} if tem_link else {MARCADOR_NOME}
    if set(_MARCADOR.findall(texto)) - permitidos:
        return "com marcador desconhecido"
    if not set(redacao.criterios_citados) <= {criterio for criterio, _ in fits}:
        return "citando critério sem evidência"
    return None


def _redigir(
    vaga: Vaga, fits: list[tuple[str, str]], tem_link: bool, cliente_modelo: ClienteModelo
) -> str | None:
    """Mensagem do modelo com marcadores, ou None quando ela não pode ser usada."""
    try:
        resposta = cliente_modelo.completar(
            SISTEMA_CONVITE,
            montar_pedido_convite(vaga, fits, tem_link),
            RedacaoConvite,
            ETAPA_CONVITE,
        )
        redacao = RedacaoConvite.model_validate(resposta.model_dump())
    except (ModeloIndisponivel, RespostaInvalida) as erro:
        logger.warning("convite da vaga %s usou a mensagem padrão: %s", vaga.id, erro)
        return None
    problema = _problema_na_redacao(redacao, vaga, fits, tem_link)
    if problema:
        logger.warning("convite da vaga %s usou a mensagem padrão: redação %s", vaga.id, problema)
        return None
    return redacao.mensagem


def criar_convite(
    vaga: Vaga,
    candidato: Candidato,
    analise: Analise,
    link_agendamento: str | None,
    cliente_modelo: ClienteModelo,
    *,
    preferencias: PreferenciasContato | None = None,
    tentativa: int = 1,
) -> Convite:
    """Cria o convite para a vaga. Quem decide se pode contatar é o fluxo (`pode_contatar`)."""
    _conferir_ids(vaga, candidato, analise)
    preferencias = preferencias or PreferenciasContato()
    tem_link = bool(link_agendamento)

    texto = None
    if preferencias.personalizar:
        texto = _redigir(vaga, _fits(analise, candidato.nome), tem_link, cliente_modelo)
    if texto is None:
        texto = mensagem_padrao(vaga, analise, tem_link)

    if link_agendamento:
        texto = texto.replace(MARCADOR_LINK, link_agendamento)
    texto = texto.replace(MARCADOR_NOME, candidato.nome)
    texto = f"{texto} {rodape(candidato)}"

    chave = chave_convite(vaga.empresa_id, vaga.id, candidato.id, TipoConvite.VAGA, tentativa)
    return Convite(
        id=chave,
        empresa_id=vaga.empresa_id,
        tipo=TipoConvite.VAGA,
        canal=preferencias.canal,
        vaga_id=vaga.id,
        candidato_id=candidato.id,
        mensagem=texto,
        link_agendamento=link_agendamento,
        chave_idempotencia=chave,
        simulado=True,
    )


class MensageiroSimulado:
    """Caixa de saída simulada, separada por empresa e idempotente por chave.

    `falhas_restantes` falha antes de enviar; `falhas_apos_envio` envia e mesmo assim
    devolve falha, como uma confirmação perdida. Em ambos os casos repetir é seguro.
    """

    def __init__(self, falhas_restantes: int = 0, falhas_apos_envio: int = 0) -> None:
        self.falhas_restantes = falhas_restantes
        self.falhas_apos_envio = falhas_apos_envio
        self._caixas: dict[str, dict[str, Convite]] = {}

    def _caixa(self, empresa_id: str) -> dict[str, Convite]:
        if not empresa_id or not empresa_id.strip():
            raise ValueError("empresa_id é obrigatório em toda leitura e escrita")
        return self._caixas.setdefault(empresa_id, {})

    def enviar(self, convite: Convite) -> bool:
        if not convite.simulado:
            raise ValueError("não há canal real: o mensageiro só envia convites simulados")
        caixa = self._caixa(convite.empresa_id)
        if convite.chave_idempotencia in caixa:
            return True
        if self.falhas_restantes > 0:
            self.falhas_restantes -= 1
            return False
        caixa[convite.chave_idempotencia] = convite
        if self.falhas_apos_envio > 0:
            self.falhas_apos_envio -= 1
            return False
        return True

    def enviados(self, empresa_id: str) -> list[Convite]:
        return list(self._caixa(empresa_id).values())
