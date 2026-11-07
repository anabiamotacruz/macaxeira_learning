"""Conector MCP: entrega o pacote de contexto a outro agente recrutador.

`ConectorMCP` implementa `AgenteRecrutador` chamando as ferramentas de um servidor MCP por
Streamable HTTP. Os nomes das ferramentas vêm de `DestinoMCP`; a Nara é o primeiro destino e
continua simulada e identificada até haver acesso real. O formato abaixo ainda precisa ser
combinado com a Frente 3:

- entrega: recebe `pacote` e `chave_idempotencia`; devolve `entregue` e a mesma chave, e o destino
  descarta chave repetida;
- agenda: recebe `empresa_id`, `vaga_id` e `candidato_id`; devolve `link`, que pode ser nulo;
- resultados: recebe `empresa_id` e `vaga_id`; devolve `resultados`, lista de `ResultadoEntrevista`.

A resposta do servidor é dado, nunca instrução: só o conteúdo estruturado é lido, depois de
validado, e o texto do servidor não vai para modelo, log, rastro ou mensagem de erro.
"""

import asyncio
import ipaddress
import logging
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, NoReturn, Self
from urllib.parse import urlsplit

from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import REQUEST_TIMEOUT, CallToolResult
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    model_validator,
)

from backend.agente.auditoria import contexto_atual, contexto_rastro, rastreado
from backend.contratos.erros import ErroContrato
from backend.contratos.modelos import Contrato, PacoteContexto, ResultadoEntrevista, Texto

logger = logging.getLogger(__name__)

TEMPO_LIMITE_PADRAO_S = 10.0
_TAMANHO_MAXIMO_LINK = 2048
_ESPACO_OU_CONTROLE = re.compile(r"[\s\x00-\x1f\x7f]")
_NOME_DE_VARIAVEL = re.compile(r"[A-Z][A-Z0-9_]*")


class ErroDestinoMCP(ErroContrato):
    """Falha previsível ao falar com o destino. O fluxo mantém a entrega pendente."""


class DestinoIndisponivel(ErroDestinoMCP):
    """Servidor fora do ar, erro de protocolo ou ferramenta que devolveu erro."""


class TempoLimiteDestino(DestinoIndisponivel):
    """O destino não respondeu dentro do tempo limite configurado."""


class RespostaDestinoInvalida(ErroDestinoMCP):
    """Resposta fora do formato combinado com o destino."""


class EmpresaForaDoEscopo(ErroDestinoMCP):
    """Pedido ou resultado de uma empresa diferente da configurada no destino."""


class DestinoMCP(Contrato):
    """Servidor MCP de um agente recrutador, sempre ligado a uma única empresa.

    Sem `ferramenta_agenda` ou `ferramenta_resultados`, o destino não oferece o recurso. Destino
    real precisa de `simulado=False` explícito. A chave de acesso nunca entra na URL nem aqui:
    `variavel_credencial` guarda só o nome da variável de ambiente, lida a cada chamada e enviada
    no cabeçalho `Authorization`.
    """

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    nome: Texto
    empresa_id: Texto
    url: HttpUrl
    ferramenta_entrega: Texto
    ferramenta_agenda: Texto | None = None
    ferramenta_resultados: Texto | None = None
    tempo_limite_s: Annotated[float, Field(gt=0, allow_inf_nan=False)] = TEMPO_LIMITE_PADRAO_S
    simulado: bool = True
    variavel_credencial: Texto | None = None

    @model_validator(mode="after")
    def _url_segura(self) -> Self:
        if self.url.username or self.url.password:
            raise ValueError("a URL do destino não pode conter credenciais")
        if self.url.scheme != "https" and not (self.simulado and _endereco_local(self.url.host)):
            raise ValueError("destino exige https; só simulação em endereço local dispensa")
        if self.variavel_credencial and not _NOME_DE_VARIAVEL.fullmatch(self.variavel_credencial):
            raise ValueError("variavel_credencial é o nome da variável, não a chave")
        return self


def _endereco_local(host: str | None) -> bool:
    """O pacote leva dados de candidatos: fora desta máquina, ele não trafega sem criptografia."""
    nome = (host or "").strip("[]").casefold().rstrip(".")
    if nome == "localhost" or nome.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(nome).is_loopback
    except ValueError:
        return False


