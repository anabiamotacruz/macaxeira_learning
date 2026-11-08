"""Analisa um candidato diante da vaga (T2.3). O modelo interpreta; o código confere.

Requisito eliminatório vem de `backend/agente/regras.py`. Do modelo ficam só nota, trecho e
perguntas. Todo trecho precisa ser literal do texto pseudonimizado, mas a nota fica mesmo sem
trecho: como recrutador, o modelo dá nota a toda competência, e a falta de trecho direto já está
na nota. Competência que volta sem nota é pedida de novo, uma vez. Atributos,
histórico e descrição da vaga não são enviados: datas revelam períodos sem trabalho, e o texto
livre da vaga pode citar gênero ou outro tema sensível.
"""

import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, Field

from backend.agente.prompts import como_dado
from backend.agente.regras import (
    StatusRequisito,
    TipoEvidencia,
    avaliar_requisitos,
    classificar_evidencia,
    verificar_requisitos,
)
from backend.contratos.erros import RespostaInvalida
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, EstadoBanco, Evidencia, Vaga
from backend.fontes.anonimizador import (
    PerfilPseudonimizado,
    Pseudonimizador,
    SessaoPseudonimizacao,
    termos_preservados_da_vaga,
)
from backend.fontes.consultas import tem_termo_sensivel
from backend.fontes.prompts import SISTEMA_ANALISE, USUARIO_ANALISE, USUARIO_NOTAS_FALTANTES

logger = logging.getLogger(__name__)

ETAPA_ANALISE = "analise"

ALERTA_INSTRUCAO = (
    "instrucao_no_perfil: o perfil traz texto dirigido ao avaliador; ele foi retirado da análise."
)
"""Texto fixo: o alerta não repete o texto do candidato, que pode ir a outro modelo ou sistema."""

CONFIRMAR_PERFIL_DESATUALIZADO = "Confirmar com a pessoa: perfil desatualizado"
"""A autorização vale e a análise segue: o pacote avisa que o perfil precisa ser confirmado."""

FIM_DE_FRASE = re.compile(r"(?<=[.!?])\s+|\n+")
_RACE_CONDITION = re.compile(r"\brace conditions?\b")

INSTRUCAO = re.compile(
    r"(?<!nao )(?<!sem )"
    r"\b(ignore\w*|ignorar|desconsidere\w*|desconsiderar|esqueca\w*|esquecer|disregard|forget)\b"
    r".{0,60}\b(regras?|instruc\w+|anteriores|previous|instructions?|prompt)\b"
    r"|\b(me de|de me|atribua|conceda|give|assign)\b.{0,30}\b(nota|score)\b"
    r"|\b(revele|mostre|exiba|imprima|reveal|print)\b"
    r".{0,30}\b(chave|api key|segredo|senha|prompt)\b"
    r"|\b(aprove|indique|selecione|contrate)\b"
    r".{0,30}\b(este|esta|me|candidat\w+|perfil|pessoa)\b"
    r"|\b(approve|hire|select|recommend)"
    r" (me|this (candidate|person|profile|resume)|the candidate)\b"
    r"|\b(system prompt|prompt do sistema|voce agora|you are now"
    r"|as an ai (model|assistant|language)|como modelo de ia,)\b"
)
"""Sobre texto sem acento nem caixa. Basta sozinho: quase não aparece em frase de trabalho."""

