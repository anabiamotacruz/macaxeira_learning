"""Contratos de dados compartilhados entre as frentes.

Mudanças aqui exigem aviso às quatro frentes (constituição, princípio III).
Campos seguem `specs/001-agente-recrutador/plan.md`.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Self

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
