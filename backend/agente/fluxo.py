"""Máquina de estados de uma vaga e a condução do fluxo por ela.

Os estados não citam um destino específico: agendamento e retorno da entrevista são
opcionais. `FluxoVaga` não guarda estado em memória: tudo o que permite continuar está
no `Repositorio`, e um novo objeto sobre o mesmo arquivo continua de onde o outro parou.
"""

import hashlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from pydantic import AwareDatetime

from backend.agente.mandato import (
    Mandato,
    MandatoInvalido,
    ModoEntrega,
    Politica,
    assinar,
    hash_da_vaga,
    mandato_valido,
)
from backend.agente.persistencia import Repositorio
from backend.agente.regras import (
    TipoEvidencia,
    autorizacao_ativa,
    classificar_evidencia,
    criterios_sem_evidencia,
    decidir,
    decisao_sem_analise,
    nao_priorizada,
    pode_contatar,
    validar_criterios,
)
from backend.contratos.erros import (
    ErroContrato,
    FonteIndisponivel,
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
    EventoFluxo,
    Evidencia,
    PacoteContexto,
    RespostaCandidato,
    TipoConvite,
    TipoDecisao,
    TipoResposta,
    Vaga,
)


class TransicaoInvalida(ErroContrato):
    """Transição fora da tabela ou sem a guarda exigida."""


class EstadoFluxo(StrEnum):
    RASCUNHO = "rascunho"
    AGUARDANDO_MANDATO = "aguardando_mandato"
    BUSCANDO = "buscando"
    ANALISANDO = "analisando"
    REVISANDO = "revisando"
    DECIDINDO = "decidindo"
    META_EM_RISCO = "meta_em_risco"
    CONVIDANDO = "convidando"
    ENTREGANDO = "entregando"
    PAUSADA = "pausada"
    CONCLUIDA = "concluida"


ESTADOS_ATIVOS = frozenset(
    {
        EstadoFluxo.BUSCANDO,
        EstadoFluxo.ANALISANDO,
        EstadoFluxo.REVISANDO,
        EstadoFluxo.DECIDINDO,
        EstadoFluxo.META_EM_RISCO,
        EstadoFluxo.CONVIDANDO,
        EstadoFluxo.ENTREGANDO,
    }
)
"""Estados em execução, depois da assinatura: só eles pausam e só eles exigem mandato válido."""


def _ou_pausa(*destinos: EstadoFluxo) -> frozenset[EstadoFluxo]:
    return frozenset({*destinos, EstadoFluxo.PAUSADA})


TRANSICOES: Mapping[EstadoFluxo, frozenset[EstadoFluxo]] = MappingProxyType(
    {
        EstadoFluxo.RASCUNHO: frozenset({EstadoFluxo.AGUARDANDO_MANDATO}),
        EstadoFluxo.AGUARDANDO_MANDATO: frozenset({EstadoFluxo.BUSCANDO, EstadoFluxo.RASCUNHO}),
        EstadoFluxo.BUSCANDO: _ou_pausa(EstadoFluxo.ANALISANDO, EstadoFluxo.META_EM_RISCO),
        EstadoFluxo.ANALISANDO: _ou_pausa(EstadoFluxo.REVISANDO),
        EstadoFluxo.REVISANDO: _ou_pausa(EstadoFluxo.DECIDINDO),
        EstadoFluxo.DECIDINDO: _ou_pausa(
            EstadoFluxo.BUSCANDO,
            EstadoFluxo.META_EM_RISCO,
            EstadoFluxo.CONVIDANDO,
            EstadoFluxo.ENTREGANDO,
        ),
        EstadoFluxo.META_EM_RISCO: _ou_pausa(
            EstadoFluxo.CONVIDANDO, EstadoFluxo.ENTREGANDO, EstadoFluxo.CONCLUIDA
        ),
        EstadoFluxo.CONVIDANDO: _ou_pausa(EstadoFluxo.ENTREGANDO),
        EstadoFluxo.ENTREGANDO: _ou_pausa(EstadoFluxo.CONCLUIDA),
        # A tabela lista os destinos possíveis; `_transitar` só aceita o estado anterior salvo.
        EstadoFluxo.PAUSADA: ESTADOS_ATIVOS,
        EstadoFluxo.CONCLUIDA: frozenset(),
    }
)


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
LIMITE_INVALIDAS_SEGUIDAS = 3
MINIMO_PARA_MEDIR_TAXA = 10
TAXA_VERDE_MAXIMA = 0.8
REGRAS_DA_FAIXA_VERDE = frozenset({"faixa_verde_v1", "nao_priorizado"})
RESSALVA_REVISOR_INVALIDO = "revisor_resposta_invalida"