_QUEM_AVALIA = (
    r"avaliador\w*|recrutador\w*|analista\w*|leitor\w*|revisor\w*"
    r"|recruiter|reviewer|evaluator|screener|reader"
)
_DIRIGIDO_AO_AVALIADOR = re.compile(
    r"\b(prezad[oa]s?|car[oa]s?|ola|atencao|dear|hello|hi|attention)[ ,:]+(o |a |os |as |the )?"
    rf"({_QUEM_AVALIA}|sistema|modelo|ia|assistente|assistant|model|ai|llm|gpt)\b"
    rf"|\b(ao|aos|para o|para a|note to the|to the)[ ,:]+({_QUEM_AVALIA})\b(?! tecnic)"
    r"|\bquem (ler|avaliar|analisar|revisar)\b|\b(whoever|anyone) (reads|reviews)\b"
    r"|\b(classifique|ranqueie|coloque|priorize|recomende|avance|promova|marque|pontue|considere"
    r"|trate|recomendar|classificar|aprovar|indicar|selecionar|contratar|considerar|pontuar"
    r"|rank|rate|recommend|advance|promote|mark|treat|consider|select)\b"
    r".{0,40}\b(este|esta|me|candidat\w+|perfil|pessoa|this|candidate|profile|person)\b"
    r"|\b(est[ea]|this) (perfil|candidat\w+|pessoa|curriculo|profile|person|resume)"
    r" (deve|precisa|merece|tem que|should|must|deserves)\b"
    r"|\b(voce|you) (deve|precisa|tem que|must|should|are)\b"
    r"|\b(atue|aja|finja|comporte-se|pretend|act)\b.{0,20}\b(como|que|as|you|to)\b"
    r"|\b(retorne|responda|devolva|return|respond|output)\b.{0,30}\b(nota|score|aprovad\w*|approved)\b"
)
"""O que confere um apontamento do modelo: fala com quem avalia ou manda no resultado. Sozinho
daria falso alarme em frase de trabalho; junto com o apontamento, não."""

_SENSIVEL_ALEM_DA_LISTA = re.compile(
    r"\b(mae|pai|filh[oa]s?|maternidade|paternidade|nascid[oa]|divorciad[oa]|viuv[oa]|bissexual"
    r"|cadeirante|afrodescendente|tenho \d{1,3} anos(?! (de|em|com|no|na|como|atuando|trabalhando))"
    r"|\d{1,3} years old)\b"
)
"""Completa `tem_termo_sensivel`, feita para consultas, com o que aparece em texto corrido."""

_PERIODO_SEM_TRABALHO = re.compile(
    r"\b(sem (trabalho|trabalhar|emprego|atividade profissional|ocupacao)|desempreg\w+"
    r"|sabatic\w+|hiatos?|gaps?|afastamentos?|afastad[oa]s?|fiquei parad[oa]"
    r"|(pausas?|interrupc\w+|intervalos?|buracos?|lacunas?) "
    r"(na|da|de|no|do|em|entre|sem) "
    r"(carreira|trabalho|emprego|empregos|curriculo|historico|atividade))\b"
)


def normalizar(texto: str) -> str:
    """Sem acento, caixa nem caracteres invisíveis, que serviriam para esconder uma instrução."""
    decomposto = unicodedata.normalize("NFKD", texto)
    visivel = "".join(
        c for c in decomposto if not unicodedata.combining(c) and unicodedata.category(c) != "Cf"
    )
    return " ".join(visivel.casefold().split())


def texto_permitido(texto: str) -> bool:
    """Diz se o texto não fala de dado sensível nem de período sem trabalho."""
    normalizado = _RACE_CONDITION.sub(" ", normalizar(texto))
    return not (
        tem_termo_sensivel(normalizado)
        or _SENSIVEL_ALEM_DA_LISTA.search(normalizado)
        or _PERIODO_SEM_TRABALHO.search(normalizado)
    )


@dataclass(frozen=True)
class PerfilPreparado:
    """O perfil como o modelo pode vê-lo. `texto` ainda não passou por `como_dado`."""

    texto: str
    tem_instrucao: bool
    pseudonimizado: PerfilPseudonimizado = field(repr=False)
    frases_originais: tuple[str, ...] = field(default=(), repr=False)


def preparar_perfil(
    candidato: Candidato,
    retirar: Iterable[str] = (),
    *,
    pseudonimizador: Pseudonimizador,
    preservar: Iterable[str] = (),
) -> PerfilPreparado:
    """O perfil da pessoa como o modelo pode vê-lo. As regras estão em `preparar_texto`."""
    return preparar_texto(pseudonimizador.sessao(candidato, preservar), retirar)


