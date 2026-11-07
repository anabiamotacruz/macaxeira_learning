"""Contratos de dados compartilhados entre as frentes.

Mudanças aqui exigem aviso às quatro frentes (constituição, princípio III).
Campos seguem `specs/001-agente-recrutador/plan.md`.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator


class Contrato(BaseModel):
    """Base dos contratos: campo desconhecido é rejeitado."""

    model_config = ConfigDict(extra="forbid")


Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""Texto obrigatório e não vazio, para identificadores, regras e chaves."""


class Competencia(Contrato):
    nome: str
    peso: float


class Requisito(Contrato):
    id: str
    descricao: str
    campo: str
    valor_esperado: str


class Vaga(Contrato):
    id: Texto
    empresa_id: Texto
    titulo: str
    descricao: str
    requisitos: list[Requisito]
    competencias: list[Competencia]
    meta_candidatos: int
    prazo_dias: int
    max_tentativas_contato: int
    aprovada: bool = False


class Experiencia(Contrato):
    empresa: str
    cargo: str
    inicio: date
    fim: date | None
    descricao: str


class EstadoBanco(StrEnum):
    PENDENTE = "pendente"
    ATIVO = "ativo"
    DESATUALIZADO = "desatualizado"
    EXPIRADO = "expirado"
    REMOVIDO = "removido"


class Candidato(Contrato):
    id: Texto
    empresa_id: Texto
    nome: str
    fonte: str
    simulado: bool
    origem: str
    atualizado_em: date
    autorizacao_valida_ate: date | None
    estado: EstadoBanco
    perfil_texto: str
    atributos: dict[str, str]
    historico: list[Experiencia]
    autorizou_contato: bool
    opt_out: bool = False


class Evidencia(Contrato):
    criterio: str
    trecho: str
    fonte: str


class Analise(Contrato):
    empresa_id: Texto
    vaga_id: str
    candidato_id: str
    requisitos_ok: dict[str, bool]
    notas: dict[str, float]
    evidencias: list[Evidencia]
    lacunas: list[str]
    pontos_a_aprofundar: list[str]
    alertas: list[str]
    ressalvas_revisor: list[str] = []


class TipoDecisao(StrEnum):
    DESCARTAR = "descartar"
    INDICAR = "indicar"
    PEDIR_HUMANO = "pedir_humano"


class Decisao(Contrato):
    empresa_id: Texto
    vaga_id: str
    candidato_id: str
    tipo: TipoDecisao
    regra: Texto
    motivo: str
    responsavel: Texto
    rastro_id: str
    entrada: dict[str, str]
    evidencias: list[Evidencia]
    momento: AwareDatetime


class TipoConvite(StrEnum):
    AUTORIZACAO = "autorizacao"
    VAGA = "vaga"


class Convite(Contrato):
    id: Texto
    empresa_id: Texto
    tipo: TipoConvite
    canal: str
    vaga_id: str | None
    candidato_id: Texto
    mensagem: str
    link_agendamento: str | None = None
    chave_idempotencia: Texto
    simulado: bool


class TipoResposta(StrEnum):
    ACEITE = "aceite"
    RECUSA = "recusa"
    DUVIDA = "duvida"
    SILENCIO = "silencio"
    OPT_OUT = "opt_out"


class RespostaCandidato(Contrato):
    convite_id: str
    tipo: TipoResposta
    texto: str = ""


class PacoteContexto(Contrato):
    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    motivo_por_criterio: dict[str, str]
    historico: list[Experiencia]
    evidencias: list[Evidencia]
    lacunas: list[str]
    pontos_a_aprofundar: list[str]
    ressalvas_revisor: list[str]
    autorizacao: str
    fonte: str
    rastro_id: str
    chave_idempotencia: Texto
    simulado: bool


class ResultadoEntrevista(Contrato):
    empresa_id: Texto
    vaga_id: str
    candidato_id: str
    notas: dict[str, float]
    aprovado: bool
    simulado: bool = True


