"""Reduz os candidatos antes das análises por modelo (T2.8). Nenhuma regra aqui usa modelo.

A ordem vem primeiro dos requisitos confirmados, que são atributos profissionais validados na
vaga, e depois de quanto do título e das competências o perfil cobre. A cobertura lê só
`perfil_texto`, cargo e descrição do histórico, sem flexão de gênero e sem contar repetição. Nome,
fonte, empresas do histórico e os demais atributos nunca entram na conta, então não há como
favorecer alguém por nome, gênero da palavra, atributo sensível, GitHub ou volume de texto.

Requisito sem dado nunca elimina, mas perde a vez para quem o tem confirmado: sem o dado, a análise
não leva a uma indicação automática. Quem tem requisito sem dado e não cita a função fica na
reserva, sem gastar modelo nem ocupar a fila humana, até faltarem aderentes para a meta da vaga.
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
STATUS_ATENDE = "atende"

TAMANHO_DO_RADICAL = 5
"""Junta flexões como `liderei` e `liderança`, ou `distribuída` e `distribuídos`, sem dicionário."""

COBERTURA_DE_QUEM_CITA_A_FUNCAO = Fraction(1, 2)
"""A maioria do título ou das competências. Não é nota: só decide quem gasta modelo primeiro."""

PALAVRAS_VAZIAS = frozenset(
    {"a", "as", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos", "o"}
    | {"os", "ou", "para", "and", "of", "the"}
)


CAMPOS_FORA_DO_PERFIL = {"autorizacao_valida_ate", "autorizou_contato", "estado", "nome", "opt_out"}
"""Autorização não muda o que o perfil diz: renovar não pede nova análise. O nome não entra na
análise: trocar o nome não pode pedir outra, que poderia dar outro resultado."""

MOTIVO_RESERVA = "requisito sem dado e sem ligação à função: fica no banco, sem decisão"


class RegraCorte(StrEnum):
    DUPLICATA = "duplicata"
    OPT_OUT = "opt_out"
    ESTADO_BLOQUEADO = "estado_bloqueado"
    SEM_AUTORIZACAO = "sem_autorizacao"
    AUTORIZACAO_VENCIDA = "autorizacao_vencida"
    REQUISITO_NAO_ATENDIDO = "requisito_nao_atendido"
    PERFIL_DESATUALIZADO = "perfil_desatualizado"
    FORA_DO_LIMITE = "fora_do_limite"
    RESERVA = "reserva"


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
    """Radicais sem acento, caixa nem flexão de gênero, mantendo `+` e `#`: `C++` não é `C#`.

    É um conjunto: repetir uma palavra ou escrever mais sobre outro assunto não soma nada.
    """
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    palavras = re.findall(r"[^\W_]+[+#]*", sem_acento.casefold())
    return {sem_genero(p)[:TAMANHO_DO_RADICAL] for p in palavras}


def _competencias_validas(vaga: Vaga) -> list[tuple[Fraction, set[str]]]:
    """Fica com peso positivo e finito; ignora competência sensível ou ligada ao GitHub."""
    validas = []
    for competencia in vaga.competencias:
        termos = _palavras(competencia.nome) - PALAVRAS_VAZIAS
        if (
            termos
            and math.isfinite(competencia.peso)
            and competencia.peso > 0
            and "github" not in competencia.nome.casefold()
            and not tem_termo_sensivel(competencia.nome)
        ):
            validas.append((Fraction(competencia.peso), termos))
    return validas


def _palavras_do_perfil(candidato: Candidato) -> set[str]:
    trechos = [candidato.perfil_texto]
    trechos += [f"{e.cargo} {e.descricao}" for e in candidato.historico]
    return _palavras(" ".join(trechos))


def _cobertura_de_competencias(
    competencias: list[tuple[Fraction, set[str]]], perfil: set[str]
) -> Fraction:
    """Fração do peso das competências coberta pelo perfil, em conta exata: empate depende do id."""
    total = sum((peso for peso, _ in competencias), Fraction(0))
    if not total:
        return Fraction(0)
    cobertos = sum(
        (peso * Fraction(len(termos & perfil), len(termos)) for peso, termos in competencias),
        Fraction(0),
    )
    return cobertos / total


def _cobertura_do_titulo(termos: set[str], perfil: set[str]) -> Fraction:
    return Fraction(len(termos & perfil), len(termos)) if termos else Fraction(0)


@dataclass(frozen=True, slots=True)
class _Prioridade:
    """Como a pessoa entra na fila das análises. Sem dado do perfil além da cobertura."""

    candidato: Candidato
    confirmados: int
    completo: bool
    titulo: Fraction
    competencias: Fraction

    @property
    def aderente(self) -> bool:
        """Tem todos os requisitos confirmados ou cita a função pelo título ou competências."""
        return self.completo or (
            max(self.titulo, self.competencias) >= COBERTURA_DE_QUEM_CITA_A_FUNCAO
        )

    @property
    def ordem(self) -> tuple[int, Fraction, str]:
        return (-self.confirmados, -(self.titulo + self.competencias), self.candidato.id)


def _prioridade(
    vaga: Vaga,
    registros: list[Candidato],
    competencias: list[tuple[Fraction, set[str]]],
    avaliar_requisitos: AvaliadorRequisitos,
) -> _Prioridade:
    candidato = registros[0]
    perfil = _palavras_do_perfil(candidato)
    status = _status_conhecidos(vaga, registros, avaliar_requisitos)
    confirmados = sum(valor == STATUS_ATENDE for valor in status.values())
    return _Prioridade(
        candidato=candidato,
        confirmados=confirmados,
        completo=bool(status) and confirmados == len(status),
        titulo=_cobertura_do_titulo(_palavras(vaga.titulo) - PALAVRAS_VAZIAS, perfil),
        competencias=_cobertura_de_competencias(competencias, perfil),
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


def _status_conhecidos(
    vaga: Vaga, registros: list[Candidato], avaliar_requisitos: AvaliadorRequisitos
) -> dict[str, str]:
    """Cada requisito vale pelo registro mais recente que tem o dado: lacuna não esconde falta."""
    conhecidos: dict[str, str] = {}
    for registro in registros:
        for id_requisito, valor in avaliar_requisitos(vaga, registro).items():
            if conhecidos.get(id_requisito, STATUS_SEM_DADO) == STATUS_SEM_DADO:
                conhecidos[id_requisito] = valor
    return conhecidos


def _faltas_de_requisito(
    vaga: Vaga, registros: list[Candidato], avaliar_requisitos: AvaliadorRequisitos
) -> list[str]:
    conhecidos = _status_conhecidos(vaga, registros, avaliar_requisitos)
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
    válida sai para uma pessoa confirmar, sem análise. Quem tem os requisitos confirmados e não
    coube sai por `FORA_DO_LIMITE`; os demais que ficam de fora vão para a `RESERVA`, e só entram
    nesta rodada se os aderentes não bastam para a meta da vaga. Cada saída passa por
    `registrar_corte`. Candidato de outra empresa levanta `ValueError` antes de qualquer registro.
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
    competencias = _competencias_validas(vaga)
    elegiveis: list[_Prioridade] = []
    for pessoa_id in sorted(por_pessoa):
        registros = por_pessoa[pessoa_id]
        corte = _regra_de_corte(vaga, registros, hoje, avaliar_requisitos)
        pessoa = _prioridade(vaga, registros, competencias, avaliar_requisitos)
        if corte is None:
            elegiveis.append(pessoa)
        elif corte[0] == RegraCorte.PERFIL_DESATUALIZADO and not pessoa.aderente:
            cortar(registros[0], RegraCorte.RESERVA, MOTIVO_RESERVA)
        else:
            cortar(registros[0], *corte)

    for duplicata in sorted(duplicatas, key=lambda c: (c.id, c.fonte, c.origem)):
        cortar(duplicata, RegraCorte.DUPLICATA, "outro registro da mesma pessoa foi mantido")

    elegiveis.sort(key=lambda p: p.ordem)
    aderentes = [p for p in elegiveis if p.aderente]
    fila = elegiveis if len(aderentes) < vaga.meta_candidatos else aderentes
    selecionados = [p.candidato for p in fila[:limite]]
    escolhidos = {c.id for c in selecionados}
    for pessoa in elegiveis:
        if pessoa.candidato.id in escolhidos:
            continue
        if pessoa.completo:
            cortar(pessoa.candidato, RegraCorte.FORA_DO_LIMITE, f"além dos {limite} mais aderentes")
        else:
            cortar(pessoa.candidato, RegraCorte.RESERVA, MOTIVO_RESERVA)

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
