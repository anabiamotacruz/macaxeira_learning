"""Máquina de estados de uma vaga e a condução do fluxo por ela.

Os estados não citam um destino específico: agendamento e retorno da entrevista são
opcionais. `FluxoVaga` não guarda estado em memória: tudo o que permite continuar está
no `Repositorio`, e um novo objeto sobre o mesmo arquivo continua de onde o outro parou.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from pydantic import AwareDatetime

from backend.agente.mandato import (
    Mandato,
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
    decidir,
    nao_priorizada,
    pode_contatar,
    validar_criterios,
)
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
    Analise,
    Candidato,
    Contrato,
    Convite,
    Decisao,
    EventoFluxo,
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


class EstadoConvite(StrEnum):
    A_ENVIAR = "a_enviar"
    AGUARDANDO = "aguardando"
    ACEITO = "aceito"
    ENCERRADO = "encerrado"


class RegistroConvite(Contrato):
    convite: Convite
    tentativa: int
    estado: EstadoConvite = EstadoConvite.A_ENVIAR


class ProgressoFluxo(Contrato):
    """O trabalho feito até aqui. Modelo local: não cruza frentes."""

    iniciado_em: AwareDatetime
    candidatos: list[Candidato] = []
    analises: dict[str, Analise] = {}
    convites: list[RegistroConvite] = []
    entregues: list[str] = []

    def candidato(self, candidato_id: str) -> Candidato:
        return next(c for c in self.candidatos if c.id == candidato_id)


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
        """Registra a assinatura e executa até a vaga depender de resposta externa."""
        if self.estado != EstadoFluxo.AGUARDANDO_MANDATO:
            raise TransicaoInvalida(f"{self.estado} não aceita assinatura de mandato")
        agora = self._relogio()
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
        elif registro.estado == EstadoConvite.ENCERRADO:
            self._evento("resposta", "resposta tardia: convite já encerrado", candidato_id)
        elif registro.estado == EstadoConvite.AGUARDANDO:
            self._aplicar_resposta(progresso, registro, resposta.tipo)
        self._salvar_progresso(progresso)

        if resposta.tipo == TipoResposta.ACEITE and registro.estado == EstadoConvite.ACEITO:
            self._entregar_pendentes()
        if self.estado == EstadoFluxo.CONVIDANDO:
            self._executar()

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
        novo, evento = _transitar(
            self.estado,
            destino,
            vaga=self.vaga,
            mandato=self.mandato,
            agora=self._relogio(),
            motivo=motivo,
        )
        self._repo.salvar_estado(self.vaga.empresa_id, self.vaga.id, novo, cursor)
        self._repo.registrar_evento(evento)

    def _salvar_cursor(self, cursor: int) -> None:
        self._repo.salvar_estado(self.vaga.empresa_id, self.vaga.id, self.estado, cursor)

    def _executar(self) -> None:
        """Avança etapa por etapa até a vaga depender de algo externo ou terminar."""
        passos = {
            EstadoFluxo.BUSCANDO: self._passo_buscar,
            EstadoFluxo.ANALISANDO: self._passo_analisar,
            EstadoFluxo.REVISANDO: self._passo_revisar,
            EstadoFluxo.DECIDINDO: self._passo_decidir,
            EstadoFluxo.CONVIDANDO: self._passo_convidar,
            EstadoFluxo.ENTREGANDO: self._passo_entregar,
        }
        continuar = True
        while continuar and self.estado in passos:
            continuar = passos[self.estado]()

    def _passo_buscar(self) -> bool:
        progresso = self._progresso()
        progresso.candidatos.extend(self._buscar(progresso))
        self._salvar_progresso(progresso)
        self._ir(EstadoFluxo.ANALISANDO)
        return True

    def _buscar(self, progresso: ProgressoFluxo) -> list[Candidato]:
        """Procura no banco e depois nas fontes externas, sem repetir pessoas."""
        vistos = {c.id for c in progresso.candidatos}
        novos = []
        consultas = self._consultas(self.vaga, 0)
        for fonte in (self._banco, *self._fontes):
            for consulta in consultas:
                for candidato in fonte.buscar(self.vaga.empresa_id, consulta):
                    if candidato.empresa_id != self.vaga.empresa_id:
                        self._evento("busca", "candidato de outra empresa ignorado")
                    elif candidato.id not in vistos:
                        vistos.add(candidato.id)
                        novos.append(candidato)
        return novos

    def _passo_analisar(self) -> bool:
        progresso = self._progresso()
        for indice in range(self._cursor(), len(progresso.candidatos)):
            candidato = progresso.candidatos[indice]
            progresso.analises[candidato.id] = self._analisador.analisar(self.vaga, candidato)
            self._salvar_progresso(progresso)
            self._salvar_cursor(indice + 1)
        self._ir(EstadoFluxo.REVISANDO)
        return True

    def _passo_revisar(self) -> bool:
        progresso = self._progresso()
        for indice in range(self._cursor(), len(progresso.candidatos)):
            candidato = progresso.candidatos[indice]
            analise = progresso.analises[candidato.id]
            progresso.analises[candidato.id] = self._revisor.revisar(self.vaga, candidato, analise)
            self._salvar_progresso(progresso)
            self._salvar_cursor(indice + 1)
        self._ir(EstadoFluxo.DECIDINDO)
        return True

    def _passo_decidir(self) -> bool:
        """Decide quem falta. Refazer depois de uma queda não repete decisão já salva."""
        progresso = self._progresso()
        mandato = self.mandato
        agora = self._relogio()
        decididos = self._ultimas_decisoes()
        decisoes = [
            decidir(
                self.vaga,
                candidato,
                progresso.analises[candidato.id],
                mandato,
                agora.date(),
                agora,
                f"rastro:{self.vaga.id}:{candidato.id}",
            )
            for candidato in progresso.candidatos
            if candidato.id not in decididos
        ]
        limite = mandato.politica.max_indicacoes
        indicados = len(self._indicados())
        for decisao in sorted(decisoes, key=_ordem_de_decisao):
            if decisao.tipo == TipoDecisao.INDICAR:
                if indicados >= limite:
                    decisao = nao_priorizada(decisao, limite)
                else:
                    indicados += 1
            self._repo.salvar_decisao(decisao)
            self._evento("decisao", f"{decisao.tipo}: {decisao.regra}", decisao.candidato_id)
        self._ir(self._estado_de_saida(mandato))
        return True

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
        progresso = self._progresso()
        for candidato_id in self._indicados():
            self._convidar(progresso, candidato_id)
        self._salvar_progresso(progresso)
        abertos = (EstadoConvite.A_ENVIAR, EstadoConvite.AGUARDANDO)
        if any(r.estado in abertos for r in progresso.convites):
            return False
        self._ir(EstadoFluxo.ENTREGANDO)
        return True

    def _convidar(self, progresso: ProgressoFluxo, candidato_id: str) -> None:
        """Envia o primeiro convite da pessoa ou repete o que falhou, com a mesma chave."""
        registros = [r for r in progresso.convites if r.convite.candidato_id == candidato_id]
        if not registros:
            registro = self._novo_convite(progresso, candidato_id, tentativa=1)
        elif registros[-1].estado == EstadoConvite.A_ENVIAR:
            registro = registros[-1]
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
            link_agendamento=self._destino.link_agendamento(self.vaga.id, candidato_id),
            chave_idempotencia=f"convite:{self.vaga.empresa_id}:{identificador}",
            simulado=candidato.simulado,
        )
        registro = RegistroConvite(convite=convite, tentativa=tentativa)
        progresso.convites.append(registro)
        return registro

    def _enviar(self, progresso: ProgressoFluxo, registro: RegistroConvite) -> None:
        candidato = progresso.candidato(registro.convite.candidato_id)
        hoje = self._relogio().date()
        if not pode_contatar(candidato, registro.tentativa - 1, self.vaga, hoje):
            registro.estado = EstadoConvite.ENCERRADO
            self._evento("convite", "contato bloqueado pelas regras", candidato.id)
        elif self._mensageiro.enviar(registro.convite):
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
        progresso = self._progresso()
        hoje = self._relogio().date()
        for candidato_id in self._a_entregar(progresso):
            candidato = progresso.candidato(candidato_id)
            if not autorizacao_ativa(candidato, hoje):
                self._evento("entrega", "entrega cancelada: sem autorização", candidato_id)
                continue
            chave = f"entrega:{self.vaga.empresa_id}:{self.vaga.id}:{candidato_id}"
            decisao = self._ultimas_decisoes()[candidato_id]
            pacote = self._pacote(
                candidato, progresso.analises[candidato_id], decisao.rastro_id, chave
            )
            if self._repo.registrar_chave(self.vaga.empresa_id, chave):
                self._destino.entregar(pacote)
            progresso.entregues.append(candidato_id)
            self._salvar_progresso(progresso)
            self._evento("entrega", "pacote de contexto entregue", candidato_id)

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
