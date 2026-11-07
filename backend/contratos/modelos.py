"""Contratos de dados compartilhados entre as frentes.

Mudanças aqui exigem aviso às quatro frentes (constituição, princípio III).
Campos seguem `specs/001-agente-recrutador/plan.md`.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from backend.contratos.criterios import julgamentos_proibidos, termos_proibidos_em_conversa


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
    desenvolvivel: bool = False
    """Marcado pela empresa: a falta dele pode ser desenvolvida e não elimina sozinha."""


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


class NivelCriterio(StrEnum):
    """Escala ancorada: o perfil nega, alega sem exemplo, mostra parte ou mostra direto."""

    NEGA = "nega"
    GENERICA = "generica"
    PARCIAL = "parcial"
    DIRETA = "direta"


class SituacaoResposta(StrEnum):
    CONFIRMA = "confirma"
    NEGA = "nega"
    INCERTA = "incerta"


class DadoPreTriagem(Contrato):
    """Uma resposta da pré-triagem, com o trecho da mensagem, a fonte e a data."""

    pergunta_id: Texto
    criterio: Texto
    situacao: SituacaoResposta
    trecho: Texto
    fonte: Texto
    coletado_em: date
    nivel: NivelCriterio | None = None
    voltar_em: date | None = None
    motivo: str | None = None

    @model_validator(mode="after")
    def _sem_dado_sensivel(self) -> Self:
        if termos_proibidos_em_conversa(self.trecho, self.motivo or ""):
            raise ValueError("resposta com dado sensível não é guardada")
        return self


class TipoPonto(StrEnum):
    LACUNA = "lacuna"
    CONTRADICAO = "contradicao"
    AFIRMACAO_SEM_EXEMPLO = "afirmacao_sem_exemplo"
    EXPERIENCIA_PARECIDA = "experiencia_parecida"


class PontoExplorar(Contrato):
    """O que o recrutador e a entrevista podem aprofundar, sempre com trecho e fonte."""

    tipo: TipoPonto
    criterio: Texto
    descricao: Texto
    trecho: Texto
    fonte: Texto
    verificado: bool
    inferencia: bool = False
    rotulo: Literal["Verificado", "Não verificado"] = "Não verificado"

    @model_validator(mode="before")
    @classmethod
    def _rotulo_segue_o_fato(cls, dados: object) -> object:
        """O rótulo visível nunca é informado: vem de `verificado`, para não poder mentir."""
        if isinstance(dados, dict):
            rotulo = "Verificado" if dados.get("verificado") else "Não verificado"
            return {**dados, "rotulo": rotulo}
        return dados

    @model_validator(mode="after")
    def _ponto_permitido(self) -> Self:
        if termos_proibidos_em_conversa(self.descricao, self.trecho):
            raise ValueError("ponto a explorar não cita dado sensível")
        if julgamentos_proibidos(self.descricao, self.trecho):
            raise ValueError("ponto a explorar não julga personalidade nem fit cultural")
        if self.tipo == TipoPonto.EXPERIENCIA_PARECIDA and not self.inferencia:
            raise ValueError("experiência parecida é sempre inferência")
        if self.inferencia and self.verificado:
            raise ValueError("inferência nunca aparece como verificada")
        return self


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
    pontos_a_explorar: list[PontoExplorar] = []
    respostas_pre_triagem: list[DadoPreTriagem] = []


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
    lapidar_exige_confirmacao: bool = True
    prazo_garden_dias: Annotated[int, Field(ge=1)] = 180

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


class TipoFato(StrEnum):
    COMPROVADO = "comprovado"
    DECLARADO = "declarado"
    INFERIDO = "inferido"


class TipoContato(StrEnum):
    EMAIL = "email"
    TELEFONE = "telefone"
    PERFIL = "perfil"
    LINK = "link"


class _ComOrigem(Contrato):
    """Toda informação coletada diz de onde veio: uma URL ou um documento, nunca os dois."""

    fonte: Texto
    url: str | None = None
    documento: Texto | None = None
    coletado_em: date

    @model_validator(mode="after")
    def _uma_origem_conferivel(self) -> Self:
        if (self.url is None) == (self.documento is None):
            raise ValueError("informe a URL ou o documento de origem, e só um deles")
        if self.url is not None and not self.url.startswith(("http://", "https://")):
            raise ValueError("a URL de origem precisa ser http ou https")
        return self


class FatoColetado(_ComOrigem):
    texto: Texto
    trecho: Texto
    tipo: TipoFato


class ContatoColetado(_ComOrigem):
    """Contato sem publicação pela própria pessoa não serve para contato frio."""

    tipo: TipoContato
    valor: Texto
    publicado_pela_pessoa: bool


class PerfilColetado(Contrato):
    """Perfil estruturado em JSON, antes de virar `Candidato`. Continua sendo dado pessoal."""

    empresa_id: Texto
    candidato_id: Texto
    simulado: bool
    coletado_em: date
    nome: str = ""
    fatos: list[FatoColetado] = []
    contatos: list[ContatoColetado] = []
    alertas: list[str] = []


class DestinoDecisao(StrEnum):
    """Para onde a pessoa vai depois da decisão. Agendar e contratar ficam fora do agente."""

    APROVAR = "aprovar"
    RECUSAR = "recusar"
    GARDEN_INDISPONIVEL = "garden_indisponivel"
    GARDEN_A_LAPIDAR = "garden_a_lapidar"
    REVISAO_HUMANA = "revisao_humana"


class OrigemDecisao(StrEnum):
    ANALISE = "analise"
    PRE_TRIAGEM = "pre_triagem"
    CONFIRMACAO_HUMANA = "confirmacao_humana"


class TipoCriterio(StrEnum):
    REQUISITO = "requisito"
    COMPETENCIA = "competencia"


class QualidadeDado(StrEnum):
    COMPROVADO = "comprovado"
    DECLARADO = "declarado"
    INFERIDO = "inferido"
    SEM_DADO = "sem_dado"


class FaixaScore(StrEnum):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


class SeloCalibracao(StrEnum):
    NAO_CALIBRADO = "nao_calibrado"
    CERTIFICADO = "certificado"


class TrechoCitado(Contrato):
    trecho: Texto
    fonte: Texto


class NotaCriterio(Contrato):
    """Um critério como o recrutador o vê. Requisito elimina e não pesa na nota geral."""

    criterio: Texto
    tipo: TipoCriterio
    descricao: str
    peso: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    qualidade: QualidadeDado
    nota: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    nota_considerada: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    nivel: NivelCriterio | None = None
    trechos: list[TrechoCitado] = []
    status_requisito: Literal["atende", "nao_atende", "sem_dado"] | None = None
    confirmado_na_analise: bool = False
    evidencia_aceita: bool = False
    eliminatorio: bool = False
    desenvolvivel: bool = False


class SinalNota(Contrato):
    """O que tirou pontos da nota geral. Sinal nunca recusa nem aprova."""

    codigo: Texto
    criterio: str | None = None
    reducao: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ScoreRecrutador(Contrato):
    """Nota por critério, nota geral e faixa. Sem limiar certificado, leva o selo não calibrado."""

    criterios: list[NotaCriterio]
    nota_geral: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None
    faixa: FaixaScore | None
    sinais: list[SinalNota]
    selo: SeloCalibracao
    qualidade: dict[QualidadeDado, Annotated[int, Field(ge=0)]]


class MotivoLacuna(StrEnum):
    NAO_ATENDE = "nao_atende"
    SEM_DADO = "sem_dado"
    SEM_EVIDENCIA_ACEITA = "sem_evidencia_aceita"
    NAO_CONFIRMADO = "nao_confirmado"
    SEM_EVIDENCIA = "sem_evidencia"


class LacunaCriterio(Contrato):
    """O que falta num critério da vaga. Nasce em código, do registro, não do texto do modelo."""

    criterio: Texto
    tipo: TipoCriterio
    descricao: Texto
    motivo: MotivoLacuna
    peso: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0
    eliminatorio: bool = False
    desenvolvivel: bool = False


class FatoIndisponibilidade(Contrato):
    """A própria pessoa disse que não pode agora, e quando ou por que isso muda."""

    trecho: Texto
    fonte: Texto
    voltar_em: date | None = None
    motivo: str | None = None

    @model_validator(mode="after")
    def _data_ou_motivo(self) -> Self:
        if self.voltar_em is None and not (self.motivo or "").strip():
            raise ValueError("indisponibilidade precisa de data ou motivo de volta")
        return self


REGRA_RECUSA_AUTORIZACAO = "sem_autorizacao"
PREFIXO_RECUSA_REQUISITO = "requisito_eliminatorio:"


def regra_de_recusa_objetiva(regra: str) -> bool:
    """Recusa automática só por autorização ou por requisito comprovadamente não atendido."""
    if regra == REGRA_RECUSA_AUTORIZACAO:
        return True
    return regra.startswith(PREFIXO_RECUSA_REQUISITO) and bool(
        regra.removeprefix(PREFIXO_RECUSA_REQUISITO).strip()
    )


class DecisaoFinal(Contrato):
    """Decisão com destino e score. As invariantes do produto valem aqui, para qualquer autor."""

    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    destino: DestinoDecisao
    regra: Texto
    motivo: Texto
    responsavel: Texto
    rastro_id: str
    score: ScoreRecrutador
    entrada: dict[str, str]
    evidencias: list[Evidencia]
    simulado: bool
    momento: AwareDatetime
    origem: OrigemDecisao = OrigemDecisao.ANALISE
    portoes: list[str] = []
    lacunas: list[LacunaCriterio] = []
    indisponibilidade: FatoIndisponibilidade | None = None
    pendente_confirmacao: bool = False
    reavaliados: list[str] = []
    alertas: list[str] = []

    @model_validator(mode="after")
    def _invariantes_do_destino(self) -> Self:
        if self.destino == DestinoDecisao.RECUSAR and not regra_de_recusa_objetiva(self.regra):
            raise ValueError("recusa automática só por regra objetiva")
        if self.destino == DestinoDecisao.APROVAR:
            self._exigir_aprovacao_completa()
        if self.destino == DestinoDecisao.GARDEN_INDISPONIVEL and self.indisponibilidade is None:
            raise ValueError("garden de indisponível precisa do fato dito pela pessoa")
        if self.destino == DestinoDecisao.GARDEN_A_LAPIDAR and not self.lacunas:
            raise ValueError("garden a lapidar precisa das lacunas listadas")
        if self.pendente_confirmacao and self.destino != DestinoDecisao.GARDEN_A_LAPIDAR:
            raise ValueError("só o garden a lapidar espera confirmação do RH")
        return self

    def _exigir_aprovacao_completa(self) -> None:
        if self.portoes:
            raise ValueError("aprovação não passa por portão duro")
        if self.score.nota_geral is None:
            raise ValueError("aprovação precisa de nota geral")
        for criterio in self.score.criterios:
            if criterio.tipo == TipoCriterio.REQUISITO and criterio.status_requisito != "atende":
                raise ValueError("requisito sem dado ou não atendido nunca aprova")


class EstadoGarden(StrEnum):
    AGUARDANDO_AUTORIZACAO = "aguardando_autorizacao"
    ATIVA = "ativa"
    PARA_REVISAO = "para_revisao"
    ENCERRADA = "encerrada"


class EntradaGarden(Contrato):
    """Entrada no garden: depende da autorização da pessoa, tem prazo e pode ser revista."""

    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    destino: DestinoDecisao
    regra: Texto
    estado: EstadoGarden
    revisar_em: date
    autorizada_em: date | None = None
    valida_ate: date | None = None
    voltar_em: date | None = None
    motivo_retorno: str | None = None
    lacunas: list[LacunaCriterio] = []
    motivo_encerramento: str | None = None

    @model_validator(mode="after")
    def _estado_coerente(self) -> Self:
        if self.destino not in (
            DestinoDecisao.GARDEN_INDISPONIVEL,
            DestinoDecisao.GARDEN_A_LAPIDAR,
        ):
            raise ValueError("entrada no garden só para destinos de garden")
        ativa = self.estado in (EstadoGarden.ATIVA, EstadoGarden.PARA_REVISAO)
        if ativa and (self.autorizada_em is None or self.valida_ate is None):
            raise ValueError("garden ativo exige autorização da pessoa, com prazo")
        return self


class TipoPergunta(StrEnum):
    DISPONIBILIDADE = "disponibilidade"
    REQUISITO = "requisito"
    COMPETENCIA = "competencia"


class PerguntaRoteiro(Contrato):
    """Pergunta da pré-triagem. Pergunta sobre dado sensível não existe, nem para o canal."""

    model_config = ConfigDict(frozen=True)

    id: Texto
    ordem: Annotated[int, Field(ge=1)]
    tipo: TipoPergunta
    criterio: Texto
    texto: Texto
    motivo: Texto
    eliminatorio: bool = False

    @model_validator(mode="after")
    def _sem_dado_sensivel(self) -> Self:
        if termos_proibidos_em_conversa(self.texto, self.motivo):
            raise ValueError("pergunta sobre dado sensível é proibida")
        return self


class RoteiroPreTriagem(Contrato):
    """Só o que falta, em ordem de importância. A pré-triagem não substitui a entrevista."""

    id: Texto
    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    motivo_contato: Texto
    perguntas: list[PerguntaRoteiro]
    criterios_bloqueados: list[str] = []
    nao_perguntados: list[str] = []
    liberado_por: str | None = None
    simulado: bool


class AtualizacaoPerfil(Contrato):
    """O que a resposta muda no perfil: atributos, fatos com fonte e data, e critérios afetados."""

    dados: dict[str, str]
    fatos: list[FatoColetado]
    criterios_afetados: list[str]


class SituacaoPreTriagem(StrEnum):
    PASSOU = "passou"
    AMBIGUO = "ambiguo"
    NAO_PASSOU = "nao_passou"


class ResultadoPreTriagem(Contrato):
    """Validação em código. Só quem passou pode receber o link do agente de destino."""

    situacao: SituacaoPreTriagem
    decisao: DecisaoFinal
    atualizacao: AtualizacaoPerfil | None = None
    respostas: list[DadoPreTriagem] = []
    link_agendamento: str | None = None
    link_indisponivel: bool = False

    @model_validator(mode="after")
    def _situacao_coerente(self) -> Self:
        esperados = {
            SituacaoPreTriagem.PASSOU: {DestinoDecisao.APROVAR},
            SituacaoPreTriagem.AMBIGUO: {DestinoDecisao.REVISAO_HUMANA},
            SituacaoPreTriagem.NAO_PASSOU: {
                DestinoDecisao.RECUSAR,
                DestinoDecisao.GARDEN_INDISPONIVEL,
                DestinoDecisao.GARDEN_A_LAPIDAR,
            },
        }
        if self.decisao.destino not in esperados[self.situacao]:
            raise ValueError("situação da pré-triagem não bate com o destino da decisão")
        if self.link_agendamento is not None and self.situacao != SituacaoPreTriagem.PASSOU:
            raise ValueError("link de agendamento só para quem passou")
        return self


class ContextoOnboarding(Contrato):
    """O que o canal precisa para conversar. Sem nota, faixa, ranking nem texto do modelo."""

    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    nome_tratamento: str
    titulo_vaga: str
    motivo_contato: Texto
    origem_contato: str
    fonte: str
    autorizacao_valida_ate: date
    roteiro: RoteiroPreTriagem
    simulado: bool


class InsightVaga(Contrato):
    """Agregado da vaga, sem pessoas. O trecho é o critério, não o texto de um candidato."""

    criterio: Texto
    descricao: Texto
    trecho: Texto
    fonte: Texto
    pessoas: Annotated[int, Field(ge=0)]
    total: Annotated[int, Field(ge=1)]


class InsightsDaVaga(Contrato):
    empresa_id: Texto
    vaga_id: Texto
    total: Annotated[int, Field(ge=0)]
    suprimido: bool
    insights: list[InsightVaga]


class PedidoFeedback(Contrato):
    """Só existe feedback quando a pessoa pede. `texto` é dado, nunca instrução."""

    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    canal: Texto
    pedido_em: AwareDatetime
    texto: str = ""
    contestacao: bool = False


class MotivoDestino(Contrato):
    criterio: Texto
    trecho: Texto


class RetornoDestino(Contrato):
    """O que o agente de destino informou depois da entrevista, e nada além disso."""

    empresa_id: Texto
    vaga_id: Texto
    candidato_id: Texto
    fonte: Texto
    motivos: list[MotivoDestino]
    simulado: bool = True


class MotivoFeedback(Contrato):
    """Cada motivo liga um critério a um trecho registrado na decisão."""

    criterio: Texto
    descricao: Texto
    trecho: Texto
    fonte: Texto
    evidencia_faltante: str
    o_que_pode_mudar: str


class StatusFeedback(StrEnum):
    GERADO = "gerado"
    ENCAMINHADO = "encaminhado"


class FeedbackCandidato(Contrato):
    """Vai para a pessoa. Não tem nota, faixa, ranking nem menção a outros candidatos."""

    status: StatusFeedback
    saudacao: str
    texto: str
    motivos: list[MotivoFeedback] = []
    encaminhado_por: str | None = None
    responsavel: str | None = None

    @model_validator(mode="after")
    def _status_coerente(self) -> Self:
        if self.status == StatusFeedback.GERADO and not self.motivos:
            raise ValueError("feedback gerado precisa de motivo ligado a critério e trecho")
        if self.status == StatusFeedback.ENCAMINHADO and (
            self.motivos or self.encaminhado_por is None
        ):
            raise ValueError("encaminhamento não traz motivo e diz por que foi para uma pessoa")
        return self
