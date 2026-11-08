"""Máquina de estados de uma vaga e a condução do fluxo por ela.

Os estados não citam um destino específico: agendamento e retorno da entrevista são
opcionais. `FluxoVaga` não guarda estado em memória: tudo o que permite continuar está
no `Repositorio`, e um novo objeto sobre o mesmo arquivo continua de onde o outro parou.

Respostas podem chegar durante uma execução. Por isso o progresso nunca é regravado inteiro:
`_mudar` aplica só a mudança sobre o que está salvo agora. A cópia da busca nunca decide
contato ou entrega: `_candidato_atual` consulta o banco e os opt-outs da empresa antes de cada um.
"""

import contextvars
import hashlib
import logging
import os
import threading
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from functools import partial
from itertools import count

from pydantic import AwareDatetime, Field

from backend.agente.auditoria import (
    MOTIVO_AUDITORIA_REPROVADA,
    REGRA_DUPLICATA,
    Auditoria,
    ContextoRastro,
    DecisaoIncompleta,
    DecisoesAutomaticasPausadas,
    contexto_rastro,
    decisoes_vigentes,
    rastreado,
)
from backend.agente.mandato import (
    Mandato,
    MandatoInvalido,
    ModoEntrega,
    Politica,
    assinar,
    hash_da_vaga,
    mandato_valido,
)
from backend.agente.maquina import ESTADOS_ATIVOS, TRANSICOES
from backend.agente.persistencia import Repositorio, resumos_da_pessoa
from backend.agente.regras import (
    CORTES_POR_AUTORIZACAO,
    CORTES_SEM_DECISAO,
    CorteFunil,
    StatusRequisito,
    TipoEvidencia,
    autorizacao_ativa,
    avaliar_requisitos,
    classificar_evidencia,
    corte_de_autorizacao,
    criterios_sem_evidencia,
    decidir,
    decisao_de_corte,
    decisao_por_novos_requisitos,
    decisao_sem_analise,
    nao_priorizada,
    parece_instrucao,
    pode_contatar,
    separar_palavras,
    validar_criterios,
)
from backend.contratos.criterios import tem_termo_sensivel
from backend.contratos.erros import (
    ErroContrato,
    LimiteGastoAtingido,
    ModeloIndisponivel,
    RespostaInvalida,
)
from backend.contratos.interfaces import (
    AgenteRecrutador,
    Analisador,
    BancoTalentos,
    FonteCandidatos,
    Mensageiro,
    Revisor,
)
from backend.contratos.modelos import (
    Analise,
    Candidato,
    Contrato,
    Convite,
    Decisao,
    DestinoPessoa,
    EstadoBanco,
    EstadoFluxo,
    EventoFluxo,
    Evidencia,
    PacoteContexto,
    RespostaCandidato,
    TipoConvite,
    TipoDecisao,
    TipoResposta,
    Vaga,
)
from backend.modelos.resiliencia import ERROS_TEMPORARIOS, Resiliencia

logger = logging.getLogger(__name__)

ProvedorConsultas = Callable[[Vaga, int, Sequence[str]], list[str]]
"""Recebe a vaga, a rodada e as consultas já usadas. Devolve as consultas desta rodada."""

RegistrarCorte = Callable[[CorteFunil], None]
Priorizador = Callable[[Vaga, list[Candidato], date, RegistrarCorte], list[Candidato]]
RedatorConvite = Callable[[Vaga, Candidato, Analise, str | None], str]
"""Escreve o texto do convite a partir da análise. Sem ele, o convite usa um texto fixo."""
Reidentificador = Callable[[PacoteContexto, Candidato, Vaga, Decisao], PacoteContexto]
"""Reduz os achados antes das análises e informa quem saiu, por `RegistrarCorte`."""


class TransicaoInvalida(ErroContrato):
    """Transição fora da tabela ou sem a guarda exigida."""


class AcaoRecusada(ErroContrato, ValueError):
    """A ação não vale para esta pessoa agora. A mensagem é segura para mostrar."""


class ResponsavelInvalido(ErroContrato, ValueError):
    """A ação é de uma pessoa, e o responsável informado não identifica uma."""


def _transitar(
    estado: EstadoFluxo,
    destino: EstadoFluxo,
    *,
    vaga: Vaga,
    mandato: Mandato | None,
    agora: datetime,
    estado_anterior: EstadoFluxo | None = None,
    motivo: str = "",
) -> tuple[EstadoFluxo, EventoFluxo]:
    """Devolve o novo estado e o evento da transição, ou levanta `TransicaoInvalida`.

    `estado_anterior` é o estado salvo ao pausar, exigido só para sair de `PAUSADA`.
    Pausar e concluir não exigem mandato, para o fluxo sempre poder parar quando ele
    deixa de valer. As demais guardas da tabela ficam com quem chama.
    """
    if destino not in TRANSICOES.get(estado, frozenset()):
        raise TransicaoInvalida(f"transição não listada: {estado} -> {destino}")
    if estado == EstadoFluxo.PAUSADA and destino != estado_anterior:
        raise TransicaoInvalida(
            f"retomada só volta ao estado anterior: {destino} != {estado_anterior}"
        )
    if destino in ESTADOS_ATIVOS and (mandato is None or not mandato_valido(mandato, vaga, agora)):
        raise TransicaoInvalida(f"{estado} -> {destino} exige mandato válido para a vaga")

    novo = EstadoFluxo(destino)
    mensagem = f"{estado} -> {novo}"
    if motivo:
        mensagem = f"{mensagem}: {motivo}"
    evento = EventoFluxo(
        empresa_id=vaga.empresa_id,
        vaga_id=vaga.id,
        etapa=novo.value,
        mensagem=mensagem,
        momento=agora,
    )
    return novo, evento


CANAL_CONVITE = "email"
ETAPA_RESERVA = "reserva"
CONSULTA_TODO_O_BANCO = ""
"""Consulta vazia devolve todos os perfis aptos da empresa: ver `BancoTalentos.buscar`."""
LIMITE_INVALIDAS_SEGUIDAS = 3
MINIMO_PARA_MEDIR_TAXA = 10
TAXA_VERDE_MAXIMA = 0.8
REGRAS_DA_FAIXA_VERDE = frozenset({"faixa_verde_v1", "nao_priorizado"})
RESSALVA_REVISOR_INVALIDO = "revisor_resposta_invalida"
REGRA_REVERSAO = "reversao_humana"
VALIDADE_DA_RESERVA = timedelta(minutes=5)
"""Por quanto tempo uma ação reservada segura as outras execuções, caso a primeira tenha caído."""
ROTULO_NAO_VERIFICADO = "Não verificado: "
"""Marca, no pacote, o texto livre do modelo que não tem trecho conferido do perfil."""
CAMPOS_DE_CONTROLE = ("autorizacao_valida_ate", "autorizou_contato", "estado", "opt_out")
"""O que muda depois da busca e decide contato e entrega. O perfil analisado continua o mesmo."""
_PALAVRAS_DE_NAO_PESSOA = frozenset(
    "agente ai auto automacao automatica automatico bot gpt ia llm modelo robo script "
    "sistema".split()
)


CONCORRENCIA_PADRAO = 1


def concorrencia_do_ambiente() -> int:
    """Quantas análises ou revisões seguem juntas. `CONCORRENCIA_MODELO` ajusta sem mudar o código.

    O provedor limita chamadas simultâneas conforme o plano, por isso o padrão é uma de cada vez.
    """
    texto = (os.environ.get("CONCORRENCIA_MODELO") or "").strip()
    if not texto:
        return CONCORRENCIA_PADRAO
    try:
        valor = int(texto)
    except ValueError:
        valor = 0
    if valor < 1:
        raise ValueError("CONCORRENCIA_MODELO precisa ser um inteiro de pelo menos 1")
    return valor


class _ChamadorNaLinha:
    """Uma chamada de cada vez, na thread de quem pediu: sem threads quando a concorrência é 1."""

    def submit[T](self, funcao: Callable[..., T], *argumentos: object) -> Future[T]:
        futuro: Future[T] = Future()
        try:
            futuro.set_result(funcao(*argumentos))
        except Exception as erro:
            futuro.set_exception(erro)
        return futuro

    def shutdown(self, wait: bool = True) -> None:
        return None


@dataclass(frozen=True)
class _Percurso:
    """O que muda entre a análise e a revisão ao passar pelos candidatos de uma etapa.

    `chamar` roda fora da thread principal e só fala com o modelo. Tudo o que grava fica na thread
    principal, em ordem: `pular`, `concluir` e `falhar`. `guardar` recebe o que já foi pago e
    terminou depois do ponto de parada, sem mexer no cursor.
    """

    pular: Callable[[Candidato], bool]
    chamar: Callable[[Candidato], Analise]
    concluir: Callable[[Analise, int], None]
    falhar: Callable[[Candidato, int], None]
    guardar: Callable[[Analise], None]


class MotivoPausa(StrEnum):
    LIMITE_GASTO = "LIMITE_GASTO"
    MODELO_INDISPONIVEL = "MODELO_INDISPONIVEL"
    FONTES_INDISPONIVEIS = "FONTES_INDISPONIVEIS"
    BANCO_INDISPONIVEL = "BANCO_INDISPONIVEL"
    DESTINO_INDISPONIVEL = "DESTINO_INDISPONIVEL"
    MANDATO_INVALIDO = "MANDATO_INVALIDO"
    RESPOSTAS_INVALIDAS = "RESPOSTAS_INVALIDAS"
    AUDITORIA_REPROVADA = MOTIVO_AUDITORIA_REPROVADA
    TAXA_ANOMALA = "TAXA_ANOMALA"
    PARADA_PELO_RH = "PARADA_PELO_RH"


MOTIVOS_QUE_EXIGEM_ADITIVO = frozenset({MotivoPausa.LIMITE_GASTO, MotivoPausa.MANDATO_INVALIDO})


class _PausaNecessaria(Exception):
    """Sinal interno: a etapa não pode seguir, e o motivo vai para o estado salvo."""

    def __init__(self, motivo: MotivoPausa) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class _VagaInterrompida(Exception):
    """Sinal interno: outra chamada mudou o estado da vaga, e esta execução deve sair."""


class EstadoConvite(StrEnum):
    A_ENVIAR = "a_enviar"
    AGUARDANDO = "aguardando"
    ACEITO = "aceito"
    ENCERRADO = "encerrado"
    CANCELADO = "cancelado"


class ResumoVaga(Contrato):
    """Controle depois da ação: o que o agente fez dentro do mandato. Modelo local."""

    vaga_id: str
    estado: str
    analisados: int
    motivo_pausa: str | None
    mandato_versao: int | None
    limite_gasto_usd: float | None
    gasto_usd: float
    meta_candidatos: int
    contagens: dict[str, int]
    fila_humana: list[str]
    entregues: list[str]
    ampliacoes: int
    fontes_fora: list[str]
    destinos: dict[str, str]
    simulado: bool


class RegistroConvite(Contrato):
    convite: Convite
    tentativa: int
    estado: EstadoConvite = EstadoConvite.A_ENVIAR


