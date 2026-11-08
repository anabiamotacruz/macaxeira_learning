import type {
  Candidato,
  Convite,
  Decisao,
  EstadoVaga,
  EventoFluxo,
  TipoResposta,
  Vaga,
} from "./tipos";

export type ApiEnvelope = {
  simulado?: boolean;
  exemplo_fixo?: boolean;
};

export type ApiVagaResponse = ApiEnvelope & {
  vaga: Vaga;
  estado: EstadoVaga;
  mandato: Record<string, unknown> | null;
};

export type ApiCandidatosResponse = ApiEnvelope & {
  pagina: number;
  limite: number;
  total: number;
  itens: Array<{
    candidato: Candidato;
    decisao: Decisao["tipo"] | null;
    destino: string | null;
  }>;
};

export type ApiDecisaoResponse = ApiEnvelope & { decisao: Decisao };

export type ApiConvitesResponse = ApiEnvelope & {
  vaga_id: string;
  itens: Array<
    Convite & {
      estado: string;
      tentativa: number;
      link_destino: string | null;
    }
  >;
};

export type ApiRespostaResponse = ApiEnvelope & {
  vaga_id: string;
  convite_id: string;
  tipo: TipoResposta;
};

export type ApiVagaListItem = ApiVagaResponse & {
  fonte: "api" | "reserva";
};

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(
      status === 404
        ? "O recurso não foi encontrado nesta empresa."
        : status === 422
          ? "Os dados enviados são inválidos. Revise os campos e tente novamente."
          : "Não foi possível conectar ao serviço. Verifique se a API está em execução.",
    );
    this.name = "ApiError";
    this.status = status;
  }
}

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const EMPRESA_ID = process.env.NEXT_PUBLIC_EMPRESA_ID || "empresa-exemplo";
const RESERVA_ATIVA = process.env.NEXT_PUBLIC_MODO_RESERVA === "true";
const IDS_VAGAS = "macaxeira.vagas.ids";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Empresa-Id": EMPRESA_ID,
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0);
  }

  if (!resposta.ok) throw new ApiError(resposta.status);
  return (await resposta.json()) as T;
}

