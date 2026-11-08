"""`FonteCandidatos` por cima da cadeia, supressão pelo banco e estado visível das fontes.

Quem vem de provedor entra sempre sem autorização e como pendente: o funil o corta até a pessoa
autorizar. Nada aqui contata ninguém, e o contato vindo de provedor fica marcado como tal.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import ValidationError

from backend.agente.persistencia import resumos_da_pessoa
from backend.contratos.erros import FonteIndisponivel
from backend.contratos.interfaces import BancoTalentos, FonteCandidatos
from backend.contratos.modelos import Candidato, EstadoBanco
from backend.fontes.provedores.cadeia import CadeiaProvedores, ModoDados, VerificadorSupressao
from backend.fontes.provedores.modelos import (
    CONTATO_NAO_PUBLICADO,
    ConsultaProvedor,
    IdentidadeConsulta,
    ItemColetado,
    ResultadoCadeia,
    SituacaoConsulta,
    id_externo,
)

logger = logging.getLogger(__name__)

PAGINAS_POR_CONSULTA_PADRAO = 3
ROTULO_ATIVA = "fontes externas ativas"
ROTULO_SEM_FONTES = "sem fontes externas"
ROTULO_SINTETICOS = "somente dados sintéticos"
_DESCARTADOS_NA_LEITURA = frozenset({SituacaoConsulta.RECUSADA, SituacaoConsulta.SUPRIMIDO})


class SituacaoFontes(StrEnum):
    ATIVA = "ativa"
    SEM_FONTES_EXTERNAS = "sem_fontes_externas"
    SOMENTE_SINTETICOS = "somente_sinteticos"


@dataclass(frozen=True)
class EstadoFontes:
    """O que as telas e a API mostram: nunca há troca silenciosa para só o banco."""

    situacao: SituacaoFontes
    rotulo: str
    provedores: tuple[str, ...]
    avisos: tuple[str, ...] = ()


class Bloqueios(Protocol):
    """`Repositorio` cumpre. `BancoTalentos` cumpriria se expusesse a tabela de bloqueios dele."""

    def tem_bloqueio(self, empresa_id: str, resumos: list[str]) -> bool: ...


class SupressaoPorBanco:
    """Quem saiu fica de fora: opt-out e remoção no banco, além dos bloqueios por resumo."""

    def __init__(self, banco: BancoTalentos, *, bloqueios: Sequence[Bloqueios] = ()) -> None:
        self._banco = banco
        self._bloqueios = tuple(bloqueios)

    def suprimida(self, empresa_id: str, candidato_id: str, email: str | None) -> bool:
        atual = self._banco.obter(empresa_id, candidato_id)
        if atual is not None and (atual.opt_out or atual.estado == EstadoBanco.REMOVIDO):
            return True
        resumos = resumos_da_pessoa(empresa_id, candidato_id, email)
        return any(fonte.tem_bloqueio(empresa_id, resumos) for fonte in self._bloqueios)


def candidato_de_item(empresa_id: str, item: ItemColetado) -> Candidato:
    """Converte para o contrato atual. A procedência vem por último: dado externo não a troca."""
    atributos = dict(item.atributos)
    if item.email:
        atributos["email"] = item.email
        atributos["contato_origem"] = CONTATO_NAO_PUBLICADO
    if item.url:
        atributos["url"] = item.url
    atributos |= {
        "provedor": item.provedor,
        "confianca": item.confianca.value,
        "coletado_em": item.coletado_em.isoformat(),
    }
    return Candidato(
        id=id_externo(item),
        empresa_id=empresa_id,
        nome=item.nome,
        fonte=item.fonte,
        simulado=False,
        origem=item.url or item.fonte,
        atualizado_em=item.coletado_em.date(),
        autorizacao_valida_ate=None,
        estado=EstadoBanco.PENDENTE,
        perfil_texto=item.texto,
        atributos=atributos,
        historico=item.historico,
        autorizou_contato=False,
    )


class FonteProvedores:
    """Implementa `FonteCandidatos`. Falha de todos os provedores sobe como `FonteIndisponivel`."""

    def __init__(
        self,
        cadeia: CadeiaProvedores,
        *,
        supressao: VerificadorSupressao,
        banco: BancoTalentos | None = None,
        fonte_sintetica: FonteCandidatos | None = None,
        paginas_por_consulta: int = PAGINAS_POR_CONSULTA_PADRAO,
        avisos: Sequence[str] = (),
    ) -> None:
        self.cadeia = cadeia
        self._supressao = supressao
        self._banco = banco
        self._fonte_sintetica = fonte_sintetica
        self._paginas_por_consulta = paginas_por_consulta
        self._avisos = tuple(avisos)

    def estado(self) -> EstadoFontes:
        if self.cadeia.modo is ModoDados.SINTETICOS:
            return EstadoFontes(SituacaoFontes.SOMENTE_SINTETICOS, ROTULO_SINTETICOS, ())
        nomes = tuple(p.nome for p in self.cadeia.provedores)
        if not nomes:
            return EstadoFontes(
                SituacaoFontes.SEM_FONTES_EXTERNAS, ROTULO_SEM_FONTES, (), self._avisos
            )
        return EstadoFontes(SituacaoFontes.ATIVA, ROTULO_ATIVA, nomes, self._avisos)

    def metricas(self) -> dict:
        return self.cadeia.metricas.fotografia()

    def buscar(self, empresa_id: str, consulta: str, pagina: int = 1) -> list[Candidato]:
        if self.cadeia.modo is ModoDados.SINTETICOS:
            return self._buscar_sinteticos(empresa_id, consulta, pagina)
        try:
            pedido = ConsultaProvedor(texto=consulta, pagina=pagina)
        except ValidationError:  # o erro copia a consulta: nem a mensagem dele vai ao log
            logger.warning("consulta externa fora do formato: ignorada")
            return []
        resultado = self.coletar(empresa_id, pedido)
        return [candidato_de_item(empresa_id, item) for item in resultado.itens]

    def coletar(self, empresa_id: str, consulta: ConsultaProvedor) -> ResultadoCadeia:
        """O resultado local completo, para a conversão em `PerfilColetado` na integração."""
        resultado = self.cadeia.consultar(empresa_id, consulta)
        if consulta.texto is None or resultado.situacao != SituacaoConsulta.ENCONTRADO:
            return resultado
        return resultado.model_copy(update={"itens": self._aprofundar(empresa_id, resultado.itens)})

    def ler_pagina(self, empresa_id: str, url: str) -> ResultadoCadeia:
        return self.cadeia.consultar(empresa_id, ConsultaProvedor(url=url))

    def enriquecer(self, empresa_id: str, identidade: IdentidadeConsulta) -> ResultadoCadeia:
        return self.cadeia.consultar(empresa_id, ConsultaProvedor(identidade=identidade))

    def guardar(self, empresa_id: str, candidatos: list[Candidato]) -> list[Candidato]:
        """Grava como pendente quem pode voltar. `importar` também recusa remoção anterior."""
        if self._banco is None:
            raise ValueError("guardar exige um banco de talentos na montagem")
        permitidos = [
            c
            for c in candidatos
            if not self._supressao.suprimida(empresa_id, c.id, c.atributos.get("email"))
        ]
        gravados = self._banco.importar(empresa_id, [c.model_dump() for c in permitidos])
        return [c for c in gravados if not c.opt_out and c.estado != EstadoBanco.REMOVIDO]

    def _buscar_sinteticos(self, empresa_id: str, consulta: str, pagina: int) -> list[Candidato]:
        """Dado sem a marca de simulado não aparece no link público."""
        if self._fonte_sintetica is None:
            return []
        return [
            c for c in self._fonte_sintetica.buscar(empresa_id, consulta, pagina) if c.simulado
        ]

    def _aprofundar(self, empresa_id: str, itens: list[ItemColetado]) -> list[ItemColetado]:
        """Um trecho de busca não é perfil: lê as primeiras páginas, cada uma com os controles."""
        aprofundados: list[ItemColetado] = []
        for posicao, item in enumerate(itens):
            if posicao >= self._paginas_por_consulta or item.url is None:
                aprofundados.append(item)
                continue
            aprofundados.extend(self._ler_ou_manter(empresa_id, item))
        return aprofundados

    def _ler_ou_manter(self, empresa_id: str, item: ItemColetado) -> list[ItemColetado]:
        try:
            lido = self.ler_pagina(empresa_id, item.url)
        except FonteIndisponivel as erro:
            logger.info("página não lida, trecho mantido: %s", type(erro).__name__)
            return [item]
        if lido.situacao in _DESCARTADOS_NA_LEITURA:
            return []
        return lido.itens or [item]