def _link_seguro(valor: str) -> str:
    """O link vai para o convite da pessoa: só https, com host e sem texto solto."""
    partes = urlsplit(valor)
    if (
        partes.scheme != "https"
        or not partes.hostname
        or partes.username
        or partes.password
        or len(valor) > _TAMANHO_MAXIMO_LINK
        or _ESPACO_OU_CONTROLE.search(valor)
    ):
        raise ValueError("link fora do formato")
    return valor


class _RespostaEntrega(BaseModel):
    entregue: bool
    chave_idempotencia: str


class _RespostaAgenda(BaseModel):
    link: Annotated[str, AfterValidator(_link_seguro)] | None


class _RespostaResultados(BaseModel):
    resultados: list[ResultadoEntrevista]


class ConectorMCP:
    """`AgenteRecrutador` que abre uma conexão MCP por chamada, sem estado entre chamadas.

    A interface é síncrona: a chamada bloqueia quem a fez até o tempo limite. Falhas viram erros
    de `ErroContrato`, que o fluxo trata deixando a entrega pendente para repetir com a mesma chave.
    """

    def __init__(self, destino: DestinoMCP) -> None:
        self._destino = destino

    @property
    def simulado(self) -> bool:
        return self._destino.simulado

    def link_agendamento(self, vaga_id: str, candidato_id: str) -> str | None:
        self._exigir_escopo(self._destino.empresa_id)
        ferramenta = self._destino.ferramenta_agenda
        if ferramenta is None:
            return None
        argumentos = {
            "empresa_id": self._destino.empresa_id,
            "vaga_id": vaga_id,
            "candidato_id": candidato_id,
        }

        def interpretar(dados: dict[str, Any]) -> str | None:
            return _RespostaAgenda.model_validate(dados, strict=True).link

        return self._chamar(ferramenta, argumentos, interpretar, vaga_id, candidato_id)

    def entregar(self, pacote: PacoteContexto) -> bool:
        self._exigir_escopo(pacote.empresa_id)
        ferramenta = self._destino.ferramenta_entrega
        argumentos = {
            "pacote": pacote.model_dump(mode="json"),
            "chave_idempotencia": pacote.chave_idempotencia,
        }

        def interpretar(dados: dict[str, Any]) -> bool:
            resposta = _RespostaEntrega.model_validate(dados, strict=True)
            if resposta.chave_idempotencia != pacote.chave_idempotencia:
                raise RespostaDestinoInvalida(self._mensagem(ferramenta, "confirmou outra entrega"))
            return resposta.entregue

        return self._chamar(
            ferramenta, argumentos, interpretar, pacote.vaga_id, pacote.candidato_id
        )

    def resultados(self, empresa_id: str, vaga_id: str) -> list[ResultadoEntrevista]:
        self._exigir_escopo(empresa_id)
        ferramenta = self._destino.ferramenta_resultados
        if ferramenta is None:
            return []
        argumentos = {"empresa_id": empresa_id, "vaga_id": vaga_id}

        def interpretar(dados: dict[str, Any]) -> list[ResultadoEntrevista]:
            resposta = _RespostaResultados.model_validate(dados, strict=True)
            return [self._conferir(r, ferramenta, vaga_id) for r in resposta.resultados]

        return self._chamar(ferramenta, argumentos, interpretar, vaga_id)

    def _conferir(
        self, resultado: ResultadoEntrevista, ferramenta: str, vaga_id: str
    ) -> ResultadoEntrevista:
        """Um resultado fora do escopo recusa a resposta inteira, sem repetir o conteúdo."""
        if resultado.empresa_id != self._destino.empresa_id:
            raise EmpresaForaDoEscopo(self._mensagem(ferramenta, "devolveu outra empresa"))
        if resultado.vaga_id != vaga_id:
            raise RespostaDestinoInvalida(self._mensagem(ferramenta, "devolveu outra vaga"))
        simulado = resultado.simulado or self._destino.simulado
        return resultado.model_copy(update={"simulado": simulado})

    def _exigir_escopo(self, empresa_id: str) -> None:
        """Recusa, antes de qualquer chamada, empresa diferente da configurada no destino."""
        empresa = self._destino.empresa_id
        atual = contexto_atual()
        if empresa_id == empresa and (atual is None or atual.empresa_id == empresa):
            return
        logger.warning("destino %s recusou empresa fora do escopo", self._destino.nome)
        rastreado(self._etapa("escopo"))(self._recusar_empresa)()

    def _recusar_empresa(self) -> NoReturn:
        raise EmpresaForaDoEscopo(f"destino {self._destino.nome}: empresa fora do escopo")

    def _etapa(self, sufixo: str) -> str:
        prefixo = "destino_mcp_simulado" if self._destino.simulado else "destino_mcp"
        return f"{prefixo}:{self._destino.nome}:{sufixo}"

    def _mensagem(self, ferramenta: str, problema: str) -> str:
        return f"destino {self._destino.nome}, ferramenta {ferramenta}: {problema}"

    def _chamar[T](
        self,
        ferramenta: str,
        argumentos: dict[str, Any],
        interpretar: Callable[[dict[str, Any]], T],
        vaga_id: str,
        candidato_id: str | None = None,
    ) -> T:
        """Registra a chamada e a interpretação no rastro: resposta recusada conta como falha."""
        with contexto_rastro(
            empresa_id=self._destino.empresa_id, vaga_id=vaga_id, candidato_id=candidato_id
        ):
            medir = rastreado(self._etapa(ferramenta))(self._chamar_e_interpretar)
            return medir(ferramenta, argumentos, interpretar)

    def _chamar_e_interpretar[T](
        self,
        ferramenta: str,
        argumentos: dict[str, Any],
        interpretar: Callable[[dict[str, Any]], T],
    ) -> T:
        resultado = self._executar(ferramenta, argumentos)
        if resultado.is_error:
            raise DestinoIndisponivel(self._mensagem(ferramenta, "a ferramenta devolveu erro"))
        if resultado.structured_content is None:
            raise RespostaDestinoInvalida(self._mensagem(ferramenta, "resposta sem dados"))
        try:
            return interpretar(resultado.structured_content)
        except ValidationError:  # a mensagem de validação repete o texto do servidor
            raise RespostaDestinoInvalida(
                self._mensagem(ferramenta, "resposta fora do formato")
            ) from None

    def _executar(self, ferramenta: str, argumentos: dict[str, Any]) -> CallToolResult:
        """Roda o cliente assíncrono numa thread própria, com ou sem laço ativo em quem chamou.

        Só o tipo da falha vai ao log, e `from None` tira do erro o texto vindo do servidor.
        """
        tempo_limite = self._mensagem(
            ferramenta, f"sem resposta em {self._destino.tempo_limite_s:g} s (tempo limite)"
        )
        fora_do_ar = self._mensagem(ferramenta, "servidor indisponível")
        cabecalhos = self._cabecalhos(ferramenta)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                chamada = self._chamar_servidor(ferramenta, argumentos, cabecalhos)
                return executor.submit(asyncio.run, chamada).result()
        except TimeoutError:
            raise TempoLimiteDestino(tempo_limite) from None
        except MCPError as erro:
            if erro.code == REQUEST_TIMEOUT:
                raise TempoLimiteDestino(tempo_limite) from None
            logger.warning("%s: código %s", fora_do_ar, erro.code)
            raise DestinoIndisponivel(fora_do_ar) from None
        except (ValidationError, RuntimeError) as erro:  # o SDK recusou o que o servidor mandou
            logger.warning("%s: %s", ferramenta, type(erro).__name__)
            raise RespostaDestinoInvalida(
                self._mensagem(ferramenta, "resposta fora do protocolo")
            ) from None
        except Exception as erro:  # o transporte do SDK levanta tipos variados, até em grupo
            logger.warning("%s: %s", fora_do_ar, type(erro).__name__)
            raise DestinoIndisponivel(fora_do_ar) from None

    def _cabecalhos(self, ferramenta: str) -> dict[str, str] | None:
        """Sem a variável, nada sai: o destino recusaria, e a entrega fica pendente."""
        variavel = self._destino.variavel_credencial
        if variavel is None:
            return None
        credencial = os.environ.get(variavel, "").strip()
        if not credencial:
            raise DestinoIndisponivel(self._mensagem(ferramenta, "credencial não configurada"))
        return {"Authorization": f"Bearer {credencial}"}

    async def _chamar_servidor(
        self, ferramenta: str, argumentos: dict[str, Any], cabecalhos: dict[str, str] | None = None
    ) -> CallToolResult:
        """O tempo limite cobre conexão, negociação e chamada."""
        url = str(self._destino.url)
        async with asyncio.timeout(self._destino.tempo_limite_s):
            if cabecalhos is None:
                async with Client(url) as cliente:
                    return await cliente.call_tool(ferramenta, argumentos)
            async with create_mcp_http_client(headers=cabecalhos) as http:
                async with Client(streamable_http_client(url, http_client=http)) as cliente:
                    return await cliente.call_tool(ferramenta, argumentos)
