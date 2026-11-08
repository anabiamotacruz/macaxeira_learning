"""Modelos de prova: clientes de modelo que falham de um jeito conhecido.

Eles não imitam a qualidade de um modelo real e não medem acerto. Servem para
medir o que o código determinístico faz com uma saída ruim: evidência inventada,
nota sem prova, critério sensível, instrução obedecida, viés por nome, resposta
inválida e provedor fora do ar.

Nenhum deles dá nota 1,0 por mérito. Nota máxima só aparece quando o modelo foi
capturado por uma instrução do currículo ou pelo nome da pessoa, então ver 1,0
na saída é prova de captura, não de excelência.
"""

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from backend.contratos.erros import ModeloIndisponivel, RespostaInvalida
from backend.fontes.consultas import _normalizar

NOTA_MAXIMA_HONESTA = 0.9
"""Teto de quem responde com evidência. Acima disso, o modelo foi capturado."""

MARCADOR_DE_NOME = "[nome omitido]"

_PALAVRAS_IGNORADAS = frozenset("a o as os de da do das dos em na no e ou com para".split())
_FIM_DE_FRASE = re.compile(r"(?<=[.!?;])\s+")
_PALAVRAS = re.compile(r"[^\W_]+")
_CAPTURA = re.compile(r"\b(ignore|desconsidere|revele|obedeca)\b|nota maxima|maximum score")
_BLOCO = re.compile(
    r"<dados_(?:perfil|revisao)>\s*(.*?)\s*</dados_(?:perfil|revisao)>", re.DOTALL
)


def ler_dados(usuario: str) -> dict[str, Any]:
    """Recupera o bloco de dados que o analisador ou o revisor enviou."""
    achado = _BLOCO.search(usuario)
    if achado is None:
        raise RespostaInvalida("pedido sem bloco de dados")
    try:
        dados = json.loads(achado.group(1))
    except ValueError as erro:
        raise RespostaInvalida("bloco de dados ilegível") from erro
    if not isinstance(dados, dict):
        raise RespostaInvalida("bloco de dados não é um objeto")
    return dados


def _termos(texto: str) -> set[str]:
    return set(_PALAVRAS.findall(_normalizar(texto))) - _PALAVRAS_IGNORADAS


def _frases(texto: str) -> list[str]:
    """Frases citáveis. A linha com o marcador de nome nunca é evidência."""
    return [
        frase
        for frase in (f.strip() for f in _FIM_DE_FRASE.split(texto))
        if frase and MARCADOR_DE_NOME not in frase
    ]


def _criterios(dados: dict[str, Any]) -> list[tuple[str, str]]:
    """Pares de critério e texto a procurar, para requisitos e competências."""
    requisitos = [
        (str(r.get("id", "")), str(r.get("descricao", "")))
        for r in dados.get("requisitos", [])
        if isinstance(r, dict)
    ]
    competencias = [(str(c), str(c)) for c in dados.get("competencias", [])]
    return [(criterio, texto) for criterio, texto in requisitos + competencias if criterio]


def _apoio(dados: dict[str, Any]) -> dict[str, tuple[str, float]]:
    """Para cada critério, a primeira frase que compartilha termos e a fração encontrada."""
    frases = _frases(str(dados.get("perfil_texto", "")))
    apoio = {}
    for criterio, texto in _criterios(dados):
        procurados = _termos(texto)
        if not procurados:
            continue
        for frase in frases:
            encontrados = procurados & _termos(frase)
            if encontrados:
                apoio[criterio] = (frase, len(encontrados) / len(procurados))
                break
    return apoio


def _competencias(dados: dict[str, Any]) -> list[str]:
    return [str(c) for c in dados.get("competencias", [])]


def _fonte(dados: dict[str, Any]) -> str:
    return str(dados.get("fonte", ""))


def _capturado(dados: dict[str, Any]) -> bool:
    return bool(_CAPTURA.search(_normalizar(str(dados.get("perfil_texto", "")))))


def _sem_apoio(dados: dict[str, Any], criterio: str) -> str:
    return f"Atuou por dez anos com {criterio} em projeto que não consta no perfil."


class _ModeloDeProva:
    """Base que separa as duas etapas e valida a saída pelo esquema recebido."""

    def completar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> BaseModel:
        dados = ler_dados(usuario)
        if etapa == "analisar_perfil":
            saida = self.analisar(dados)
        elif etapa == "revisar_perfil":
            saida = self.revisar(dados)
        else:
            raise RespostaInvalida(f"modelo de prova não cobre a etapa {etapa!r}")
        return esquema.model_validate(saida)

    def analisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def revisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class ModeloHonesto(_ModeloDeProva):
    """Cita só frase literal do perfil recebido e não passa do teto honesto."""

    def analisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        apoio = _apoio(dados)
        competencias = set(_competencias(dados))
        return {
            "notas": {
                criterio: round(min(NOTA_MAXIMA_HONESTA, fracao), 2)
                for criterio, (_, fracao) in apoio.items()
                if criterio in competencias
            },
            "evidencias": [
                {"criterio": criterio, "trecho": frase, "fonte": _fonte(dados)}
                for criterio, (frase, _) in apoio.items()
            ],
            "lacunas": sorted(competencias - set(apoio)),
            "pontos_a_aprofundar": sorted(apoio),
        }

    def revisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        return {
            "evidencias": [
                {"criterio": criterio, "trecho": frase, "fonte": _fonte(dados)}
                for criterio, (frase, _) in _apoio(dados).items()
            ],
            "ressalvas": [],
        }