function idsSalvos(): string[] {
  try {
    const bruto = window.localStorage.getItem(IDS_VAGAS);
    const ids = bruto ? JSON.parse(bruto) : [];
    return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function salvarId(id: string): void {
  try {
    window.localStorage.setItem(IDS_VAGAS, JSON.stringify([...new Set([...idsSalvos(), id])]));
  } catch {
    // O catálogo continua funcionando; a API permanece como fonte da criação atual.
  }
}

export function modoReservaAtivo(): boolean {
  return RESERVA_ATIVA;
}

export function listarIdsLocais(): string[] {
  return idsSalvos();
}

export async function listarVagas(): Promise<ApiVagaListItem[]> {
  if (RESERVA_ATIVA) return [];
  try {
    const resposta = await request<ApiEnvelope & { itens: ApiVagaResponse[] }>("/vagas");
    return resposta.itens.map((item) => ({ ...item, fonte: "api" as const }));
  } catch (erro) {
    // API sem a listagem: cai para as vagas criadas neste navegador.
    if (!(erro instanceof ApiError) || (erro.status !== 404 && erro.status !== 405)) throw erro;
  }
  const vagas: Array<ApiVagaListItem | null> = await Promise.all(
    idsSalvos().map(async (id) => {
      try {
        return { ...(await obterVaga(id)), fonte: "api" as const };
      } catch (erro) {
        // A API guarda as vagas em memória: uma vaga que sumiu no reinício não derruba o catálogo.
        if (erro instanceof ApiError && erro.status === 404) return null;
        throw erro;
      }
    }),
  );
  return vagas.filter((vaga): vaga is ApiVagaListItem => vaga !== null);
}

export async function obterVaga(id: string): Promise<ApiVagaResponse> {
  return request<ApiVagaResponse>(`/vagas/${encodeURIComponent(id)}`);
}

export async function criarVaga(
  pedido: Omit<Vaga, "id" | "empresa_id" | "aprovada">,
): Promise<ApiVagaResponse> {
  const resposta = await request<ApiVagaResponse>("/vagas", {
    method: "POST",
    body: JSON.stringify(pedido),
  });
  salvarId(resposta.vaga.id);
  return resposta;
}

export async function listarCandidatos(
  vagaId: string,
  pagina = 1,
  limite = 20,
): Promise<ApiCandidatosResponse> {
  return request<ApiCandidatosResponse>(
    `/vagas/${encodeURIComponent(vagaId)}/candidatos?pagina=${pagina}&limite=${limite}`,
  );
}

export async function obterDecisao(candidatoId: string, vagaId: string): Promise<ApiDecisaoResponse> {
  return request<ApiDecisaoResponse>(
    `/candidatos/${encodeURIComponent(candidatoId)}/decisao?vaga_id=${encodeURIComponent(vagaId)}`,
  );
}

export async function obterDecisaoCandidato(
  candidatoId: string,
  vagaId: string,
): Promise<ApiDecisaoResponse> {
  return obterDecisao(candidatoId, vagaId);
}

export async function listarConvites(vagaId: string): Promise<ApiConvitesResponse> {
  return request<ApiConvitesResponse>(`/vagas/${encodeURIComponent(vagaId)}/convites`);
}

export async function responderConvite(
  conviteId: string,
  pedido: { vaga_id: string; tipo: TipoResposta; texto: string; chave_idempotencia?: string },
): Promise<ApiRespostaResponse> {
  const chave = pedido.chave_idempotencia || crypto.randomUUID();
  return request<ApiRespostaResponse>(`/convites/${encodeURIComponent(conviteId)}/resposta`, {
    method: "POST",
    body: JSON.stringify({ ...pedido, chave_idempotencia: chave }),
  });
}

export async function listarEventos(vagaId: string): Promise<ApiEnvelope & { itens: EventoFluxo[] }> {
  return request<ApiEnvelope & { itens: EventoFluxo[] }>(
    `/vagas/${encodeURIComponent(vagaId)}/eventos`,
  );
}

// Fluxo completo da vaga: mandato, andamento, fila do RH, entrega e retorno depois da entrevista.

/** Erro com a mensagem que a API escreveu para mostrar à pessoa, como a recusa de uma revisão. */
export class ApiRecusa extends Error {
  readonly status: number;

  constructor(status: number, mensagem: string) {
    super(mensagem);
    this.name = "ApiRecusa";
    this.status = status;
  }
}

async function requestComMotivo<T>(path: string, init?: RequestInit): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-Empresa-Id": EMPRESA_ID, ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0);
  }
  if (resposta.ok) return (await resposta.json()) as T;
  let mensagem = "";
  try {
    const corpo = (await resposta.json()) as { erro?: { mensagem?: string } };
    mensagem = corpo.erro?.mensagem ?? "";
  } catch {
    // Sem corpo legível, vale a mensagem padrão do status.
  }
  if (mensagem) throw new ApiRecusa(resposta.status, mensagem);
  throw new ApiError(resposta.status);
}

export type PoliticaMandato = {
  limiar_verde: number;
  piso_nota: number;
  max_indicacoes: number;
  max_ampliacoes: number;
  aceitar_declarada: boolean;
};

export type ResumoVaga = {
  vaga_id: string;
  estado: EstadoVaga;
  analisados: number;
  indicados: number;
  descartados: number;
  na_fila_humana: number;
  gasto_usd: number;
  limite_gasto_usd: number | null;
};

export type DuvidaConvite = {
  pergunta: string;
  resposta: string | null;
  encaminhada_a_pessoa: boolean;
  simulado: boolean;
  momento: string;
};

export type RetornoEntrevista = {
  candidato_id: string;
  convite_id: string;
  aprovado: boolean;
  mensagem: string;
  enviado: boolean;
  simulado: boolean;
  momento: string;
};

export type ConviteDaVaga = {
  id: string;
  candidato_id: string;
  canal: string;
  mensagem: string;
  link_destino: string | null;
  simulado: boolean;
  estado: string;
  tentativa: number;
  duvidas: DuvidaConvite[];
  retorno: RetornoEntrevista | null;
};

export type PacoteEntregue = {
  candidato_id: string;
  motivo_por_criterio: Record<string, string>;
  pontos_a_aprofundar: string[];
  lacunas: string[];
};

export type ModeloDeVaga = Omit<Vaga, "id" | "empresa_id" | "aprovada">;