class MotivoPausa(StrEnum):
    LIMITE_GASTO = "LIMITE_GASTO"
    MODELO_INDISPONIVEL = "MODELO_INDISPONIVEL"
    FONTES_INDISPONIVEIS = "FONTES_INDISPONIVEIS"
    DESTINO_INDISPONIVEL = "DESTINO_INDISPONIVEL"
    MANDATO_INVALIDO = "MANDATO_INVALIDO"
    RESPOSTAS_INVALIDAS = "RESPOSTAS_INVALIDAS"
    AUDITORIA_REPROVADA = "AUDITORIA_REPROVADA"
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


class DestinoPessoa(StrEnum):
    """Para onde a pessoa vai depois da vaga. É sempre decisão humana."""

    BANCO = "banco"
    TALENT_GARDEN = "talent_garden"
    CONTRATADA = "contratada"


class ResumoVaga(Contrato):
    """Controle depois da ação: o que o agente fez dentro do mandato. Modelo local."""

    vaga_id: str
    estado: str
    motivo_pausa: str | None
    mandato_versao: int | None
    limite_gasto_usd: float | None
    gasto_usd: float | None
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
    ampliacoes: int = 0
    inicio_rodada: int = 0
    fontes_fora: list[str] = []
    taxa_aceita: bool = False
    candidatos: list[Candidato] = []
    analises: dict[str, Analise] = {}
    analises_invalidas: list[str] = []
    invalidas_seguidas: int = 0
    versao_mandato_na_pausa: int | None = None
    convites: list[RegistroConvite] = []
    entregues: list[str] = []
    destinos: dict[str, DestinoPessoa] = {}

    def candidato(self, candidato_id: str) -> Candidato:
        return next(c for c in self.candidatos if c.id == candidato_id)


def _exigir_humano(responsavel: str) -> str:
    nome = responsavel.strip()
    if not nome or nome.casefold().startswith("agente"):
        raise ValueError("esta é uma decisão humana: informe a pessoa responsável")
    return nome


def _exigir_motivo(motivo: str) -> str:
    texto = motivo.strip()
    if not texto:
        raise ValueError("informe o motivo da decisão")
    return texto


def _resumo_da_decisao(decisao: Decisao) -> str:
    return hashlib.sha256(decisao.model_dump_json().encode("utf-8")).hexdigest()[:16]


def _consulta_pelo_titulo(vaga: Vaga, rodada: int) -> list[str]:
    return [vaga.titulo]