class PropostaAjuste(Contrato):
    vaga_id: str
    motivo: str
    antes: Vaga
    depois: Vaga
    resultado_avaliacao: dict[str, float]
    aprovada: bool = False


class EventoFluxo(Contrato):
    empresa_id: Texto
    vaga_id: str
    etapa: str
    mensagem: str
    candidato_id: str | None = None
    custo_usd: float = 0
    momento: AwareDatetime


class ModoEntrega(StrEnum):
    APOS_ACEITE = "apos_aceite"
    NA_DECISAO = "na_decisao"


class Politica(Contrato):
    """Limites dentro dos quais o agente decide sozinho."""

    model_config = ConfigDict(frozen=True)

    limiar_verde: Annotated[float, Field(ge=0, le=1)] | None
    piso_nota: Annotated[float, Field(ge=0, le=1)]
    max_indicacoes: Annotated[int, Field(ge=1)]
    max_ampliacoes: Annotated[int, Field(ge=0)]
    modo_entrega: ModoEntrega = ModoEntrega.APOS_ACEITE
    aceitar_declarada: bool = False

    @model_validator(mode="after")
    def _piso_nao_passa_do_limiar(self) -> Self:
        if self.limiar_verde is not None and self.piso_nota > self.limiar_verde:
            raise ValueError("piso_nota não pode ser maior que limiar_verde")
        return self


class Mandato(Contrato):
    """Critérios, limite de gasto e política assinados por uma pessoa responsável."""

    model_config = ConfigDict(frozen=True)

    id: Texto
    versao: Annotated[int, Field(ge=1)]
    empresa_id: Texto
    vaga_id: Texto
    hash_vaga: Texto
    assinante: Texto
    limite_gasto_usd: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
    politica: Politica
    assinado_em: AwareDatetime
    valido_ate: AwareDatetime | None = None


class EstadoVaga(StrEnum):
    """Estados da vaga, usados pela máquina de estados e expostos ao painel."""

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


EstadoFluxo = EstadoVaga
"""Nome usado pela máquina de estados. É o mesmo enum, com o nome publicado no OpenAPI."""


class DestinoPessoa(StrEnum):
    """Destino da pessoa depois da vaga, sempre decidido pelo RH, nunca pelo agente."""

    BANCO = "banco"
    TALENT_GARDEN = "talent_garden"
    CONTRATADA = "contratada"


class SaidaPersonalizada(Contrato):
    """Pacotes de contexto dos indicados de uma vaga, para leitura na interface.

    O pacote só leva contexto: agendar, entrevistar e contratar ficam fora do agente.
    """

    empresa_id: Texto
    vaga_id: Texto
    pacotes: list[PacoteContexto]
    simulado: bool
    momento: AwareDatetime

    @model_validator(mode="after")
    def _pacotes_coerentes(self) -> Self:
        for pacote in self.pacotes:
            if pacote.empresa_id != self.empresa_id or pacote.vaga_id != self.vaga_id:
                raise ValueError("pacote de outra empresa ou vaga não entra na saída")
            if pacote.simulado and not self.simulado:
                raise ValueError("saída com pacote simulado precisa estar identificada")
        return self


class ResumoExecucao(Contrato):
    """Contagens e gasto de uma vaga, para o controle depois da ação."""

    empresa_id: Texto
    vaga_id: Texto
    estado: Texto
    analisados: Annotated[int, Field(ge=0)]
    indicados: Annotated[int, Field(ge=0)]
    descartados: Annotated[int, Field(ge=0)]
    na_fila_humana: Annotated[int, Field(ge=0)]
    revertidos: Annotated[int, Field(ge=0)]
    gasto_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    limite_gasto_usd: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None
    simulado: bool
    momento: AwareDatetime