export async function listarModelosDeVaga(): Promise<ModeloDeVaga[]> {
  return (await request<ApiEnvelope & { itens: ModeloDeVaga[] }>("/vagas/modelos")).itens;
}

export async function assinarMandato(
  vagaId: string,
  assinante: string,
  politica: PoliticaMandato,
  limiteGastoUsd = 5,
): Promise<ApiVagaResponse> {
  return requestComMotivo<ApiVagaResponse>(`/vagas/${encodeURIComponent(vagaId)}/mandato`, {
    method: "POST",
    body: JSON.stringify({ assinante, limite_gasto_usd: limiteGastoUsd, politica }),
  });
}

export async function obterResumo(vagaId: string): Promise<ResumoVaga> {
  return (await request<ApiEnvelope & { resumo: ResumoVaga }>(`/vagas/${encodeURIComponent(vagaId)}/resumo`)).resumo;
}

export async function listarEventosRecentes(vagaId: string): Promise<EventoFluxo[]> {
  return (
    await request<ApiEnvelope & { itens: EventoFluxo[] }>(`/vagas/${encodeURIComponent(vagaId)}/eventos?limite=100`)
  ).itens;
}

export async function listarConvitesDaVaga(vagaId: string): Promise<ConviteDaVaga[]> {
  return (await request<ApiEnvelope & { itens: ConviteDaVaga[] }>(`/vagas/${encodeURIComponent(vagaId)}/convites`)).itens;
}

export async function listarPacotesEntregues(vagaId: string): Promise<PacoteEntregue[]> {
  const resposta = await request<ApiEnvelope & { saida: { pacotes: PacoteEntregue[] } }>(
    `/vagas/${encodeURIComponent(vagaId)}/entrega`,
  );
  return resposta.saida.pacotes;
}

export async function revisarCandidato(
  candidatoId: string,
  pedido: { vaga_id: string; decisao: "indicar" | "descartar"; motivo: string; responsavel: string },
): Promise<ApiDecisaoResponse> {
  return requestComMotivo<ApiDecisaoResponse>(`/candidatos/${encodeURIComponent(candidatoId)}/revisao`, {
    method: "POST",
    body: JSON.stringify({ ...pedido, chave_idempotencia: crypto.randomUUID() }),
  });
}

export async function avisarResultadosDasEntrevistas(vagaId: string): Promise<RetornoEntrevista[]> {
  const resposta = await requestComMotivo<ApiEnvelope & { itens: RetornoEntrevista[] }>(
    `/vagas/${encodeURIComponent(vagaId)}/retornos`,
    { method: "POST", body: JSON.stringify({ chave_idempotencia: crypto.randomUUID() }) },
  );
  return resposta.itens;
}

export function guardarVagaNoCatalogo(id: string): void {
  salvarId(id);
}

export async function obterDocumentoDeEntrega(vagaId: string, candidatoId: string): Promise<string> {
  const resposta = await requestComMotivo<ApiEnvelope & { documento: string }>(
    `/vagas/${encodeURIComponent(vagaId)}/entrega/${encodeURIComponent(candidatoId)}/documento`,
  );
  return resposta.documento;
}

export type SugestaoAjuste = {
  criterio: string;
  peso_atual: number;
  peso_sugerido: number;
  motivo: string;
  reprovacoes: number;
  resultados_lidos: number;
  aplicada: false;
};

export async function obterSugestaoDeAjuste(vagaId: string): Promise<SugestaoAjuste | null> {
  const resposta = await request<ApiEnvelope & { sugestao: SugestaoAjuste | null }>(
    `/vagas/${encodeURIComponent(vagaId)}/ajuste`,
  );
  return resposta.sugestao;
}

export async function proporVaga(
  descricao: string,
): Promise<{ proposta: ModeloDeVaga | null; pergunta: string | null }> {
  const resposta = await requestComMotivo<
    ApiEnvelope & { proposta: ModeloDeVaga | null; pergunta: string | null }
  >("/vagas/proposta", { method: "POST", body: JSON.stringify({ descricao }) });
  return { proposta: resposta.proposta, pergunta: resposta.pergunta };
}

export type MensagemWhatsApp = {
  id: string;
  direcao: "entrada" | "saida";
  texto: string;
  momento: string;
  audio_id: string | null;
  enviada: boolean;
};

