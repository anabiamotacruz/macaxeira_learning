"""Reduz os candidatos antes das análises por modelo (T2.8). Nenhuma regra aqui usa modelo.

A ordenação lê só `perfil_texto`, cargo e descrição do histórico, sem flexão de gênero. Nome,
atributos, fonte e empresas do histórico nunca entram na conta, então não há como favorecer ou
prejudicar alguém por nome, gênero da palavra, atributo sensível, GitHub ou dado que faltou.
"""

import hashlib
import json
import logging
import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from fractions import Fraction

from backend.contratos.criterios import sem_genero, tem_termo_sensivel
from backend.contratos.interfaces import Analisador
from backend.contratos.modelos import Analise, Candidato, EstadoBanco, Vaga

logger = logging.getLogger(__name__)

AvaliadorRequisitos = Callable[[Vaga, Candidato], Mapping[str, str]]
"""Devolve o status de cada requisito, como `avaliar_requisitos` de `backend/agente/regras.py`."""

STATUS_NAO_ATENDE = "nao_atende"
"""Único status que elimina. `sem_dado` e qualquer outro seguem no funil."""
STATUS_SEM_DADO = "sem_dado"

PALAVRAS_VAZIAS = frozenset(
    {"a", "as", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos", "o"}
    | {"os", "ou", "para", "and", "of", "the"}
)


CAMPOS_FORA_DO_PERFIL = {"autorizacao_valida_ate", "autorizou_contato", "estado", "nome", "opt_out"}
"""Autorização não muda o que o perfil diz: renovar não pede nova análise. O nome não entra na
análise: trocar o nome não pode pedir outra, que poderia dar outro resultado."""


class RegraCorte(StrEnum):
    DUPLICATA = "duplicata"
    OPT_OUT = "opt_out"
    ESTADO_BLOQUEADO = "estado_bloqueado"
    SEM_AUTORIZACAO = "sem_autorizacao"
    AUTORIZACAO_VENCIDA = "autorizacao_vencida"
    REQUISITO_NAO_ATENDIDO = "requisito_nao_atendido"
    PERFIL_DESATUALIZADO = "perfil_desatualizado"
    FORA_DO_LIMITE = "fora_do_limite"


@dataclass(frozen=True, slots=True)
class Corte:
    """Registro de quem saiu do funil e por qual regra, sem dados do perfil."""

    empresa_id: str
    vaga_id: str
    candidato_id: str
    fonte: str
    origem: str
    regra: RegraCorte
    motivo: str


RegistrarCorte = Callable[[Corte], None]


def _palavras(texto: str) -> set[str]:
    """Palavras sem acento, caixa nem flexão de gênero, mantendo `+` e `#`: `C++` não é `C#`."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return {sem_genero(p) for p in re.findall(r"[^\W_]+[+#]*", sem_acento.casefold())}


def _competencias_validas(vaga: Vaga) -> list[tuple[Fraction, set[str]]]:
    """Fica com peso positivo e finito; ignora competência sensível ou ligada ao GitHub."""
    validas = []
    for competencia in vaga.competencias:
        termos = _palavras(competencia.nome) - PALAVRAS_VAZIAS
        if (
            termos
            and math.isfinite(competencia.peso)
            and competencia.peso > 0
            and "github" not in termos
            and not tem_termo_sensivel(competencia.nome)
        ):
            validas.append((Fraction(competencia.peso), termos))
    return validas


def _aderencia(competencias: list[tuple[Fraction, set[str]]], candidato: Candidato) -> Fraction:
    """Soma o peso de cada competência pela fração de seus termos presentes no perfil.

    Usa frações para que empates sejam exatos e dependam só do `id`.
    """
    trechos = [candidato.perfil_texto]
    trechos += [f"{e.cargo} {e.descricao}" for e in candidato.historico]
    perfil = _palavras(" ".join(trechos))
    return sum(
        (peso * Fraction(len(termos & perfil), len(termos)) for peso, termos in competencias),
        Fraction(0),
    )


def _exigir_mesma_empresa(vaga: Vaga, candidatos: list[Candidato]) -> None:
    if any(candidato.empresa_id != vaga.empresa_id for candidato in candidatos):
        raise ValueError("a lista traz candidato de outra empresa")


def _separar_duplicatas(
    candidatos: list[Candidato],
) -> tuple[dict[str, list[Candidato]], list[Candidato]]:
    """Agrupa os registros por pessoa, com o mais recente primeiro e a fonte como desempate."""
    por_pessoa: dict[str, list[Candidato]] = {}
    ordenados = sorted(candidatos, key=lambda c: (-c.atualizado_em.toordinal(), c.fonte, c.origem))
    for candidato in ordenados:
        por_pessoa.setdefault(candidato.id, []).append(candidato)
    duplicatas = [registro for registros in por_pessoa.values() for registro in registros[1:]]
    return por_pessoa, duplicatas


def _regra_de_autorizacao(registros: list[Candidato], hoje: date) -> tuple[RegraCorte, str] | None:
    """Vale a regra mais restritiva: um registro novo de outra fonte não anula uma restrição."""
    if any(r.opt_out for r in registros):
        return RegraCorte.OPT_OUT, "a pessoa pediu para não ser contatada"
    if any(r.estado == EstadoBanco.REMOVIDO for r in registros):
        return RegraCorte.ESTADO_BLOQUEADO, "perfil removido"
    for registro in registros:
        if not registro.autorizou_contato or registro.autorizacao_valida_ate is None:
            return RegraCorte.SEM_AUTORIZACAO, "sem autorização registrada"
    for registro in registros:
        if registro.autorizacao_valida_ate < hoje:
            return (
                RegraCorte.AUTORIZACAO_VENCIDA,
                f"autorização vencida em {registro.autorizacao_valida_ate.isoformat()}",
            )
    for registro in registros:
        if registro.estado in (EstadoBanco.PENDENTE, EstadoBanco.EXPIRADO):
            return RegraCorte.ESTADO_BLOQUEADO, f"perfil com estado {registro.estado.value}"
    return None


def _faltas_de_requisito(
    vaga: Vaga, registros: list[Candidato], avaliar_requisitos: AvaliadorRequisitos
) -> list[str]:
    """Cada requisito vale pelo registro mais recente que tem o dado: lacuna não esconde falta."""
    conhecidos: dict[str, str] = {}
    for registro in registros:
        for id_requisito, valor in avaliar_requisitos(vaga, registro).items():
            if conhecidos.get(id_requisito, STATUS_SEM_DADO) == STATUS_SEM_DADO:
                conhecidos[id_requisito] = valor
    return sorted(i for i, valor in conhecidos.items() if valor == STATUS_NAO_ATENDE)


def _regra_de_corte(
    vaga: Vaga,
    registros: list[Candidato],
    hoje: date,
    avaliar_requisitos: AvaliadorRequisitos,
) -> tuple[RegraCorte, str] | None:
    bloqueio = _regra_de_autorizacao(registros, hoje)
    if bloqueio is not None:
        return bloqueio
    if registros[0].estado == EstadoBanco.DESATUALIZADO:
        return (
            RegraCorte.PERFIL_DESATUALIZADO,
            "autorização válida, perfil desatualizado: uma pessoa confirma antes de analisar",
        )
    faltas = _faltas_de_requisito(vaga, registros, avaliar_requisitos)
    if faltas:
        return (
            RegraCorte.REQUISITO_NAO_ATENDIDO,
            f"requisitos não atendidos: {', '.join(faltas)}",
        )
    return None


def priorizar(
    vaga: Vaga,
    candidatos: list[Candidato],
    limite: int = 20,
    *,
    hoje: date,
    avaliar_requisitos: AvaliadorRequisitos,
    registrar_corte: RegistrarCorte,
) -> list[Candidato]:
    """Devolve até `limite` candidatos elegíveis, do mais aderente ao menos, com empate por `id`.

    Só falta comprovada elimina: dado ausente segue adiante. Perfil desatualizado com autorização
    válida sai para uma pessoa confirmar, sem análise. Cada saída passa por `registrar_corte`.
    Candidato de outra empresa levanta `ValueError` antes de qualquer registro.
    """
    if limite < 0:
        raise ValueError("limite não pode ser negativo")
    _exigir_mesma_empresa(vaga, candidatos)

    def cortar(candidato: Candidato, regra: RegraCorte, motivo: str) -> None:
        registrar_corte(
            Corte(
                empresa_id=vaga.empresa_id,
                vaga_id=vaga.id,
                candidato_id=candidato.id,
                fonte=candidato.fonte,
                origem=candidato.origem,
                regra=regra,
                motivo=motivo,
            )
        )

    por_pessoa, duplicatas = _separar_duplicatas(candidatos)
    elegiveis: list[Candidato] = []
    for pessoa_id in sorted(por_pessoa):
        registros = por_pessoa[pessoa_id]
        corte = _regra_de_corte(vaga, registros, hoje, avaliar_requisitos)
        if corte is None:
            elegiveis.append(registros[0])
        else:
            cortar(registros[0], *corte)

    for duplicata in sorted(duplicatas, key=lambda c: (c.id, c.fonte, c.origem)):
        cortar(duplicata, RegraCorte.DUPLICATA, "outro registro da mesma pessoa foi mantido")

    competencias = _competencias_validas(vaga)
    elegiveis.sort(key=lambda c: (-_aderencia(competencias, c), c.id))
    for candidato in elegiveis[limite:]:
        cortar(candidato, RegraCorte.FORA_DO_LIMITE, f"além dos {limite} mais aderentes")

    selecionados = elegiveis[:limite]
    logger.info(
        "funil: vaga=%s entrada=%d selecionados=%d", vaga.id, len(candidatos), len(selecionados)
    )
    return selecionados


def _resumo(conteudo: dict) -> str:
    canonico = json.dumps(conteudo, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


class CacheAnalise:
    """Guarda análises em memória, por empresa, conteúdo da vaga, perfil e versão da configuração.

    O resumo do conteúdo faz a entrada expirar sozinha: vaga ou perfil editados, mesmo com o
    mesmo `id`, geram outra chave. Mudar `aprovada` na vaga ou a autorização da pessoa não muda.
    """

    def __init__(self) -> None:
        self._analises: dict[tuple[str, str, str, str], Analise] = {}

    @staticmethod
    def _chave(vaga: Vaga, candidato: Candidato, versao_config: str) -> tuple[str, str, str, str]:
        if vaga.empresa_id != candidato.empresa_id:
            raise ValueError("vaga e candidato pertencem a empresas diferentes")
        if not versao_config.strip():
            raise ValueError("versão da configuração é obrigatória")
        return (
            vaga.empresa_id,
            _resumo(vaga.model_dump(mode="json", exclude={"aprovada"})),
            _resumo(candidato.model_dump(mode="json", exclude=CAMPOS_FORA_DO_PERFIL)),
            versao_config,
        )

    def obter(self, vaga: Vaga, candidato: Candidato, versao_config: str) -> Analise | None:
        analise = self._analises.get(self._chave(vaga, candidato, versao_config))
        return None if analise is None else analise.model_copy(deep=True)

    def guardar(
        self, vaga: Vaga, candidato: Candidato, versao_config: str, analise: Analise
    ) -> None:
        chave = self._chave(vaga, candidato, versao_config)
        if (analise.empresa_id, analise.vaga_id, analise.candidato_id) != (
            vaga.empresa_id,
            vaga.id,
            candidato.id,
        ):
            raise ValueError("a análise é de outra empresa, vaga ou pessoa")
        self._analises[chave] = analise.model_copy(deep=True)

    def obter_ou_analisar(
        self, vaga: Vaga, candidato: Candidato, analisador: Analisador, versao_config: str
    ) -> Analise:
        """Devolve a análise guardada ou chama o analisador. Falha não fica guardada."""
        guardada = self.obter(vaga, candidato, versao_config)
        if guardada is not None:
            return guardada
        analise = analisador.analisar(vaga, candidato)
        self.guardar(vaga, candidato, versao_config, analise)
        return analise
