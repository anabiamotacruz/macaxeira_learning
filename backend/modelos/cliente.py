"""Cliente único de modelos, pela API da Featherless compatível com a OpenAI.

A chave só é lida do ambiente e entregue ao SDK. Erros e mensagens nunca copiam o texto de
exceções do SDK nem a resposta do modelo, pois ambos podem trazer a chave ou texto de candidato.
"""

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Any

import httpx2
from openai import APIStatusError, AuthenticationError, OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from backend.agente.auditoria import rastreado
from backend.contratos.erros import LimiteGastoAtingido, ModeloIndisponivel, RespostaInvalida
from backend.modelos.prompts import CORRECAO, REGRA_DADOS, SAIDA_JSON
from backend.modelos.rastro import Rastro, RegistroChamada, criar_rastro

logger = logging.getLogger(__name__)

URL_BASE_PADRAO = "https://api.featherless.ai/v1"
MODELO_PADRAO = "zai-org/GLM-5.2"
ETAPA_CHAMADA_MODELO = "chamada_modelo"
MAX_TOKENS_MINIMO = 1000
MAX_TOKENS_PADRAO = 2000
TEMPO_LIMITE_PADRAO_S = 120.0
REPETICOES_DO_SDK = 1
MAX_PROBLEMAS_DESCRITOS = 5
TAMANHO_MAXIMO_DE_CAMPO = 40

PRECOS_USD: dict[str, tuple[float, float]] = {
    "zai-org/GLM-5.2": (1.4, 4.4),
    "zai-org/GLM-5.1": (1.3, 4.3),
    "zai-org/GLM-4.7-Flash": (0.0653, 0.4),
}
"""Entrada e saída, em USD por milhão de tokens, conforme `GET /v1/models` em 7/11/2026."""

PRECO_DE_REFERENCIA = PRECOS_USD[MODELO_PADRAO]
"""Usado em modelo fora da tabela, para o limite de gasto nunca ser ignorado."""

TETO_GASTO_PADRAO_USD = 5.0
"""Teto quando `LIMITE_GASTO_SESSAO_USD` não está definida: gasto nunca fica sem limite."""

CARACTERES_POR_TOKEN = 3
"""Estimativa conservadora, usada antes da chamada e quando o provedor não informa tokens."""

_RACIOCINIO = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_BLOCO_DE_CODIGO = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class MetricasEtapa:
    """Acumulado de uma etapa. `falhas` conta erro do provedor e resposta recusada."""

    chamadas: int = 0
    falhas: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0
    custo_estimado: bool = False
    tempo_s: float = 0.0


@dataclass(frozen=True)
class _Consumo:
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0
    custo_estimado: bool = False


def _variavel(nome: str) -> str | None:
    """Lê uma variável de ambiente; vazia conta como ausente, como no `.env.example`."""
    return (os.environ.get(nome) or "").strip() or None


def _limite_valido(valor: float) -> bool:
    return math.isfinite(valor) and valor >= 0


def _teto_do_ambiente() -> float:
    texto = _variavel("LIMITE_GASTO_SESSAO_USD")
    if texto is None:
        return TETO_GASTO_PADRAO_USD
    try:
        teto = float(texto)
    except ValueError:
        teto = math.nan
    if not _limite_valido(teto):
        raise ValueError("LIMITE_GASTO_SESSAO_USD precisa ser um número finito e não negativo")
    return teto


def _custo_usd(modelo: str, tokens_entrada: int, tokens_saida: int) -> float:
    entrada, saida = PRECOS_USD.get(modelo, PRECO_DE_REFERENCIA)
    return (tokens_entrada * entrada + tokens_saida * saida) / 1_000_000


def _tokens_estimados(texto: str) -> int:
    return len(texto) // CARACTERES_POR_TOKEN


def _tokens_informados(usage: Any, campo: str) -> int | None:
    valor = getattr(usage, campo, None)
    if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0:
        return valor
    return None


def _custo_informado(resposta: Any, usage: Any) -> float | None:
    """Em plano de créditos a Featherless informa `cost`; em assinatura, omite."""
    for fonte in (usage, resposta):
        valor = getattr(fonte, "cost", None)
        if isinstance(valor, int | float) and not isinstance(valor, bool) and _limite_valido(valor):
            return float(valor)
    return None