export type ConversaWhatsApp = {
  numero_mascarado: string;
  empresa_id: string;
  vaga_id: string;
  candidato_id: string;
  codigo: string;
  encerrada: boolean;
  mensagens: MensagemWhatsApp[];
  simulado: boolean;
};

/** Conversas do WhatsApp real desta vaga. Sem WhatsApp configurado na API, a lista vem vazia. */
export async function listarConversasWhatsApp(vagaId: string): Promise<ConversaWhatsApp[]> {
  try {
    return await request<ConversaWhatsApp[]>(`/vagas/${encodeURIComponent(vagaId)}/whatsapp`);
  } catch {
    return [];
  }
}

/** O MP3 de uma resposta por voz, como URL local para o <audio>. A rota exige a empresa. */
export async function obterAudioWhatsApp(vagaId: string, audioId: string): Promise<string> {
  const resposta = await fetch(
    `${API_URL}/vagas/${encodeURIComponent(vagaId)}/whatsapp/audio/${encodeURIComponent(audioId)}`,
    { headers: { "X-Empresa-Id": EMPRESA_ID }, cache: "no-store" },
  );
  if (!resposta.ok) throw new ApiError(resposta.status);
  return URL.createObjectURL(await resposta.blob());
}

// Controle da vaga e da decisão: pausa, retomada, reversão, destino, métricas e reinício da sessão.

export type ControleVaga = { vaga_id: string; estado: EstadoVaga; estado_anterior: EstadoVaga };

export async function pararVaga(vagaId: string, responsavel: string, motivo = ""): Promise<ControleVaga> {
  return requestComMotivo<ControleVaga>(`/vagas/${encodeURIComponent(vagaId)}/parar`, {
    method: "POST",
    body: JSON.stringify({ responsavel, motivo, chave_idempotencia: crypto.randomUUID() }),
  });
}

export async function retomarVaga(vagaId: string, responsavel: string, motivo = ""): Promise<ControleVaga> {
  return requestComMotivo<ControleVaga>(`/vagas/${encodeURIComponent(vagaId)}/retomar`, {
    method: "POST",
    body: JSON.stringify({ responsavel, motivo, chave_idempotencia: crypto.randomUUID() }),
  });
}

export async function reverterDecisao(
  candidatoId: string,
  pedido: { vaga_id: string; motivo: string; responsavel: string },
): Promise<{ decisao_original: Decisao; decisao_nova: Decisao }> {
  return requestComMotivo(`/candidatos/${encodeURIComponent(candidatoId)}/reverter`, {
    method: "POST",
    body: JSON.stringify({ ...pedido, chave_idempotencia: crypto.randomUUID() }),
  });
}

export type DestinoPessoa = "banco" | "talent_garden" | "contratada";

export async function registrarDestino(
  candidatoId: string,
  pedido: { vaga_id: string; destino: DestinoPessoa; responsavel: string },
): Promise<{ vaga_id: string; candidato_id: string; destino: DestinoPessoa; responsavel: string }> {
  return requestComMotivo(`/candidatos/${encodeURIComponent(candidatoId)}/destino`, {
    method: "POST",
    body: JSON.stringify({ ...pedido, chave_idempotencia: crypto.randomUUID() }),
  });
}

export type TaxaMedida = {
  valor: number | null;
  casos: number;
  wilson_inferior: number | null;
  wilson_superior: number | null;
};

export type MetricasVaga = ApiEnvelope & {
  vaga_id: string;
  sem_revisao: TaxaMedida;
  erros_por_tipo: Record<string, TaxaMedida>;
};

export async function obterMetricas(vagaId: string): Promise<MetricasVaga> {
  return request<MetricasVaga>(`/vagas/${encodeURIComponent(vagaId)}/metricas`);
}

export async function reiniciarSessao(): Promise<ApiEnvelope & { dados_recarregados: boolean; mensagem: string }> {
  return requestComMotivo(`/sessoes/reiniciar`, { method: "POST", body: "{}" });
}

export async function statusWhatsApp(): Promise<{ ligado: boolean; voz: string | null }> {
  try {
    return await request<{ ligado: boolean; voz: string | null }>(`/whatsapp/status`);
  } catch {
    return { ligado: false, voz: null };
  }
}