class TipoErro(StrEnum):
    INDICACAO_ERRADA = "indicacao_errada"
    DESCARTE_ERRADO = "descarte_errado"
    VIOLACAO_ELIMINATORIA = "violacao_eliminatoria"
    CONTATO_OPT_OUT = "contato_opt_out"
    MUDANCA_NOME_GENERO = "mudanca_nome_genero"
    AFIRMACAO_SEM_EVIDENCIA = "afirmacao_sem_evidencia"


class TaxaMedida(Contrato):
    """Taxa com o tamanho da amostra e o intervalo de Wilson.

    Sem casos, a taxa não foi medida: valor e intervalo ficam nulos, nunca zero.
    """

    valor: Annotated[float, Field(ge=0, le=1)] | None
    casos: Annotated[int, Field(ge=0)]
    wilson_inferior: Annotated[float, Field(ge=0, le=1)] | None
    wilson_superior: Annotated[float, Field(ge=0, le=1)] | None

    @model_validator(mode="after")
    def _medida_coerente(self) -> Self:
        limites = (self.wilson_inferior, self.wilson_superior)
        if self.valor is None:
            if self.casos != 0 or limites != (None, None):
                raise ValueError("taxa não medida não tem casos nem intervalo")
            return self
        if self.casos == 0:
            raise ValueError("taxa sem casos não foi medida e deve ter valor nulo")
        if self.wilson_inferior is None or self.wilson_superior is None:
            raise ValueError("taxa medida precisa do intervalo de Wilson")
        if not self.wilson_inferior <= self.valor <= self.wilson_superior:
            raise ValueError("o valor precisa estar dentro do intervalo de Wilson")
        return self


class Particao(StrEnum):
    AJUSTE = "ajuste"
    VALIDACAO = "validacao"
    PROVA = "prova"


class CasoAvaliacao(Contrato):
    """Um caso sintético de avaliação. Só `perfil` e `vaga` chegam ao agente.

    `gabarito` nunca vem do modelo avaliado. `requisitos_atendidos` lista só o que tem estado
    `atende`: requisito negado ou desconhecido fica de fora. `dificuldade` fica nula quando
    o conjunto não a informa.
    """

    model_config = ConfigDict(frozen=True)

    id: Texto
    perfil: Candidato
    vaga: Vaga
    gabarito: TipoDecisao
    motivo_gabarito: Texto
    requisitos_atendidos: list[str]
    autorizacao_bloqueada: bool = False
    particao: Particao
    armadilha: str | None = None
    dificuldade: str | None = None
    par_vies: str | None = None
    semente: int
    versao_gerador: Texto

    @model_validator(mode="after")
    def _caso_coerente(self) -> Self:
        if not self.perfil.simulado:
            raise ValueError("caso de avaliação usa somente perfil sintético")
        if self.perfil.empresa_id != self.vaga.empresa_id:
            raise ValueError("perfil e vaga precisam ser da mesma empresa")
        da_vaga = {requisito.id for requisito in self.vaga.requisitos}
        if not set(self.requisitos_atendidos) <= da_vaga:
            raise ValueError("requisito atendido que a vaga não tem")
        if self.gabarito == TipoDecisao.INDICAR and (
            self.autorizacao_bloqueada or set(self.requisitos_atendidos) != da_vaga
        ):
            raise ValueError("gabarito indicar exige autorização e todos os requisitos")
        return self


class RespostaAgente(Contrato):
    """O que o agente avaliado devolve para um perfil e uma vaga.

    `nota` vem da regra determinística, nunca da confiança declarada pelo modelo.
    """

    decisao: TipoDecisao
    regra: Texto
    nota: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    evidencias: list[Evidencia] = []


