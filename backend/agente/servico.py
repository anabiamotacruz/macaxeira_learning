"""Casos de uso da vaga para a API: cria, executa, controla e consulta, sempre por empresa.

Regra de negócio continua em `fluxo.py` e `regras.py`. Este módulo guarda a vaga, monta um
`FluxoVaga` novo a cada pedido e impede duas execuções da mesma vaga ao mesmo tempo.
"""

import hashlib
import logging
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.agente.aprendizado import propor_ajuste
from backend.agente.auditoria import Auditoria, decisoes_vigentes
from backend.agente.configuracao import PerguntaVaga, PropostaComObservacoes
from backend.agente.contato_publicado import ContatoPorEmpresa
from backend.agente.documento import documento_de_ingestao
from backend.agente.documento_html import documento_html
from backend.agente.feedback import responder_pedido_de_feedback
from backend.agente.fluxo import (
    REGRA_REVERSAO,
    DuvidaConvite,
    FluxoVaga,
    Priorizador,
    ProvedorConsultas,
    RedatorConvite,
    RedatorRetorno,
    RegistroConvite,
    Reidentificador,
    RespondedorDuvida,
    RetornoEntrevista,
    concorrencia_do_ambiente,
    consulta_pelo_titulo,
    exigir_humano,
)
from backend.agente.mandato import MandatoInvalido, Politica
from backend.agente.palavras_chave import limpar_palavras_chave
from backend.agente.persistencia import Repositorio
from backend.agente.regras import requisitos_sem_valor, validar_criterios
from backend.contratos.erros import ErroContrato
from backend.contratos.interfaces import (
    AgenteRecrutador,
    Analisador,
    BancoTalentos,
    FonteCandidatos,
    Mensageiro,
    Revisor,
)
from backend.contratos.modelos import (
    Candidato,
    Contrato,
    Decisao,
    DestinoPessoa,
    EstadoVaga,
    EventoFluxo,
    FeedbackCandidato,
    Mandato,
    PacoteContexto,
    PedidoFeedback,
    PropostaAjuste,
    RespostaCandidato,
    ResumoExecucao,
    SaidaPersonalizada,
    TaxaMedida,
    TipoDecisao,
    TipoErro,
    TipoResposta,
    Vaga,
)
from backend.modelos.resiliencia import Resiliencia

logger = logging.getLogger(__name__)


class PropostaSemModelo(ErroContrato):
    """A proposta de critérios precisa do modelo, e esta montagem não tem um."""


class VagaInexistente(ErroContrato):
    """Vaga que não existe nesta empresa. Vale também para a vaga de outra empresa."""


class CandidatoInexistente(ErroContrato):
    """Pessoa sem decisão nesta empresa e vaga. Vale também para quem é de outra empresa."""


class CriteriosSensiveis(ErroContrato):
    """A vaga usa dado sensível como critério. Nada foi gravado."""


class RequisitoIncompleto(ErroContrato):
    """Requisito sem atributo ou valor esperado nunca eliminaria ninguém. Nada foi gravado."""


class AditivoNecessario(ErroContrato):
    """A pausa da vaga só termina com um novo mandato assinado."""


class ChaveReutilizada(ErroContrato):
    """A mesma chave de idempotência chegou com outro pedido."""


@dataclass(frozen=True)
class MetricasVaga:
    """Taxas medidas de uma vaga, vindas do provedor injetado."""

    sem_revisao: TaxaMedida
    erros_por_tipo: Mapping[TipoErro, TaxaMedida]


ProvedorMetricas = Callable[[str, str], MetricasVaga]
"""Recebe empresa e vaga. Sem provedor, a API segue com o exemplo fixo identificado."""


@dataclass(frozen=True)
class DependenciasFluxo:
    """Peças de todo `FluxoVaga`. Só `resiliencia` guarda estado em memória entre pedidos."""

    repositorio: Repositorio
    banco: BancoTalentos
    fontes: Sequence[FonteCandidatos]
    analisador: Analisador
    revisor: Revisor
    mensageiro: Mensageiro
    destino: AgenteRecrutador
    relogio: Callable[[], datetime]
    medidor_gasto: Callable[[], float]
    priorizador: Priorizador
    consultas: ProvedorConsultas = consulta_pelo_titulo
    resiliencia: Resiliencia = field(default_factory=Resiliencia)
    reidentificador: Reidentificador | None = None
    concorrencia: int = field(default_factory=concorrencia_do_ambiente)
    redator_convite: RedatorConvite | None = None
    respondedor_duvida: RespondedorDuvida | None = None
    redator_retorno: RedatorRetorno | None = None
    propositor_vaga: (
        Callable[[str, str], Vaga | PerguntaVaga | PropostaComObservacoes] | None
    ) = None
    """Recebe a descrição e a empresa. Sem ele, a proposta de critérios fica indisponível."""
    buscador_contato: ContatoPorEmpresa | None = None
    """EnvoAPI, só com a busca real e `ENVO_API_KEY`. Guarda o resultado por empresa e pessoa."""


