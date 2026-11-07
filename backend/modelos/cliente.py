"""Cliente único de modelos, pela API da Featherless compatível com a OpenAI.

A chave só é lida do ambiente e entregue ao SDK. Erros e mensagens nunca copiam o texto de
exceções do SDK nem a resposta do modelo, pois ambos podem trazer a chave ou texto de candidato.
"""

import json
import math
import os
import re
from collections.abc import Iterator
from typing import Any

import httpx2
from openai import APIStatusError, AuthenticationError, OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from backend.contratos.erros import LimiteGastoAtingido, ModeloIndisponivel, RespostaInvalida
from backend.modelos.prompts import CORRECAO, REGRA_DADOS, SAIDA_JSON

URL_BASE_PADRAO = "https://api.featherless.ai/v1"
MODELO_PADRAO = "zai-org/GLM-5.2"
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
    opcoes = getattr(resposta, "choices", None)
    if not opcoes:
        return None
    return opcoes[0].message.content


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
    """Implementa `ClienteModelo`: valida a saída, corrige uma vez e respeita o limite de gasto."""

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
        self._gasto_usd = 0.0
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

    def definir_limite_mandato(self, limite_usd: float) -> None:
        """Aplica o limite assinado no mandato. O teto da sessão continua valendo."""
        if not _limite_valido(limite_usd):
            raise ValueError("limite de gasto precisa ser um número finito e não negativo")
        self._limite_mandato_usd = limite_usd

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
        falhas: list[str] = []
        chave_recusada = False
        for modelo in dict.fromkeys(filter(None, (self.modelo, self.modelo_alternativo))):
            self._verificar_limite(modelo, sistema, usuario, etapa)
            falha = None
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
                falha = _descrever_falha(erro)
                chave_recusada = isinstance(erro, AuthenticationError)
            if falha is None:
                return _validar(_texto_da_resposta(resposta), esquema)
            falhas.append(f"{modelo}: {falha}")
            if chave_recusada:
                # A alternativa usa a mesma chave, então também seria recusada.
                falhas.append("confira FEATHERLESS_API_KEY")
                break
        # Fora do `except`, para o erro novo não encadear a exceção do SDK.
        raise ModeloIndisponivel(f"etapa {etapa!r}: {'; '.join(falhas)}")

    def _verificar_limite(self, modelo: str, sistema: str, usuario: str, etapa: str) -> None:
        """Recusa a chamada se o pior caso dela, com toda a saída permitida, passar do limite."""
        tokens_entrada = (len(sistema) + len(usuario)) // CARACTERES_POR_TOKEN
        previsto = _custo_usd(modelo, tokens_entrada, self.max_tokens)
        limite = self.limite_gasto_usd
        if self._gasto_usd + previsto > limite:
            raise LimiteGastoAtingido(
                f"etapa {etapa!r}: gasto de US$ {self._gasto_usd:.6f} mais a previsão de "
                f"US$ {previsto:.6f} passa do limite de US$ {limite}"
            )
