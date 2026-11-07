"""Pré-seleção determinística e cache de análises (T2.8).

O ranking usa somente competências estruturadas, nunca nome, contatos, texto
livre ou lacunas. É prioridade para análise, não nota final nem contratação.
"""

import hashlib
import json
import logging
import math
import re
from collections import OrderedDict, defaultdict
from datetime import UTC, date, datetime

from backend.contratos.modelos import Analise, Candidato, EstadoBanco, Vaga
from backend.fontes.consultas import _dados_vaga, _normalizar, _tem_sensivel

logger = logging.getLogger(__name__)

_CAMPOS_PROFISSIONAIS = {
    "cargo", "competencias", "habilidades", "skills", "tecnologias", "linguagens", "cloud",
}
_ESTADOS_BUSCAVEIS = {EstadoBanco.ATIVO, EstadoBanco.DESATUALIZADO}
_PALAVRAS_VAZIAS = {"a", "as", "o", "os", "de", "da", "do", "das", "dos", "e", "em", "com"}
_VALORES_SEM_COMPETENCIA = {"", "nao", "false", "no", "0", "desconhecido", "nao informado"}


def _hoje() -> date:
    return datetime.now(UTC).date()


def _validar_vaga(vaga: Vaga) -> None:
    _dados_vaga(vaga)
    if any(not math.isfinite(c.peso) or c.peso < 0 for c in vaga.competencias):
        raise ValueError("peso de competência deve ser finito e não negativo")


def _motivo_exclusao(vaga: Vaga, perfil: Candidato, hoje: date) -> str | None:
    if perfil.empresa_id != vaga.empresa_id:
        return "outra_empresa"
    if perfil.opt_out:
        return "opt_out"
    if (not perfil.autorizou_contato or perfil.autorizacao_valida_ate is None
            or perfil.autorizacao_valida_ate < hoje or perfil.estado not in _ESTADOS_BUSCAVEIS):
        return "sem_autorizacao_valida"
    for requisito in vaga.requisitos:
        valor = perfil.atributos.get(requisito.campo)
        if valor is None:
            return "requisito_desconhecido"
        if _normalizar(valor) != _normalizar(requisito.valor_esperado):
            return "requisito_nao_atendido"
    return None


def _texto_profissional(vaga: Vaga, perfil: Candidato) -> str:
    campos = _CAMPOS_PROFISSIONAIS | {_normalizar(c.nome) for c in vaga.competencias}
    return " ".join(
        f"{chave} {valor}"
        for chave, valor in sorted(perfil.atributos.items())
        if _normalizar(chave) in campos and not _tem_sensivel(chave)
        and _normalizar(valor) not in _VALORES_SEM_COMPETENCIA
    )


def _termos(texto: str) -> set[str]:
    return set(re.findall(r"[^\W_]+[+#]*", _normalizar(texto))) - _PALAVRAS_VAZIAS


def _pontuar(vaga: Vaga, perfil: Candidato) -> float:
    termos = _termos(_texto_profissional(vaga, perfil))
    pontuacao = 0.0
    for competencia in vaga.competencias:
        procurados = _termos(competencia.nome)
        if procurados:
            pontuacao += competencia.peso * len(procurados & termos) / len(procurados)
    return pontuacao


def priorizar(
    vaga: Vaga, candidatos: list[Candidato], limite: int = 20, *, hoje: date | None = None
) -> list[Candidato]:
    """Filtra elegíveis e retorna os primeiros por aderência lexical e id.

    Requisitos usam igualdade no campo estruturado, conforme o contrato atual;
    não há interpretação de intervalos, cálculo de anos ou inferência de texto.
    Ausência de dado impede pré-seleção e é registrada como desconhecida, sem
    representar decisão final de descarte. Duplicatas conflitantes ficam fora.
    """
    if type(limite) is not int or limite < 0:
        raise ValueError("limite deve ser inteiro não negativo")
    _validar_vaga(vaga)
    hoje = hoje if hoje is not None else _hoje()
    grupos: dict[str, list[Candidato]] = defaultdict(list)
    for perfil in candidatos:
        if perfil.empresa_id == vaga.empresa_id:
            grupos[perfil.id].append(perfil)

    aptos = []
    for identificador, grupo in sorted(grupos.items()):
        motivos = {_motivo_exclusao(vaga, perfil, hoje) for perfil in grupo} - {None}
        if motivos:
            logger.info(
                "Perfil fora da pré-seleção",
                extra={"empresa_id": vaga.empresa_id, "vaga_id": vaga.id,
                       "candidato_id": identificador, "etapa": "priorizar",
                       "regra": ",".join(sorted(motivos))},
            )
            continue
        perfil = max(grupo, key=lambda p: (p.atualizado_em, _texto_profissional(vaga, p),
                                          p.fonte, p.origem))
        aptos.append(perfil)
    aptos.sort(key=lambda p: (-_pontuar(vaga, p), p.id))
    selecionados = aptos[:limite]
    logger.info(
        "Pré-seleção registrada",
        extra={"empresa_id": vaga.empresa_id, "vaga_id": vaga.id, "etapa": "priorizar",
               "regra": "competencias_estruturadas_desempate_por_id",
               "quantidade": len(selecionados)},
    )
    return [p.model_copy(deep=True) for p in selecionados]


def _chave(vaga: Vaga, perfil: Candidato, versao: str) -> str:
    conteudo = json.dumps(
        {"vaga": vaga.model_dump(mode="json"), "perfil": perfil.model_dump(mode="json"),
         "versao_configuracao": versao},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(conteudo.encode()).hexdigest()


class CacheAnalise:
    """Cache local limitado; mudanças no perfil, vaga ou versão geram outra chave.

    A versão da configuração deve incorporar versão de prompt/modelo quando
    esses mudarem. O cache nunca sobrepõe autorização nem o isolamento por empresa.
    `hoje=None` consulta a data UTC a cada operação, sem congelá-la no construtor.
    """

    def __init__(self, *, hoje: date | None = None, max_itens: int = 1000) -> None:
        if type(max_itens) is not int or max_itens < 1:
            raise ValueError("max_itens deve ser inteiro positivo")
        self.hoje = hoje
        self.max_itens = max_itens
        self._itens: OrderedDict[str, Analise] = OrderedDict()

    def obter(
        self, vaga: Vaga, candidato: Candidato, *, versao_configuracao: str = "1"
    ) -> Analise | None:
        _validar_vaga(vaga)
        if _motivo_exclusao(vaga, candidato, self.hoje or _hoje()) is not None:
            return None
        chave = _chave(vaga, candidato, versao_configuracao)
        if chave not in self._itens:
            return None
        self._itens.move_to_end(chave)
        return self._itens[chave].model_copy(deep=True)

    def salvar(
        self, vaga: Vaga, candidato: Candidato, analise: Analise, *, versao_configuracao: str = "1"
    ) -> None:
        _validar_vaga(vaga)
        if (analise.empresa_id != vaga.empresa_id or candidato.empresa_id != vaga.empresa_id
                or analise.vaga_id != vaga.id or analise.candidato_id != candidato.id):
            raise ValueError("análise e perfil precisam corresponder ao escopo da vaga")
        if _motivo_exclusao(vaga, candidato, self.hoje or _hoje()) is not None:
            raise ValueError("perfil não é elegível para cache de análise")
        valida = Analise.model_validate(analise.model_dump())
        chave = _chave(vaga, candidato, versao_configuracao)
        self._itens[chave] = valida.model_copy(deep=True)
        self._itens.move_to_end(chave)
        while len(self._itens) > self.max_itens:
            self._itens.popitem(last=False)