def _ordem_de_decisao(decisao: Decisao) -> tuple[float, str]:
    """Faixa verde primeiro, por nota decrescente; empates e demais, por `id`."""
    if decisao.tipo == TipoDecisao.INDICAR:
        return (-float(decisao.entrada["nota"]), decisao.candidato_id)
    return (1.0, decisao.candidato_id)


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
        consultas: Callable[[Vaga, int], list[str]] = _consulta_pelo_titulo,
        medidor_gasto: Callable[[], float] | None = None,
    ) -> None:
        self._repo = repositorio
        self._banco = banco
        self._fontes = fontes
        self._analisador = analisador
        self._revisor = revisor
        self._mensageiro = mensageiro
        self._destino = destino
        self._relogio = relogio
        self._consultas = consultas
        self._medidor_gasto = medidor_gasto
        self.vaga = vaga
        if self.mandato is not None:
            self.vaga = vaga.model_copy(update={"aprovada": True})

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
        """Troca o conteúdo da vaga. Antes da assinatura, uma mudança volta ao rascunho."""
        if (vaga.id, vaga.empresa_id) != (self.vaga.id, self.vaga.empresa_id):
            raise ValueError("a edição precisa ser da mesma vaga e da mesma empresa")
        mudou = hash_da_vaga(vaga) != hash_da_vaga(self.vaga)
        self.vaga = vaga
        if mudou and self.estado == EstadoFluxo.AGUARDANDO_MANDATO:
            self._ir(EstadoFluxo.RASCUNHO, motivo="vaga editada antes da assinatura")

    def assinar_mandato(
        self,
        assinante: str,
        limite_gasto_usd: float,
        politica: Politica,
        valido_ate: datetime | None = None,
    ) -> None:
        """Registra a assinatura e executa até a vaga depender de resposta externa.

        Com a vaga pausada, vira um aditivo: uma nova versão, que só vale depois de `retomar`.
        """
        agora = self._relogio()
        if self.estado == EstadoFluxo.PAUSADA:
            versao = self.mandato.versao + 1
            aditivo = self._assinar(
                assinante, limite_gasto_usd, politica, valido_ate, versao, agora
            )
            self._evento("mandato", f"aditivo assinado: versão {aditivo.versao}")
            self._avisar_limiar(aditivo)
            return
        if self.estado != EstadoFluxo.AGUARDANDO_MANDATO:
            raise TransicaoInvalida(f"{self.estado} não aceita assinatura de mandato")
        mandato = self._assinar(assinante, limite_gasto_usd, politica, valido_ate, 1, agora)
        self.vaga = self.vaga.model_copy(update={"aprovada": True})
        self._salvar_progresso(ProgressoFluxo(iniciado_em=agora))
        self._avisar_limiar(mandato)
        self._ir(EstadoFluxo.BUSCANDO)
        self._executar()

    def registrar_resposta(self, resposta: RespostaCandidato) -> None:
        """Aplica a resposta da pessoa. O texto dela é dado e não entra nos eventos."""
        progresso = self._progresso()
        registro = next(
            (r for r in progresso.convites if r.convite.id == resposta.convite_id), None
        )
        if registro is None:
            raise ValueError(f"convite desconhecido nesta vaga: {resposta.convite_id!r}")
        candidato_id = registro.convite.candidato_id
        self._evento("resposta", f"resposta: {resposta.tipo}", candidato_id)

        if resposta.tipo == TipoResposta.OPT_OUT:
            self._registrar_opt_out(progresso, candidato_id)
        elif registro.estado in (EstadoConvite.ENCERRADO, EstadoConvite.CANCELADO):
            self._evento("resposta", "resposta tardia: convite já encerrado", candidato_id)
        elif registro.estado == EstadoConvite.AGUARDANDO:
            self._aplicar_resposta(progresso, registro, resposta.tipo)
        self._salvar_progresso(progresso)

        if self.estado == EstadoFluxo.CONVIDANDO:
            self._executar()
        elif self.estado == EstadoFluxo.CONCLUIDA and resposta.tipo == TipoResposta.ACEITE:
            self._entregar_fora_da_execucao()

    def verificar_prazo(self) -> None:
        """Reenvia convites que falharam e, com o prazo da vaga vencido, encerra os abertos."""
        if self.estado != EstadoFluxo.CONVIDANDO:
            return
        progresso = self._progresso()
        limite = progresso.iniciado_em + timedelta(days=self.vaga.prazo_dias)
        if self._relogio() >= limite:
            for registro in progresso.convites:
                if registro.estado == EstadoConvite.AGUARDANDO:
                    registro.estado = EstadoConvite.ENCERRADO
                    self._evento("convite", "prazo vencido", registro.convite.candidato_id)
            self._salvar_progresso(progresso)
        self._executar()

    def parar(self) -> None:
        """Pausa a vaga. Quem está em execução sai antes do próximo candidato."""
        estado = self.estado
        if estado == EstadoFluxo.PAUSADA:
            return
        try:
            self._ir(EstadoFluxo.PAUSADA, cursor=self._cursor(), motivo=MotivoPausa.PARADA_PELO_RH)
        except _VagaInterrompida:
            self.parar()

    def retomar(self) -> None:
        """Continua de onde parou: depois de uma pausa ou de uma queda em estado ativo."""
        execucao = self._repo.carregar_estado(self.vaga.empresa_id, self.vaga.id)
        estado = self.estado
        if estado == EstadoFluxo.PAUSADA:
            self._sair_da_pausa(execucao.motivo, execucao.estado_anterior, execucao.cursor)
        elif estado == EstadoFluxo.CONCLUIDA:
            self._entregar_fora_da_execucao()
            return
        elif estado not in ESTADOS_ATIVOS:
            raise TransicaoInvalida(f"{estado} não tem execução para retomar")
        self._executar()

    def reverter(self, candidato_id: str, motivo: str, responsavel: str) -> Decisao:
        """Devolve a decisão à fila humana, sem apagar a original nem mudar o estado da vaga.

        Depois da entrega, o pacote não pode ser retirado: fica o aviso para combinar com o destino.
        """
        nome, motivo = _exigir_humano(responsavel), _exigir_motivo(motivo)
        atual = self._decisao_vigente(candidato_id)
        if atual.regra == "reversao_humana":
            return atual
        if atual.tipo == TipoDecisao.PEDIR_HUMANO:
            raise ValueError("não há decisão a reverter: a pessoa já está na fila humana")
        nova = self._decisao_humana(
            atual, TipoDecisao.PEDIR_HUMANO, "reversao_humana", motivo, nome, atual.evidencias
        )
        self._cancelar_convites(candidato_id)
        progresso = self._progresso()
        if candidato_id in progresso.entregues:
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
        nome, motivo = _exigir_humano(responsavel), _exigir_motivo(motivo)
        if tipo not in (TipoDecisao.INDICAR, TipoDecisao.DESCARTAR):
            raise ValueError("a fila se resolve com indicar ou descartar")
        atual = self._decisao_vigente(candidato_id)
        if atual.tipo != TipoDecisao.PEDIR_HUMANO:
            raise ValueError("a pessoa não está na fila humana")
        progresso = self._progresso()
        analise = progresso.analises.get(candidato_id)
        if tipo == TipoDecisao.INDICAR:
            self._exigir_evidencias(progresso.candidato(candidato_id), analise)
        evidencias = [] if analise is None else analise.evidencias
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
            motivo_pausa=None if execucao is None else execucao.motivo,
            mandato_versao=None if mandato is None else mandato.versao,
            limite_gasto_usd=None if mandato is None else mandato.limite_gasto_usd,
            gasto_usd=None if self._medidor_gasto is None else self._medidor_gasto(),
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
            simulado=progresso is not None and any(c.simulado for c in progresso.candidatos),
        )

    def registrar_destino(
        self, candidato_id: str, destino: DestinoPessoa, responsavel: str
    ) -> None:
        """Guarda para onde a pessoa vai depois da vaga. Só uma pessoa decide isso."""
        nome = _exigir_humano(responsavel)
        destino = DestinoPessoa(destino)
        self._decisao_vigente(candidato_id)
        progresso = self._progresso()
        candidato = progresso.candidato(candidato_id)
        if candidato.opt_out and destino != DestinoPessoa.CONTRATADA:
            raise ValueError("pessoa com opt-out não volta ao banco nem ao talent garden")
        progresso.destinos[candidato_id] = destino
        self._salvar_progresso(progresso)
        self._evento("destino", f"destino {destino} definido por {nome}", candidato_id)

    def _decisao_vigente(self, candidato_id: str) -> Decisao:
        decisao = self._ultimas_decisoes().get(candidato_id)
        if decisao is None:
            raise ValueError(f"candidato sem decisão nesta vaga: {candidato_id!r}")
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
            },
            evidencias=evidencias,
            momento=self._relogio(),
        )
        self._repo.salvar_decisao(decisao)
        self._evento("decisao", f"{decisao.tipo}: {decisao.regra}", decisao.candidato_id)
        return decisao

    def _exigir_evidencias(self, candidato: Candidato, analise: Analise | None) -> None:
        if analise is None:
            raise ValueError("sem análise válida não há evidência para indicar a pessoa")
        faltando = criterios_sem_evidencia(self.vaga, candidato, analise)
        if faltando:
            raise ValueError(f"sem evidência conferida para: {', '.join(faltando)}")

    def _cancelar_convites(self, candidato_id: str) -> None:
        """Encerra o que estava aberto. Convite já enviado não volta, e resposta vira tardia."""
        progresso = self._progresso()
        abertos = (EstadoConvite.A_ENVIAR, EstadoConvite.AGUARDANDO, EstadoConvite.ACEITO)
        for registro in progresso.convites:
            if registro.convite.candidato_id == candidato_id and registro.estado in abertos:
                registro.estado = EstadoConvite.CANCELADO
        self._salvar_progresso(progresso)

    def _agir_sobre_indicacao(self, candidato_id: str) -> None:
        """Convoca ou entrega quem uma pessoa indicou. Antes disso, o fluxo cuida ao chegar lá."""
        estado = self.estado
        if estado == EstadoFluxo.CONVIDANDO:
            self._executar()
        elif estado in (EstadoFluxo.ENTREGANDO, EstadoFluxo.CONCLUIDA):
            if self.mandato.politica.modo_entrega == ModoEntrega.NA_DECISAO:
                self._entregar_fora_da_execucao()
            else:
                progresso = self._progresso()
                self._convidar(progresso, candidato_id)
                self._salvar_progresso(progresso)

    def _entregar_fora_da_execucao(self) -> None:
        """Entrega tardia, com a vaga concluída: uma falha fica pendente e não reabre a vaga."""
        with self._pausando_em_falha():
            self._entregar_pendentes()

    def _sair_da_pausa(self, motivo: str | None, anterior: str | None, cursor: int) -> None:
        progresso = self._progresso()
        versao_na_pausa = progresso.versao_mandato_na_pausa
        if motivo in MOTIVOS_QUE_EXIGEM_ADITIVO and self.mandato.versao == versao_na_pausa:
            raise MandatoInvalido(f"{motivo} só retoma com um aditivo assinado")
        self._ir(EstadoFluxo(anterior), cursor=cursor, motivo=f"retomada de {motivo}")
        progresso.invalidas_seguidas = 0
        progresso.taxa_aceita = progresso.taxa_aceita or motivo == MotivoPausa.TAXA_ANOMALA
        self._salvar_progresso(progresso)

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

    def _conferir_execucao(self) -> None:
        if self.estado == EstadoFluxo.PAUSADA:
            raise _VagaInterrompida
        mandato = self.mandato
        if mandato is None or not mandato_valido(mandato, self.vaga, self._relogio()):
            raise MandatoInvalido("mandato não vale para esta vaga neste momento")

    def _conferir_gasto(self) -> None:
        if (
            self._medidor_gasto is not None
            and self._medidor_gasto() >= self.mandato.limite_gasto_usd
        ):
            raise LimiteGastoAtingido("gasto chegou ao limite assinado no mandato")

    def _pausar(self, motivo: MotivoPausa) -> None:
        """Salva o motivo e o ponto de retomada. Parada humana em curso não é sobrescrita."""
        if self.estado not in ESTADOS_ATIVOS:
            self._evento("pausa", f"sem execução para pausar: {motivo}")
            return
        progresso = self._progresso()
        progresso.versao_mandato_na_pausa = self.mandato.versao
        self._salvar_progresso(progresso)
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
        with self._pausando_em_falha():
            continuar = True
            while continuar and self.estado in passos:
                if self.estado != EstadoFluxo.ENTREGANDO:
                    self._conferir_execucao()
                continuar = passos[self.estado]()

    def _passo_buscar(self) -> bool:
        """Busca a rodada atual. Sem ninguém novo, gasta ampliações até o limite do mandato."""
        progresso = self._progresso()
        limite = self.mandato.politica.max_ampliacoes
        novos = self._buscar(progresso)
        while not novos and progresso.ampliacoes < limite:
            self._registrar_ampliacao(progresso)
            novos = self._buscar(progresso)
        progresso.inicio_rodada = len(progresso.candidatos)
        progresso.candidatos.extend(novos)
        self._salvar_progresso(progresso)
        if novos:
            self._avancar(EstadoFluxo.ANALISANDO, cursor=progresso.inicio_rodada)
        else:
            self._avancar(EstadoFluxo.META_EM_RISCO)
        return True

    def _registrar_ampliacao(self, progresso: ProgressoFluxo) -> None:
        progresso.ampliacoes += 1
        self._salvar_progresso(progresso)
        self._evento("ampliacao", f"ampliação {progresso.ampliacoes} da busca, mesmos requisitos")

    def _buscar(self, progresso: ProgressoFluxo) -> list[Candidato]:
        """Procura no banco e depois nas fontes externas, sem repetir pessoas.

        Uma fonte fora do ar reduz a cobertura e fica registrada. Todas fora pausam a vaga.
        """
        vistos = {c.id for c in progresso.candidatos}
        fontes = (self._banco, *self._fontes)
        consultas = self._consultas(self.vaga, progresso.ampliacoes)
        novos: list[Candidato] = []
        fora: list[str] = []
        for fonte in fontes:
            try:
                for consulta in consultas:
                    achados = fonte.buscar(
                        self.vaga.empresa_id, consulta, pagina=progresso.ampliacoes + 1
                    )
                    novos.extend(self._filtrar_achados(achados, vistos))
            except FonteIndisponivel:
                fora.append(type(fonte).__name__)
        progresso.fontes_fora = fora
        if len(fora) == len(fontes):
            raise _PausaNecessaria(MotivoPausa.FONTES_INDISPONIVEIS)
        if fora:
            responderam = len(fontes) - len(fora)
            self._evento(
                "cobertura",
                f"cobertura parcial: {responderam} de {len(fontes)} fontes; "
                f"fora do ar: {', '.join(fora)}",
            )
        return novos

    def _filtrar_achados(self, achados: list[Candidato], vistos: set[str]) -> list[Candidato]:
        novos = []
        for candidato in achados:
            if candidato.empresa_id != self.vaga.empresa_id:
                self._evento("busca", "candidato de outra empresa ignorado")
            elif candidato.id not in vistos:
                vistos.add(candidato.id)
                novos.append(candidato)
        return novos

    def _passo_analisar(self) -> bool:
        progresso = self._progresso()
        for indice in range(self._cursor(), len(progresso.candidatos)):
            self._conferir_execucao()
            self._conferir_gasto()
            candidato = progresso.candidatos[indice]
            try:
                analise = self._analisador.analisar(self.vaga, candidato)
                self._exigir_coerencia(analise, candidato)
            except RespostaInvalida:
                progresso.analises_invalidas.append(candidato.id)
                self._contar_invalida(progresso, candidato, indice, "análise inválida")
                continue
            progresso.analises[candidato.id] = analise
            progresso.invalidas_seguidas = 0
            self._concluir_candidato(progresso, indice)
        self._avancar(EstadoFluxo.REVISANDO, cursor=progresso.inicio_rodada)
        return True

    def _passo_revisar(self) -> bool:
        progresso = self._progresso()
        for indice in range(self._cursor(), len(progresso.candidatos)):
            self._conferir_execucao()
            candidato = progresso.candidatos[indice]
            analise = progresso.analises.get(candidato.id)
            if analise is None:
                self._concluir_candidato(progresso, indice)
                continue
            self._conferir_gasto()
            try:
                revisada = self._revisor.revisar(self.vaga, candidato, analise)
                self._exigir_coerencia(revisada, candidato)
            except RespostaInvalida:
                ressalvas = [*analise.ressalvas_revisor, RESSALVA_REVISOR_INVALIDO]
                progresso.analises[candidato.id] = analise.model_copy(
                    update={"ressalvas_revisor": ressalvas}
                )
                self._contar_invalida(progresso, candidato, indice, "revisão inválida")
                continue
            progresso.analises[candidato.id] = revisada
            progresso.invalidas_seguidas = 0
            self._concluir_candidato(progresso, indice)
        self._avancar(EstadoFluxo.DECIDINDO)
        return True

    def _exigir_coerencia(self, analise: Analise, candidato: Candidato) -> None:
        esperado = (self.vaga.empresa_id, self.vaga.id, candidato.id)
        if (analise.empresa_id, analise.vaga_id, analise.candidato_id) != esperado:
            raise RespostaInvalida("análise de outra empresa, vaga ou candidato")

    def _concluir_candidato(self, progresso: ProgressoFluxo, indice: int) -> None:
        self._salvar_progresso(progresso)
        self._repo.atualizar_cursor(self.vaga.empresa_id, self.vaga.id, indice + 1)

    def _contar_invalida(
        self, progresso: ProgressoFluxo, candidato: Candidato, indice: int, mensagem: str
    ) -> None:
        """Falha isolada não para a vaga; três seguidas indicam um problema maior."""
        progresso.invalidas_seguidas += 1
        self._evento("falha_individual", mensagem, candidato.id)
        self._concluir_candidato(progresso, indice)
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
            self._repo.salvar_decisao(decisao)
            self._evento("decisao", f"{decisao.tipo}: {decisao.regra}", decisao.candidato_id)
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
        rastro_id = f"rastro:{self.vaga.id}:{candidato.id}"
        analise = progresso.analises.get(candidato.id)
        if analise is None:
            return decisao_sem_analise(self.vaga, candidato, mandato, agora, rastro_id)
        return decidir(self.vaga, candidato, analise, mandato, agora.date(), agora, rastro_id)

    def _estado_de_saida(self, mandato: Mandato) -> EstadoFluxo:
        if mandato.politica.modo_entrega == ModoEntrega.NA_DECISAO:
            return EstadoFluxo.ENTREGANDO
        return EstadoFluxo.CONVIDANDO

    def _ultimas_decisoes(self) -> dict[str, Decisao]:
        """A decisão vigente de cada candidato, na ordem em que apareceram."""
        ultimas: dict[str, Decisao] = {}
        for decisao in self._repo.listar_decisoes(self.vaga.empresa_id, self.vaga.id):
            ultimas[decisao.candidato_id] = decisao
        return ultimas

    def _indicados(self) -> list[str]:
        return [
            candidato_id
            for candidato_id, decisao in self._ultimas_decisoes().items()
            if decisao.tipo == TipoDecisao.INDICAR
        ]

    def _passo_convidar(self) -> bool:
        """Entrega quem já aceitou, envia o que falta e só segue com os convites encerrados."""
        self._entregar_pendentes()
        progresso = self._progresso()
        for candidato_id in self._indicados():
            self._conferir_execucao()
            self._convidar(progresso, candidato_id)
            self._salvar_progresso(progresso)
        abertos = (EstadoConvite.A_ENVIAR, EstadoConvite.AGUARDANDO)
        if any(r.estado in abertos for r in progresso.convites):
            return False
        self._avancar(EstadoFluxo.ENTREGANDO)
        return True

    def _convidar(self, progresso: ProgressoFluxo, candidato_id: str) -> None:
        """Envia o primeiro convite da pessoa ou repete o que falhou, com a mesma chave."""
        registros = [r for r in progresso.convites if r.convite.candidato_id == candidato_id]
        ultimo = registros[-1] if registros else None
        if ultimo is None:
            registro = self._novo_convite(progresso, candidato_id, tentativa=1)
        elif ultimo.estado == EstadoConvite.CANCELADO:
            registro = self._novo_convite(progresso, candidato_id, ultimo.tentativa + 1)
        elif ultimo.estado == EstadoConvite.A_ENVIAR:
            registro = ultimo
        else:
            return
        self._enviar(progresso, registro)

    def _novo_convite(
        self, progresso: ProgressoFluxo, candidato_id: str, tentativa: int
    ) -> RegistroConvite:
        identificador = f"{self.vaga.id}:{candidato_id}:{tentativa}"
        candidato = progresso.candidato(candidato_id)
        convite = Convite(
            id=f"convite:{identificador}",
            empresa_id=self.vaga.empresa_id,
            tipo=TipoConvite.VAGA,
            canal=CANAL_CONVITE,
            vaga_id=self.vaga.id,
            candidato_id=candidato_id,
            mensagem=f"Temos uma vaga de {self.vaga.titulo} que combina com o seu perfil.",
            link_agendamento=self._link_de_agendamento(candidato_id),
            chave_idempotencia=f"convite:{self.vaga.empresa_id}:{identificador}",
            simulado=candidato.simulado,
        )
        registro = RegistroConvite(convite=convite, tentativa=tentativa)
        progresso.convites.append(registro)
        return registro

    def _link_de_agendamento(self, candidato_id: str) -> str | None:
        """O agendamento é opcional: sem link, o convite segue e o fluxo não trava."""
        try:
            return self._destino.link_agendamento(self.vaga.id, candidato_id)
        except (ErroContrato, OSError) as erro:
            self._evento("convite", f"destino sem link: {type(erro).__name__}", candidato_id)
            return None

    def _acao_idempotente(self, chave: str, acao: Callable[[], bool]) -> bool:
        """Faz a ação ao menos uma vez e nunca de novo depois de concluída.

        Uma queda deixa a chave pendente, e a ação se repete com a mesma chave, que o
        destino usa para descartar a duplicata.
        """
        if self._repo.chave_concluida(self.vaga.empresa_id, chave):
            return True
        self._repo.registrar_chave(self.vaga.empresa_id, chave)
        try:
            feita = acao()
        except (ErroContrato, OSError) as erro:
            self._evento("idempotencia", f"ação falhou: {type(erro).__name__}")
            return False
        if feita:
            self._repo.concluir_chave(self.vaga.empresa_id, chave)
        return feita

    def _enviar(self, progresso: ProgressoFluxo, registro: RegistroConvite) -> None:
        candidato = progresso.candidato(registro.convite.candidato_id)
        hoje = self._relogio().date()
        if not pode_contatar(candidato, registro.tentativa - 1, self.vaga, hoje):
            registro.estado = EstadoConvite.ENCERRADO
            self._evento("convite", "contato bloqueado pelas regras", candidato.id)
        elif self._acao_idempotente(
            registro.convite.chave_idempotencia, lambda: self._mensageiro.enviar(registro.convite)
        ):
            registro.estado = EstadoConvite.AGUARDANDO
            self._evento("convite", "convite enviado", candidato.id)
        else:
            self._evento("convite", "envio do convite falhou", candidato.id)

    def _aplicar_resposta(
        self, progresso: ProgressoFluxo, registro: RegistroConvite, tipo: TipoResposta
    ) -> None:
        if tipo == TipoResposta.ACEITE:
            registro.estado = EstadoConvite.ACEITO
        elif tipo == TipoResposta.RECUSA:
            registro.estado = EstadoConvite.ENCERRADO
        elif tipo == TipoResposta.SILENCIO:
            registro.estado = EstadoConvite.ENCERRADO
            candidato = progresso.candidato(registro.convite.candidato_id)
            hoje = self._relogio().date()
            if pode_contatar(candidato, registro.tentativa, self.vaga, hoje):
                novo = self._novo_convite(progresso, candidato.id, registro.tentativa + 1)
                self._enviar(progresso, novo)

    def _registrar_opt_out(self, progresso: ProgressoFluxo, candidato_id: str) -> None:
        """Vale em qualquer estado: encerra os convites e impede contato e entrega."""
        indice = next(i for i, c in enumerate(progresso.candidatos) if c.id == candidato_id)
        progresso.candidatos[indice] = progresso.candidatos[indice].model_copy(
            update={"opt_out": True}
        )
        for registro in progresso.convites:
            if registro.convite.candidato_id == candidato_id:
                registro.estado = EstadoConvite.ENCERRADO
        try:
            self._banco.registrar_opt_out(self.vaga.empresa_id, candidato_id)
        except KeyError:
            self._evento("resposta", "opt-out de pessoa fora do banco de talentos", candidato_id)

    def _passo_entregar(self) -> bool:
        self._entregar_pendentes()
        if self.estado == EstadoFluxo.PAUSADA:
            raise _VagaInterrompida
        self._ir(EstadoFluxo.CONCLUIDA)
        return False

    def _a_entregar(self, progresso: ProgressoFluxo) -> list[str]:
        indicados = self._indicados()
        if self.mandato.politica.modo_entrega == ModoEntrega.NA_DECISAO:
            base = indicados
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
            candidato = progresso.candidato(candidato_id)
            if autorizacao_ativa(candidato, hoje):
                self._entregar(progresso, candidato)
            else:
                self._evento("entrega", "entrega cancelada: sem autorização", candidato_id)

    def _entregar(self, progresso: ProgressoFluxo, candidato: Candidato) -> None:
        chave = f"entrega:{self.vaga.empresa_id}:{self.vaga.id}:{candidato.id}"
        decisao = self._ultimas_decisoes()[candidato.id]
        pacote = self._pacote(candidato, progresso.analises[candidato.id], decisao.rastro_id, chave)
        if not self._acao_idempotente(chave, lambda: self._destino.entregar(pacote)):
            raise _PausaNecessaria(MotivoPausa.DESTINO_INDISPONIVEL)
        progresso.entregues.append(candidato.id)
        self._salvar_progresso(progresso)
        self._evento("entrega", "pacote de contexto entregue", candidato.id)

    def _pacote(
        self, candidato: Candidato, analise: Analise, rastro_id: str, chave: str
    ) -> PacoteContexto:
        """Monta o pacote só com evidência conferida: afirmação sem fonte não vai adiante."""
        evidencias = [
            e
            for e in analise.evidencias
            if classificar_evidencia(e, candidato) != TipoEvidencia.INFERIDA
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
            lacunas=analise.lacunas,
            pontos_a_aprofundar=analise.pontos_a_aprofundar,
            ressalvas_revisor=analise.ressalvas_revisor,
            autorizacao=f"valida_ate:{candidato.autorizacao_valida_ate}",
            fonte=candidato.fonte,
            rastro_id=rastro_id,
            chave_idempotencia=chave,
            simulado=candidato.simulado,
        )
