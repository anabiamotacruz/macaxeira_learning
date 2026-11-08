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
  return Promise.all(idsSalvos().map(async (id) => ({ ...(await obterVaga(id)), fonte: "api" as const })));
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