def _medir_consumo(resposta: Any, modelo: str, entrada: str, saida: str | None) -> _Consumo:
    """Usa os números do provedor; o que faltar é estimado e fica marcado como tal."""
    usage = getattr(resposta, "usage", None)
    informados_entrada = _tokens_informados(usage, "prompt_tokens")
    informados_saida = _tokens_informados(usage, "completion_tokens")
    tokens_entrada = (
        _tokens_estimados(entrada) if informados_entrada is None else informados_entrada
    )
    tokens_saida = _tokens_estimados(saida or "") if informados_saida is None else informados_saida
    custo = _custo_informado(resposta, usage)
    if custo is not None:
        return _Consumo(tokens_entrada, tokens_saida, custo, custo_estimado=False)
    return _Consumo(
        tokens_entrada,
        tokens_saida,
        _custo_usd(modelo, tokens_entrada, tokens_saida),
        custo_estimado=True,
    )


def _registro(
    etapa: str, modelo: str, resultado: str, consumo: _Consumo, tempo_s: float, problema: str
) -> RegistroChamada:
    return RegistroChamada(
        etapa=etapa,
        modelo=modelo,
        resultado=resultado,
        tokens_entrada=consumo.tokens_entrada,
        tokens_saida=consumo.tokens_saida,
        custo_usd=consumo.custo_usd,
        custo_estimado=consumo.custo_estimado,
        tempo_s=tempo_s,
        erro=problema or None,
    )


def _recusar_constante(constante: str) -> None:
    raise ValueError(f"constante JSON não aceita: {constante}")


def _candidatos_a_json(texto: str) -> Iterator[str]:
    """Texto inteiro, bloco de código único ou trecho entre a primeira e a última chave."""
    limpo = _RACIOCINIO.sub("", texto).strip()
    yield limpo
    blocos = _BLOCO_DE_CODIGO.findall(limpo)
    if len(blocos) == 1:
        yield blocos[0]
    inicio, fim = limpo.find("{"), limpo.rfind("}")
    if 0 <= inicio < fim:
        yield limpo[inicio : fim + 1]


def _extrair_objeto(texto: str) -> dict[str, Any] | None:
    for candidato in _candidatos_a_json(texto):
        try:
            dados = json.loads(candidato, parse_constant=_recusar_constante)
        except (ValueError, RecursionError):
            continue
        if isinstance(dados, dict):
            return dados
    return None


def _campo_seguro(parte: str | int) -> str:
    """Nome de campo vindo da resposta do modelo só é copiado se parecer um identificador."""
    texto = str(parte)
    if texto.isdigit() or (texto.isidentifier() and len(texto) <= TAMANHO_MAXIMO_DE_CAMPO):
        return texto
    return "*"


def _descrever_validacao(erro: ValidationError) -> str:
    """Descreve campo e tipo do problema, sem os valores recebidos do modelo."""
    problemas = erro.errors(include_url=False, include_context=False, include_input=False)
    return "; ".join(
        f"{'.'.join(_campo_seguro(parte) for parte in problema['loc']) or 'raiz'}: "
        f"{problema['type']}"
        for problema in problemas[:MAX_PROBLEMAS_DESCRITOS]
    )


def _texto_da_resposta(resposta: Any) -> str | None:
    """O SDK não valida o corpo, e o provedor pode devolver 200 com outro formato."""
    opcoes = getattr(resposta, "choices", None)
    if not opcoes or not isinstance(opcoes, list):
        return None
    conteudo = getattr(getattr(opcoes[0], "message", None), "content", None)
    return conteudo if isinstance(conteudo, str) else None


def _validar(texto: str | None, esquema: type[BaseModel]) -> tuple[BaseModel | None, str]:
    """Devolve a instância do esquema ou a descrição do problema, segura para exibir."""
    if not texto:
        return None, "resposta sem conteúdo"
    dados = _extrair_objeto(texto)
    if dados is None:
        return None, "resposta sem um objeto JSON válido"
    try:
        return esquema.model_validate(dados), ""
    except ValidationError as erro:
        return None, _descrever_validacao(erro)


