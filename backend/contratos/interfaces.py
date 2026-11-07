"""Interfaces entre as frentes. Implementações são injetadas no construtor."""

from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from backend.contratos.modelos import (
    Analise,
    Candidato,
    Convite,
    PacoteContexto,
    ResultadoEntrevista,
    Vaga,
)


@runtime_checkable
class FonteCandidatos(Protocol):
    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]: ...


@runtime_checkable
class BancoTalentos(FonteCandidatos, Protocol):
    def importar(self, empresa_id: str, registros: list[dict]) -> list[Candidato]: ...

    def registrar_autorizacao(
        self, empresa_id: str, candidato_id: str, valida_ate: date
    ) -> Candidato: ...

    def atualizar(self, empresa_id: str, candidato_id: str, dados: dict[str, str]) -> Candidato: ...

    def registrar_opt_out(self, empresa_id: str, candidato_id: str) -> Candidato: ...

    def remover(self, empresa_id: str, candidato_id: str) -> None: ...

    def vencendo(self, empresa_id: str, ate: date) -> list[Candidato]: ...


@runtime_checkable
class Analisador(Protocol):
    def analisar(self, vaga: Vaga, candidato: Candidato) -> Analise: ...


@runtime_checkable
class Revisor(Protocol):
    def revisar(self, vaga: Vaga, candidato: Candidato, analise: Analise) -> Analise: ...


@runtime_checkable
class Mensageiro(Protocol):
    def enviar(self, convite: Convite) -> bool: ...


@runtime_checkable
class AgenteRecrutador(Protocol):
    """Destino do pacote de contexto. A Nara é a primeira integração.

    `link_agendamento` devolve None e `resultados` devolve lista vazia quando o
    destino não oferece agendamento ou retorno da entrevista.
    """

    def link_agendamento(self, vaga_id: str, candidato_id: str) -> str | None: ...

    def entregar(self, pacote: PacoteContexto) -> bool: ...

    def resultados(self, empresa_id: str, vaga_id: str) -> list[ResultadoEntrevista]: ...


@runtime_checkable
class ClienteModelo(Protocol):
    def completar(
        self, sistema: str, usuario: str, esquema: type[BaseModel], etapa: str
    ) -> BaseModel: ...
