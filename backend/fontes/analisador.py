"""Analisa um candidato diante da vaga (T2.3). O modelo interpreta; o código confere.

Requisito eliminatório vem de `backend/agente/regras.py`. Do modelo ficam só nota, trecho e
perguntas, e cada afirmação precisa de um trecho literal do perfil. Nome, atributos, histórico
e descrição da vaga não são enviados: datas revelam períodos sem trabalho, e o texto livre da
vaga pode citar gênero ou outro tema sensível.
"""

import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
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
from backend.contratos.interfaces import ClienteModelo
from backend.contratos.modelos import Analise, Candidato, Evidencia, Vaga
from backend.fontes.consultas import tem_termo_sensivel
from backend.fontes.prompts import SISTEMA_ANALISE, USUARIO_ANALISE

logger = logging.getLogger(__name__)

ETAPA_ANALISE = "analise"

ALERTA_INSTRUCAO = (
    "instrucao_no_perfil: o perfil traz texto dirigido ao avaliador; ele foi retirado da análise."
)
"""Texto fixo: o alerta não repete o texto do candidato, que pode ir a outro modelo ou sistema."""

MARCA_NOME = "[nome]"
MARCA_CONTATO = "[contato]"
TAMANHO_MINIMO_PARTE_DO_NOME = 3
PARTICULAS_DO_NOME = frozenset({"das", "dos"})

_EMAIL = re.compile(r"\S+@\S+\.\w+")
_FIM_DE_FRASE = re.compile(r"(?<=[.!?])\s+|\n+")
_PALAVRA = re.compile(r"\w+")
_RACE_CONDITION = re.compile(r"\brace conditions?\b")

