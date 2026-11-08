"""Rastro das chamadas de modelo: local sempre, Langfuse quando configurado.

O registro local guarda só números e tipos de erro, nunca o texto trocado com o modelo. O Langfuse
recebe também entrada e saída, com as chaves mascaradas antes do envio.
"""

import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from langfuse import Langfuse

logger = logging.getLogger(__name__)

MAXIMO_DE_REGISTROS_LOCAIS = 1000
SEGREDOS_NO_AMBIENTE = ("FEATHERLESS_API_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY")
MASCARA = "[segredo removido]"

_CABECALHO_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


@dataclass(frozen=True)
class RegistroChamada:
    """Resumo de uma chamada. `erro` só traz texto seguro, como tipo e código HTTP."""

    etapa: str
    modelo: str
    resultado: str
    tokens_entrada: int
    tokens_saida: int
    custo_usd: float
    custo_estimado: bool
    tempo_s: float
    erro: str | None = None


class Rastro(Protocol):
    def iniciar(self, *, etapa: str, modelo: str, sistema: str, usuario: str) -> Any: ...

    def concluir(self, marca: Any, registro: RegistroChamada, saida: str | None) -> None: ...


def mascarar_segredos(dados: Any) -> Any:
    """Troca os valores das chaves do ambiente e cabeçalhos `Bearer` em qualquer estrutura."""
    if isinstance(dados, dict):
        return {chave: mascarar_segredos(valor) for chave, valor in dados.items()}
    if isinstance(dados, list | tuple):
        return [mascarar_segredos(valor) for valor in dados]
    if not isinstance(dados, str):
        return dados
    texto = _CABECALHO_BEARER.sub(MASCARA, dados)
    for nome in SEGREDOS_NO_AMBIENTE:
        segredo = (os.environ.get(nome) or "").strip()
        if segredo:
            texto = texto.replace(segredo, MASCARA)
    return texto


class RastroLocal:
    """Guarda os registros mais recentes em memória e os escreve no log."""

    def __init__(self, maximo: int = MAXIMO_DE_REGISTROS_LOCAIS) -> None:
        self.registros: deque[RegistroChamada] = deque(maxlen=maximo)

    def iniciar(self, *, etapa: str, modelo: str, sistema: str, usuario: str) -> None:
        return None

    def concluir(self, marca: Any, registro: RegistroChamada, saida: str | None) -> None:
        self.registros.append(registro)
        logger.info(
            "chamada de modelo: etapa=%s modelo=%s resultado=%s tokens=%d+%d custo_usd=%.6f "
            "estimado=%s tempo_s=%.3f erro=%s",
            registro.etapa,
            registro.modelo,
            registro.resultado,
            registro.tokens_entrada,
            registro.tokens_saida,
            registro.custo_usd,
            registro.custo_estimado,
            registro.tempo_s,
            registro.erro,
        )


class RastroLangfuse:
    """Cria uma geração por chamada no Langfuse e mantém o registro local como reserva."""

    def __init__(self, cliente: Any, local: RastroLocal) -> None:
        self._cliente = cliente
        self.registros_locais = local

    def iniciar(self, *, etapa: str, modelo: str, sistema: str, usuario: str) -> Any:
        return self._cliente.start_observation(
            as_type="generation",
            name=etapa,
            model=modelo,
            input=mascarar_segredos(
                [
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": usuario},
                ]
            ),
        )

    def concluir(self, marca: Any, registro: RegistroChamada, saida: str | None) -> None:
        self.registros_locais.concluir(None, registro, saida)
        if marca is None:
            return
        try:
            marca.update(
                output=mascarar_segredos(saida),
                usage_details={
                    "input": registro.tokens_entrada,
                    "output": registro.tokens_saida,
                },
                cost_details={"total": registro.custo_usd},
                metadata={
                    "custo_estimado": registro.custo_estimado,
                    "resultado": registro.resultado,
                },
                level="ERROR" if registro.erro else "DEFAULT",
                status_message=mascarar_segredos(registro.erro),
            )
        finally:
            marca.end()


def criar_rastro() -> Rastro:
    """Usa o Langfuse só com as duas credenciais; qualquer falha cai no rastro local."""
    local = RastroLocal()
    credenciais = (os.environ.get(nome) for nome in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))
    if not all(valor and valor.strip() for valor in credenciais):
        return local
    try:
        return RastroLangfuse(Langfuse(), local)
    except Exception as erro:  # rastro nunca derruba a chamada
        logger.warning("Langfuse indisponível (%s); usando rastro local", type(erro).__name__)
        return local