def preparar_texto(sessao: SessaoPseudonimizacao, retirar: Iterable[str] = ()) -> PerfilPreparado:
    """Tira instruções e frases sobre dado sensível ou período sem trabalho, e pseudonimiza o resto.

    Sai a frase inteira, sem alerta quando é dado sensível: mencionar gênero não pode mudar
    o caminho de ninguém. `retirar` traz o que só o modelo apontou, já com marcadores: a frase só
    sai, com alerta, se o próprio texto dela confirma que fala com quem avalia. A opinião do modelo
    sozinha não basta. A instrução é procurada também depois da troca: `Aprove Fulana` só aparece
    como `Aprove [PESSOA]`, e por isso a conferência do apontamento usa o texto pseudonimizado.
    """
    retirados = [normalizar(trecho) for trecho in retirar]
    frases = []
    originais = []
    tem_instrucao = False
    for inicio, fim in _posicoes_das_frases(sessao.fonte):
        frase = sessao.fonte[inicio:fim]
        if INSTRUCAO.search(normalizar(frase)):
            tem_instrucao = True
            continue
        if not texto_permitido(frase):
            continue
        pseudonimizada = sessao.frase(inicio, fim)
        normalizada = normalizar(pseudonimizada.texto)
        apontada = any(trecho in normalizada or normalizada in trecho for trecho in retirados)
        if INSTRUCAO.search(normalizada) or (
            apontada and _DIRIGIDO_AO_AVALIADOR.search(normalizada)
        ):
            tem_instrucao = True
        elif texto_permitido(pseudonimizada.texto):
            frases.append(pseudonimizada)
            originais.append(" ".join(frase.split()))
    perfil = sessao.montar(frases)
    return PerfilPreparado(perfil.texto, tem_instrucao, perfil, tuple(originais))


def _posicoes_das_frases(texto: str) -> Iterable[tuple[int, int]]:
    inicio = 0
    for separador in FIM_DE_FRASE.finditer(texto):
        if texto[inicio : separador.start()].strip():
            yield inicio, separador.start()
        inicio = separador.end()
    if texto[inicio:].strip():
        yield inicio, len(texto)


def como_no_perfil(trecho: str) -> str:
    """Desfaz a troca de `como_dado`, para o trecho voltar a ser literal."""
    return trecho.replace("‹", "<").replace("›", ">")


def trecho_confere(trecho: str, candidato: Candidato, perfil: PerfilPreparado) -> bool:
    """Exige o trecho no texto enviado e o caminho até o original: nada retirado pode ser citado."""
    if perfil.pseudonimizado.na_fonte(trecho) is None:
        return False
    citacao = Evidencia(criterio="", trecho=trecho, fonte=candidato.fonte)
    return classificar_evidencia(citacao, candidato) is not TipoEvidencia.INFERIDA


def criterios_da_vaga(vaga: Vaga) -> dict[str, str]:
    """Id de requisito e nome de competência, indexados como o modelo pode escrevê-los."""
    criterios = {normalizar(r.descricao): r.id for r in vaga.requisitos}
    criterios |= {normalizar(r.id): r.id for r in vaga.requisitos}
    return criterios | {normalizar(c.nome): c.nome for c in vaga.competencias}


def criterio_citado(criterios: dict[str, str], citado: str) -> str | None:
    return criterios.get(normalizar(citado))


def descrever_vaga(vaga: Vaga) -> str:
    """Título e critérios. Peso e descrição ficam de fora."""
    linhas = [f"Título: {vaga.titulo}", "Requisitos (identificador: descrição):"]
    linhas += [f"- {r.id}: {r.descricao}" for r in vaga.requisitos]
    linhas.append("Competências (nome):")
    linhas += [f"- {c.nome}" for c in vaga.competencias]
    return como_dado("\n".join(linhas))


class EvidenciaModelo(BaseModel):
    criterio: str
    trecho: str


