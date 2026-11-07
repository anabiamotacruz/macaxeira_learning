"""Análise com evidências literais e pré-condições determinísticas (T2.3)."""

import json
import logging
import re
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Evidencia, Vaga
from backend.fontes.consultas import _normalizar, _tem_sensivel
from backend.fontes.funil import CacheAnalise, priorizar
from backend.fontes.prompts import SISTEMA_ANALISE

logger = logging.getLogger(__name__)
Nota = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]


class PropostaAnalise(BaseModel):
    """Modelo interpreta evidências; não recebe controle de ids ou requisitos."""

    model_config = ConfigDict(extra="forbid")
    notas: dict[str, Nota]
    evidencias: list[Evidencia] = Field(max_length=100)
    lacunas: list[StrictStr] = Field(max_length=30)
    pontos_a_aprofundar: list[StrictStr] = Field(max_length=30)


_INSTRUCAO = re.compile(
    r"\b(ignore|desconsidere|revele|obede[çc]a|instrucoes|system prompt)\b|"
    r"nota maxima|maximum score|previous instructions",
    re.IGNORECASE,
)


def _perfil_seguro(candidato: Candidato) -> tuple[str, bool]:
    linhas = []
    suspeita = False
    for linha in re.split(r"(?<=[.!?;])\s+|\n+", candidato.perfil_texto):
        if _INSTRUCAO.search(_normalizar(linha)):
            suspeita = True
            continue
        # O contexto profissional pode conter dados pessoais. Segmentos com
        # critérios sensíveis conhecidos não são usadas para pontuar.
        if _tem_sensivel(linha):
            continue
        linhas.append(linha.replace(candidato.nome, "[nome omitido]"))
    return " ".join(linhas), suspeita


def _registrar(vaga: Vaga, candidato: Candidato, regra: str) -> None:
    logger.info(
        "Análise de perfil registrada",
        extra={"empresa_id": vaga.empresa_id, "vaga_id": vaga.id,
               "candidato_id": candidato.id, "etapa": "analisar_perfil", "regra": regra},
    )


class Analisador:
    """Implementa o contrato Analisador, sem decidir indicação ou contratação.

    Notas propostas ficam entre 0 e 1 e só entram com evidência literal da
    competência. Lacunas são perguntas, nunca descontos calculados pelo código.
    """

    def __init__(
        self, cliente_modelo: ClienteModelo, *, hoje: date | None = None,
        cache: CacheAnalise | None = None, versao_configuracao: str = "analise-v1",
    ) -> None:
        self.cliente = cliente_modelo
        self.hoje = hoje
        self.cache = cache if cache is not None else CacheAnalise(hoje=hoje)
        self.versao = versao_configuracao

    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise:
        if not priorizar(vaga, [candidato], limite=1, hoje=self.hoje):
            _registrar(vaga, candidato, "perfil_nao_elegivel")
            raise ValueError("perfil não é elegível para análise desta vaga")
        anterior = self.cache.obter(vaga, candidato, versao_configuracao=self.versao)
        if anterior is not None:
            _registrar(vaga, candidato, "cache")
            return anterior
        texto, suspeita = _perfil_seguro(candidato)
        if len(texto) > 30000:
            raise ValueError("perfil excede o limite de texto para análise")
        dados = {
            "requisitos": [{"id": r.id, "descricao": r.descricao} for r in vaga.requisitos],
            "competencias": [c.nome for c in vaga.competencias],
            "perfil_texto": texto, "fonte": candidato.fonte,
        }
        # JSON escapa conteúdo e delimitadores; nenhum nome, contato, datas de
        # lacunas ou atributos arbitrários é necessário para interpretar o perfil.
        pedido = json.dumps(dados, ensure_ascii=True).replace("<", "\\u003c")
        usuario = f"<dados_perfil>\n{pedido}\n</dados_perfil>"
        proposta = None
        for _ in range(2):
            _registrar(vaga, candidato, "solicitar_evidencias")
            try:
                resposta = self.cliente.completar(
                    sistema=SISTEMA_ANALISE, usuario=usuario,
                    esquema=PropostaAnalise, etapa="analisar_perfil",
                )
                proposta = PropostaAnalise.model_validate(resposta.model_dump())
                break
            except (RespostaInvalida, ModeloIndisponivel, ValidationError):
                _registrar(vaga, candidato, "resposta_indisponivel_ou_invalida")
        alertas = ["Possível instrução no currículo removida da análise."] if suspeita else []
        criterios = {r.id for r in vaga.requisitos} | {c.nome for c in vaga.competencias}
        evidencias = []
        if proposta is not None:
            for evidencia in proposta.evidencias:
                if (evidencia.criterio in criterios and evidencia.trecho.strip()
                        and evidencia.trecho in texto and evidencia.trecho in candidato.perfil_texto
                        and evidencia.fonte == candidato.fonte):
                    evidencias.append(evidencia)
                else:
                    alertas.append("Afirmação sem trecho, critério ou fonte válida removida.")
        else:
            alertas.append("Modelo indisponível ou resposta inválida: requer revisão humana.")
        comprovados = {e.criterio for e in evidencias}
        competencias = {c.nome for c in vaga.competencias}
        notas = {k: v for k, v in proposta.notas.items()
                 if k in comprovados & competencias} if proposta is not None else {}
        analise = Analise(
            empresa_id=vaga.empresa_id, vaga_id=vaga.id, candidato_id=candidato.id,
            requisitos_ok={r.id: _normalizar(candidato.atributos[r.campo])
                           == _normalizar(r.valor_esperado) for r in vaga.requisitos},
            notas=notas if proposta is not None else {}, evidencias=evidencias,
            lacunas=proposta.lacunas if proposta is not None else [],
            pontos_a_aprofundar=proposta.pontos_a_aprofundar if proposta is not None else [],
            alertas=list(dict.fromkeys(alertas)),
        )
        if proposta is not None:
            self.cache.salvar(vaga, candidato, analise, versao_configuracao=self.versao)
        _registrar(vaga, candidato, "evidencias_validadas" if proposta else "revisao_humana")
        return analise