def _descrever_falha(erro: OpenAIError) -> str:
    """Só tipo e código: o texto da exceção pode repetir a chave enviada ao provedor."""
    if isinstance(erro, APIStatusError):
        return f"{type(erro).__name__} (HTTP {erro.status_code})"
    return type(erro).__name__


class ClienteFeatherless:
    """Implementa `ClienteModelo`: valida a saída, corrige uma vez, respeita o limite de gasto
    e registra tokens, custo e tempo de cada chamada."""

    def __init__(
        self,
        *,
        modelo: str | None = None,
        modelo_alternativo: str | None = None,
        limite_gasto_usd: float | None = None,
        max_tokens: int = MAX_TOKENS_PADRAO,
        tempo_limite_s: float = TEMPO_LIMITE_PADRAO_S,
        max_repeticoes: int = REPETICOES_DO_SDK,
        http_client: httpx2.Client | None = None,
        relogio: Callable[[], float] = time.monotonic,
        rastro: Rastro | None = None,
    ) -> None:
        if max_tokens < MAX_TOKENS_MINIMO:
            raise ValueError(f"max_tokens precisa ser de pelo menos {MAX_TOKENS_MINIMO}")
        chave = _variavel("FEATHERLESS_API_KEY")
        if chave is None:
            raise ModeloIndisponivel("defina a variável de ambiente FEATHERLESS_API_KEY")
        self.modelo = modelo or _variavel("MODELO_PADRAO") or MODELO_PADRAO
        self.modelo_alternativo = modelo_alternativo or _variavel("MODELO_ALTERNATIVO")
        self.max_tokens = max_tokens
        self._teto_usd = _teto_do_ambiente()
        self._limite_mandato_usd: float | None = None
        self._relogio = relogio
        self.rastro = criar_rastro() if rastro is None else rastro
        self._trava = threading.Lock()
        self._metricas: dict[str, MetricasEtapa] = {}
        if limite_gasto_usd is not None:
            self.definir_limite_mandato(limite_gasto_usd)
        self._api = OpenAI(
            api_key=chave,
            base_url=_variavel("FEATHERLESS_BASE_URL") or URL_BASE_PADRAO,
            timeout=tempo_limite_s,
            max_retries=max_repeticoes,
            http_client=http_client,
        )

    @property
    def limite_gasto_usd(self) -> float:
        """O menor entre o limite do mandato e o teto da sessão."""
        if self._limite_mandato_usd is None:
            return self._teto_usd
        return min(self._limite_mandato_usd, self._teto_usd)

    @property
    def custo_total_usd(self) -> float:
        """Gasto da sessão, incluindo respostas recusadas."""
        with self._trava:
            return sum(metricas.custo_usd for metricas in self._metricas.values())

    @property
    def custo_estimado(self) -> bool:
        """Verdadeiro se alguma parcela de `custo_total_usd` não veio do provedor."""
        with self._trava:
            return any(metricas.custo_estimado for metricas in self._metricas.values())

    def metricas(self) -> dict[str, MetricasEtapa]:
        """Cópia das métricas acumuladas, por etapa."""
        with self._trava:
            return {etapa: replace(metricas) for etapa, metricas in self._metricas.items()}

    def definir_limite_mandato(self, limite_usd: float) -> None:
        """Aplica o limite assinado no mandato. O teto da sessão continua valendo."""
        if not _limite_valido(limite_usd):
            raise ValueError("limite de gasto precisa ser um número finito e não negativo")
        self._limite_mandato_usd = limite_usd

    @rastreado(ETAPA_CHAMADA_MODELO)
    def completar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> BaseModel:
        """Devolve a instância do esquema. Texto de candidato só entra em `usuario`."""
        if not etapa.strip():
            raise ValueError("etapa é obrigatória")
        base = "\n\n".join(
            [
                sistema,
                REGRA_DADOS,
                SAIDA_JSON.format(esquema=json.dumps(esquema.model_json_schema())),
            ]
        )
        instancia, problema = self._tentar(base, usuario, esquema, etapa)
        if instancia is not None:
            return instancia
        # A correção vai no sistema e não repete a resposta recusada, que pode ter sido
        # influenciada por texto de candidato.
        corrigido = f"{base}\n\n{CORRECAO.format(problemas=problema)}"
        instancia, problema = self._tentar(corrigido, usuario, esquema, etapa)
        if instancia is not None:
            return instancia
        raise RespostaInvalida(
            f"etapa {etapa!r}: resposta fora do esquema {esquema.__name__} "
            f"depois de uma correção ({problema})"
        )

    def _tentar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> tuple[BaseModel | None, str]:
        """Uma chamada, com alternativa se o modelo falhar. Devolve instância ou problema."""
        falhas: list[str] = []
        for modelo in dict.fromkeys(filter(None, (self.modelo, self.modelo_alternativo))):
            self._verificar_limite(modelo, sistema, usuario, etapa)
            marca = self._iniciar_rastro(etapa, modelo, sistema, usuario)
            inicio = self._relogio()
            resposta, falha, chave_recusada = self._chamar(modelo, sistema, usuario)
            tempo_s = self._relogio() - inicio
            if falha is None:
                texto = _texto_da_resposta(resposta)
                instancia, problema = _validar(texto, esquema)
                resultado = "ok" if instancia is not None else "resposta_invalida"
                consumo = _medir_consumo(resposta, modelo, sistema + usuario, texto)
                registro = _registro(etapa, modelo, resultado, consumo, tempo_s, problema)
                self._contabilizar(registro, marca, texto)
                return instancia, problema
            registro = _registro(etapa, modelo, "indisponivel", _Consumo(), tempo_s, falha)
            self._contabilizar(registro, marca, None)
            falhas.append(f"{modelo}: {falha}")
            if chave_recusada:
                # A alternativa usa a mesma chave, então também seria recusada.
                falhas.append("confira FEATHERLESS_API_KEY")
                break
        raise ModeloIndisponivel(f"etapa {etapa!r}: {'; '.join(falhas)}")

    def _chamar(self, modelo: str, sistema: str, usuario: str) -> tuple[Any, str | None, bool]:
        """Devolve resposta, descrição segura da falha e se a chave foi recusada.

        A falha sai como texto, e não como exceção, para o erro levantado depois não encadear a
        exceção do SDK, cujo texto pode repetir a chave.
        """
        try:
            resposta = self._api.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": usuario},
                ],
                max_tokens=self.max_tokens,
                temperature=0,
            )
        except OpenAIError as erro:
            return None, _descrever_falha(erro), isinstance(erro, AuthenticationError)
        return resposta, None, False

    def _verificar_limite(self, modelo: str, sistema: str, usuario: str, etapa: str) -> None:
        """Recusa a chamada se o pior caso dela, com toda a saída permitida, passar do limite."""
        tokens_entrada = _tokens_estimados(sistema + usuario)
        previsto = _custo_usd(modelo, tokens_entrada, self.max_tokens)
        limite = self.limite_gasto_usd
        gasto = self.custo_total_usd
        if gasto + previsto > limite:
            raise LimiteGastoAtingido(
                f"etapa {etapa!r}: gasto de US$ {gasto:.6f} mais a previsão de "
                f"US$ {previsto:.6f} passa do limite de US$ {limite}"
            )

    def _contabilizar(self, registro: RegistroChamada, marca: Any, saida: str | None) -> None:
        with self._trava:
            metricas = self._metricas.setdefault(registro.etapa, MetricasEtapa())
            metricas.chamadas += 1
            metricas.falhas += registro.resultado != "ok"
            metricas.tokens_entrada += registro.tokens_entrada
            metricas.tokens_saida += registro.tokens_saida
            metricas.custo_usd += registro.custo_usd
            metricas.custo_estimado = metricas.custo_estimado or registro.custo_estimado
            metricas.tempo_s += registro.tempo_s
        # O rastro nunca derruba a chamada; o log só traz o tipo, pois o texto pode ter segredo.
        try:
            self.rastro.concluir(marca, registro, saida)
        except Exception as erro:
            logger.warning("falha no rastro de %s: %s", registro.etapa, type(erro).__name__)

    def _iniciar_rastro(self, etapa: str, modelo: str, sistema: str, usuario: str) -> Any:
        try:
            return self.rastro.iniciar(etapa=etapa, modelo=modelo, sistema=sistema, usuario=usuario)
        except Exception as erro:
            logger.warning("falha no rastro de %s: %s", etapa, type(erro).__name__)
            return None
