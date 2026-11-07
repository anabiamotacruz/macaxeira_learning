"""Revisão independente de evidências, sem decidir indicação (T2.4)."""

import json
import logging
import math
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Evidencia, Vaga
from backend.fontes.analisador import _perfil_seguro
from backend.fontes.consultas import _normalizar
from backend.fontes.funil import priorizar
from backend.fontes.prompts import SISTEMA_REVISAO

logger = logging.getLogger(__name__)


class RessalvaProposta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterio: StrictStr = Field(min_length=1, max_length=500)
    trecho: StrictStr = Field(min_length=1, max_length=30000)
    motivo: StrictStr = Field(min_length=1, max_length=1000)


class PropostaRevisao(BaseModel):
    """O revisor produz sua própria leitura, não recebe a análise original."""

    model_config = ConfigDict(extra="forbid")
    evidencias: list[Evidencia] = Field(max_length=100)
    ressalvas: list[RessalvaProposta] = Field(max_length=30)


def _registrar(vaga: Vaga, candidato: Candidato, regra: str) -> None:
    logger.info(
        "Revisão de perfil registrada",
        extra={"empresa_id": vaga.empresa_id, "vaga_id": vaga.id,
               "candidato_id": candidato.id, "etapa": "revisar_perfil", "regra": regra},
    )


def _evidencia_valida(
    evidencia: Evidencia, criterios: set[str], candidato: Candidato, texto: str
) -> bool:
    return (
        evidencia.criterio in criterios and bool(evidencia.trecho.strip())
        and evidencia.trecho in candidato.perfil_texto and evidencia.trecho in texto
        and evidencia.fonte == candidato.fonte
    )


def _conferir_analise(
    vaga: Vaga, candidato: Candidato, analise: Analise, texto: str
) -> list[str]:
    criterios = {r.id for r in vaga.requisitos} | {c.nome for c in vaga.competencias}
    competencias = {c.nome for c in vaga.competencias}
    ressalvas = []
    validas = set()
    for evidencia in analise.evidencias:
        if _evidencia_valida(evidencia, criterios, candidato, texto):
            validas.add(evidencia.criterio)
        else:
            ressalvas.append("Análise contém evidência sem trecho, critério ou fonte válida.")
    for criterio, nota in analise.notas.items():
        if criterio not in competencias or not math.isfinite(nota) or not 0 <= nota <= 1:
            ressalvas.append("Análise contém nota ou competência inválida: requer revisão humana.")
        elif criterio not in validas:
            ressalvas.append(f"Nota sem evidência verificável para {criterio}.")
    requisitos = {
        r.id: _normalizar(candidato.atributos.get(r.campo, "")) == _normalizar(r.valor_esperado)
        for r in vaga.requisitos
    }
    if analise.requisitos_ok != requisitos:
        ressalvas.append("Resultado de requisitos diverge da verificação determinística.")
    return ressalvas


class Revisor:
    """Devolve cópia da análise com ressalvas e alertas adicionais.

    Notas originais são preservadas para avaliação humana. A ausência de
    evidência independente é inconclusiva, nunca reprovação automática.
    """

    def __init__(self, cliente_modelo: ClienteModelo, *, hoje: date | None = None) -> None:
        self.cliente = cliente_modelo
        self.hoje = hoje

    def revisar(self, vaga: Vaga, candidato: Candidato, analise: Analise) -> Analise:
        if (analise.empresa_id != vaga.empresa_id or candidato.empresa_id != vaga.empresa_id
                or analise.vaga_id != vaga.id or analise.candidato_id != candidato.id):
            _registrar(vaga, candidato, "escopo_invalido")
            raise ValueError("análise e perfil precisam pertencer ao escopo da vaga")
        if not priorizar(vaga, [candidato], limite=1, hoje=self.hoje):
            _registrar(vaga, candidato, "perfil_nao_elegivel")
            raise ValueError("perfil não é elegível para revisão desta vaga")
        texto, suspeita = _perfil_seguro(candidato)
        if len(texto) > 30000:
            raise ValueError("perfil excede o limite de texto para revisão")
        dados = {
            "requisitos": [{"id": r.id, "descricao": r.descricao} for r in vaga.requisitos],
            "competencias": [c.nome for c in vaga.competencias],
            "perfil_texto": texto, "fonte": candidato.fonte,
        }
        pedido = json.dumps(dados, ensure_ascii=True).replace("<", "\\u003c")
        proposta = None
        for _ in range(2):
            _registrar(vaga, candidato, "solicitar_revisao_independente")
            try:
                resposta = self.cliente.completar(
                    sistema=SISTEMA_REVISAO, usuario=f"<dados_revisao>\n{pedido}\n</dados_revisao>",
                    esquema=PropostaRevisao, etapa="revisar_perfil",
                )
                proposta = PropostaRevisao.model_validate(resposta.model_dump())
                break
            except (RespostaInvalida, ModeloIndisponivel, ValidationError):
                _registrar(vaga, candidato, "resposta_indisponivel_ou_invalida")
        ressalvas = _conferir_analise(vaga, candidato, analise, texto)
        criterios = {r.id for r in vaga.requisitos} | {c.nome for c in vaga.competencias}
        independentes = set()
        if proposta is None:
            ressalvas.append("Revisão indisponível ou inválida: requer revisão humana.")
        else:
            for evidencia in proposta.evidencias:
                if _evidencia_valida(evidencia, criterios, candidato, texto):
                    independentes.add(evidencia.criterio)
                else:
                    ressalvas.append("Evidência independente inválida: requer revisão humana.")
            for ressalva in proposta.ressalvas:
                if (ressalva.criterio in criterios and ressalva.trecho.strip()
                        and ressalva.motivo.strip() and ressalva.trecho in texto
                        and ressalva.trecho in candidato.perfil_texto):
                    ressalvas.append(
                        f"{ressalva.criterio}: {ressalva.motivo} Trecho: {ressalva.trecho}"
                    )
                else:
                    ressalvas.append("Ressalva independente inválida: requer revisão humana.")
            for criterio in sorted(set(analise.notas) - independentes):
                ressalvas.append(
                    f"Revisão inconclusiva para {criterio}: falta evidência independente."
                )
        resultado = analise.model_copy(deep=True)
        resultado.ressalvas_revisor = list(dict.fromkeys([
            *analise.ressalvas_revisor, *ressalvas,
        ]))
        if suspeita:
            resultado.alertas = list(dict.fromkeys([
                *resultado.alertas, "Possível instrução no currículo removida da revisão.",
            ]))
        _registrar(
            vaga, candidato, "com_ressalvas" if resultado.ressalvas_revisor else "sem_ressalvas"
        )
        return resultado
