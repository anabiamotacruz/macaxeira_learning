"""Cadeia de provedores de dados externos: tenta na ordem e registra cada troca.

Falha de todos sobe como `ProvedoresIndisponiveis`, um `FonteIndisponivel`: o fluxo segue com
cobertura parcial. Política, supressão e orçamento são conferidos aqui, em código determinístico,
antes de qualquer provedor ser chamado.
"""

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from backend.agente.auditoria import SEM_CONTEXTO, contexto_atual
from backend.contratos.erros import FonteIndisponivel
from backend.fontes.provedores.controles import (
    CacheConsultas,
    CacheDescobertas,
    MetricasProvedores,
    OrcamentoProvedores,
)
from backend.fontes.provedores.erros import (
    ErroProvedor,
    MotivoTroca,
    ProvedoresIndisponiveis,
    UrlRecusada,
)
from backend.fontes.provedores.modelos import (
    ConsultaProvedor,
    ItemColetado,
    ProvedorDados,
    RespostaProvedor,
    ResultadoCadeia,
    SituacaoConsulta,
    Troca,
    id_externo,
    id_externo_de_email,
    id_externo_de_url,
)
from backend.fontes.provedores.url_segura import (
    validar_forma,
    validar_perfil,
    validar_texto_de_busca,
)
from backend.modelos.resiliencia import (
    ERROS_TEMPORARIOS,
    ESPERA_DO_DISJUNTOR_PADRAO_S,
    LIMITE_DE_FALHAS_PADRAO,
    TEMPO_LIMITE_INTEGRACAO_S,
    DisjuntorFonte,
    EstadoDisjuntor,
    com_tentativas,
)

logger = logging.getLogger(__name__)

TENTATIVAS_PADRAO = 2
"""O fluxo também repete a fonte inteira: aqui só o bastante para uma queda passageira."""
TRAVAS_POR_CONSULTA = 64


class ModoDados(StrEnum):
    REAIS = "reais"
    SINTETICOS = "sinteticos"


@runtime_checkable
class VerificadorSupressao(Protocol):
    """Diz se a pessoa saiu: opt-out, remoção ou bloqueio. Falha deve subir, nunca virar False."""

    def suprimida(self, empresa_id: str, candidato_id: str, email: str | None) -> bool: ...


def _so_descoberta(provedor: ProvedorDados) -> bool:
    """Provedor cujo resultado só aponta páginas a ler, como a Brave."""
    return getattr(provedor, "so_descoberta", False) is True


@dataclass
class _Percurso:
    """O andamento de uma consulta pela cadeia."""

    empresa_id: str
    execucao_id: str
    consulta: ConsultaProvedor
    trocas: list[Troca] = field(default_factory=list)
    falhas: list[tuple[str, MotivoTroca]] = field(default_factory=list)
    responderam: bool = False
    custo: float = 0.0