def _novo_id_de_vaga() -> str:
    return f"vaga-{uuid.uuid4().hex[:12]}"


class ServicoVagas:
    """O que a API faz com as vagas, sempre dentro da empresa informada."""

    def __init__(
        self,
        dependencias: DependenciasFluxo,
        *,
        metricas: ProvedorMetricas | None = None,
        recarregar: Callable[[str], None] | None = None,
        gerar_id: Callable[[], str] = _novo_id_de_vaga,
        modelos_de_vaga: Sequence[dict] = (),
    ) -> None:
        self._dependencias = dependencias
        self.repositorio = dependencias.repositorio
        self._metricas = metricas
        self._recarregar = recarregar
        self._gerar_id = gerar_id
        self._modelos_de_vaga = [dict(m) for m in modelos_de_vaga]
        self._auditoria = Auditoria(dependencias.repositorio)
        self._trava_das_travas = threading.Lock()
        self._travas: dict[tuple[str, str], threading.RLock] = {}

    def _novo_fluxo(self, vaga: Vaga) -> FluxoVaga:
        d = self._dependencias
        return FluxoVaga(
            vaga,
            repositorio=d.repositorio,
            banco=d.banco,
            fontes=d.fontes,
            analisador=d.analisador,
            revisor=d.revisor,
            mensageiro=d.mensageiro,
            destino=d.destino,
            relogio=d.relogio,
            consultas=d.consultas,
            priorizador=d.priorizador,
            medidor_gasto=d.medidor_gasto,
            auditoria=self._auditoria,
            resiliencia=d.resiliencia,
            reidentificador=d.reidentificador,
            concorrencia=d.concorrencia,
            redator_convite=d.redator_convite,
            respondedor_duvida=d.respondedor_duvida,
            redator_retorno=d.redator_retorno,
            buscador_contato=d.buscador_contato,
        )

    def _fluxo(self, empresa_id: str, vaga_id: str) -> FluxoVaga:
        vaga = self.repositorio.carregar_vaga(empresa_id, vaga_id)
        if vaga is None:
            raise VagaInexistente("vaga não encontrada nesta empresa")
        return self._novo_fluxo(vaga)

    @contextmanager
    def _exclusivo(self, empresa_id: str, vaga_id: str) -> Iterator[None]:
        """Só uma execução por vaga neste processo. Parar não espera: é o que a interrompe."""
        with self._trava_das_travas:
            trava = self._travas.setdefault((empresa_id, vaga_id), threading.RLock())
        with trava:
            yield

    def vagas(self, empresa_id: str) -> list[Vaga]:
        return self.repositorio.listar_vagas(empresa_id)

    def criar_vaga(self, empresa_id: str, dados: dict[str, Any]) -> FluxoVaga:
        """Grava a vaga e a deixa à espera do mandato. Critério sensível não entra.

        As palavras-chave são gravadas já limpas: é o que a busca vai usar.
        """
        palavras = limpar_palavras_chave(dados.get("palavras_chave") or [])
        vaga = Vaga.model_validate(
            {**dados, "palavras_chave": palavras, "id": self._gerar_id(), "empresa_id": empresa_id}
        )
        if requisitos_sem_valor(vaga):
            raise RequisitoIncompleto("todo requisito precisa do atributo e do valor esperado")
        if validar_criterios(vaga):
            raise CriteriosSensiveis("a vaga usa dado sensível como critério")
        self.repositorio.salvar_vaga(vaga)
        fluxo = self._novo_fluxo(vaga)
        fluxo.iniciar()
        return fluxo

    def modelos_de_vaga(self) -> list[dict]:
        """Vagas de exemplo para preencher o formulário. Sem id nem empresa."""
        return [dict(m) for m in self._modelos_de_vaga]

    def consultar(self, empresa_id: str, vaga_id: str) -> FluxoVaga:
        return self._fluxo(empresa_id, vaga_id)

    def assinar(
        self,
        empresa_id: str,
        vaga_id: str,
        assinante: str,
        limite_gasto_usd: float,
        politica: Politica,
        valido_ate: datetime | None,
    ) -> tuple[Mandato, EstadoVaga]:
        """Registra a assinatura de uma pessoa, sem executar. Em vaga pausada, é um aditivo."""
        exigir_humano(assinante)
        fluxo = self._fluxo(empresa_id, vaga_id)
        with self._exclusivo(empresa_id, vaga_id):
            fluxo.assinar_mandato(assinante, limite_gasto_usd, politica, valido_ate, executar=False)
        return fluxo.mandato, fluxo.estado

    def executar(self, empresa_id: str, vaga_id: str) -> None:
        """Conduz a vaga até depender de algo externo. Roda em segundo plano."""
        with self._exclusivo(empresa_id, vaga_id):
            fluxo = self._fluxo(empresa_id, vaga_id)
            try:
                fluxo.continuar()
            except Exception as erro:  # sem chamador para avisar: registra e relança ao servidor
                logger.error("falha na execução da vaga %s: %s", vaga_id, type(erro).__name__)
                self.repositorio.registrar_evento(
                    EventoFluxo(
                        empresa_id=empresa_id,
                        vaga_id=vaga_id,
                        etapa="falha_execucao",
                        mensagem=f"execução interrompida: {type(erro).__name__}",
                        momento=self._dependencias.relogio(),
                    )
                )
                raise

    def parar(
        self, empresa_id: str, vaga_id: str, responsavel: str, motivo: str
    ) -> tuple[EstadoVaga, EstadoVaga]:
        """Pausa sem esperar a execução em curso, que sai antes do próximo candidato."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        anterior = fluxo.estado
        fluxo.parar(responsavel, motivo)
        return fluxo.estado, anterior

    def retomar(
        self, empresa_id: str, vaga_id: str, responsavel: str, motivo: str
    ) -> tuple[EstadoVaga, EstadoVaga]:
        """Tira da pausa sem executar: quem chama agenda `executar`."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        with self._exclusivo(empresa_id, vaga_id):
            anterior = fluxo.estado
            try:
                fluxo.retomar(executar=False, responsavel=responsavel, motivo=motivo)
            except MandatoInvalido as erro:
                raise AditivoNecessario("esta pausa só termina com um novo mandato") from erro
        return fluxo.estado, anterior

    def registrar_resposta(
        self, empresa_id: str, vaga_id: str, resposta: RespostaCandidato
    ) -> None:
        """Aplica a resposta da pessoa, recebida por `POST /convites/{id}/resposta`.

        Opt-out não espera a execução em curso: enquanto ela anda, novos contatos sairiam.
        """
        fluxo = self._fluxo(empresa_id, vaga_id)
        if resposta.tipo == TipoResposta.OPT_OUT:
            fluxo.registrar_resposta(resposta)
            return
        with self._exclusivo(empresa_id, vaga_id):
            fluxo.registrar_resposta(resposta)

    def convites(self, empresa_id: str, vaga_id: str) -> list[RegistroConvite]:
        return self._fluxo(empresa_id, vaga_id).convites()

    def acompanhar_entrevistas(self, empresa_id: str, vaga_id: str) -> list[RetornoEntrevista]:
        """Manda o retorno do destino a quem já foi entrevistado. Repetir não reenvia."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        with self._exclusivo(empresa_id, vaga_id):
            return fluxo.acompanhar_entrevistas()

    def entregar(self, empresa_id: str, vaga_id: str) -> tuple[list[str], list[str]]:
        """Entrega quem o fluxo já libera. Devolve quem foi entregue e quem ficou pendente."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        with self._exclusivo(empresa_id, vaga_id):
            return fluxo.entregar_indicados()

    def situacao_candidatos(
        self, empresa_id: str, vaga_id: str
    ) -> list[tuple[Candidato, TipoDecisao | None, DestinoPessoa | None]]:
        return self._fluxo(empresa_id, vaga_id).situacao_candidatos()

    def eventos(self, empresa_id: str, vaga_id: str) -> list[EventoFluxo]:
        return self._fluxo(empresa_id, vaga_id).eventos

    def saida(self, empresa_id: str, vaga_id: str) -> SaidaPersonalizada:
        """Os pacotes já entregues. Enquanto o envelope for simulado, a saída também é."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        return SaidaPersonalizada(
            empresa_id=empresa_id,
            vaga_id=vaga_id,
            pacotes=fluxo.pacotes_entregues(),
            simulado=True,
            momento=self._dependencias.relogio(),
        )

    def propor_vaga(
        self, empresa_id: str, descricao: str
    ) -> Vaga | PerguntaVaga | PropostaComObservacoes:
        """Critérios propostos a partir da descrição. Não cria vaga: a pessoa revisa e cria."""
        propositor = self._dependencias.propositor_vaga
        if propositor is None:
            raise PropostaSemModelo("a proposta de critérios precisa do modelo")
        return propositor(descricao, empresa_id)

    def sugestao_de_ajuste(self, empresa_id: str, vaga_id: str) -> PropostaAjuste | None:
        """Lê os resultados do destino e sugere ajuste. Só alerta: nada muda na vaga."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        try:
            resultados = self._dependencias.destino.resultados(empresa_id, vaga_id)
        except (ErroContrato, OSError) as erro:
            logger.warning("sem resultados do destino para sugerir ajuste: %s", type(erro).__name__)
            return None
        return propor_ajuste(fluxo.vaga, resultados)

    def documento(self, empresa_id: str, vaga_id: str, candidato_id: str) -> str:
        """O documento de ingestão de quem já foi entregue ao destino, com a conversa."""
        return documento_de_ingestao(*self._entregue(empresa_id, vaga_id, candidato_id))

    def documento_html(self, empresa_id: str, vaga_id: str, candidato_id: str) -> str:
        """O mesmo documento como dossiê HTML para o recrutador, pronto para salvar em PDF."""
        return documento_html(*self._entregue(empresa_id, vaga_id, candidato_id))

    def _entregue(
        self, empresa_id: str, vaga_id: str, candidato_id: str
    ) -> tuple[PacoteContexto, Vaga, list[DuvidaConvite]]:
        fluxo = self._fluxo(empresa_id, vaga_id)
        pacote = next(
            (p for p in fluxo.pacotes_entregues() if p.candidato_id == candidato_id), None
        )
        if pacote is None:
            raise CandidatoInexistente("não há entrega para esta pessoa nesta vaga")
        duvidas = [
            duvida
            for registro in fluxo.convites()
            if registro.convite.candidato_id == candidato_id
            for duvida in registro.duvidas
        ]
        return pacote, fluxo.vaga, duvidas

    def resumo(self, empresa_id: str, vaga_id: str) -> ResumoExecucao:
        fluxo = self._fluxo(empresa_id, vaga_id)
        resumo = fluxo.resumo()
        decisoes = self.repositorio.listar_decisoes(empresa_id, vaga_id)
        return ResumoExecucao(
            empresa_id=empresa_id,
            vaga_id=vaga_id,
            estado=resumo.estado,
            analisados=resumo.analisados,
            indicados=resumo.contagens["verde"],
            descartados=resumo.contagens["vermelha"],
            na_fila_humana=resumo.contagens["amarela"],
            revertidos=sum(d.regra == REGRA_REVERSAO for d in decisoes),
            gasto_usd=resumo.gasto_usd,
            limite_gasto_usd=resumo.limite_gasto_usd,
            simulado=True,
            momento=self._dependencias.relogio(),
        )

    def metricas(self, empresa_id: str, vaga_id: str) -> MetricasVaga | None:
        """As taxas do provedor injetado, ou None se ainda não há quem as meça."""
        self._fluxo(empresa_id, vaga_id)
        return None if self._metricas is None else self._metricas(empresa_id, vaga_id)

    def decisao(self, empresa_id: str, candidato_id: str, vaga_id: str | None) -> Decisao:
        """A decisão vigente na vaga pedida ou, sem vaga, a mais recente entre as da empresa."""
        if vaga_id is not None:
            self._fluxo(empresa_id, vaga_id)
            vagas = [vaga_id]
        else:
            vagas = [vaga.id for vaga in self.vagas(empresa_id)]
        achadas = [
            vigente
            for vaga in vagas
            if (vigente := self._decisao_na_vaga(empresa_id, vaga, candidato_id)) is not None
        ]
        if not achadas:
            raise CandidatoInexistente("candidato não encontrado nesta empresa")
        return max(achadas, key=lambda decisao: decisao.momento)

    def _decisao_na_vaga(self, empresa_id: str, vaga_id: str, candidato_id: str) -> Decisao | None:
        decisoes = self.repositorio.listar_decisoes(empresa_id, vaga_id)
        return decisoes_vigentes(decisoes).get(candidato_id)

    def responder_feedback(
        self,
        empresa_id: str,
        vaga_id: str,
        candidato_id: str,
        canal: str,
        texto: str = "",
        contestacao: bool = False,
    ) -> FeedbackCandidato:
        """Responde ao pedido da pessoa pela decisão vigente no registro, ou o encaminha.

        Só existe a pedido. Quem não tem decisão nesta empresa e vaga não existe para o pedido.
        """
        fluxo = self._fluxo(empresa_id, vaga_id)
        registro = self._decisao_na_vaga(empresa_id, vaga_id, candidato_id)
        candidato = next(
            (c for c, _, _ in fluxo.situacao_candidatos() if c.id == candidato_id), None
        )
        if registro is None or candidato is None:
            raise CandidatoInexistente("candidato não encontrado nesta empresa")
        agora = self._dependencias.relogio()
        pedido = PedidoFeedback(
            empresa_id=empresa_id,
            vaga_id=vaga_id,
            candidato_id=candidato_id,
            canal=canal,
            pedido_em=agora,
            texto=texto,
            contestacao=contestacao,
        )
        return responder_pedido_de_feedback(
            pedido,
            fluxo.vaga,
            candidato.nome,
            registrar=self.repositorio.registrar_evento,
            agora=agora,
            registro=registro,
        )

    def _exigir_candidato_na_vaga(self, empresa_id: str, vaga_id: str, candidato_id: str) -> None:
        if self._decisao_na_vaga(empresa_id, vaga_id, candidato_id) is None:
            raise CandidatoInexistente("candidato não encontrado nesta empresa")

    def reverter(
        self, empresa_id: str, vaga_id: str, candidato_id: str, motivo: str, responsavel: str
    ) -> tuple[Decisao, Decisao]:
        """Devolve a decisão original e a nova. A original continua no histórico."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        self._exigir_candidato_na_vaga(empresa_id, vaga_id, candidato_id)
        with self._exclusivo(empresa_id, vaga_id):
            nova = fluxo.reverter(candidato_id, motivo, responsavel)
        historico = [
            decisao
            for decisao in self.repositorio.listar_decisoes(empresa_id, vaga_id)
            if decisao.candidato_id == candidato_id and decisao.regra != REGRA_REVERSAO
        ]
        return historico[-1], nova

    def resolver_fila(
        self,
        empresa_id: str,
        vaga_id: str,
        candidato_id: str,
        tipo: TipoDecisao,
        motivo: str,
        responsavel: str,
    ) -> Decisao:
        """Uma pessoa do RH decide quem estava na fila humana: indicar ou descartar."""
        fluxo = self._fluxo(empresa_id, vaga_id)
        self._exigir_candidato_na_vaga(empresa_id, vaga_id, candidato_id)
        with self._exclusivo(empresa_id, vaga_id):
            return fluxo.resolver_fila(candidato_id, tipo, motivo, responsavel)

    def registrar_destino(
        self,
        empresa_id: str,
        vaga_id: str,
        candidato_id: str,
        destino: DestinoPessoa,
        responsavel: str,
    ) -> None:
        fluxo = self._fluxo(empresa_id, vaga_id)
        self._exigir_candidato_na_vaga(empresa_id, vaga_id, candidato_id)
        with self._exclusivo(empresa_id, vaga_id):
            fluxo.registrar_destino(candidato_id, destino, responsavel)

    def reiniciar(self, empresa_id: str) -> bool:
        """Apaga e recarrega os dados da empresa, se houver recarga. Sem ela, nada é apagado."""
        if self._recarregar is None:
            return False
        self.repositorio.apagar_empresa(empresa_id)
        self._recarregar(empresa_id)
        return True

    def idempotente[R: Contrato](
        self, empresa_id: str, escopo: str, pedido: str, tipo: type[R], acao: Callable[[], R]
    ) -> R:
        """Repetir com a mesma chave devolve a primeira resposta, sem refazer a ação.

        `escopo` identifica a ação e a chave; só o sucesso fica guardado.
        """
        resumo = hashlib.sha256(pedido.encode("utf-8")).hexdigest()
        guardada = self.repositorio.carregar_resposta(empresa_id, escopo)
        if guardada is None:
            guardada = self.repositorio.guardar_resposta(
                empresa_id, escopo, resumo, acao().model_dump_json()
            )
        if guardada[0] != resumo:
            raise ChaveReutilizada("a chave de idempotência já foi usada em outro pedido")
        return tipo.model_validate_json(guardada[1])