Nota = Annotated[float, Field(ge=0, le=1, strict=True, allow_inf_nan=False)]


class RespostaAnalise(BaseModel):
    """O que se aceita do modelo. Qualquer outro campo, como confiança ou fonte, é ignorado."""

    notas: dict[str, Nota | None]
    evidencias: list[EvidenciaModelo]
    lacunas: list[str] = []
    pontos_a_aprofundar: list[str] = []
    instrucoes_detectadas: list[str] = []


def _sem_repetir(textos: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(textos))


class AnalisadorPorModelo:
    """Implementa `Analisador`. Falhas do cliente seguem para o fluxo, que sabe tratá-las."""

    def __init__(
        self, cliente: ClienteModelo, pseudonimizador: Pseudonimizador | None = None
    ) -> None:
        self._cliente = cliente
        self._pseudonimizador = pseudonimizador or Pseudonimizador()

    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise:
        requisitos_ok = verificar_requisitos(vaga, candidato)
        preservar = termos_preservados_da_vaga(vaga)
        perfil = preparar_perfil(
            candidato, pseudonimizador=self._pseudonimizador, preservar=preservar
        )
        resposta = self._perguntar(vaga, perfil)
        apontadas = [
            como_no_perfil(trecho)
            for trecho in resposta.instrucoes_detectadas
            if trecho_confere(como_no_perfil(trecho), candidato, perfil)
        ]
        if apontadas:
            conferido = preparar_perfil(
                candidato, apontadas, pseudonimizador=self._pseudonimizador, preservar=preservar
            )
            if conferido.texto == perfil.texto:
                # Só o id: o trecho é texto do candidato e não vai para o log.
                logger.info("apontamento do modelo sem confirmação no texto: %s", candidato.id)
            else:
                # A nota pode ter sido influenciada: vale a análise do perfil sem a instrução.
                perfil = conferido
                resposta = self._perguntar(vaga, perfil)

        evidencias = self._evidencias(vaga, candidato, perfil, resposta)
        notas = self._notas(vaga, resposta)
        faltantes = [c.nome for c in vaga.competencias if c.nome not in notas]
        if faltantes:
            notas, evidencias = self._completar_notas(
                vaga, candidato, perfil, faltantes, notas, evidencias
            )
        return Analise(
            empresa_id=vaga.empresa_id,
            vaga_id=vaga.id,
            candidato_id=candidato.id,
            requisitos_ok=requisitos_ok,
            notas=notas,
            evidencias=evidencias,
            lacunas=_sem_repetir(
                [
                    *filter(texto_permitido, resposta.lacunas),
                    *self._lacunas(vaga, candidato, evidencias, notas),
                ]
            ),
            pontos_a_aprofundar=_sem_repetir(
                [
                    *filter(texto_permitido, resposta.pontos_a_aprofundar),
                    *self._confirmacoes(vaga, candidato),
                ]
            ),
            alertas=[ALERTA_INSTRUCAO] if perfil.tem_instrucao else [],
        )

    def _perguntar(self, vaga: Vaga, perfil: PerfilPreparado) -> RespostaAnalise:
        usuario = USUARIO_ANALISE.format(vaga=descrever_vaga(vaga), perfil=como_dado(perfil.texto))
        return self._cliente.completar(SISTEMA_ANALISE, usuario, RespostaAnalise, ETAPA_ANALISE)

    def _completar_notas(
        self,
        vaga: Vaga,
        candidato: Candidato,
        perfil: PerfilPreparado,
        faltantes: list[str],
        notas: dict[str, float],
        evidencias: list[Evidencia],
    ) -> tuple[dict[str, float], list[Evidencia]]:
        """Pede de novo, uma vez, só as notas que faltaram. Do novo pedido fica só nota e trecho
        dessas competências: o resto da primeira análise não muda. Resposta inválida mantém a
        primeira análise, e a regra de decisão trata a competência que segue sem nota.
        """
        usuario = USUARIO_NOTAS_FALTANTES.format(
            vaga=descrever_vaga(vaga),
            perfil=como_dado(perfil.texto),
            competencias=como_dado("\n".join(f"- {nome}" for nome in faltantes)),
        )
        try:
            resposta = self._cliente.completar(
                SISTEMA_ANALISE, usuario, RespostaAnalise, ETAPA_ANALISE
            )
        except RespostaInvalida:
            logger.info("novo pedido de notas voltou inválido: %s", candidato.id)
            return notas, evidencias
        novas = self._notas(vaga, resposta)
        completas = notas | {nome: novas[nome] for nome in faltantes if nome in novas}
        citadas = [
            e
            for e in self._evidencias(vaga, candidato, perfil, resposta)
            if e.criterio in faltantes
        ]
        vistas = {(e.criterio, normalizar(e.trecho)) for e in evidencias}
        extras = [e for e in citadas if (e.criterio, normalizar(e.trecho)) not in vistas]
        return completas, [*evidencias, *extras]

    @staticmethod
    def _evidencias(
        vaga: Vaga, candidato: Candidato, perfil: PerfilPreparado, resposta: RespostaAnalise
    ) -> list[Evidencia]:
        """Fica só o que cita critério da vaga e trecho literal. A fonte é sempre a do perfil."""
        criterios = criterios_da_vaga(vaga)
        aceitas: dict[tuple[str, str], Evidencia] = {}
        for evidencia in resposta.evidencias:
            criterio = criterio_citado(criterios, evidencia.criterio)
            trecho = como_no_perfil(evidencia.trecho).strip()
            if criterio is not None and trecho_confere(trecho, candidato, perfil):
                aceitas.setdefault(
                    (criterio, normalizar(trecho)),
                    Evidencia(criterio=criterio, trecho=trecho, fonte=candidato.fonte),
                )
        return list(aceitas.values())

    @staticmethod
    def _notas(vaga: Vaga, resposta: RespostaAnalise) -> dict[str, float]:
        """Toda nota que o modelo deu a uma competência da vaga, com ou sem trecho, em [0, 1].

        Competência sem nota fica de fora, e não vira zero: quem decide o que fazer é a regra.
        """
        informadas = {
            normalizar(nome): min(1.0, max(0.0, nota))
            for nome, nota in resposta.notas.items()
            if nota is not None
        }
        return {
            c.nome: informadas[normalizar(c.nome)]
            for c in vaga.competencias
            if normalizar(c.nome) in informadas
        }

    @staticmethod
    def _lacunas(
        vaga: Vaga, candidato: Candidato, evidencias: list[Evidencia], notas: dict[str, float]
    ) -> list[str]:
        com_evidencia = {e.criterio for e in evidencias}
        status = avaliar_requisitos(vaga, candidato)
        lacunas = []
        for requisito in vaga.requisitos:
            if status[requisito.id] is StatusRequisito.SEM_DADO:
                lacunas.append(f"Requisito sem dado confirmado: {requisito.descricao}")
            elif requisito.id not in com_evidencia:
                lacunas.append(f"Perfil sem trecho sobre o requisito: {requisito.descricao}")
        for competencia in vaga.competencias:
            if competencia.nome not in notas:
                lacunas.append(f"Competência sem nota: {competencia.nome}")
            elif competencia.nome not in com_evidencia:
                lacunas.append(f"Perfil sem trecho sobre a competência: {competencia.nome}")
        return lacunas

    @staticmethod
    def _confirmacoes(vaga: Vaga, candidato: Candidato) -> list[str]:
        status = avaliar_requisitos(vaga, candidato)
        confirmacoes = [
            f"Confirmar com a pessoa: {r.descricao}"
            for r in vaga.requisitos
            if status[r.id] is StatusRequisito.SEM_DADO
        ]
        if candidato.estado == EstadoBanco.DESATUALIZADO:
            confirmacoes.append(CONFIRMAR_PERFIL_DESATUALIZADO)
        return confirmacoes