class CadeiaProvedores:
    """Implementa a ordem da cadeia. Compartilhe o objeto entre execuções: guarda os disjuntores."""

    def __init__(
        self,
        provedores: Sequence[ProvedorDados],
        *,
        supressao: VerificadorSupressao,
        orcamento: OrcamentoProvedores,
        cache: CacheConsultas | None = None,
        cache_descobertas: CacheDescobertas | None = None,
        metricas: MetricasProvedores | None = None,
        modo: ModoDados = ModoDados.REAIS,
        tentativas: int = TENTATIVAS_PADRAO,
        espera: float = 1.0,
        tempo_limite: float = TEMPO_LIMITE_INTEGRACAO_S,
        limite_falhas: int = LIMITE_DE_FALHAS_PADRAO,
        espera_disjuntor: float = ESPERA_DO_DISJUNTOR_PADRAO_S,
        dormir: Callable[[float], None] = time.sleep,
        relogio_disjuntor: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provedores = tuple(provedores)
        self.modo = modo
        self.metricas = metricas or MetricasProvedores()
        self._supressao = supressao
        self._orcamento = orcamento
        self._cache = cache or CacheConsultas()
        self._descobertas = cache_descobertas or CacheDescobertas()
        self._tentativas = tentativas
        self._espera = espera
        self._tempo_limite = tempo_limite
        self._dormir = dormir
        self._disjuntores = {
            p.nome: DisjuntorFonte(
                p.nome,
                limite_falhas=limite_falhas,
                espera=espera_disjuntor,
                relogio=relogio_disjuntor,
            )
            for p in self.provedores
        }
        self._travas = [threading.Lock() for _ in range(TRAVAS_POR_CONSULTA)]

    def consultar(self, empresa_id: str, consulta: ConsultaProvedor) -> ResultadoCadeia:
        if not isinstance(empresa_id, str) or not empresa_id.strip():
            raise ValueError("empresa_id é obrigatório")
        empresa_id = empresa_id.strip()
        if self.modo is ModoDados.SINTETICOS:
            return ResultadoCadeia(situacao=SituacaoConsulta.SOMENTE_SINTETICOS)
        if not self.provedores:
            logger.warning("consulta externa ignorada: sem fontes externas configuradas")
            return ResultadoCadeia(situacao=SituacaoConsulta.SEM_FONTES_EXTERNAS)
        try:
            self._validar_politica(consulta)
        except UrlRecusada as erro:
            return ResultadoCadeia(situacao=SituacaoConsulta.RECUSADA, motivo_recusa=erro.motivo)
        if self._consulta_suprimida(empresa_id, consulta):
            return ResultadoCadeia(situacao=SituacaoConsulta.SUPRIMIDO)

        chave = consulta.chave()
        execucao = self._execucao_atual()
        trava = self._travas[hash((empresa_id, chave)) % TRAVAS_POR_CONSULTA]
        with trava:  # a segunda chamada igual espera e sai pelo cache: não paga de novo
            guardado = self._descobertas.obter(empresa_id, execucao, chave)
            if guardado is not None:
                return self._do_cache(
                    consulta,
                    guardado,
                    empresa_id,
                    lambda: self._descobertas.esquecer(empresa_id, execucao, chave),
                )
            guardado = self._cache.obter(empresa_id, chave)
            if guardado is not None:
                return self._do_cache(
                    consulta, guardado, empresa_id, lambda: self._cache.esquecer(empresa_id, chave)
                )
            resultado = self._percorrer(empresa_id, consulta)
            if self._pode_guardar(resultado):
                self._guardar(empresa_id, execucao, chave, consulta, resultado)
        return resultado

    def _guardar(
        self,
        empresa_id: str,
        execucao: str,
        chave: str,
        consulta: ConsultaProvedor,
        resultado: ResultadoCadeia,
    ) -> None:
        """Resultado de descoberta só fica no cache da execução, e fora de uma, em lugar nenhum."""
        if not self._de_descoberta(consulta, resultado):
            self._cache.guardar(empresa_id, chave, resultado)
        elif execucao != SEM_CONTEXTO:
            self._descobertas.guardar(empresa_id, execucao, chave, resultado)

    def _de_descoberta(self, consulta: ConsultaProvedor, resultado: ResultadoCadeia) -> bool:
        """Também o vazio: "a Brave não achou" ainda é resultado dela."""
        if resultado.itens:
            return any(item.descoberta for item in resultado.itens)
        return any(_so_descoberta(p) and p.aceita(consulta) for p in self.provedores)

    @staticmethod
    def _validar_politica(consulta: ConsultaProvedor) -> None:
        if consulta.url is not None:
            validar_forma(consulta.url)
        if consulta.texto is not None:
            validar_texto_de_busca(consulta.texto)
        if consulta.identidade is not None and consulta.identidade.perfil:
            validar_perfil(consulta.identidade.perfil)

    def _suprimida(self, empresa_id: str, candidato_id: str, email: str | None) -> bool:
        """Sem como conferir, ninguém é consultado: nem quem saiu pode voltar por uma falha."""
        try:
            return self._supressao.suprimida(empresa_id, candidato_id, email)
        except Exception as erro:  # a mensagem pode trazer dado pessoal: só o tipo vai ao log
            logger.warning("falha ao conferir supressão: %s", type(erro).__name__)
            raise FonteIndisponivel("supressão indisponível: consulta não enviada") from None

    def _consulta_suprimida(self, empresa_id: str, consulta: ConsultaProvedor) -> bool:
        identidade = consulta.identidade
        email = identidade.email if identidade else None
        ids = []
        if identidade and identidade.candidato_id:
            ids.append(identidade.candidato_id)
        if email:
            ids.append(id_externo_de_email(email))
        if identidade and identidade.perfil:
            ids.append(id_externo_de_url(identidade.perfil))
        if consulta.url:
            ids.append(id_externo_de_url(consulta.url))
        return any(self._suprimida(empresa_id, candidato_id, email) for candidato_id in ids)

    def _item_suprimido(
        self, empresa_id: str, consulta: ConsultaProvedor, item: ItemColetado
    ) -> bool:
        ids = {id_externo(item)}
        if item.url:
            ids.add(id_externo_de_url(item.url))
        if consulta.identidade and consulta.identidade.candidato_id:
            ids.add(consulta.identidade.candidato_id)
        return any(self._suprimida(empresa_id, c, item.email) for c in sorted(ids))

    def _sem_suprimidos(
        self, empresa_id: str, consulta: ConsultaProvedor, itens: list[ItemColetado]
    ) -> list[ItemColetado]:
        return [i for i in itens if not self._item_suprimido(empresa_id, consulta, i)]

    def _do_cache(
        self,
        consulta: ConsultaProvedor,
        guardado: ResultadoCadeia,
        empresa_id: str,
        esquecer: Callable[[], None],
    ) -> ResultadoCadeia:
        """Quem saiu depois de guardado não volta: a supressão é conferida a cada leitura."""
        self.metricas.registrar_acerto_de_cache()
        itens = self._sem_suprimidos(empresa_id, consulta, guardado.itens)
        if guardado.itens and not itens:
            esquecer()
            return ResultadoCadeia(
                situacao=SituacaoConsulta.SUPRIMIDO, suprimidos=len(guardado.itens), do_cache=True
            )
        return guardado.model_copy(
            update={
                "itens": itens,
                "do_cache": True,
                "custo_usd": 0.0,
                "suprimidos": guardado.suprimidos + len(guardado.itens) - len(itens),
            }
        )

    @staticmethod
    def _pode_guardar(resultado: ResultadoCadeia) -> bool:
        if resultado.situacao == SituacaoConsulta.ENCONTRADO:
            return True
        return resultado.situacao == SituacaoConsulta.NAO_ENCONTRADO and not (
            resultado.cobertura_parcial
        )

    def _percorrer(self, empresa_id: str, consulta: ConsultaProvedor) -> ResultadoCadeia:
        percurso = _Percurso(empresa_id, self._execucao_atual(), consulta)
        for indice in range(len(self.provedores)):
            final = self._tentar(indice, percurso)
            if final is not None:
                return final
        if percurso.responderam:
            return ResultadoCadeia(
                situacao=SituacaoConsulta.NAO_ENCONTRADO,
                trocas=percurso.trocas,
                custo_usd=percurso.custo,
                cobertura_parcial=bool(percurso.falhas),
            )
        if percurso.falhas:
            raise ProvedoresIndisponiveis(percurso.falhas)
        return ResultadoCadeia(situacao=SituacaoConsulta.NAO_SUPORTADA, trocas=percurso.trocas)

    def _trocar(self, indice: int, percurso: "_Percurso", motivo: MotivoTroca) -> None:
        nome = self.provedores[indice].nome
        seguinte = self.provedores[indice + 1].nome if indice + 1 < len(self.provedores) else None
        percurso.trocas.append(Troca(de=nome, para=seguinte, motivo=motivo))
        self.metricas.registrar_troca(nome, motivo)
        logger.info("troca de provedor: de=%s para=%s motivo=%s", nome, seguinte, motivo.value)

    def _falhou(self, indice: int, percurso: "_Percurso", motivo: MotivoTroca) -> None:
        percurso.falhas.append((self.provedores[indice].nome, motivo))
        self._trocar(indice, percurso, motivo)

    def _tentar(self, indice: int, percurso: "_Percurso") -> ResultadoCadeia | None:
        """Um provedor. `None` significa seguir para o próximo."""
        provedor = self.provedores[indice]
        consulta = percurso.consulta
        if not provedor.aceita(consulta):
            self._trocar(indice, percurso, MotivoTroca.CONSULTA_NAO_SUPORTADA)
            return None
        reserva = self._orcamento.reservar(
            percurso.empresa_id, percurso.execucao_id, provedor.custo_maximo(consulta)
        )
        if reserva is None:
            self._falhou(indice, percurso, MotivoTroca.ORCAMENTO_ESGOTADO)
            return None
        if self._disjuntores[provedor.nome].estado is EstadoDisjuntor.ABERTO:
            self._orcamento.liquidar(reserva, 0.0)
            self._falhou(indice, percurso, MotivoTroca.DISJUNTOR_ABERTO)
            return None
        try:
            resposta = self._chamar(provedor, consulta)
        except UrlRecusada as erro:
            self._orcamento.liquidar(reserva, erro.custo_usd)
            self.metricas.registrar_falha(provedor.nome, erro.custo_usd)
            return ResultadoCadeia(
                situacao=SituacaoConsulta.RECUSADA,
                trocas=percurso.trocas,
                custo_usd=percurso.custo + erro.custo_usd,
                motivo_recusa=erro.motivo,
            )
        except ErroProvedor as erro:
            self._orcamento.liquidar(reserva, erro.custo_usd)
            self.metricas.registrar_falha(provedor.nome, erro.custo_usd)
            percurso.custo += erro.custo_usd
            self._falhou(indice, percurso, erro.motivo)
            return None
        except ERROS_TEMPORARIOS:
            self._orcamento.liquidar(reserva, 0.0)
            self.metricas.registrar_falha(provedor.nome, 0.0)
            self._falhou(indice, percurso, MotivoTroca.FALHA_TEMPORARIA)
            return None
        except BaseException:
            self._orcamento.liquidar(reserva, reserva.valor)  # na dúvida, conta como gasto
            raise
        self._orcamento.liquidar(reserva, resposta.custo_usd)
        percurso.custo += resposta.custo_usd
        return self._aproveitar(indice, percurso, resposta)

    def _aproveitar(
        self, indice: int, percurso: "_Percurso", resposta: RespostaProvedor
    ) -> ResultadoCadeia | None:
        nome = self.provedores[indice].nome
        itens = self._sem_suprimidos(percurso.empresa_id, percurso.consulta, resposta.itens)
        if resposta.itens and not itens:  # todos saíram: o próximo provedor cobraria à toa
            self.metricas.registrar_nao_encontrado(nome, resposta.custo_usd)
            return ResultadoCadeia(
                situacao=SituacaoConsulta.SUPRIMIDO,
                trocas=percurso.trocas,
                custo_usd=percurso.custo,
                suprimidos=len(resposta.itens),
            )
        if itens:
            self.metricas.registrar_acerto(nome, resposta.custo_usd)
            return ResultadoCadeia(
                situacao=SituacaoConsulta.ENCONTRADO,
                provedor=nome,
                itens=itens,
                trocas=percurso.trocas,
                custo_usd=percurso.custo,
                suprimidos=len(resposta.itens) - len(itens),
                cobertura_parcial=bool(percurso.falhas),
            )
        self.metricas.registrar_nao_encontrado(nome, resposta.custo_usd)
        percurso.responderam = True
        self._trocar(indice, percurso, MotivoTroca.NAO_ENCONTRADO)
        return None

    def _chamar(self, provedor: ProvedorDados, consulta: ConsultaProvedor) -> RespostaProvedor:
        """Repetição por dentro do disjuntor. Resposta fora do contrato é erro permanente."""

        def tentar() -> RespostaProvedor:
            try:
                return provedor.consultar(consulta)
            except ValidationError:  # o erro do pydantic copia o dado recebido: não vai adiante
                raise ErroProvedor(MotivoTroca.RESPOSTA_INVALIDA) from None

        return self._disjuntores[provedor.nome].chamar(
            lambda: com_tentativas(
                tentar,
                self._tentativas,
                self._espera,
                self._tempo_limite,
                etapa=f"provedor:{provedor.nome}",
                dormir=self._dormir,
            )
        )

    @staticmethod
    def _execucao_atual() -> str:
        """O orçamento por execução usa o contexto do rastro. Fora dele, todos dividem um só."""
        contexto = contexto_atual()
        return contexto.execucao_id if contexto else SEM_CONTEXTO