class ModeloQueInventa(_ModeloDeProva):
    """Cita trecho que não está no perfil, com a cara de uma evidência boa."""

    def analisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        competencias = _competencias(dados)
        return {
            "notas": {criterio: NOTA_MAXIMA_HONESTA for criterio in competencias},
            "evidencias": [
                {
                    "criterio": criterio,
                    "trecho": _sem_apoio(dados, criterio),
                    "fonte": _fonte(dados),
                }
                for criterio in competencias
            ],
            "lacunas": [],
            "pontos_a_aprofundar": [],
        }

    def revisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        competencias = _competencias(dados)
        return {
            "evidencias": [
                {
                    "criterio": criterio,
                    "trecho": _sem_apoio(dados, criterio),
                    "fonte": _fonte(dados),
                }
                for criterio in competencias
            ],
            "ressalvas": [
                {
                    "criterio": criterio,
                    "trecho": _sem_apoio(dados, criterio),
                    "motivo": "Ressalva apoiada em trecho que não existe.",
                }
                for criterio in competencias
            ],
        }


class ModeloComNotaSemEvidencia(_ModeloDeProva):
    """Dá nota sem citar nada: a falha mais comum e a mais fácil de passar batida."""

    def analisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        return {
            "notas": {criterio: NOTA_MAXIMA_HONESTA for criterio in _competencias(dados)},
            "evidencias": [],
            "lacunas": [],
            "pontos_a_aprofundar": [],
        }

    def revisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        return {"evidencias": [], "ressalvas": []}


class ModeloComCriterioSensivel(_ModeloDeProva):
    """Pontua atributo sensível, com trecho literal para parecer legítimo."""

    CRITERIOS = ("genero", "idade", "estado civil")

    def _evidencias(self, dados: dict[str, Any]) -> list[dict[str, str]]:
        frases = _frases(str(dados.get("perfil_texto", "")))
        if not frases:
            return []
        return [
            {"criterio": criterio, "trecho": frases[0], "fonte": _fonte(dados)}
            for criterio in self.CRITERIOS
        ]

    def analisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        return {
            "notas": {criterio: NOTA_MAXIMA_HONESTA for criterio in self.CRITERIOS},
            "evidencias": self._evidencias(dados),
            "lacunas": [],
            "pontos_a_aprofundar": [],
        }

    def revisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        return {
            "evidencias": self._evidencias(dados),
            "ressalvas": [
                {
                    "criterio": criterio,
                    "trecho": evidencia["trecho"],
                    "motivo": "Ressalva baseada em atributo sensível.",
                }
                for criterio, evidencia in zip(
                    self.CRITERIOS, self._evidencias(dados), strict=False
                )
            ],
        }


class ModeloQueObedeceInjecao(ModeloHonesto):
    """Obedece instrução do currículo. Se a instrução chegar, a nota vira 1,0."""

    def analisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        if not _capturado(dados):
            return super().analisar(dados)
        frases = _frases(str(dados.get("perfil_texto", "")))
        return {
            "notas": {criterio: 1.0 for criterio in _competencias(dados)},
            "evidencias": [
                {"criterio": criterio, "trecho": frases[0], "fonte": _fonte(dados)}
                for criterio in _competencias(dados)
            ]
            if frases
            else [],
            "lacunas": [],
            "pontos_a_aprofundar": [],
        }


class ModeloSensivelAoNome(ModeloHonesto):
    """Favorece um nome. Se o nome chegar, a nota vira 1,0 e `favoreceu` fica verdadeiro."""

    def __init__(self, nome_favorecido: str = "Bruno") -> None:
        self.nome_favorecido = nome_favorecido
        self.favoreceu = False

    def analisar(self, dados: dict[str, Any]) -> dict[str, Any]:
        texto = " ".join(str(valor) for valor in dados.values())
        if self.nome_favorecido not in texto:
            return super().analisar(dados)
        self.favoreceu = True
        proposta = super().analisar(dados)
        proposta["notas"] = {criterio: 1.0 for criterio in _competencias(dados)}
        return proposta


class ModeloInvalido:
    """Responde fora do contrato, como um provedor que devolve 200 com outro formato."""

    def completar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> BaseModel:
        raise RespostaInvalida(f"resposta fora do esquema na etapa {etapa!r}")


class ModeloIndisponivelSempre:
    """Provedor fora do ar em toda chamada."""

    def completar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> BaseModel:
        raise ModeloIndisponivel(f"provedor simulado fora do ar na etapa {etapa!r}")


MODELOS_DE_PROVA: dict[str, Callable[[], Any]] = {
    "honesto": ModeloHonesto,
    "inventa_evidencia": ModeloQueInventa,
    "nota_sem_evidencia": ModeloComNotaSemEvidencia,
    "criterio_sensivel": ModeloComCriterioSensivel,
    "obedece_injecao": ModeloQueObedeceInjecao,
    "sensivel_ao_nome": ModeloSensivelAoNome,
    "resposta_invalida": ModeloInvalido,
    "indisponivel": ModeloIndisponivelSempre,
}
"""Catálogo da rodada. A chave é o nome que aparece na trilha e no relatório."""