_INSTRUCAO = re.compile(
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


def _normalizar(texto: str) -> str:
    """Sem acento, caixa nem caracteres invisíveis, que serviriam para esconder uma instrução."""
    decomposto = unicodedata.normalize("NFKD", texto)
    visivel = "".join(
        c for c in decomposto if not unicodedata.combining(c) and unicodedata.category(c) != "Cf"
    )
    return " ".join(visivel.casefold().split())


def texto_permitido(texto: str) -> bool:
    """Diz se o texto não fala de dado sensível nem de período sem trabalho."""
    normalizado = _RACE_CONDITION.sub(" ", _normalizar(texto))
    return not (
        tem_termo_sensivel(normalizado)
        or _SENSIVEL_ALEM_DA_LISTA.search(normalizado)
        or _PERIODO_SEM_TRABALHO.search(normalizado)
    )


def _mascarar_nome(texto: str, nome: str) -> str:
    partes = {
        parte
        for parte in _PALAVRA.findall(_normalizar(nome))
        if len(parte) >= TAMANHO_MINIMO_PARTE_DO_NOME
        and not parte.isdigit()
        and parte not in PARTICULAS_DO_NOME
    }
    return _PALAVRA.sub(
        lambda palavra: MARCA_NOME if _normalizar(palavra.group()) in partes else palavra.group(),
        texto,
    )


@dataclass(frozen=True)
class PerfilPreparado:
    """O perfil como o modelo pode vê-lo. `texto` ainda não passou por `como_dado`."""

    texto: str
    tem_instrucao: bool


def preparar_perfil(candidato: Candidato, retirar: Iterable[str] = ()) -> PerfilPreparado:
    """Tira nome, contato, instruções e frases sobre dado sensível ou período sem trabalho.

    Sai a frase inteira, sem alerta quando é dado sensível: mencionar gênero não pode mudar
    o caminho de ninguém. `retirar` traz o que só o modelo apontou: a frase só sai, com alerta, se
    o próprio texto dela confirma que fala com quem avalia. A opinião do modelo sozinha não basta.
    """
    retirados = [_normalizar(trecho) for trecho in retirar]
    frases = []
    tem_instrucao = False
    for frase in _FIM_DE_FRASE.split(candidato.perfil_texto):
        normalizada = _normalizar(frase)
        if not normalizada:
            continue
        apontada = any(trecho in normalizada or normalizada in trecho for trecho in retirados)
        if _INSTRUCAO.search(normalizada) or (
            apontada and _DIRIGIDO_AO_AVALIADOR.search(normalizada)
        ):
            tem_instrucao = True
        elif texto_permitido(frase):
            frases.append(_EMAIL.sub(MARCA_CONTATO, frase))
    return PerfilPreparado(_mascarar_nome(" ".join(frases), candidato.nome), tem_instrucao)


def como_no_perfil(trecho: str) -> str:
    """Desfaz a troca de `como_dado`, para o trecho voltar a ser literal."""
    return trecho.replace("‹", "<").replace("›", ">")


def trecho_confere(trecho: str, candidato: Candidato, perfil: PerfilPreparado) -> bool:
    """Exige o trecho no perfil original e no texto enviado: nada retirado pode ser citado."""
    citacao = Evidencia(criterio="", trecho=trecho, fonte=candidato.fonte)
    enviado = candidato.model_copy(update={"perfil_texto": perfil.texto})
    return all(
        classificar_evidencia(citacao, alvo) is not TipoEvidencia.INFERIDA
        for alvo in (candidato, enviado)
    )


def criterios_da_vaga(vaga: Vaga) -> dict[str, str]:
    """Id de requisito e nome de competência, indexados como o modelo pode escrevê-los."""
    criterios = {_normalizar(r.descricao): r.id for r in vaga.requisitos}
    criterios |= {_normalizar(r.id): r.id for r in vaga.requisitos}
    return criterios | {_normalizar(c.nome): c.nome for c in vaga.competencias}


def criterio_citado(criterios: dict[str, str], citado: str) -> str | None:
    return criterios.get(_normalizar(citado))


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

    def __init__(self, cliente: ClienteModelo) -> None:
        self._cliente = cliente

    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise:
        requisitos_ok = verificar_requisitos(vaga, candidato)
        perfil = preparar_perfil(candidato)
        resposta = self._perguntar(vaga, perfil)
        apontadas = [
            como_no_perfil(trecho)
            for trecho in resposta.instrucoes_detectadas
            if trecho_confere(como_no_perfil(trecho), candidato, perfil)
        ]
        if apontadas:
            conferido = preparar_perfil(candidato, apontadas)
            if conferido.texto == perfil.texto:
                # Só o id: o trecho é texto do candidato e não vai para o log.
                logger.info("apontamento do modelo sem confirmação no texto: %s", candidato.id)
            else:
                # A nota pode ter sido influenciada: vale a análise do perfil sem a instrução.
                perfil = conferido
                resposta = self._perguntar(vaga, perfil)

        evidencias = self._evidencias(vaga, candidato, perfil, resposta)
        notas = self._notas(vaga, resposta, evidencias)
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
                    (criterio, _normalizar(trecho)),
                    Evidencia(criterio=criterio, trecho=trecho, fonte=candidato.fonte),
                )
        return list(aceitas.values())

    @staticmethod
    def _notas(
        vaga: Vaga, resposta: RespostaAnalise, evidencias: list[Evidencia]
    ) -> dict[str, float]:
        """Nota sem trecho sai, e não vira zero: falta de informação não reduz a nota."""
        com_evidencia = {e.criterio for e in evidencias}
        informadas = {
            _normalizar(nome): nota for nome, nota in resposta.notas.items() if nota is not None
        }
        return {
            c.nome: informadas[_normalizar(c.nome)]
            for c in vaga.competencias
            if c.nome in com_evidencia and _normalizar(c.nome) in informadas
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
            if competencia.nome not in com_evidencia:
                lacunas.append(f"Perfil sem trecho sobre a competência: {competencia.nome}")
            elif competencia.nome not in notas:
                lacunas.append(f"Competência sem nota: {competencia.nome}")
        return lacunas

    @staticmethod
    def _confirmacoes(vaga: Vaga, candidato: Candidato) -> list[str]:
        status = avaliar_requisitos(vaga, candidato)
        return [
            f"Confirmar com a pessoa: {r.descricao}"
            for r in vaga.requisitos
            if status[r.id] is StatusRequisito.SEM_DADO
        ]
