// A fonte da verdade destes tipos é backend/contratos/modelos.py.

export type Competencia = {
  nome: string;
  peso: number;
};

export type Requisito = {
  id: string;
  descricao: string;
  campo: string;
  valor_esperado: string;
};

export type Vaga = {
  id: string;
  empresa_id: string;
  titulo: string;
  descricao: string;
  requisitos: Requisito[];
  competencias: Competencia[];
  meta_candidatos: number;
  prazo_dias: number;
  max_tentativas_contato: number;
  aprovada: boolean;
};

export type EstadoVaga =
  | "rascunho"
  | "aguardando_mandato"
  | "buscando"
  | "analisando"
  | "revisando"
  | "decidindo"
  | "concluida"
  | "pausada";

export type Experiencia = {
  empresa: string;
  cargo: string;
  inicio: string;
  fim: string | null;
  descricao: string;
};

export type EstadoBanco =
  | "pendente"
  | "ativo"
  | "desatualizado"
  | "expirado"
  | "removido";

export type Candidato = {
  id: string;
  empresa_id: string;
  nome: string;
  fonte: string;
  simulado: boolean;
  origem: string;
  atualizado_em: string;
  autorizacao_valida_ate: string | null;
  estado: EstadoBanco;
  perfil_texto: string;
  atributos: Record<string, string>;
  historico: Experiencia[];
  autorizou_contato: boolean;
  opt_out: boolean;
};

export type Evidencia = {
  criterio: string;
  trecho: string;
  fonte: string;
};

export type Analise = {
  vaga_id: string;
  candidato_id: string;
  requisitos_ok: Record<string, boolean>;
  notas: Record<string, number>;
  evidencias: Evidencia[];
  lacunas: string[];
  pontos_a_aprofundar: string[];
  alertas: string[];
  ressalvas_revisor: string[];
};

export type TipoDecisao = "descartar" | "indicar" | "pedir_humano";

export type Decisao = {
  empresa_id?: string;
  vaga_id: string;
  candidato_id: string;
  tipo: TipoDecisao;
  regra: string;
  motivo: string;
  responsavel: string;
  rastro_id: string;
  entrada: Record<string, string>;
  evidencias: Evidencia[];
  momento: string;
};

export type TipoConvite = "autorizacao" | "vaga";

export type Convite = {
  id: string;
  empresa_id: string;
  tipo: TipoConvite;
  canal: string;
  vaga_id: string | null;
  candidato_id: string;
  mensagem: string;
  link_destino?: string | null;
  chave_idempotencia: string;
  simulado: boolean;
};

export type TipoResposta = "aceite" | "recusa" | "duvida" | "silencio" | "opt_out";

export type RespostaCandidato = {
  convite_id: string;
  tipo: TipoResposta;
  texto: string;
};

export type PacoteNara = {
  vaga_id: string;
  candidato_id: string;
  motivo_por_criterio: Record<string, string>;
  historico: Experiencia[];
  evidencias: Evidencia[];
  lacunas: string[];
  pontos_a_aprofundar: string[];
  ressalvas_revisor: string[];
  autorizacao: string;
  fonte: string;
  rastro_id: string;
  chave_idempotencia: string;
};

export type ResultadoNara = {
  vaga_id: string;
  candidato_id: string;
  notas: Record<string, number>;
  aprovado: boolean;
  simulado: boolean;
};

export type PropostaAjuste = {
  vaga_id: string;
  motivo: string;
  antes: Vaga;
  depois: Vaga;
  resultado_avaliacao: Record<string, number>;
  aprovada: boolean;
};

export type EventoFluxo = {
  vaga_id: string;
  etapa: string;
  mensagem: string;
  candidato_id: string | null;
  custo_usd: number;
  momento: string;
};