class ResultadoCaso(Contrato):
    """Resposta do agente ao lado do gabarito. Sem decisão, `falha` diz por quê."""

    model_config = ConfigDict(frozen=True)

    caso_id: Texto
    particao: Particao
    versao_hash: Texto
    gabarito: TipoDecisao
    decisao: TipoDecisao | None
    regra: Texto | None = None
    nota: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    evidencias: list[Evidencia] = []
    falha: Texto | None = None
    requisitos_cumpridos: bool = True
    autorizacao_bloqueada: bool = False
    opt_out: bool = False
    afirmacao_sem_evidencia: bool = False
    armadilha: str | None = None
    par_vies: str | None = None
    rastro_id: str | None = None

    @model_validator(mode="after")
    def _resultado_coerente(self) -> Self:
        if (self.decisao is None) != (self.falha is not None):
            raise ValueError("resultado tem decisão ou falha, nunca as duas nem nenhuma")
        if self.decisao is not None and self.regra is None:
            raise ValueError("decisão precisa da regra aplicada")
        return self


class MetricasMedicao(Contrato):
    """Só agregados de uma rodada: nenhum dado caso a caso. Taxa nula significa não medida."""

    particao: Particao | None
    versao_hash: str | None
    conjunto_hash: str | None
    casos: Annotated[int, Field(ge=0)]
    erros: dict[TipoErro, TaxaMedida]
    revisao: TaxaMedida
    cobertura: TaxaMedida
    falhas: TaxaMedida

    @model_validator(mode="after")
    def _todos_os_tipos(self) -> Self:
        if set(self.erros) != set(TipoErro):
            raise ValueError("métricas precisam trazer todo tipo de erro, medido ou não")
        return self


class VersaoPrompt(Contrato):
    """Versão imutável de um prompt: o hash cobre o texto e o modelo."""

    model_config = ConfigDict(frozen=True)

    etapa: Texto
    modelo: Texto
    hash: Texto


class DecisaoPortao(Contrato):
    """Resultado do portão. Passar significa não piorar nas réguas, não melhora comprovada."""

    passou: bool
    motivos: list[str]

    @model_validator(mode="after")
    def _motivos_coerentes(self) -> Self:
        if self.passou == bool(self.motivos):
            raise ValueError("o portão barra se, e somente se, houver motivo")
        return self


class ResultadoProva(Contrato):
    """Uma abertura da prova: só agregados, nada caso a caso.

    `aberturas_do_conjunto` conta quantas versões já olharam estes casos. Acima de 1, o
    resultado vale menos, porque cada olhada aumenta a chance de um prompt ruim passar.
    """

    versao: VersaoPrompt
    limiar: Annotated[float, Field(ge=0, le=1)] | None
    metricas: MetricasMedicao
    aberta_em: AwareDatetime
    aberturas_do_conjunto: Annotated[int, Field(ge=1)]


class ResumoConjunto(Contrato):
    """Quantos casos um conjunto tem e quantos deles são de fato diferentes.

    `casos_independentes` conta entradas distintas ao ignorar empresa, pessoa, fonte e nome
    de projeto. É um teto: cenários repetidos também não são independentes entre si.
    """

    particao: Particao | None
    registros: Annotated[int, Field(ge=0)]
    pares_pessoa_vaga: Annotated[int, Field(ge=0)]
    casos_independentes: Annotated[int, Field(ge=0)]
    textos_distintos: Annotated[int, Field(ge=0)]
    cenarios: Annotated[int, Field(ge=0)]
    vagas: Annotated[int, Field(ge=0)]
    composicao_gabarito: dict[TipoDecisao, Annotated[int, Field(ge=0)]]


class RelatorioMedicao(Contrato):
    """Relatório para o painel: só agregados, sempre identificado como dado sintético."""

    simulado: Literal[True] = True
    dados_sinteticos: Literal[True] = True
    gabarito_validado_por_recrutador: bool
    regra_gabarito: Texto
    versao: VersaoPrompt
    limiar: Annotated[float, Field(ge=0, le=1)] | None
    meta: Annotated[float, Field(gt=0, lt=1)] | None
    metricas: MetricasMedicao
    conjunto: ResumoConjunto
    aberturas_do_conjunto: Annotated[int, Field(ge=1)] | None = None
    limites: Annotated[list[str], Field(min_length=1)]