class ProgressoFluxo(Contrato):
    """O trabalho feito até aqui. Modelo local: não cruza frentes."""

    iniciado_em: AwareDatetime
    execucao_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ampliacoes: int = 0
    inicio_rodada: int = 0
    fontes_fora: list[str] = []
    taxa_aceita: bool = False
    candidatos: list[Candidato] = []
    cortados: list[Candidato] = []
    consultas_por_rodada: dict[int, list[str]] = {}
    paginas_por_fonte: dict[str, int] = {}
    do_banco: list[str] = []
    dono_execucao: str | None = None
    opt_outs_a_propagar: list[str] = []
    analises: dict[str, Analise] = {}
    revisadas: list[str] = []
    invalidas_seguidas: int = 0
    versao_mandato_na_pausa: int | None = None
    convites: list[RegistroConvite] = []
    entregues: list[str] = []
    destinos: dict[str, DestinoPessoa] = {}

    def candidato(self, candidato_id: str) -> Candidato:
        for candidato in (*self.candidatos, *self.cortados):
            if candidato.id == candidato_id:
                return candidato
        raise AcaoRecusada(f"candidato desconhecido nesta vaga: {candidato_id!r}")


def exigir_humano(responsavel: str) -> str:
    nome = responsavel.strip()
    palavras = separar_palavras(nome)
    if (
        not palavras
        or nome.casefold().startswith("agente")
        or (palavras[0] in _PALAVRAS_DE_NAO_PESSOA)
    ):
        raise ResponsavelInvalido("esta é uma decisão humana: informe a pessoa responsável")
    return nome


def _exigir_motivo(motivo: str) -> str:
    texto = motivo.strip()
    if not texto:
        raise AcaoRecusada("informe o motivo da decisão")
    return texto


def _resumo_da_decisao(decisao: Decisao) -> str:
    return hashlib.sha256(decisao.model_dump_json().encode("utf-8")).hexdigest()[:16]


def consulta_pelo_titulo(vaga: Vaga, rodada: int, anteriores: Sequence[str]) -> list[str]:
    return [vaga.titulo]


def _sem_dados_do_perfil(candidato: Candidato) -> Candidato:
    """Quem saiu por falta de autorização não deixa nome, perfil nem histórico na vaga."""
    return candidato.model_copy(
        update={"nome": "", "perfil_texto": "", "atributos": {}, "historico": []}
    )


def _email(candidato: Candidato) -> str | None:
    return candidato.atributos.get("email")


def _ordem_de_decisao(decisao: Decisao) -> tuple[float, str]:
    """Faixa verde primeiro, por nota decrescente; empates e demais, por `id`."""
    if decisao.tipo == TipoDecisao.INDICAR:
        return (-float(decisao.entrada["nota"]), decisao.candidato_id)
    return (1.0, decisao.candidato_id)


@rastreado("consultas")
def _pedir_consultas(
    consultas: ProvedorConsultas, vaga: Vaga, rodada: int, anteriores: Sequence[str]
) -> list[str]:
    return consultas(vaga, rodada, anteriores)


@rastreado("busca_fonte")
def _buscar_na_fonte(fonte: FonteCandidatos, empresa_id: str, consulta: str, pagina: int):
    return fonte.buscar(empresa_id, consulta, pagina=pagina)


@rastreado("leitura_banco")
def _ler_do_banco(banco: BancoTalentos, empresa_id: str, candidato_id: str) -> Candidato | None:
    return banco.obter(empresa_id, candidato_id)


@rastreado("analise")
def _analisar(analisador: Analisador, vaga: Vaga, candidato: Candidato) -> Analise:
    return analisador.analisar(vaga, candidato)


@rastreado("revisao")
def _revisar(revisor: Revisor, vaga: Vaga, candidato: Candidato, analise: Analise) -> Analise:
    return revisor.revisar(vaga, candidato, analise)


@rastreado("link_agendamento")
def _pedir_link(destino: AgenteRecrutador, vaga_id: str, candidato_id: str) -> str | None:
    return destino.link_agendamento(vaga_id, candidato_id)


@rastreado("envio_convite")
def _enviar_convite(mensageiro: Mensageiro, convite: Convite) -> bool:
    return mensageiro.enviar(convite)


@rastreado("entrega_destino")
def _entregar_pacote(destino: AgenteRecrutador, pacote: PacoteContexto) -> bool:
    return destino.entregar(pacote)


@rastreado("registro_opt_out")
def _gravar_opt_out(banco: BancoTalentos, empresa_id: str, candidato_id: str) -> None:
    banco.registrar_opt_out(empresa_id, candidato_id)


class FluxoVaga:
    """Conduz uma vaga de `RASCUNHO` a `CONCLUIDA`, dentro do mandato assinado."""

    def __init__(
        self,
        vaga: Vaga,
        *,
        repositorio: Repositorio,
        banco: BancoTalentos,
        fontes: Sequence[FonteCandidatos],
        analisador: Analisador,
        revisor: Revisor,
        mensageiro: Mensageiro,
        destino: AgenteRecrutador,
        relogio: Callable[[], datetime],
        consultas: ProvedorConsultas = consulta_pelo_titulo,
        priorizador: Priorizador | None = None,
        medidor_gasto: Callable[[], float],
        auditoria: Auditoria | None = None,
        resiliencia: Resiliencia | None = None,
        reidentificador: Reidentificador | None = None,
        concorrencia: int = CONCORRENCIA_PADRAO,
        redator_convite: RedatorConvite | None = None,
    ) -> None:
        if medidor_gasto is None:
            raise ValueError("sem medidor, o limite de gasto do mandato não seria aplicado")
        if concorrencia < 1:
            raise ValueError("concorrencia precisa ser de pelo menos 1")
        self._concorrencia = concorrencia
        self._repo = repositorio
        self._execucao_local = threading.local()
        self._auditoria = Auditoria(repositorio) if auditoria is None else auditoria
        self._resiliencia = Resiliencia() if resiliencia is None else resiliencia
        self._reidentificador = reidentificador
        self._redator_convite = redator_convite
        self._banco = banco
        self._fontes = fontes
        self._analisador = analisador
        self._revisor = revisor
        self._mensageiro = mensageiro
        self._destino = destino
        self._relogio = relogio
        self._consultas = consultas
        self._priorizador = priorizador
        self._medidor_gasto = medidor_gasto
        persistida = repositorio.carregar_vaga(vaga.empresa_id, vaga.id)
        self.vaga = vaga if persistida is None else persistida
        mandato = self.mandato
        if mandato is not None:
            aprovada = mandato_valido(mandato, self.vaga, relogio())
            self.vaga = self.vaga.model_copy(update={"aprovada": aprovada})

    @property
    def estado(self) -> EstadoFluxo:
        execucao = self._repo.carregar_estado(self.vaga.empresa_id, self.vaga.id)
        return EstadoFluxo.RASCUNHO if execucao is None else EstadoFluxo(execucao.estado)

    @property
    def eventos(self) -> list[EventoFluxo]:
        return self._repo.listar_eventos(self.vaga.empresa_id, self.vaga.id)

    @property
    def mandato(self) -> Mandato | None:
        dados = self._repo.carregar_mandato(self.vaga.empresa_id, self.vaga.id)
        return None if dados is None else Mandato.model_validate_json(dados)

    def iniciar(self) -> None:
        """Leva a vaga a aguardar o mandato, se os critérios não usam dado sensível."""
        problemas = validar_criterios(self.vaga)
        if problemas:
            raise TransicaoInvalida(f"vaga com problemas nos critérios: {'; '.join(problemas)}")
        self._ir(EstadoFluxo.AGUARDANDO_MANDATO)

    def editar_vaga(self, vaga: Vaga) -> None:
        """Troca e grava o conteúdo da vaga. Antes da assinatura, uma mudança volta ao rascunho."""
        if (vaga.id, vaga.empresa_id) != (self.vaga.id, self.vaga.empresa_id):
            raise ValueError("a edição precisa ser da mesma vaga e da mesma empresa")
        mudou = hash_da_vaga(vaga) != hash_da_vaga(self.vaga)
        self.vaga = vaga.model_copy(update={"aprovada": self.vaga.aprovada and not mudou})
        self._repo.salvar_vaga(self.vaga)
        if mudou and self.estado == EstadoFluxo.AGUARDANDO_MANDATO:
            self._ir(EstadoFluxo.RASCUNHO, motivo="vaga editada antes da assinatura")

    def assinar_mandato(
        self,
        assinante: str,
        limite_gasto_usd: float,
        politica: Politica,
        valido_ate: datetime | None = None,
        *,
        executar: bool = True,
    ) -> None:
        """Registra a assinatura e executa até a vaga depender de resposta externa.

        Com a vaga pausada, vira um aditivo: uma nova versão, que só vale depois de `retomar`.
        Com a vaga concluída, o aditivo só serve para destravar indicações pendentes.
        Com `executar=False`, a vaga fica em `BUSCANDO`, e `continuar` segue dali.
        """
        if assinante.strip():
            assinante = exigir_humano(assinante)
        agora = self._relogio()
        estado = self.estado
        if estado == EstadoFluxo.PAUSADA or (
            estado == EstadoFluxo.CONCLUIDA and self._indicacoes_pendentes()
        ):
            self._assinar_aditivo(assinante, limite_gasto_usd, politica, valido_ate, agora)
            return
        if estado != EstadoFluxo.AGUARDANDO_MANDATO:
            raise TransicaoInvalida(f"{estado} não aceita assinatura de mandato")
        mandato = self._assinar(assinante, limite_gasto_usd, politica, valido_ate, 1, agora)
        self.vaga = self.vaga.model_copy(update={"aprovada": True})
        self._salvar_progresso(ProgressoFluxo(iniciado_em=agora))
        self._avisar_limiar(mandato)
        self._ir(EstadoFluxo.BUSCANDO)
        if executar:
            self._executar()

    def _assinar_aditivo(
        self,
        assinante: str,
        limite_gasto_usd: float,
        politica: Politica,
        valido_ate: datetime | None,
        agora: datetime,
    ) -> None:
        anterior = self.mandato
        versao = anterior.versao + 1
        aditivo = self._assinar(assinante, limite_gasto_usd, politica, valido_ate, versao, agora)
        self.vaga = self.vaga.model_copy(update={"aprovada": True})
        self._evento("mandato", f"aditivo assinado: versão {aditivo.versao}")
        self._avisar_limiar(aditivo)
        if aditivo.hash_vaga != anterior.hash_vaga:
            self._reavaliar_indicados(aditivo, agora)

    def _reavaliar_indicados(self, mandato: Mandato, agora: datetime) -> None:
        """A vaga mudou: quem estava indicado passa de novo pelos requisitos, sem o modelo."""
        progresso = self._progresso()
        decisoes = self._ultimas_decisoes()
        with self._contexto(progresso), self._pausando_em_falha():
            for candidato_id in self._indicados():
                candidato = progresso.candidato(candidato_id)
                nova = decisao_por_novos_requisitos(
                    self.vaga, candidato, decisoes[candidato_id], mandato, agora
                )
                if nova is None:
                    continue
                self._registrar_decisao(nova)
                self._cancelar_convites(candidato_id)
                if self._ja_chegou_ao_destino(progresso, candidato_id):
                    self._evento(
                        "aviso_destino",
                        "requisito novo depois da entrega: avisar o destino, sem retirada",
                        candidato_id,
                    )

    def _indicacoes_pendentes(self) -> list[str]:
        """Quem está indicado e ainda não chegou ao destino, sem contar quem recusou."""
        dados = self._repo.carregar_progresso(self.vaga.empresa_id, self.vaga.id)
        if dados is None:
            return []
        progresso = ProgressoFluxo.model_validate_json(dados)
        return [
            candidato_id
            for candidato_id in self._indicados()
            if candidato_id not in progresso.entregues
            and not self._convite_encerrado(progresso, candidato_id)
        ]

    def registrar_resposta(self, resposta: RespostaCandidato) -> None:
        """Aplica a resposta da pessoa. O texto dela é dado e não entra nos eventos.

        Só registra a resposta. Quem manda convite é a execução, que confere estado e mandato.
        """
        progresso = self._progresso()
        registro = next(
            (r for r in progresso.convites if r.convite.id == resposta.convite_id), None
        )
        if registro is None:
            raise AcaoRecusada(f"convite desconhecido nesta vaga: {resposta.convite_id!r}")
        candidato_id = registro.convite.candidato_id
        self._evento("resposta", f"resposta: {resposta.tipo}", candidato_id)

        with self._contexto(progresso, candidato_id), self._pausando_em_falha():
            if resposta.tipo == TipoResposta.OPT_OUT:
                self._registrar_opt_out(candidato_id)
            else:
                self._aplicar_resposta(resposta.convite_id, resposta.tipo)

        estado = self.estado
        if estado == EstadoFluxo.CONVIDANDO:
            self._executar()
        elif estado == EstadoFluxo.CONCLUIDA and resposta.tipo in (
            TipoResposta.ACEITE,
            TipoResposta.SILENCIO,
        ):
            self._entregar_fora_da_execucao()

    def verificar_prazo(self) -> None:
        """Reenvia convites que falharam e, com o prazo da vaga vencido, encerra os abertos."""
        if self.estado != EstadoFluxo.CONVIDANDO:
            return
        self._executar()

    def _prazo_vencido(self, progresso: ProgressoFluxo) -> bool:
        return self._relogio() >= progresso.iniciado_em + timedelta(days=self.vaga.prazo_dias)

    def _encerrar_convites_vencidos(self) -> None:
        """Depois do prazo, nenhum convite aberto sai nem espera mais."""
        if not self._prazo_vencido(self._progresso()):
            return

        def encerrar(progresso: ProgressoFluxo) -> list[str]:
            abertos = (EstadoConvite.A_ENVIAR, EstadoConvite.AGUARDANDO)
            encerrados = []
            for registro in progresso.convites:
                if registro.estado in abertos:
                    registro.estado = EstadoConvite.ENCERRADO
                    encerrados.append(registro.convite.candidato_id)
            return encerrados

        for candidato_id in self._mudar(encerrar):
            self._evento("convite", "prazo vencido", candidato_id)

    def parar(self, responsavel: str | None = None, motivo: str = "") -> None:
        """Pausa a vaga. Quem está em execução sai antes do próximo candidato."""
        nome = None if responsavel is None else exigir_humano(responsavel)
        while self.estado != EstadoFluxo.PAUSADA:
            try:
                self._ir(
                    EstadoFluxo.PAUSADA, cursor=self._cursor(), motivo=MotivoPausa.PARADA_PELO_RH
                )
            except _VagaInterrompida:
                continue
            self._registrar_controle("parada", nome, motivo)

    def retomar(
        self, *, executar: bool = True, responsavel: str | None = None, motivo: str = ""
    ) -> None:
        """Continua de onde parou: depois de uma pausa ou de uma queda em estado ativo.

        Com `executar=False`, só tira da pausa, e `continuar` segue dali.
        """
        nome = None if responsavel is None else exigir_humano(responsavel)
        execucao = self._repo.carregar_estado(self.vaga.empresa_id, self.vaga.id)
        estado = self.estado
        if estado == EstadoFluxo.PAUSADA:
            if self._barreira_da_auditoria():
                raise DecisoesAutomaticasPausadas(
                    "erro na amostra auditada: uma pessoa precisa liberar antes de retomar"
                )
            self._sair_da_pausa(execucao.motivo, execucao.estado_anterior, execucao.cursor)
            self._registrar_controle("retomada", nome, motivo)
        elif estado != EstadoFluxo.CONCLUIDA and estado not in ESTADOS_ATIVOS:
            raise TransicaoInvalida(f"{estado} não tem execução para retomar")
        if executar:
            self.continuar()

    def continuar(self) -> None:
        """Segue a execução em andamento. Vaga pausada fica parada: retomar é com `retomar`."""
        estado = self.estado
        if estado == EstadoFluxo.CONCLUIDA:
            self._entregar_fora_da_execucao()
        elif estado in ESTADOS_ATIVOS:
            self._executar()

    def entregar_indicados(self) -> tuple[list[str], list[str]]:
        """Entrega quem já pode receber, sem convidar nem mudar de etapa. Vaga parada não entrega.

        Devolve quem já foi entregue e quem pode receber, mas ficou pendente.
        """
        if self.mandato is None:
            return [], []
        if self.estado in (EstadoFluxo.CONVIDANDO, EstadoFluxo.ENTREGANDO, EstadoFluxo.CONCLUIDA):
            with self._contexto(self._progresso()), self._pausando_em_falha():
                self._entregar_pendentes()
        progresso = self._progresso()
        return progresso.entregues, self._a_entregar(progresso)

    def _registrar_controle(self, acao: str, nome: str | None, motivo: str) -> None:
        if nome is not None:
            detalhe = f": {motivo.strip()}" if motivo.strip() else ""
            self._evento("controle", f"{acao} pedida por {nome}{detalhe}")

    def reverter(self, candidato_id: str, motivo: str, responsavel: str) -> Decisao:
        """Devolve a decisão à fila humana, sem apagar a original nem mudar o estado da vaga.

        Depois da entrega, o pacote não pode ser retirado: fica o aviso para combinar com o destino.
        """
        nome, motivo = exigir_humano(responsavel), _exigir_motivo(motivo)
        atual = self._decisao_vigente(candidato_id)
        if atual.regra == REGRA_REVERSAO:
            return atual
        if atual.tipo == TipoDecisao.PEDIR_HUMANO:
            raise AcaoRecusada("não há decisão a reverter: a pessoa já está na fila humana")
        nova = self._decisao_humana(
            atual, TipoDecisao.PEDIR_HUMANO, REGRA_REVERSAO, motivo, nome, atual.evidencias
        )
        self._cancelar_convites(candidato_id)
        progresso = self._progresso()
        if self._ja_chegou_ao_destino(progresso, candidato_id):
            self._evento(
                "aviso_destino",
                "decisão revertida depois da entrega: avisar o destino, sem retirada do pacote",
                candidato_id,
            )
        if self.estado == EstadoFluxo.CONVIDANDO:
            self._executar()
        return nova

    def resolver_fila(
        self, candidato_id: str, tipo: TipoDecisao, motivo: str, responsavel: str
    ) -> Decisao:
        """Registra o que uma pessoa decidiu sobre um item da fila, sem mudar o estado da vaga."""
        nome, motivo = exigir_humano(responsavel), _exigir_motivo(motivo)
        if tipo not in (TipoDecisao.INDICAR, TipoDecisao.DESCARTAR):
            raise AcaoRecusada("a fila se resolve com indicar ou descartar")
        atual = self._decisao_vigente(candidato_id)
        if atual.tipo != TipoDecisao.PEDIR_HUMANO:
            raise AcaoRecusada("a pessoa não está na fila humana")
        progresso = self._progresso()
        analise = progresso.analises.get(candidato_id)
        if tipo == TipoDecisao.INDICAR:
            candidato = progresso.candidato(candidato_id)
            if StatusRequisito.NAO_ATENDE in avaliar_requisitos(self.vaga, candidato).values():
                raise AcaoRecusada("a pessoa não atende a um requisito eliminatório da vaga")
            self._exigir_evidencias(candidato, analise)
        evidencias = atual.evidencias if analise is None else analise.evidencias
        nova = self._decisao_humana(atual, tipo, "decisao_humana", motivo, nome, evidencias)
        if tipo == TipoDecisao.INDICAR:
            self._agir_sobre_indicacao(candidato_id)
        return nova

    def resumo(self) -> ResumoVaga:
        """Contagens por faixa, gasto e pendências, a partir da decisão vigente de cada pessoa."""
        execucao = self._repo.carregar_estado(self.vaga.empresa_id, self.vaga.id)
        dados = self._repo.carregar_progresso(self.vaga.empresa_id, self.vaga.id)
        progresso = None if dados is None else ProgressoFluxo.model_validate_json(dados)
        mandato = self.mandato
        decisoes = self._ultimas_decisoes()
        tipos = [decisao.tipo for decisao in decisoes.values()]
        return ResumoVaga(
            vaga_id=self.vaga.id,
            estado=self.estado,
            analisados=0 if progresso is None else len(progresso.analises),
            motivo_pausa=None if execucao is None else execucao.motivo,
            mandato_versao=None if mandato is None else mandato.versao,
            limite_gasto_usd=None if mandato is None else mandato.limite_gasto_usd,
            gasto_usd=self._medidor_gasto(),
            meta_candidatos=self.vaga.meta_candidatos,
            contagens={
                "verde": tipos.count(TipoDecisao.INDICAR),
                "amarela": tipos.count(TipoDecisao.PEDIR_HUMANO),
                "vermelha": tipos.count(TipoDecisao.DESCARTAR),
            },
            fila_humana=sorted(
                candidato_id
                for candidato_id, decisao in decisoes.items()
                if decisao.tipo == TipoDecisao.PEDIR_HUMANO
            ),
            entregues=[] if progresso is None else progresso.entregues,
            ampliacoes=0 if progresso is None else progresso.ampliacoes,
            fontes_fora=[] if progresso is None else progresso.fontes_fora,
            destinos={} if progresso is None else progresso.destinos,
            simulado=progresso is not None
            and any(c.simulado for c in (*progresso.candidatos, *progresso.cortados)),
        )

    def situacao_candidatos(
        self,
    ) -> list[tuple[Candidato, TipoDecisao | None, DestinoPessoa | None]]:
        """Quem passou pela vaga, com a decisão vigente e o destino dado pelo RH."""
        dados = self._repo.carregar_progresso(self.vaga.empresa_id, self.vaga.id)
        if dados is None:
            return []
        progresso = ProgressoFluxo.model_validate_json(dados)
        decisoes = self._ultimas_decisoes()
        situacao = []
        for candidato in (*progresso.candidatos, *progresso.cortados):
            decisao = decisoes.get(candidato.id)
            situacao.append(
                (
                    candidato,
                    None if decisao is None else decisao.tipo,
                    progresso.destinos.get(candidato.id),
                )
            )
        return situacao

    def convites(self) -> list[RegistroConvite]:
        """Os convites da vaga, na ordem de envio, com o estado de cada um."""
        dados = self._repo.carregar_progresso(self.vaga.empresa_id, self.vaga.id)
        if dados is None:
            return []
        return ProgressoFluxo.model_validate_json(dados).convites

    def pacotes_entregues(self) -> list[PacoteContexto]:
        """Os pacotes que já chegaram ao destino, montados como na entrega."""
        dados = self._repo.carregar_progresso(self.vaga.empresa_id, self.vaga.id)
        if dados is None:
            return []
        progresso = ProgressoFluxo.model_validate_json(dados)
        decisoes = self._ultimas_decisoes()
        return [
            self._pacote(
                progresso.candidato(candidato_id),
                progresso.analises[candidato_id],
                decisoes[candidato_id].rastro_id,
                self._chave_de_entrega(candidato_id),
            )
            for candidato_id in progresso.entregues
        ]

    def registrar_destino(
        self, candidato_id: str, destino: DestinoPessoa, responsavel: str
    ) -> None:
        """Guarda para onde a pessoa vai depois da vaga. Só uma pessoa decide isso."""
        nome = exigir_humano(responsavel)
        destino = DestinoPessoa(destino)
        self._decisao_vigente(candidato_id)
        progresso = self._progresso()
        candidato = progresso.candidato(candidato_id)
        saiu = candidato.opt_out or self._tem_opt_out(candidato)
        if saiu and destino != DestinoPessoa.CONTRATADA:
            raise AcaoRecusada("pessoa com opt-out não volta ao banco nem ao talent garden")

        def gravar(atual: ProgressoFluxo) -> None:
            atual.destinos[candidato_id] = destino

        self._mudar(gravar)
        self._evento("destino", f"destino {destino} definido por {nome}", candidato_id)

    def _decisao_vigente(self, candidato_id: str) -> Decisao:
        decisao = self._ultimas_decisoes().get(candidato_id)
        if decisao is None:
            raise AcaoRecusada(f"candidato sem decisão nesta vaga: {candidato_id!r}")
        return decisao

    def _decisao_humana(
        self,
        anterior: Decisao,
        tipo: TipoDecisao,
        regra: str,
        motivo: str,
        nome: str,
        evidencias: list[Evidencia],
    ) -> Decisao:
        """Acrescenta a decisão ligada à anterior, que continua no histórico."""
        decisao = Decisao(
            empresa_id=self.vaga.empresa_id,
            vaga_id=self.vaga.id,
            candidato_id=anterior.candidato_id,
            tipo=tipo,
            regra=regra,
            motivo=motivo,
            responsavel=f"humano:{nome}",
            rastro_id=anterior.rastro_id,
            entrada={
                "decisao_anterior": _resumo_da_decisao(anterior),
                "tipo_anterior": anterior.tipo,
                "regra_anterior": anterior.regra,
                "responsavel_anterior": anterior.responsavel,
                **({"rastro_revertido": anterior.rastro_id} if regra == REGRA_REVERSAO else {}),
            },
            evidencias=evidencias or anterior.evidencias,
            momento=self._relogio(),
        )
        self._auditoria.registrar_decisao(decisao)
        self._evento("decisao", f"{decisao.tipo}: {decisao.regra}", decisao.candidato_id)
        return decisao

    def _registrar_decisao(self, decisao: Decisao) -> None:
        """Registra pela auditoria. Se ela recusa, a vaga pausa e a decisão fica para a retomada."""
        try:
            self._auditoria.registrar_decisao(decisao)
        except (DecisaoIncompleta, DecisoesAutomaticasPausadas) as erro:
            self._evento(
                "auditoria", f"decisão recusada: {type(erro).__name__}", decisao.candidato_id
            )
            raise _PausaNecessaria(MotivoPausa.AUDITORIA_REPROVADA) from erro
        self._evento("decisao", f"{decisao.tipo}: {decisao.regra}", decisao.candidato_id)

    def _exigir_evidencias(self, candidato: Candidato, analise: Analise | None) -> None:
        if analise is None:
            raise AcaoRecusada("sem análise válida não há evidência para indicar a pessoa")
        faltando = criterios_sem_evidencia(self.vaga, candidato, analise)
        if faltando:
            raise AcaoRecusada(f"sem evidência conferida para: {', '.join(faltando)}")

    def _cancelar_convites(self, candidato_id: str) -> None:
        """Encerra o que estava aberto. Convite já enviado não volta, e resposta vira tardia."""

        def cancelar(progresso: ProgressoFluxo) -> None:
            abertos = (EstadoConvite.A_ENVIAR, EstadoConvite.AGUARDANDO, EstadoConvite.ACEITO)
            for registro in progresso.convites:
                if registro.convite.candidato_id == candidato_id and registro.estado in abertos:
                    registro.estado = EstadoConvite.CANCELADO

        self._mudar(cancelar)

    def _agir_sobre_indicacao(self, candidato_id: str) -> None:
        """Convoca ou entrega quem uma pessoa indicou. Antes disso, o fluxo cuida ao chegar lá.

        Com a vaga em fim de execução e o mandato vencido, a indicação fica registrada e
        pendente: um aditivo seguido de `retomar` destrava.
        """
        estado = self.estado
        if estado == EstadoFluxo.CONVIDANDO:
            self._executar()
        elif estado in (EstadoFluxo.ENTREGANDO, EstadoFluxo.CONCLUIDA):
            if not mandato_valido(self.mandato, self.vaga, self._relogio()):
                self._evento(
                    "mandato",
                    "indicação pendente: o mandato não vale, assine um aditivo",
                    candidato_id,
                )
                return
            self._entregar_fora_da_execucao()

    def _entregar_fora_da_execucao(self) -> None:
        """Cuida de indicações e aceites com a vaga fora de execução, sem reabrir a vaga."""
        with self._contexto(self._progresso()), self._pausando_em_falha():
            self._propagar_opt_outs()
            self._entregar_pendentes()
            if self.estado == EstadoFluxo.PAUSADA:
                return
            if self.mandato.politica.modo_entrega != ModoEntrega.NA_DECISAO:
                self._convidar_indicados()

    def _sair_da_pausa(self, motivo: str | None, anterior: str | None, cursor: int) -> None:
        progresso = self._progresso()
        versao_na_pausa = progresso.versao_mandato_na_pausa
        if motivo in MOTIVOS_QUE_EXIGEM_ADITIVO and self.mandato.versao == versao_na_pausa:
            raise MandatoInvalido(f"{motivo} só retoma com um aditivo assinado")
        self._ir(EstadoFluxo(anterior), cursor=cursor, motivo=f"retomada de {motivo}")

        def registrar_retomada(atual: ProgressoFluxo) -> None:
            atual.invalidas_seguidas = 0
            atual.taxa_aceita = atual.taxa_aceita or motivo == MotivoPausa.TAXA_ANOMALA
            atual.dono_execucao = None

        self._mudar(registrar_retomada)

    def _assinar(
        self,
        assinante: str,
        limite_gasto_usd: float,
        politica: Politica,
        valido_ate: datetime | None,
        versao: int,
        agora: datetime,
    ) -> Mandato:
        mandato = assinar(
            self.vaga,
            assinante,
            limite_gasto_usd,
            politica,
            agora,
            validar_criterios=validar_criterios,
            versao=versao,
            valido_ate=valido_ate,
        )
        self._repo.salvar_mandato(self.vaga.empresa_id, self.vaga.id, mandato.model_dump_json())
        return mandato

    def _avisar_limiar(self, mandato: Mandato) -> None:
        if mandato.politica.limiar_verde is None:
            self._evento(
                "limiar_nao_calibrado", "limiar não calibrado: todos os casos vão para revisão"
            )

    def _progresso(self) -> ProgressoFluxo:
        dados = self._repo.carregar_progresso(self.vaga.empresa_id, self.vaga.id)
        if dados is None:
            raise TransicaoInvalida("a vaga ainda não tem mandato assinado")
        return ProgressoFluxo.model_validate_json(dados)

    def _salvar_progresso(self, progresso: ProgressoFluxo) -> None:
        self._repo.salvar_progresso(self.vaga.empresa_id, self.vaga.id, progresso.model_dump_json())

    def _mudar[R](self, mudanca: Callable[[ProgressoFluxo], R]) -> R:
        """Aplica a mudança sobre o progresso salvo agora, numa transação: nada se perde.

        `mudanca` não pode acessar o repositório: eventos ficam para depois de ela voltar.
        """
        resultado: list[R] = []

        def aplicar(dados: str) -> str:
            progresso = ProgressoFluxo.model_validate_json(dados)
            resultado.append(mudanca(progresso))
            return progresso.model_dump_json()

        self._repo.atualizar_progresso(self.vaga.empresa_id, self.vaga.id, aplicar)
        return resultado[0]

    def _copiar_campos(self, origem: ProgressoFluxo, *campos: str) -> None:
        """Grava campos que só a execução escreve, sem tocar em convites nem em respostas."""

        def copiar(progresso: ProgressoFluxo) -> None:
            for campo in campos:
                setattr(progresso, campo, getattr(origem, campo))

        self._mudar(copiar)

    def _resumos(self, candidato: Candidato) -> list[str]:
        return resumos_da_pessoa(self.vaga.empresa_id, candidato.id, _email(candidato))

    def _tem_opt_out(self, candidato: Candidato) -> bool:
        return self._repo.tem_bloqueio(self.vaga.empresa_id, self._resumos(candidato))

    def _candidato_atual(self, candidato: Candidato, progresso: ProgressoFluxo) -> Candidato:
        """A cópia da busca com a situação de agora: banco de talentos e opt-outs da empresa.

        Quem saiu do banco depois de achado lá foi removido, e não pode receber nada. Falha na
        consulta bloqueia: a vaga pausa, e nada sai sem saber a situação da pessoa.
        """
        try:
            registro = _ler_do_banco(self._banco, self.vaga.empresa_id, candidato.id)
        except Exception as erro:
            self._evento("banco", f"banco sem resposta: {type(erro).__name__}", candidato.id)
            raise _PausaNecessaria(MotivoPausa.BANCO_INDISPONIVEL) from erro
        if registro is not None:
            atual = candidato.model_copy(
                update={campo: getattr(registro, campo) for campo in CAMPOS_DE_CONTROLE}
            )
        elif candidato.id in progresso.do_banco:
            atual = candidato.model_copy(
                update={
                    "estado": EstadoBanco.REMOVIDO,
                    "autorizou_contato": False,
                    "autorizacao_valida_ate": None,
                }
            )
        else:
            atual = candidato
        if candidato.opt_out or self._tem_opt_out(candidato):
            atual = atual.model_copy(update={"opt_out": True})
        return atual

    def _ja_chegou_ao_destino(self, progresso: ProgressoFluxo, candidato_id: str) -> bool:
        """Inclui a entrega em curso: uma queda pode ter deixado o pacote lá sem registro aqui."""
        return candidato_id in progresso.entregues or self._repo.chave_ja_usada(
            self.vaga.empresa_id, self._chave_de_entrega(candidato_id)
        )

    def _contexto(self, progresso: ProgressoFluxo, candidato_id: str | None = None):
        """Rastro das chamadas: a execução vem do progresso salvo, e sobrevive a um reinício."""
        return contexto_rastro(
            empresa_id=self.vaga.empresa_id,
            execucao_id=progresso.execucao_id,
            vaga_id=self.vaga.id,
            candidato_id=candidato_id,
        )

    def _rastro_id(self, progresso: ProgressoFluxo, candidato_id: str) -> str:
        return ContextoRastro(
            execucao_id=progresso.execucao_id,
            empresa_id=self.vaga.empresa_id,
            vaga_id=self.vaga.id,
            candidato_id=candidato_id,
        ).rastro_id

    def _cursor(self) -> int:
        execucao = self._repo.carregar_estado(self.vaga.empresa_id, self.vaga.id)
        return 0 if execucao is None else execucao.cursor

    def _evento(self, etapa: str, mensagem: str, candidato_id: str | None = None) -> None:
        self._repo.registrar_evento(
            EventoFluxo(
                empresa_id=self.vaga.empresa_id,
                vaga_id=self.vaga.id,
                etapa=etapa,
                mensagem=mensagem,
                candidato_id=candidato_id,
                momento=self._relogio(),
            )
        )

    def _ir(self, destino: EstadoFluxo, *, cursor: int = 0, motivo: str = "") -> None:
        execucao = self._repo.carregar_estado(self.vaga.empresa_id, self.vaga.id)
        atual = EstadoFluxo.RASCUNHO if execucao is None else EstadoFluxo(execucao.estado)
        novo, evento = _transitar(
            atual,
            destino,
            vaga=self.vaga,
            mandato=self.mandato,
            agora=self._relogio(),
            estado_anterior=None if execucao is None else execucao.estado_anterior,
            motivo=motivo,
        )
        pausando = novo == EstadoFluxo.PAUSADA
        dados = (
            novo,
            cursor,
            motivo if pausando else None,
            atual if pausando else None,
        )
        if execucao is None:
            self._repo.salvar_estado(self.vaga.empresa_id, self.vaga.id, *dados)
        elif not self._repo.trocar_estado(self.vaga.empresa_id, self.vaga.id, atual, *dados):
            raise _VagaInterrompida
        self._repo.registrar_evento(evento)

    def _avancar(self, destino: EstadoFluxo, *, cursor: int = 0) -> None:
        """Muda de etapa dentro de uma execução, que sai se a vaga foi parada ou o mandato caiu."""
        self._conferir_execucao()
        self._ir(destino, cursor=cursor)

    def _barreira_da_auditoria(self) -> bool:
        return self._auditoria.decisoes_automaticas_pausadas(self.vaga.empresa_id, self.vaga.id)

    def _perdeu_a_vez(self) -> bool:
        """Outra execução assumiu a vaga depois desta, que precisa sair sem escrever mais nada."""
        dono = getattr(self._execucao_local, "dono", None)
        return dono is not None and self._progresso().dono_execucao != dono

    def _conferir_execucao(self) -> None:
        if self._perdeu_a_vez():
            raise _VagaInterrompida
        if self.estado == EstadoFluxo.PAUSADA:
            raise _VagaInterrompida
        if self._barreira_da_auditoria():
            raise _PausaNecessaria(MotivoPausa.AUDITORIA_REPROVADA)
        mandato = self.mandato
        if mandato is None or not mandato_valido(mandato, self.vaga, self._relogio()):
            raise MandatoInvalido("mandato não vale para esta vaga neste momento")

    def _conferir_gasto(self) -> None:
        if self._medidor_gasto() >= self.mandato.limite_gasto_usd:
            raise LimiteGastoAtingido("gasto chegou ao limite assinado no mandato")

    def _pausar(self, motivo: MotivoPausa) -> None:
        """Salva o motivo e o ponto de retomada. Parada humana em curso não é sobrescrita."""
        if self._perdeu_a_vez():
            return
        if self.estado not in ESTADOS_ATIVOS:
            self._evento("pausa", f"sem execução para pausar: {motivo}")
            return
        versao = self.mandato.versao

        def anotar_versao(progresso: ProgressoFluxo) -> None:
            progresso.versao_mandato_na_pausa = versao

        self._mudar(anotar_versao)
        try:
            self._ir(EstadoFluxo.PAUSADA, cursor=self._cursor(), motivo=motivo)
        except _VagaInterrompida:
            self._evento("pausa", f"vaga já mudou de estado; motivo não aplicado: {motivo}")

    @contextmanager
    def _pausando_em_falha(self) -> Iterator[None]:
        """Transforma falha previsível em pausa com estado salvo."""
        try:
            yield
        except LimiteGastoAtingido:
            self._pausar(MotivoPausa.LIMITE_GASTO)
        except ModeloIndisponivel:
            self._pausar(MotivoPausa.MODELO_INDISPONIVEL)
        except MandatoInvalido:
            self._pausar(MotivoPausa.MANDATO_INVALIDO)
        except _PausaNecessaria as sinal:
            self._pausar(sinal.motivo)
        except _VagaInterrompida:
            return
        except TransicaoInvalida:
            if not self._perdeu_a_vez():
                raise

    def _executar(self) -> None:
        """Avança etapa por etapa até a vaga depender de algo externo, pausar ou terminar."""
        passos = {
            EstadoFluxo.BUSCANDO: self._passo_buscar,
            EstadoFluxo.ANALISANDO: self._passo_analisar,
            EstadoFluxo.REVISANDO: self._passo_revisar,
            EstadoFluxo.DECIDINDO: self._passo_decidir,
            EstadoFluxo.META_EM_RISCO: self._passo_meta_em_risco,
            EstadoFluxo.CONVIDANDO: self._passo_convidar,
            EstadoFluxo.ENTREGANDO: self._passo_entregar,
        }
        dono = uuid.uuid4().hex

        def assumir(progresso: ProgressoFluxo) -> None:
            progresso.dono_execucao = dono

        self._mudar(assumir)
        anterior = getattr(self._execucao_local, "dono", None)
        self._execucao_local.dono = dono
        try:
            with self._contexto(self._progresso()), self._pausando_em_falha():
                self._propagar_opt_outs()
                continuar = True
                while continuar and self.estado in passos:
                    if self.estado != EstadoFluxo.ENTREGANDO:
                        self._conferir_execucao()
                    elif self._perdeu_a_vez():
                        raise _VagaInterrompida
                    continuar = passos[self.estado]()
        finally:
            self._execucao_local.dono = anterior

    def _passo_buscar(self) -> bool:
        """Busca a rodada atual. Sem ninguém novo, gasta ampliações até o limite do mandato.

        Quem foi achado e ainda não tem decisão vem primeiro: uma queda ou parada entre a busca e
        a análise não perde ninguém.
        """
        progresso = self._progresso()
        decididos = self._ultimas_decisoes()
        if any(c.id not in decididos for c in progresso.candidatos):
            self._avancar(EstadoFluxo.ANALISANDO, cursor=progresso.inicio_rodada)
            return True
        limite = self.mandato.politica.max_ampliacoes
        novos = self._buscar(progresso)
        self._gravar_busca(progresso, novos)
        while not novos and progresso.ampliacoes < limite:
            self._registrar_ampliacao(progresso)
            novos = self._buscar(progresso)
            self._gravar_busca(progresso, novos)
        if novos:
            self._avancar(EstadoFluxo.ANALISANDO, cursor=len(progresso.candidatos))
        else:
            self._avancar(EstadoFluxo.META_EM_RISCO)
        return True

    def _gravar_busca(self, progresso: ProgressoFluxo, novos: list[Candidato]) -> None:
        """Quem foi achado e até onde cada fonte foi lida entram juntos: nada se perde na queda."""

        def gravar(atual: ProgressoFluxo) -> None:
            atual.fontes_fora = progresso.fontes_fora
            atual.paginas_por_fonte = progresso.paginas_por_fonte
            atual.do_banco = progresso.do_banco
            atual.cortados = progresso.cortados
            atual.inicio_rodada = len(atual.candidatos)
            atual.candidatos.extend(novos)

        self._mudar(gravar)

    def _registrar_ampliacao(self, progresso: ProgressoFluxo) -> None:
        progresso.ampliacoes += 1
        self._copiar_campos(progresso, "ampliacoes")
        self._evento("ampliacao", f"ampliação {progresso.ampliacoes} da busca, mesmos requisitos")

    def _buscar(self, progresso: ProgressoFluxo) -> list[Candidato]:
        """Lê todo o banco autorizado da empresa e depois procura nas fontes externas.

        O banco não depende das palavras da consulta: quem decide é o funil, por regras e com os
        cortes registrados, e assim cargo incomum e perfil com outras palavras chegam até ele.
        As consultas só valem para fontes externas, onde cada par de fonte e consulta guarda a sua
        página: fonte fora do ar não perde a dela. Sem fonte externa, não há consulta a pagar.
        Uma fonte fora do ar reduz a cobertura e fica registrada. Todas fora pausam a vaga.
        """
        vistos = {c.id for c in (*progresso.candidatos, *progresso.cortados)}
        achados: list[Candidato] = []
        fora: list[str] = []
        try:
            do_banco = self._filtrar_achados(self._ler_banco(), vistos)
        except ERROS_TEMPORARIOS as erro:
            fora.append(type(self._banco).__name__)
            self._evento("fonte", f"{type(self._banco).__name__}: {type(erro).__name__}")
        else:
            achados.extend(do_banco)
            progresso.do_banco.extend(c.id for c in do_banco if c.id not in progresso.do_banco)
        consultas = self._consultas_da_rodada(progresso) if self._fontes else []
        for indice, fonte in enumerate(self._fontes, start=1):
            nome = f"{indice}:{type(fonte).__name__}"
            try:
                for consulta in consultas:
                    chave = f"{nome}|{consulta}"
                    pagina = progresso.paginas_por_fonte.get(chave, 0) + 1
                    resultado = self._resiliencia.chamar(
                        nome,
                        partial(_buscar_na_fonte, fonte, self.vaga.empresa_id, consulta, pagina),
                        etapa="busca_fonte",
                    )
                    progresso.paginas_por_fonte[chave] = pagina
                    achados.extend(self._filtrar_achados(resultado, vistos))
            except ERROS_TEMPORARIOS as erro:
                fora.append(type(fonte).__name__)
                self._evento("fonte", f"{type(fonte).__name__}: {type(erro).__name__}")
        progresso.fontes_fora = fora
        total = 1 + len(self._fontes)
        if len(fora) == total:
            raise _PausaNecessaria(MotivoPausa.FONTES_INDISPONIVEIS)
        if fora:
            self._evento(
                "cobertura",
                f"cobertura parcial: {total - len(fora)} de {total} fontes; "
                f"fora do ar: {', '.join(fora)}",
            )
        return self._passar_pelo_funil(progresso, achados)

    def _ler_banco(self) -> list[Candidato]:
        """Todas as páginas do banco. Para quando uma página nada acrescenta: nunca fica presa."""
        lidos: dict[str, Candidato] = {}
        for pagina in count(1):
            resultado = self._resiliencia.chamar(
                f"0:{type(self._banco).__name__}",
                partial(
                    _buscar_na_fonte,
                    self._banco,
                    self.vaga.empresa_id,
                    CONSULTA_TODO_O_BANCO,
                    pagina,
                ),
                etapa="busca_fonte",
            )
            novos = {c.id: c for c in resultado if c.id not in lidos}
            if not novos:
                break
            lidos.update(novos)
        return list(lidos.values())

    def _consultas_da_rodada(self, progresso: ProgressoFluxo) -> list[str]:
        """Pede as consultas uma vez por rodada: retomar não paga pelo modelo de novo."""
        rodada = progresso.ampliacoes
        if rodada not in progresso.consultas_por_rodada:
            self._conferir_gasto()
            anteriores = list(
                dict.fromkeys(
                    consulta
                    for chave in sorted(progresso.consultas_por_rodada)
                    for consulta in progresso.consultas_por_rodada[chave]
                )
            )
            geradas = _pedir_consultas(self._consultas, self.vaga, rodada, anteriores)
            permitidas = [c for c in dict.fromkeys(geradas) if not tem_termo_sensivel(c)]
            if len(permitidas) != len(dict.fromkeys(geradas)):
                self._evento("busca", "consulta com dado sensível recusada")
            progresso.consultas_por_rodada[rodada] = permitidas
            self._copiar_campos(progresso, "consultas_por_rodada")
        return progresso.consultas_por_rodada[rodada]

    def _filtrar_achados(self, achados: list[Candidato], vistos: set[str]) -> list[Candidato]:
        novos = []
        for candidato in achados:
            if candidato.empresa_id != self.vaga.empresa_id:
                self._evento("busca", "candidato de outra empresa ignorado")
            elif candidato.id not in vistos:
                novos.append(candidato)
        return novos

    def _passar_pelo_funil(
        self, progresso: ProgressoFluxo, achados: list[Candidato]
    ) -> list[Candidato]:
        """Reduz os achados. Sem funil injetado, fica só a porta da autorização.

        O funil recebe todos os registros de cada pessoa: um opt-out em qualquer fonte vale
        para ela. Só o mesmo registro, achado por outra consulta, sai antes. Opt-out pedido em
        outra vaga da empresa vale aqui: quem saiu não vai ao modelo.
        """
        registros: dict[tuple[str, str, str], Candidato] = {}
        for candidato in achados:
            if self._tem_opt_out(candidato):
                candidato = candidato.model_copy(update={"opt_out": True})
            registros.setdefault((candidato.id, candidato.fonte, candidato.origem), candidato)
        hoje = self._relogio().date()
        cortes: list[CorteFunil] = []
        if self._priorizador is None:
            selecionados = self._so_quem_pode_ir_ao_modelo(registros.values(), hoje, cortes)
        else:
            selecionados = self._priorizador(
                self.vaga, list(registros.values()), hoje, cortes.append
            )
        self._registrar_cortes(progresso, cortes, registros)
        return selecionados

    def _so_quem_pode_ir_ao_modelo(
        self, registros: Iterable[Candidato], hoje: date, cortes: list[CorteFunil]
    ) -> list[Candidato]:
        por_pessoa: dict[str, Candidato] = {}
        for candidato in registros:
            por_pessoa.setdefault(candidato.id, candidato)
        selecionados = []
        for candidato in por_pessoa.values():
            corte = corte_de_autorizacao(candidato, hoje)
            if corte is None:
                selecionados.append(candidato)
            else:
                cortes.append(corte)
        return selecionados

    def _registrar_cortes(
        self,
        progresso: ProgressoFluxo,
        cortes: list[CorteFunil],
        registros: dict[tuple[str, str, str], Candidato],
    ) -> None:
        """Cada corte vira uma decisão. Refazer a busca depois de uma pausa não a repete.

        A reserva não é decisão: fica o evento, e a pessoa pode voltar em outra rodada.
        """
        mandato = self.mandato
        agora = self._relogio()
        ja_registradas = {
            (d.candidato_id, d.regra, d.entrada.get("fonte"), d.entrada.get("origem"))
            for d in self._repo.listar_decisoes(self.vaga.empresa_id, self.vaga.id)
        }
        na_reserva = {e.candidato_id for e in self.eventos if e.etapa == ETAPA_RESERVA}
        for corte in cortes:
            if str(corte.regra) in CORTES_SEM_DECISAO:
                if corte.candidato_id not in na_reserva:
                    self._evento(ETAPA_RESERVA, corte.motivo, corte.candidato_id)
                continue
            decisao = decisao_de_corte(
                corte, mandato, agora, self._rastro_id(progresso, corte.candidato_id)
            )
            chave = (
                decisao.candidato_id,
                decisao.regra,
                decisao.entrada["fonte"],
                decisao.entrada["origem"],
            )
            if chave not in ja_registradas:
                self._registrar_decisao(decisao)
                ja_registradas.add(chave)
            if decisao.regra != REGRA_DUPLICATA:
                candidato = registros[(corte.candidato_id, corte.fonte, corte.origem)]
                if str(corte.regra) in CORTES_POR_AUTORIZACAO:
                    candidato = _sem_dados_do_perfil(candidato)
                if candidato.id not in {c.id for c in progresso.cortados}:
                    progresso.cortados.append(candidato)

    def _percorrer(self, progresso: ProgressoFluxo, percurso: _Percurso) -> None:
        """Passa pelos candidatos da etapa, com até `concorrencia` chamadas ao modelo juntas.

        As chamadas saem em paralelo, mas cada resultado é gravado na ordem da lista, e o cursor só
        anda sobre quem já foi gravado. Assim uma queda retoma do mesmo ponto, e a sequência de
        decisões, eventos e pausas não depende de quem respondeu primeiro. O gasto é conferido
        antes de cada chamada; o limite rígido é do cliente, que reserva o pior caso de cada uma.
        """
        concorrencia = self._concorrencia
        chamador = _ChamadorNaLinha() if concorrencia == 1 else ThreadPoolExecutor(concorrencia)
        janela: deque[tuple[int, Candidato, Future[Analise] | None]] = deque()

        def gravar_o_mais_antigo() -> None:
            indice, candidato, futuro = janela.popleft()
            if futuro is None:
                self._concluir_candidato(indice)
                return
            try:
                analise = futuro.result()
                self._exigir_coerencia(analise, candidato)
            except RespostaInvalida:
                percurso.falhar(candidato, indice)
            else:
                percurso.concluir(analise, indice)

        try:
            for indice in range(self._cursor(), len(progresso.candidatos)):
                self._conferir_execucao()
                candidato = progresso.candidatos[indice]
                futuro = None
                if not percurso.pular(candidato):
                    self._conferir_gasto()
                    chamada = partial(percurso.chamar, candidato)
                    futuro = chamador.submit(contextvars.copy_context().run, chamada)
                janela.append((indice, candidato, futuro))
                while janela and (len(janela) >= concorrencia or janela[0][2] is None):
                    gravar_o_mais_antigo()
            while janela:
                gravar_o_mais_antigo()
        finally:
            self._guardar_o_que_ja_foi_pago(janela, percurso, chamador)

    def _guardar_o_que_ja_foi_pago(
        self,
        janela: deque[tuple[int, Candidato, Future[Analise] | None]],
        percurso: _Percurso,
        chamador: _ChamadorNaLinha | ThreadPoolExecutor,
    ) -> None:
        """Ao parar antes do fim, espera as chamadas em curso e guarda as que deram certo.

        Retomar não paga de novo por elas. Uma falha aqui é só registrada: o que interrompeu a
        etapa é o que precisa chegar a quem chamou.
        """
        for _, _, futuro in janela:
            if futuro is not None:
                futuro.cancel()
        chamador.shutdown(wait=True)
        try:
            if not janela or self._perdeu_a_vez():
                return
            for _, candidato, futuro in janela:
                if futuro is None or futuro.cancelled() or futuro.exception() is not None:
                    continue
                analise = futuro.result()
                self._exigir_coerencia(analise, candidato)
                percurso.guardar(analise)
        except Exception as erro:
            logger.warning("resultado em curso não foi guardado: %s", type(erro).__name__)

    def _passo_analisar(self) -> bool:
        progresso = self._progresso()
        hoje = self._relogio().date()

        def pular(candidato: Candidato) -> bool:
            atual = self._candidato_atual(candidato, progresso)
            ja_analisada = candidato.id in progresso.analises
            return ja_analisada or corte_de_autorizacao(atual, hoje) is not None

        def chamar(candidato: Candidato) -> Analise:
            with self._contexto(progresso, candidato.id):
                return _analisar(self._analisador, self.vaga, candidato)

        def falhar(candidato: Candidato, indice: int) -> None:
            self._contar_invalida(progresso, candidato, indice, "análise inválida")

        def guardar(analise: Analise) -> None:
            def gravar(atual: ProgressoFluxo) -> None:
                atual.analises[analise.candidato_id] = analise

            self._mudar(gravar)

        self._percorrer(
            progresso,
            _Percurso(
                pular=pular,
                chamar=chamar,
                concluir=partial(self._gravar_analise, progresso),
                falhar=falhar,
                guardar=guardar,
            ),
        )
        self._avancar(EstadoFluxo.REVISANDO, cursor=progresso.inicio_rodada)
        return True

    def _passo_revisar(self) -> bool:
        progresso = self._progresso()

        def pular(candidato: Candidato) -> bool:
            return candidato.id not in progresso.analises or candidato.id in progresso.revisadas

        def chamar(candidato: Candidato) -> Analise:
            analise = progresso.analises[candidato.id]
            with self._contexto(progresso, candidato.id):
                return _revisar(self._revisor, self.vaga, candidato, analise)

        def concluir(revisada: Analise, indice: int) -> None:
            progresso.revisadas.append(revisada.candidato_id)
            self._gravar_analise(progresso, revisada, indice, revisada=True)

        def falhar(candidato: Candidato, indice: int) -> None:
            analise = progresso.analises[candidato.id]
            ressalvas = [*analise.ressalvas_revisor, RESSALVA_REVISOR_INVALIDO]
            com_ressalva = analise.model_copy(update={"ressalvas_revisor": ressalvas})
            self._contar_invalida(progresso, candidato, indice, "revisão inválida", com_ressalva)

        def guardar(revisada: Analise) -> None:
            def gravar(atual: ProgressoFluxo) -> None:
                atual.analises[revisada.candidato_id] = revisada
                atual.revisadas.append(revisada.candidato_id)

            self._mudar(gravar)

        self._percorrer(
            progresso,
            _Percurso(pular, chamar, concluir, falhar, guardar),
        )
        self._avancar(EstadoFluxo.DECIDINDO)
        return True

    def _gravar_analise(
        self, progresso: ProgressoFluxo, analise: Analise, indice: int, *, revisada: bool = False
    ) -> None:
        """Depois do modelo, confere a vez: quem perdeu a vaga sai sem escrever."""
        if self._perdeu_a_vez():
            raise _VagaInterrompida
        progresso.analises[analise.candidato_id] = analise
        progresso.invalidas_seguidas = 0

        def gravar(atual: ProgressoFluxo) -> None:
            atual.analises[analise.candidato_id] = analise
            atual.invalidas_seguidas = 0
            if revisada:
                atual.revisadas.append(analise.candidato_id)

        self._mudar(gravar)
        self._concluir_candidato(indice)

    def _exigir_coerencia(self, analise: Analise, candidato: Candidato) -> None:
        esperado = (self.vaga.empresa_id, self.vaga.id, candidato.id)
        if (analise.empresa_id, analise.vaga_id, analise.candidato_id) != esperado:
            raise RespostaInvalida("análise de outra empresa, vaga ou candidato")

    def _concluir_candidato(self, indice: int) -> None:
        self._repo.atualizar_cursor(self.vaga.empresa_id, self.vaga.id, indice + 1)

    def _contar_invalida(
        self,
        progresso: ProgressoFluxo,
        candidato: Candidato,
        indice: int,
        mensagem: str,
        analise: Analise | None = None,
    ) -> None:
        """Falha isolada não para a vaga; três seguidas indicam um problema maior."""
        if self._perdeu_a_vez():
            raise _VagaInterrompida
        progresso.invalidas_seguidas += 1
        if analise is not None:
            progresso.analises[candidato.id] = analise
            progresso.revisadas.append(candidato.id)

        def gravar(atual: ProgressoFluxo) -> None:
            atual.invalidas_seguidas = progresso.invalidas_seguidas
            if analise is not None:
                atual.analises[candidato.id] = analise
                atual.revisadas.append(candidato.id)

        self._mudar(gravar)
        self._evento("falha_individual", mensagem, candidato.id)
        self._concluir_candidato(indice)
        if progresso.invalidas_seguidas >= LIMITE_INVALIDAS_SEGUIDAS:
            raise _PausaNecessaria(MotivoPausa.RESPOSTAS_INVALIDAS)

    def _passo_decidir(self) -> bool:
        """Decide quem falta. Refazer depois de uma queda não repete decisão já salva."""
        progresso = self._progresso()
        mandato = self.mandato
        agora = self._relogio()
        decididos = self._ultimas_decisoes()
        decisoes = [
            self._decidir_candidato(progresso, candidato, mandato, agora)
            for candidato in progresso.candidatos
            if candidato.id not in decididos
        ]
        limite = mandato.politica.max_indicacoes
        indicados = len(self._indicados())
        for decisao in sorted(decisoes, key=_ordem_de_decisao):
            self._conferir_execucao()
            if decisao.tipo == TipoDecisao.INDICAR:
                if indicados >= limite:
                    decisao = nao_priorizada(decisao, limite)
                else:
                    indicados += 1
            self._registrar_decisao(decisao)
        if not progresso.taxa_aceita and self._taxa_anomala(progresso, mandato):
            raise _PausaNecessaria(MotivoPausa.TAXA_ANOMALA)
        self._avaliar_meta(progresso, mandato)
        return True

    def _taxa_anomala(self, progresso: ProgressoFluxo, mandato: Mandato) -> bool:
        """Faixa verde vazia ou cheia demais sugere problema na regra ou nos dados."""
        analisados = len(progresso.analises)
        if mandato.politica.limiar_verde is None or analisados < MINIMO_PARA_MEDIR_TAXA:
            return False
        verdes = sum(
            decisao.regra in REGRAS_DA_FAIXA_VERDE for decisao in self._ultimas_decisoes().values()
        )
        return verdes == 0 or verdes / analisados > TAXA_VERDE_MAXIMA

    def _meta_efetiva(self, mandato: Mandato) -> int:
        return min(self.vaga.meta_candidatos, mandato.politica.max_indicacoes)

    def _avaliar_meta(self, progresso: ProgressoFluxo, mandato: Mandato) -> None:
        """Segue com a meta atingida; abaixo dela, amplia a busca ou avisa do risco."""
        if len(self._indicados()) >= self._meta_efetiva(mandato):
            self._avancar(self._estado_de_saida(mandato))
        elif progresso.ampliacoes < mandato.politica.max_ampliacoes:
            self._registrar_ampliacao(progresso)
            self._avancar(EstadoFluxo.BUSCANDO)
        else:
            self._avancar(EstadoFluxo.META_EM_RISCO)

    def _passo_meta_em_risco(self) -> bool:
        """Avisa quem recruta e segue com quem houver: a meta em risco não para a vaga."""
        mandato = self.mandato
        indicados = len(self._indicados())
        self._evento("aviso_rh", f"meta em risco: {indicados} de {self.vaga.meta_candidatos}")
        if indicados:
            self._avancar(self._estado_de_saida(mandato))
            return True
        self._evento("resultado", "sem indicação para esta vaga")
        self._ir(EstadoFluxo.CONCLUIDA)
        return False

    def _decidir_candidato(
        self, progresso: ProgressoFluxo, candidato: Candidato, mandato: Mandato, agora: datetime
    ) -> Decisao:
        rastro_id = self._rastro_id(progresso, candidato.id)
        analise = progresso.analises.get(candidato.id)
        atual = self._candidato_atual(candidato, progresso)
        if analise is None:
            corte = corte_de_autorizacao(atual, agora.date())
            if corte is not None:
                return decisao_de_corte(corte, mandato, agora, rastro_id)
            return decisao_sem_analise(self.vaga, candidato, mandato, agora, rastro_id)
        return decidir(self.vaga, atual, analise, mandato, agora.date(), agora, rastro_id)

    def _estado_de_saida(self, mandato: Mandato) -> EstadoFluxo:
        if mandato.politica.modo_entrega == ModoEntrega.NA_DECISAO:
            return EstadoFluxo.ENTREGANDO
        return EstadoFluxo.CONVIDANDO

    def _ultimas_decisoes(self) -> dict[str, Decisao]:
        """A decisão vigente de cada candidato, na ordem em que apareceram."""
        return decisoes_vigentes(self._repo.listar_decisoes(self.vaga.empresa_id, self.vaga.id))

    def _indicados(self) -> list[str]:
        return [
            candidato_id
            for candidato_id, decisao in self._ultimas_decisoes().items()
            if decisao.tipo == TipoDecisao.INDICAR
        ]

    def _passo_convidar(self) -> bool:
        """Entrega quem já aceitou, envia o que falta e só segue com os convites encerrados."""
        self._entregar_pendentes()
        self._convidar_indicados()
        abertos = (EstadoConvite.A_ENVIAR, EstadoConvite.AGUARDANDO)
        if any(r.estado in abertos for r in self._progresso().convites):
            return False
        self._avancar(EstadoFluxo.ENTREGANDO)
        return True

    def _convidar_indicados(self) -> None:
        """Depois do prazo da vaga, nenhum convite sai, nem o que tinha falhado."""
        self._encerrar_convites_vencidos()
        if self._prazo_vencido(self._progresso()):
            return
        for candidato_id in self._indicados():
            self._conferir_execucao()
            self._convidar(candidato_id)

    def _convidar(self, candidato_id: str) -> None:
        """Envia o primeiro convite da pessoa ou repete o que falhou, com a mesma chave."""
        progresso = self._progresso()
        registros = [r for r in progresso.convites if r.convite.candidato_id == candidato_id]
        ultimo = registros[-1] if registros else None
        with self._contexto(progresso, candidato_id):
            if ultimo is None:
                registro = self._novo_convite(progresso, candidato_id, tentativa=1)
            elif ultimo.estado == EstadoConvite.CANCELADO:
                registro = self._novo_convite(progresso, candidato_id, ultimo.tentativa + 1)
            elif ultimo.estado == EstadoConvite.A_ENVIAR:
                registro = ultimo
            else:
                return
            if registro.estado == EstadoConvite.A_ENVIAR:
                self._enviar(progresso, registro)

    def _texto_do_convite(
        self,
        progresso: ProgressoFluxo,
        candidato: Candidato,
        link: str | None,
        estado: EstadoConvite,
    ) -> str:
        """Texto do redator, quando houver; se ele falhar, o texto fixo segue sem parar o fluxo."""
        fixo = f"Temos uma vaga de {self.vaga.titulo} que combina com o seu perfil."
        analise = progresso.analises.get(candidato.id)
        if self._redator_convite is None or analise is None or estado != EstadoConvite.A_ENVIAR:
            return fixo
        try:
            return self._redator_convite(self.vaga, candidato, analise, link)
        except Exception:
            logger.warning("convite da vaga %s usou o texto fixo", self.vaga.id, exc_info=True)
            return fixo

    def _novo_convite(
        self, progresso: ProgressoFluxo, candidato_id: str, tentativa: int
    ) -> RegistroConvite:
        """Grava o convite antes do envio. Pessoa bloqueada não tem nem o link pedido ao destino."""
        candidato = progresso.candidato(candidato_id)
        atual = self._candidato_atual(candidato, progresso)
        hoje = self._relogio().date()
        if pode_contatar(atual, tentativa - 1, self.vaga, hoje):
            link = self._link_de_agendamento(candidato_id)
            estado = EstadoConvite.A_ENVIAR
        else:
            link = None
            estado = EstadoConvite.ENCERRADO
        identificador = f"{self.vaga.id}:{candidato_id}:{tentativa}"
        mensagem = self._texto_do_convite(progresso, atual, link, estado)
        convite = Convite(
            id=f"convite:{identificador}",
            empresa_id=self.vaga.empresa_id,
            tipo=TipoConvite.VAGA,
            canal=CANAL_CONVITE,
            vaga_id=self.vaga.id,
            candidato_id=candidato_id,
            mensagem=mensagem,
            link_agendamento=link,
            chave_idempotencia=f"convite:{self.vaga.empresa_id}:{identificador}",
            simulado=candidato.simulado,
        )
        registro = RegistroConvite(convite=convite, tentativa=tentativa, estado=estado)

        def acrescentar(atual_progresso: ProgressoFluxo) -> None:
            if not any(r.convite.id == convite.id for r in atual_progresso.convites):
                atual_progresso.convites.append(registro)

        self._mudar(acrescentar)
        if estado == EstadoConvite.ENCERRADO:
            self._evento("convite", "contato bloqueado pelas regras", candidato_id)
        return registro

    def _link_de_agendamento(self, candidato_id: str) -> str | None:
        """O agendamento é opcional: sem link, o convite segue e o fluxo não trava."""
        try:
            return _pedir_link(self._destino, self.vaga.id, candidato_id)
        except (ErroContrato, OSError) as erro:
            self._evento("convite", f"destino sem link: {type(erro).__name__}", candidato_id)
            return None

    def _acao_idempotente(self, chave: str, acao: Callable[[], bool]) -> bool | None:
        """Faz a ação ao menos uma vez e nunca de novo depois de concluída.

        Devolve `None` se outra execução está fazendo a mesma ação agora: a reserva evita chamar
        duas vezes. Uma queda deixa a chave pendente, e, com a reserva vencida, a ação se repete
        com a mesma chave, que o destino usa para descartar a duplicata.
        """
        empresa_id = self.vaga.empresa_id
        if self._repo.chave_concluida(empresa_id, chave):
            return True
        self._repo.registrar_chave(empresa_id, chave)
        if not self._repo.reservar_chave(empresa_id, chave, self._relogio(), VALIDADE_DA_RESERVA):
            return None
        try:
            feita = acao()
            if feita:
                self._repo.concluir_chave(empresa_id, chave)
            return feita
        except (ErroContrato, OSError) as erro:
            self._evento("idempotencia", f"ação falhou: {type(erro).__name__}")
            return False
        finally:
            self._repo.liberar_chave(empresa_id, chave)

    def _mudar_convite(self, registro: RegistroConvite, novo: EstadoConvite) -> None:
        """Só o convite ainda a enviar muda: um opt-out que chegou no meio não é desfeito."""

        def mudar(progresso: ProgressoFluxo) -> None:
            for atual in progresso.convites:
                if (
                    atual.convite.id == registro.convite.id
                    and atual.estado == EstadoConvite.A_ENVIAR
                ):
                    atual.estado = novo

        self._mudar(mudar)

    def _enviar(self, progresso: ProgressoFluxo, registro: RegistroConvite) -> None:
        """Confere a situação da pessoa imediatamente antes do envio."""
        candidato = progresso.candidato(registro.convite.candidato_id)
        atual = self._candidato_atual(candidato, progresso)
        hoje = self._relogio().date()
        if not pode_contatar(atual, registro.tentativa - 1, self.vaga, hoje):
            self._mudar_convite(registro, EstadoConvite.ENCERRADO)
            self._evento("convite", "contato bloqueado pelas regras", candidato.id)
            return
        feito = self._acao_idempotente(
            registro.convite.chave_idempotencia,
            lambda: _enviar_convite(self._mensageiro, registro.convite),
        )
        if feito is None:
            self._evento("convite", "envio em andamento em outra execução", candidato.id)
        elif feito:
            self._mudar_convite(registro, EstadoConvite.AGUARDANDO)
            self._evento("convite", "convite enviado", candidato.id)
        else:
            self._evento("convite", "envio do convite falhou", candidato.id)

    def _aplicar_resposta(self, convite_id: str, tipo: TipoResposta) -> None:
        """Grava a resposta. Com silêncio, deixa o novo convite a enviar, se a pessoa pode."""

        def aplicar(progresso: ProgressoFluxo) -> tuple[str, str, RegistroConvite] | None:
            registro = next(r for r in progresso.convites if r.convite.id == convite_id)
            candidato_id = registro.convite.candidato_id
            alvo = registro
            fechados = (EstadoConvite.ENCERRADO, EstadoConvite.CANCELADO)
            if registro.estado in fechados and tipo in (TipoResposta.ACEITE, TipoResposta.RECUSA):
                alvo = self._convite_aberto(progresso, registro) or registro
            if alvo.estado in fechados:
                return ("resposta", "resposta tardia: convite já encerrado", alvo)
            if alvo.estado == EstadoConvite.ACEITO:
                if tipo != TipoResposta.RECUSA:
                    return None
                if candidato_id in progresso.entregues:
                    return ("aviso_destino", "recusa depois da entrega: avisar o destino", alvo)
                alvo.estado = EstadoConvite.ENCERRADO
                return ("resposta", "recusa depois do aceite: entrega cancelada", alvo)
            if alvo.estado == EstadoConvite.A_ENVIAR and alvo is registro:
                return None
            if tipo == TipoResposta.ACEITE:
                alvo.estado = EstadoConvite.ACEITO
            elif tipo in (TipoResposta.RECUSA, TipoResposta.SILENCIO):
                alvo.estado = EstadoConvite.ENCERRADO
            return ("resposta_aplicada", "", alvo)

        resultado = self._mudar(aplicar)
        if resultado is None:
            return
        etapa, mensagem, registro = resultado
        candidato_id = registro.convite.candidato_id
        if etapa != "resposta_aplicada":
            self._evento(etapa, mensagem, candidato_id)
        elif tipo == TipoResposta.SILENCIO:
            self._preparar_reenvio(candidato_id, registro.tentativa)

    @staticmethod
    def _convite_aberto(
        progresso: ProgressoFluxo, registro: RegistroConvite
    ) -> RegistroConvite | None:
        """O convite mais novo em aberto da mesma pessoa: ela pode responder ao anterior."""
        abertos = (EstadoConvite.A_ENVIAR, EstadoConvite.AGUARDANDO)
        return next(
            (
                r
                for r in reversed(progresso.convites)
                if r.convite.candidato_id == registro.convite.candidato_id
                and r.tentativa > registro.tentativa
                and r.estado in abertos
            ),
            None,
        )

    def _preparar_reenvio(self, candidato_id: str, tentativa: int) -> None:
        """Deixa o convite a enviar. Quem envia é a execução, que confere estado e mandato."""
        progresso = self._progresso()
        atual = self._candidato_atual(progresso.candidato(candidato_id), progresso)
        if pode_contatar(atual, tentativa, self.vaga, self._relogio().date()):
            self._novo_convite(progresso, candidato_id, tentativa + 1)

    def _registrar_opt_out(self, candidato_id: str) -> None:
        """Vale em qualquer estado e para toda a empresa. Vale aqui antes de chegar ao banco."""
        progresso = self._progresso()
        candidato = progresso.candidato(candidato_id)
        self._repo.registrar_bloqueios(self.vaga.empresa_id, self._resumos(candidato))

        def marcar(atual: ProgressoFluxo) -> None:
            for lista in (atual.candidatos, atual.cortados):
                for indice, pessoa in enumerate(lista):
                    if pessoa.id == candidato_id:
                        lista[indice] = pessoa.model_copy(update={"opt_out": True})
            for registro in atual.convites:
                if registro.convite.candidato_id == candidato_id:
                    registro.estado = EstadoConvite.ENCERRADO
            if candidato_id not in atual.opt_outs_a_propagar:
                atual.opt_outs_a_propagar.append(candidato_id)

        self._mudar(marcar)
        if self._ja_chegou_ao_destino(progresso, candidato_id):
            self._evento(
                "aviso_destino",
                "opt-out depois da entrega: avisar o destino, sem retirada do pacote",
                candidato_id,
            )
        self._propagar_opt_outs()

    def _propagar_opt_outs(self) -> None:
        """Leva ao banco os opt-outs que já valem aqui. Falha fica para a próxima tentativa."""
        for candidato_id in list(self._progresso().opt_outs_a_propagar):
            try:
                _gravar_opt_out(self._banco, self.vaga.empresa_id, candidato_id)
            except KeyError:
                self._evento(
                    "resposta", "opt-out de pessoa fora do banco de talentos", candidato_id
                )
            except Exception as erro:
                self._evento(
                    "resposta",
                    f"opt-out vale aqui, banco sem resposta: {type(erro).__name__}",
                    candidato_id,
                )
                continue
            self._retirar_da_propagacao(candidato_id)

    def _retirar_da_propagacao(self, candidato_id: str) -> None:
        def retirar(atual: ProgressoFluxo) -> None:
            atual.opt_outs_a_propagar.remove(candidato_id)

        self._mudar(retirar)

    def _passo_entregar(self) -> bool:
        self._entregar_pendentes()
        if self.estado == EstadoFluxo.PAUSADA:
            raise _VagaInterrompida
        self._ir(EstadoFluxo.CONCLUIDA)
        return False

    def _convite_encerrado(self, progresso: ProgressoFluxo, candidato_id: str) -> bool:
        """A última resposta da pessoa fechou o convite: ela não segue para o destino."""
        registros = [r for r in progresso.convites if r.convite.candidato_id == candidato_id]
        return bool(registros) and registros[-1].estado == EstadoConvite.ENCERRADO

    def _a_entregar(self, progresso: ProgressoFluxo) -> list[str]:
        indicados = self._indicados()
        if self.mandato.politica.modo_entrega == ModoEntrega.NA_DECISAO:
            base = [c for c in indicados if not self._convite_encerrado(progresso, c)]
        else:
            base = [
                r.convite.candidato_id
                for r in progresso.convites
                if r.estado == EstadoConvite.ACEITO
            ]
        return [c for c in base if c in indicados and c not in progresso.entregues]

    def _entregar_pendentes(self) -> None:
        """Entrega quem falta. Falha do destino pausa a vaga, com a entrega ainda pendente."""
        progresso = self._progresso()
        hoje = self._relogio().date()
        for candidato_id in self._a_entregar(progresso):
            self._conferir_execucao()
            atual = self._candidato_atual(progresso.candidato(candidato_id), progresso)
            if autorizacao_ativa(atual, hoje):
                self._entregar(progresso, atual)
            else:
                self._evento("entrega", "entrega cancelada: sem autorização", candidato_id)

    def _entregar(self, progresso: ProgressoFluxo, candidato: Candidato) -> None:
        chave = self._chave_de_entrega(candidato.id)
        decisao = self._ultimas_decisoes()[candidato.id]
        pacote = self._pacote(candidato, progresso.analises[candidato.id], decisao.rastro_id, chave)
        with self._contexto(progresso, candidato.id):
            entregue = self._acao_idempotente(
                chave,
                lambda: self._resiliencia.chamar(
                    "destino",
                    partial(
                        _entregar_pacote,
                        self._destino,
                        self._identificado(pacote, candidato, decisao),
                    ),
                    etapa="entrega_destino",
                ),
            )
        if entregue is None:
            self._evento("entrega", "entrega em andamento em outra execução", candidato.id)
            return
        if not entregue:
            raise _PausaNecessaria(MotivoPausa.DESTINO_INDISPONIVEL)

        def registrar(atual: ProgressoFluxo) -> None:
            if candidato.id not in atual.entregues:
                atual.entregues.append(candidato.id)

        self._mudar(registrar)
        self._evento("entrega", "pacote de contexto entregue", candidato.id)

    def _identificado(
        self, pacote: PacoteContexto, candidato: Candidato, decisao: Decisao
    ) -> PacoteContexto:
        """Só a entrega, já decidida, devolve os dados originais. Sem reidentificador, não há."""
        if self._reidentificador is None:
            return pacote
        return self._reidentificador(pacote, candidato, self.vaga, decisao)

    def _chave_de_entrega(self, candidato_id: str) -> str:
        return f"entrega:{self.vaga.empresa_id}:{self.vaga.id}:{candidato_id}"

    def _pacote(
        self, candidato: Candidato, analise: Analise, rastro_id: str, chave: str
    ) -> PacoteContexto:
        """Monta o pacote só com evidência conferida dos critérios da vaga.

        Afirmação sem fonte não vai adiante. Texto livre do modelo que parece instrução sai, e o
        restante chega marcado como não verificado.
        """
        criterios = {r.id for r in self.vaga.requisitos} | {c.nome for c in self.vaga.competencias}
        evidencias = [
            e
            for e in analise.evidencias
            if e.criterio in criterios
            and classificar_evidencia(e, candidato) != TipoEvidencia.INFERIDA
        ]
        motivos: dict[str, str] = {}
        for evidencia in evidencias:
            motivos.setdefault(evidencia.criterio, evidencia.trecho)
        return PacoteContexto(
            empresa_id=self.vaga.empresa_id,
            vaga_id=self.vaga.id,
            candidato_id=candidato.id,
            motivo_por_criterio=motivos,
            historico=candidato.historico,
            evidencias=evidencias,
            lacunas=[t for t in analise.lacunas if not parece_instrucao(t)],
            pontos_a_aprofundar=[
                f"{ROTULO_NAO_VERIFICADO}{t}"
                for t in analise.pontos_a_aprofundar
                if not parece_instrucao(t)
            ],
            ressalvas_revisor=[t for t in analise.ressalvas_revisor if not parece_instrucao(t)],
            autorizacao=f"valida_ate:{candidato.autorizacao_valida_ate}",
            fonte=candidato.fonte,
            rastro_id=rastro_id,
            chave_idempotencia=chave,
            simulado=candidato.simulado,
        )
