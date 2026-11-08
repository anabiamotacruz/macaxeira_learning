"use client";

import Link from "next/link";
import { Settings2, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

import {
  ApiError,
  ApiRecusa,
  assinarMandato,
  avisarResultadosDasEntrevistas,
  listarCandidatos,
  listarConversasWhatsApp,
  listarConvitesDaVaga,
  listarEventosRecentes,
  listarPacotesEntregues,
  obterAudioWhatsApp,
  obterDecisao,
  obterDocumentoDeEntrega,
  obterMetricas,
  obterSugestaoDeAjuste,
  obterResumo,
  obterVaga,
  pararVaga,
  responderConvite,
  retomarVaga,
  revisarCandidato,
  statusWhatsApp,
  type ConversaWhatsApp,
  type ConviteDaVaga,
  type MetricasVaga,
  type PacoteEntregue,
  type ResumoVaga,
  type SugestaoAjuste,
  type TaxaMedida,
} from "../lib/api";
import type { Candidato, Decisao, EventoFluxo, TipoResposta, Vaga } from "../lib/tipos";
import { SimuladoBadge } from "./SimuladoBadge";

// Texto que vem da API é dado: o React o escapa, e nada aqui o interpreta como instrução.

const ESTADOS: Record<string, string> = {
  rascunho: "Rascunho",
  aguardando_mandato: "Aguardando o mandato",
  buscando: "Buscando",
  analisando: "Analisando perfis",
  revisando: "Revisando as análises",
  decidindo: "Decidindo",
  meta_em_risco: "Meta em risco",
  convidando: "Convidando",
  entregando: "Entregando à Nara",
  concluida: "Concluída",
  pausada: "Pausada",
};
const ATIVOS = new Set(["buscando", "analisando", "revisando", "decidindo"]);
const PAUSAVEIS = new Set(["buscando", "analisando", "revisando", "decidindo", "meta_em_risco", "convidando", "entregando"]);

const MOTIVOS: Record<string, string> = {
  alem_do_teto_do_mandato: "Passou do teto de segurança de indicações do mandato",
  perfil_desatualizado: "Perfil desatualizado: confirmar os dados com a pessoa",
  alerta: "Perfil com texto suspeito (instrução escondida)",
  requisito_sem_dado: "Falta informação sobre um requisito eliminatório",
  sem_evidencia_competencia: "Sem evidência de uma competência",
  sem_evidencia_comprovada: "Requisito só autodeclarado",
  nota_abaixo_do_limiar: "Nota abaixo do limiar do mandato",
  abaixo_do_piso: "Nota abaixo do piso",
  abaixo_do_limiar: "Nota abaixo do limiar do mandato",
  vaga_sem_requisitos: "A vaga não tem requisito eliminatório",
  requisito_nao_confirmado: "Requisito não confirmado no perfil",
  fora_da_faixa_verde: "Fora da faixa verde do mandato",
  fora_da_taxa_verde: "Fora da faixa verde do mandato",
  faixa_verde: "Dentro da faixa verde do mandato",
  ressalva_do_revisor: "O revisor fez uma ressalva",
  inferencia: "Parte da evidência foi inferida, não citada",
  requisito_nao_atendido: "Não atende um requisito eliminatório",
  requisito_eliminatorio: "Não atende um requisito eliminatório",
  opt_out: "Pediu para não ser contatada",
  autorizacao_vencida: "Autorização de contato vencida",
  sem_autorizacao: "Sem autorização de contato",
  duplicata: "Registro duplicado",
};

const ERROS_MEDIDOS: Record<string, string> = {
  indicacao_errada: "Indicação errada",
  descarte_errado: "Descarte errado",
  violacao_eliminatoria: "Violou um eliminatório",
  contato_opt_out: "Contato após pedido de saída",
  mudanca_nome_genero: "Decisão muda com nome ou gênero",
  afirmacao_sem_evidencia: "Afirmação sem evidência",
};

const FONTES: Record<string, string> = {
  banco_sintetico: "Banco de talentos (sintético)",
  banco: "Banco de talentos",
  linkedin: "LinkedIn",
  linkdapi: "LinkedIn, pela LinkdAPI",
  brightdata: "LinkedIn, pela Bright Data",
  pdl: "People Data Labs",
  github: "GitHub",
};

function traduzir(regra: string): string {
  const partes = regra.split(/[,|]\s*/).map((parte) => parte.trim()).filter(Boolean);
  const frases = partes.map((parte) => {
    const chave = Object.keys(MOTIVOS).find((nome) => parte.includes(nome));
    return chave ? MOTIVOS[chave] : parte;
  });
  return [...new Set(frases)].join("; ");
}

const RESPONSAVEL = "Ana Ribeiro";

const cartao = "rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]";
const etiqueta = "inline-flex h-[22px] items-center whitespace-nowrap rounded-md border px-2 text-xs font-semibold";
const etiquetaNeutra = `${etiqueta} border-cora-line-2 bg-cora-muted-bg text-cora-ink-2`;
const etiquetaOk = `${etiqueta} border-[#CDE6D5] bg-cora-ok-bg text-cora-ok-ink`;
const etiquetaEspera = `${etiqueta} border-[#F1D58A] bg-cora-warn-bg text-cora-warn-ink`;
const etiquetaCoral = `${etiqueta} border-[#F0B5AA] bg-cora-coral-bg text-cora-coral-ink`;
const etiquetaSimulada = "rounded-md border border-[#F1C36A] bg-[#FFF7DF] px-1.5 py-0.5 font-mono text-[11px] text-[#805D16]";

type Item = { candidato: Candidato; decisao: Decisao["tipo"] | null };

function mensagemDeErro(erro: unknown, padrao: string): string {
  if (erro instanceof ApiRecusa || erro instanceof ApiError) return erro.message;
  return padrao;
}

function notaDe(decisao?: Decisao): string {
  const bruta = decisao?.entrada?.nota;
  const valor = bruta === undefined ? NaN : Number(bruta);
  return Number.isFinite(valor) ? String(Math.round(valor * 100)) : "–";
}

function dataCurta(iso: unknown): string {
  if (typeof iso !== "string") return "";
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "";
  return data.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function usd(valor: number, casas = 2): string {
  return `US$ ${valor.toFixed(casas).replace(".", ",")}`;
}

function porcentagem(valor: number | null): string {
  return valor === null ? "" : `${Math.round(valor * 100)}%`;
}

function Nota({ valor, apagada = false }: { valor: string; apagada?: boolean }) {
  return valor === "–" || apagada ? (
    <span className="num text-base font-semibold text-cora-muted">{valor}</span>
  ) : (
    <span className="num text-lg font-bold leading-tight tracking-[-0.02em] text-cora-primary">{valor}</span>
  );
}

function FormMandato({ vaga, aoAssinar }: { vaga: Vaga; aoAssinar: () => void }) {
  const [assinante, setAssinante] = useState(RESPONSAVEL);
  const [limiar, setLimiar] = useState("0.7");
  const [maxIndicacoes, setMaxIndicacoes] = useState(String(Math.min(50, Math.max(20, 10 * vaga.meta_candidatos))));
  const [declarada, setDeclarada] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");

  async function assinar() {
    const limiarVerde = Number(limiar.replace(",", "."));
    const maximo = Number(maxIndicacoes);
    if (!assinante.trim() || !(limiarVerde > 0 && limiarVerde <= 1) || !Number.isInteger(maximo) || maximo < 1) {
      setErro("Preencha quem assina, um limiar entre 0 e 1 e um número inteiro de indicações.");
      return;
    }
    setEnviando(true);
    setErro("");
    try {
      await assinarMandato(vaga.id, assinante.trim(), {
        limiar_verde: limiarVerde,
        piso_nota: Math.min(0.5, limiarVerde),
        max_indicacoes: maximo,
        max_ampliacoes: 1,
        aceitar_declarada: declarada,
      });
      aoAssinar();
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível assinar o mandato."));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-label="Mandato" className={`${cartao} grid gap-4 p-5`}>
      <div className="grid gap-1">
        <h2 className="text-lg font-semibold tracking-[-0.02em]">Assine o mandato para a CORA começar</h2>
        <p className="text-[13px] text-cora-muted">
          O mandato é a autonomia que a empresa dá ao agente. Ele busca, analisa e convida sozinho só dentro destes limites; fora deles, a pessoa vai para o RH.
        </p>
      </div>
      {vaga.requisitos.length === 0 && (
        <p className="rounded-lg border border-[#F1D58A] bg-[#FFF8E3] px-4 py-3 text-[13px] text-[#6B4A0C]">
          Esta vaga não tem requisito eliminatório. Sem ele, o agente não indica ninguém sozinho e todas as pessoas analisadas vão para o RH. Para testar o fluxo completo, crie a vaga a partir de um modelo.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1.5">
          <span className="cora-label">Quem assina</span>
          <input className="cora-input" onChange={(e) => setAssinante(e.target.value)} value={assinante} />
        </label>
        <label className="grid gap-1.5">
          <span className="cora-label">Teto de segurança de indicações (não é a meta)</span>
          <input className="cora-input num" inputMode="numeric" onChange={(e) => setMaxIndicacoes(e.target.value)} value={maxIndicacoes} />
        </label>
        <label className="grid gap-1.5">
          <span className="cora-label">Nota mínima para indicar sozinho (0 a 1)</span>
          <input className="cora-input num" inputMode="decimal" onChange={(e) => setLimiar(e.target.value)} value={limiar} />
          <span className="text-xs text-cora-placeholder">Com o modelo de verdade, as notas ficam entre 0,6 e 0,9: 0,7 é um bom começo.</span>
        </label>
        <label className="flex items-start gap-2 text-[13px] text-cora-ink-2">
          <input checked={declarada} className="mt-1 accent-[#DC3209]" onChange={(e) => setDeclarada(e.target.checked)} type="checkbox" />
          <span>Aceitar o que a própria pessoa declarou (currículo e banco de talentos) como evidência. Sem isso, só vale fonte verificável, como GitHub.</span>
        </label>
      </div>
      {erro && <p className="text-[13px] text-cora-coral-ink" role="alert">{erro}</p>}
      <div>
        <button className="cora-btn cora-btn-primary h-10" disabled={enviando} onClick={assinar} type="button">
          {enviando ? "Assinando…" : "Assinar o mandato e entregar ao agente"}
        </button>
      </div>
    </section>
  );
}

function RevisaoRh({ item, vagaId, aoMudar }: { item: Item; vagaId: string; aoMudar: () => void }) {
  const [motivo, setMotivo] = useState("Conferi o perfil.");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function decidir(decisao: "indicar" | "descartar") {
    setEnviando(true);
    setErro("");
    try {
      await revisarCandidato(item.candidato.id, { vaga_id: vagaId, decisao, motivo, responsavel: RESPONSAVEL });
      aoMudar();
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível registrar a decisão."));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="grid gap-2 border-t border-cora-subtle pt-2">
      <input aria-label={`Motivo da decisão sobre ${item.candidato.nome}`} className="cora-input h-8 text-[13px]" onChange={(e) => setMotivo(e.target.value)} value={motivo} />
      <div className="flex gap-2">
        <button className="cora-btn cora-btn-primary h-8 flex-1 px-2 text-[13px]" disabled={enviando} onClick={() => decidir("indicar")} type="button">Indicar</button>
        <button className="cora-btn cora-btn-outline h-8 flex-1 px-2 text-[13px]" disabled={enviando} onClick={() => decidir("descartar")} type="button">Descartar</button>
      </div>
      {erro && <p className="text-xs text-cora-coral-ink" role="alert">O agente recusou: {erro}</p>}
    </div>
  );
}

const URL_NO_TEXTO = /(https?:\/\/[^\s)]+)/g;

/** Texto com os links clicáveis, como o wa.me do convite e o link da Nara. */
function ComLinks({ texto }: { texto: string }) {
  return (
    <>
      {texto.split(URL_NO_TEXTO).map((parte, indice) =>
        indice % 2 === 1 ? (
          <a className="break-all underline underline-offset-2" href={parte} key={indice} rel="noreferrer" target="_blank">{parte}</a>
        ) : (
          <span key={indice}>{parte}</span>
        ),
      )}
    </>
  );
}

function AudioDaResposta({ vagaId, audioId }: { vagaId: string; audioId: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let ativo = true;
    let criada = "";
    obterAudioWhatsApp(vagaId, audioId)
      .then((u) => {
        criada = u;
        if (ativo) setUrl(u);
      })
      .catch(() => undefined);
    return () => {
      ativo = false;
      if (criada) URL.revokeObjectURL(criada);
    };
  }, [vagaId, audioId]);
  if (!url) return null;
  return <audio aria-label="Resposta em voz gerada por IA" className="h-8 w-full max-w-xs" controls src={url} />;
}

function ConversaNoWhatsApp({ conversa, vagaId }: { conversa: ConversaWhatsApp; vagaId: string }) {
  const balaoAgente = "max-w-[85%] rounded-2xl rounded-tl-sm bg-[#dcf8c6] px-4 py-2 text-[13px] text-cora-ink";
  const balaoPessoa = "ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-[#075e54] px-4 py-2 text-[13px] text-white";
  return (
    <div className="grid gap-2 rounded-xl border border-[#cfe6d8] bg-[#f4fbf6] p-3">
      <p className="text-xs font-semibold text-[#075e54]">
        WhatsApp real · {conversa.numero_mascarado} · código {conversa.codigo}
        {conversa.encerrada ? " · pediu para sair" : ""}
      </p>
      <p className="text-[11px] text-[#5d7a6b]">Canal e voz reais. O perfil do convite é fictício (dados de demonstração). A voz é gerada por IA.</p>
      {conversa.mensagens.map((mensagem) => (
        <div className="grid gap-1" key={mensagem.id}>
          <p className={mensagem.direcao === "entrada" ? balaoPessoa : balaoAgente}>
            <ComLinks texto={mensagem.texto} />
          </p>
          {mensagem.audio_id && <AudioDaResposta audioId={mensagem.audio_id} vagaId={vagaId} />}
          {!mensagem.enviada && <p className="text-xs text-cora-coral-ink">Não saiu pelo WhatsApp. Veja se o celular está pareado.</p>}
        </div>
      ))}
    </div>
  );
}

function Conversa({ convite, nome, vagaId, aoMudar, whatsapp }: {
  convite: ConviteDaVaga;
  nome: string;
  vagaId: string;
  aoMudar: () => void;
  whatsapp?: ConversaWhatsApp;
}) {
  const [texto, setTexto] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function responder(tipo: TipoResposta, conteudo = "") {
    setEnviando(true);
    setErro("");
    try {
      await responderConvite(convite.id, { vaga_id: vagaId, tipo, texto: conteudo });
      if (tipo === "duvida") setTexto("");
      aoMudar();
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível registrar a resposta."));
    } finally {
      setEnviando(false);
    }
  }

  const balaoAgente = "max-w-[85%] rounded-2xl rounded-tl-sm bg-cora-muted-bg px-4 py-2 text-[13px] text-cora-ink";
  const balaoPessoa = "ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-cora-ink px-4 py-2 text-[13px] text-white";
  return (
    <article className={`${cartao} grid gap-3 p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">{nome}</span>
        <span className="flex flex-wrap items-center gap-1.5">
          <span className={convite.estado === "aguardando" ? etiquetaEspera : etiquetaNeutra}>{convite.estado}</span>
          <span className={etiquetaNeutra}>{convite.canal}</span>
          {convite.simulado && <span className={etiquetaSimulada}>envio simulado</span>}
        </span>
      </div>
      <p className={balaoAgente}><ComLinks texto={convite.mensagem} /></p>
      {whatsapp && <ConversaNoWhatsApp conversa={whatsapp} vagaId={vagaId} />}
      {convite.duvidas.map((duvida, indice) => (
        <div className="grid gap-2" key={`${duvida.momento}-${indice}`}>
          <p className={balaoPessoa}>{duvida.pergunta}</p>
          {duvida.resposta ? (
            <p className={balaoAgente}>{duvida.resposta}</p>
          ) : (
            <p className="text-xs text-cora-warn-ink">Sem resposta segura no material da vaga: a dúvida foi para uma pessoa do RH.</p>
          )}
        </div>
      ))}
      {convite.retorno && <p className={balaoAgente}>{convite.retorno.mensagem}</p>}
      {convite.estado === "aguardando" && (
        <div className="grid gap-2 border-t border-cora-subtle pt-3">
          <p className="text-xs text-cora-placeholder">Simulação: você faz o papel da pessoa convidada.</p>
          <div className="flex gap-2">
            <input className="cora-input flex-1" onChange={(e) => setTexto(e.target.value)} placeholder="Escreva uma dúvida, como a pessoa…" value={texto} />
            <button className="cora-btn cora-btn-outline" disabled={enviando || !texto.trim()} onClick={() => responder("duvida", texto)} type="button">Enviar dúvida</button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="cora-btn cora-btn-outline h-8 text-[13px]" disabled={enviando} onClick={() => responder("aceite")} type="button">Tenho interesse</button>
            <button className="cora-btn cora-btn-outline h-8 text-[13px]" disabled={enviando} onClick={() => responder("recusa")} type="button">Não tenho interesse</button>
            <button className="cora-btn cora-btn-outline h-8 text-[13px]" disabled={enviando} onClick={() => responder("silencio")} type="button">Não respondeu</button>
            <button className="cora-btn cora-btn-outline h-8 text-[13px]" disabled={enviando} onClick={() => responder("opt_out")} type="button">Não quero mais contato</button>
          </div>
        </div>
      )}
      {erro && <p className="text-[13px] text-cora-coral-ink" role="alert">{erro}</p>}
    </article>
  );
}

function BaixarDocumento({ vagaId, candidatoId }: { vagaId: string; candidatoId: string }) {
  const [erro, setErro] = useState("");

  async function baixar() {
    setErro("");
    try {
      const texto = await obterDocumentoDeEntrega(vagaId, candidatoId);
      const url = URL.createObjectURL(new Blob([texto], { type: "text/markdown;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `contexto-${candidatoId.replace(/[^\w.-]+/g, "_")}.md`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível gerar o documento."));
    }
  }

  return (
    <div>
      <button className="cora-btn cora-btn-outline h-8 text-[13px]" onClick={baixar} type="button">Baixar documento (Markdown)</button>
      {erro && <p className="mt-1 text-[13px] text-cora-coral-ink" role="alert">{erro}</p>}
    </div>
  );
}

function Numero({ rotulo, valor, detalhe, children }: { rotulo: string; valor: React.ReactNode; detalhe?: string; children?: React.ReactNode }) {
  return (
    <div className={`${cartao} flex flex-col gap-1 px-[18px] py-4`}>
      <span className="text-[13px] text-cora-muted">{rotulo}</span>
      <span className="num text-[26px] font-semibold leading-tight tracking-[-0.03em]">{valor}</span>
      {detalhe && <span className="text-xs text-cora-placeholder">{detalhe}</span>}
      {children}
    </div>
  );
}

function LinhaTaxa({ rotulo, taxa }: { rotulo: string; taxa: TaxaMedida }) {
  return (
    <>
      <dt className="text-cora-ink-2">{rotulo}</dt>
      <dd className="num m-0 text-right">
        {taxa.valor === null ? (
          <span className="text-cora-placeholder">não medido</span>
        ) : (
          <>
            <b>{porcentagem(taxa.valor)}</b>
            <span className="block text-[11px] text-cora-placeholder">
              {taxa.casos} casos · {porcentagem(taxa.wilson_inferior)}–{porcentagem(taxa.wilson_superior)}
            </span>
          </>
        )}
      </dd>
    </>
  );
}

type Aba = "quadro" | "lista" | "conversas" | "nara" | "rastro" | "criterios";

type Cartao = {
  item: Item;
  decisao?: Decisao;
  etiqueta: string;
  estilo: string;
  detalhe: string;
  vivo?: boolean;
  nara?: boolean;
  revisao?: boolean;
};

export function PainelVaga({ vagaId }: { vagaId: string }) {
  const [vaga, setVaga] = useState<Vaga | null>(null);
  const [mandato, setMandato] = useState<Record<string, unknown> | null>(null);
  const [resumo, setResumo] = useState<ResumoVaga | null>(null);
  const [itens, setItens] = useState<Item[]>([]);
  const [decisoes, setDecisoes] = useState<Record<string, Decisao>>({});
  const [convites, setConvites] = useState<ConviteDaVaga[]>([]);
  const [conversasZap, setConversasZap] = useState<ConversaWhatsApp[]>([]);
  const [pacotes, setPacotes] = useState<PacoteEntregue[]>([]);
  const [eventos, setEventos] = useState<EventoFluxo[]>([]);
  const [metricas, setMetricas] = useState<MetricasVaga | null>(null);
  const [zap, setZap] = useState<{ ligado: boolean; voz: string | null } | null>(null);
  const [erro, setErro] = useState("");
  const [avisando, setAvisando] = useState(false);
  const [controlando, setControlando] = useState(false);
  const [sugestao, setSugestao] = useState<SugestaoAjuste | null>(null);
  const [aba, setAba] = useState<Aba>("quadro");
  const [atualizadoEm, setAtualizadoEm] = useState("");
  const cacheDecisoes = useRef<Record<string, Decisao>>({});
  const ocupado = useRef(false);

  const atualizar = useCallback(async () => {
    if (ocupado.current) return;
    ocupado.current = true;
    try {
      const dadosVaga = await obterVaga(vagaId);
      setVaga(dadosVaga.vaga);
      setMandato(dadosVaga.mandato);
      if (dadosVaga.estado === "rascunho" || dadosVaga.estado === "aguardando_mandato") {
        setResumo(null);
        return;
      }
      const [novoResumo, candidatos, novosConvites, novosPacotes, novosEventos, novasConversas, novasMetricas] = await Promise.all([
        obterResumo(vagaId),
        listarCandidatos(vagaId, 1, 100),
        listarConvitesDaVaga(vagaId),
        listarPacotesEntregues(vagaId),
        listarEventosRecentes(vagaId),
        listarConversasWhatsApp(vagaId),
        obterMetricas(vagaId).catch(() => null),
      ]);
      const faltando = candidatos.itens.filter(
        (item) => item.decisao && cacheDecisoes.current[item.candidato.id]?.tipo !== item.decisao,
      );
      const lidas = await Promise.all(
        faltando.map((item) => obterDecisao(item.candidato.id, vagaId).then((r) => r.decisao).catch(() => null)),
      );
      for (const decisao of lidas) if (decisao) cacheDecisoes.current[decisao.candidato_id] = decisao;
      setResumo(novoResumo);
      setItens(candidatos.itens);
      setDecisoes({ ...cacheDecisoes.current });
      setConvites(novosConvites);
      setConversasZap(novasConversas);
      setPacotes(novosPacotes);
      setEventos(novosEventos);
      setMetricas(novasMetricas);
      setAtualizadoEm(new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
      setErro("");
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível carregar a vaga."));
    } finally {
      ocupado.current = false;
    }
  }, [vagaId]);

  useEffect(() => {
    const primeira = window.setTimeout(() => void atualizar(), 0);
    const intervalo = window.setInterval(() => void atualizar(), 4000);
    statusWhatsApp().then(setZap).catch(() => undefined);
    return () => {
      window.clearTimeout(primeira);
      window.clearInterval(intervalo);
    };
  }, [atualizar]);

  async function avisarResultados() {
    setAvisando(true);
    try {
      await avisarResultadosDasEntrevistas(vagaId);
      await atualizar();
      setSugestao(await obterSugestaoDeAjuste(vagaId).catch(() => null));
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível buscar os resultados das entrevistas."));
    } finally {
      setAvisando(false);
    }
  }

  async function alternarPausa(pausada: boolean) {
    setControlando(true);
    try {
      if (pausada) await retomarVaga(vagaId, RESPONSAVEL, "Retomada pelo painel");
      else await pararVaga(vagaId, RESPONSAVEL, "Pausada pelo painel");
      await atualizar();
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, pausada ? "Não foi possível retomar a busca." : "Não foi possível pausar a busca."));
    } finally {
      setControlando(false);
    }
  }

  if (!vaga) {
    return erro ? (
      <p className="rounded-xl border border-[#F0B5AA] bg-cora-coral-bg p-6 text-cora-coral-ink" role="alert">{erro}</p>
    ) : (
      <p className="text-cora-muted">Carregando a vaga…</p>
    );
  }

  const nomes = Object.fromEntries(itens.map((item) => [item.candidato.id, item.candidato.nome]));
  const grupo = (tipo: string) => itens.filter((item) => item.decisao === tipo);
  const indicados = grupo("indicar");
  const fila = grupo("pedir_humano");
  const descartados = grupo("descartar");
  const semDecisao = itens.filter((item) => !item.decisao);
  const contagemDescartes: Record<string, number> = {};
  for (const item of descartados) {
    const motivo = traduzir(decisoes[item.candidato.id]?.regra ?? "");
    contagemDescartes[motivo] = (contagemDescartes[motivo] ?? 0) + 1;
  }
  const contagemFontes: Record<string, number> = {};
  for (const item of itens) contagemFontes[item.candidato.fonte] = (contagemFontes[item.candidato.fonte] ?? 0) + 1;
  const semMandato = !resumo;
  const estado = resumo?.estado ?? "aguardando_mandato";
  const pausada = estado === "pausada";
  const comRetorno = convites.filter((convite) => convite.retorno);
  const convitePorPessoa = Object.fromEntries(convites.map((c) => [c.candidato_id, c]));
  const naNara = new Set(pacotes.map((p) => p.candidato_id));
  const custoTotal = eventos.reduce((soma, e) => soma + (e.custo_usd || 0), 0);
  const meta = vaga.meta_candidatos;
  const politica = (mandato?.politica ?? {}) as Record<string, unknown>;

  const cartaoDe = (item: Item): Cartao => {
    const decisao = decisoes[item.candidato.id];
    const convite = convitePorPessoa[item.candidato.id];
    if (naNara.has(item.candidato.id)) return { item, decisao, etiqueta: "Aceitou", estilo: etiquetaOk, detalhe: "Contexto entregue ao recrutador", nara: true };
    if (item.decisao === "pedir_humano")
      return { item, decisao, etiqueta: "Para o RH decidir", estilo: etiquetaEspera, detalhe: traduzir(decisao?.regra === "fora_da_faixa_verde" ? decisao.motivo : decisao?.regra ?? ""), revisao: true };
    if (convite) {
      const aguardando = convite.estado === "aguardando";
      return { item, decisao, etiqueta: aguardando ? "Convite enviado" : convite.estado, estilo: aguardando ? etiquetaEspera : etiquetaNeutra, detalhe: `${convite.canal} · tentativa ${convite.tentativa}`, vivo: aguardando };
    }
    if (item.decisao === "indicar") return { item, decisao, etiqueta: "Indicada", estilo: etiquetaOk, detalhe: decisao?.responsavel.startsWith("humano:") ? `Indicada por ${decisao.responsavel.slice(7)}` : "Acima da nota mínima do mandato" };
    return { item, decisao, etiqueta: "Em análise", estilo: etiquetaNeutra, detalhe: "Lendo histórico e evidências", vivo: true };
  };

  const ativos = [...semDecisao, ...fila, ...indicados].map(cartaoDe);
  const colunas: Array<{ titulo: string; cards: Cartao[] }> = [
    { titulo: "Analisando", cards: ativos.filter((c) => c.etiqueta === "Em análise") },
    { titulo: "Para o RH decidir", cards: ativos.filter((c) => c.revisao) },
    { titulo: "Indicadas e em conversa", cards: ativos.filter((c) => !c.revisao && !c.nara && c.etiqueta !== "Em análise") },
    { titulo: "Entregue ao recrutador", cards: ativos.filter((c) => c.nara) },
  ];
  const lista: Cartao[] = [
    ...ativos,
    ...descartados.map((item) => ({ item, decisao: decisoes[item.candidato.id], etiqueta: "Descartada", estilo: etiquetaCoral, detalhe: traduzir(decisoes[item.candidato.id]?.regra ?? "") || "Regra registrada no rastro" })),
  ];
  const linkPessoa = (id: string) => `/vagas/${encodeURIComponent(vagaId)}/candidatos/${encodeURIComponent(id)}`;

  const abas: Array<[Aba, string, number | null]> = [
    ["quadro", "Quadro", null],
    ["lista", "Lista", lista.length],
    ["conversas", "Conversas", convites.length],
    ["nara", "Nara e retorno", pacotes.length],
    ["rastro", "Rastro", eventos.length],
    ["criterios", "Critérios", null],
  ];

  return (
    <div className="flex flex-col gap-[22px]">
      <div className="flex flex-col gap-2.5">
        <nav aria-label="Caminho" className="flex items-center gap-1.5 text-[13px] text-cora-placeholder">
          <Link className="text-cora-placeholder no-underline hover:text-cora-primary" href="/">Vagas</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page" className="text-cora-ink">{vaga.titulo}</span>
        </nav>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">{vaga.titulo}</h1>
              <span className={`${etiquetaNeutra} gap-1.5`}>
                <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${pausada ? "bg-cora-warn-ink" : estado === "concluida" ? "bg-cora-ok-ink" : "bg-cora-accent"}`} />
                {ESTADOS[estado] ?? estado}
                {ATIVOS.has(estado) ? "…" : ""}
              </span>
            </div>
            <p className="m-0 text-[13px] text-cora-muted">
              <span className="font-mono">{vaga.id}</span> · meta de {meta} {meta === 1 ? "pessoa" : "pessoas"} · prazo de {vaga.prazo_dias} dias
            </p>
          </div>
          <div className="flex flex-wrap gap-2.5">
            {(PAUSAVEIS.has(estado) || pausada) && (
              <button className="cora-btn cora-btn-outline h-10" disabled={controlando} onClick={() => void alternarPausa(pausada)} type="button">
                {pausada ? (
                  <svg aria-hidden="true" fill="currentColor" height="14" viewBox="0 0 16 16" width="14"><path d="M5 3.5v9l7-4.5z" /></svg>
                ) : (
                  <svg aria-hidden="true" fill="currentColor" height="14" viewBox="0 0 16 16" width="14"><rect height="9" rx="1" width="3" x="4" y="3.5" /><rect height="9" rx="1" width="3" x="9" y="3.5" /></svg>
                )}
                {controlando ? "Aguarde…" : pausada ? "Retomar busca" : "Pausar busca"}
              </button>
            )}
            {!semMandato && (
              <Sheet>
                <SheetTrigger asChild>
                  <button className="cora-btn cora-btn-outline h-10" type="button">
                    <Settings2 aria-hidden="true" className="size-4" />
                    Configurações
                  </button>
                </SheetTrigger>
                <SheetContent className="w-full gap-0 bg-cora-surface sm:max-w-md">
                  <SheetHeader className="border-b border-cora-line">
                    <SheetTitle className="text-cora-ink">Configurações da vaga</SheetTitle>
                    <SheetDescription className="text-cora-muted">
                      Regras do mandato que a CORA segue nesta vaga. Para mudar, pause a busca e assine um novo mandato.
                    </SheetDescription>
                  </SheetHeader>
                  <dl className="m-0 flex flex-col divide-y divide-cora-line px-4 text-sm">
                    <div className="flex items-start gap-2 py-3.5">
                      <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-cora-ok-ink" />
                      <div className="flex flex-col">
                        <dt className="font-semibold text-cora-ink">Mandato assinado</dt>
                        <dd className="m-0 text-cora-muted">
                          {typeof mandato?.assinante === "string" ? mandato.assinante : "—"}
                          {dataCurta(mandato?.assinado_em) ? ` em ${dataCurta(mandato?.assinado_em)}` : ""}
                        </dd>
                      </div>
                    </div>
                    {typeof politica.limiar_verde === "number" && (
                      <div className="flex justify-between gap-4 py-3.5"><dt className="text-cora-ink-2">Nota mínima para indicar</dt><dd className="num m-0 font-semibold">{politica.limiar_verde.toFixed(2).replace(".", ",")}</dd></div>
                    )}
                    {typeof politica.max_indicacoes === "number" && (
                      <div className="flex justify-between gap-4 py-3.5"><dt className="text-cora-ink-2">Indicações sem revisão</dt><dd className="num m-0 font-semibold">até {politica.max_indicacoes}</dd></div>
                    )}
                    <div className="flex justify-between gap-4 py-3.5"><dt className="text-cora-ink-2">Tentativas de contato por pessoa</dt><dd className="num m-0 font-semibold">{vaga.max_tentativas_contato}</dd></div>
                    <div className="flex justify-between gap-4 py-3.5"><dt className="text-cora-ink-2">Evidência autodeclarada</dt><dd className="m-0 font-semibold">{politica.aceitar_declarada === true ? "Aceita" : "Não aceita"}</dd></div>
                    <div className="flex justify-between gap-4 py-3.5"><dt className="text-cora-ink-2">Meta e prazo</dt><dd className="num m-0 font-semibold">{meta} em {vaga.prazo_dias} dias</dd></div>
                  </dl>
                  <div className="px-4 py-3.5">
                    <SheetClose asChild>
                      <button className="cora-btn cora-btn-outline w-full" onClick={() => setAba("criterios")} type="button">Ver critérios da vaga</button>
                    </SheetClose>
                  </div>
                </SheetContent>
              </Sheet>
            )}
            <button className="cora-btn cora-btn-outline h-10" onClick={() => setAba("criterios")} type="button">Ver critérios</button>
          </div>
        </div>
        {erro && <p className="text-[13px] text-cora-coral-ink" role="alert">{erro}</p>}
      </div>

      {semMandato ? (
        <FormMandato aoAssinar={() => void atualizar()} vaga={vaga} />
      ) : (
        <>
          <section aria-label="Números da vaga" className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
            <Numero detalhe={semDecisao.length ? `${semDecisao.length} na fila de análise` : "todas com decisão"} rotulo="Encontradas" valor={itens.length} />
            <Numero detalhe="com nota e evidência" rotulo="Analisadas" valor={resumo.analisados} />
            <Numero detalhe="cada uma com a regra registrada" rotulo="Descartadas por regra" valor={resumo.descartados} />
            <Numero detalhe={resumo.na_fila_humana ? "aguardam você" : "nada pendente"} rotulo="Para o RH decidir" valor={resumo.na_fila_humana} />
            <Numero detalhe="ao recrutador" rotulo="Meta" valor={<>{pacotes.length} <span className="text-[15px] font-medium text-cora-muted">de {meta} entregues</span></>}>
              <span className="mt-0.5 h-1.5 overflow-hidden rounded-[3px] bg-[#EDF1EE]">
                <span className="block h-full rounded-[3px] bg-cora-accent" style={{ width: `${Math.min(100, (pacotes.length / Math.max(1, meta)) * 100)}%` }} />
              </span>
            </Numero>
          </section>

          {pausada && (
            <section aria-label="Vaga pausada" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#F1D58A] bg-[#FFF8E3] px-[18px] py-3.5">
              <span className="flex flex-col">
                <span className="font-semibold">A busca está pausada</span>
                <span className="text-[13px] text-[#6B4A0C]">Isso acontece quando alguém pausa, quando o agente manda gente demais para o RH, passa do limite de gasto ou um serviço cai. Resolva a fila do RH e retome.</span>
              </span>
              <button className="cora-btn cora-btn-primary h-10" disabled={controlando} onClick={() => void alternarPausa(true)} type="button">Retomar busca</button>
            </section>
          )}
          {!pausada && fila.length > 0 && (
            <section aria-label="Fila do RH" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#F1D58A] bg-[#FFF8E3] px-[18px] py-3.5">
              <span className="flex flex-col">
                <span className="font-semibold">{fila.length === 1 ? "1 pessoa aguarda" : `${fila.length} pessoas aguardam`} a sua decisão</span>
                <span className="text-[13px] text-[#6B4A0C]">A CORA não decide sozinha quando falta dado, o perfil é suspeito ou a pessoa ficou fora dos limites do mandato. Indicar leva ao convite; descartar encerra.</span>
              </span>
              <button className="cora-btn cora-btn-outline h-10" onClick={() => setAba("quadro")} type="button">Revisar no quadro</button>
            </section>
          )}

          <section aria-label="Pessoas da vaga" className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-cora-line">
              <div aria-label="Seções da vaga" className="flex flex-wrap gap-x-5" role="tablist">
                {abas.map(([chave, rotulo, total]) => (
                  <button
                    aria-selected={aba === chave}
                    className={`-mb-px h-10 border-0 border-b-2 bg-transparent px-0.5 text-sm ${aba === chave ? "border-cora-accent font-semibold text-cora-ink" : "border-transparent font-medium text-cora-muted hover:text-cora-ink"}`}
                    key={chave}
                    onClick={() => setAba(chave)}
                    role="tab"
                    type="button"
                  >
                    {rotulo}
                    {total ? <span className="num ml-1.5 text-xs text-cora-placeholder">{total}</span> : null}
                  </button>
                ))}
              </div>
              <span className="pb-2.5 text-xs text-cora-placeholder">
                {atualizadoEm ? `Atualizado às ${atualizadoEm}` : "Atualizando…"} · a CORA não agenda e não decide contratação
              </span>
            </div>

            {aba === "quadro" && (
              <div className="flex flex-col gap-4">
                <div className="relative overflow-x-auto pb-1">
                  <div className="grid min-w-[950px] grid-cols-4 items-start gap-3">
                    {colunas.map((coluna) => (
                      <div className="flex flex-col gap-2 rounded-xl bg-cora-muted-bg p-2.5" key={coluna.titulo}>
                        <div className="flex items-center justify-between gap-2 px-1.5 pb-1.5 pt-1">
                          <span className="text-[13px] font-semibold">{coluna.titulo}</span>
                          <span className="num inline-flex h-[22px] min-w-[22px] items-center justify-center rounded-md border border-cora-line-2 bg-cora-surface px-1.5 text-xs font-semibold text-cora-ink-2">{coluna.cards.length}</span>
                        </div>
                        {coluna.cards.length === 0 && <p className="px-1.5 pb-2 text-xs text-cora-placeholder">Ninguém aqui agora.</p>}
                        {coluna.cards.map((card) => (
                          <div className="flex flex-col gap-2 rounded-[10px] border border-cora-line-2 bg-cora-surface p-3 shadow-[0_1px_2px_rgba(11,48,56,0.06)]" key={card.item.candidato.id}>
                            <span className="flex items-start justify-between gap-2">
                              <span className="flex min-w-0 flex-col">
                                <Link className="text-sm font-semibold text-cora-ink no-underline hover:text-cora-primary" href={linkPessoa(card.item.candidato.id)}>{card.item.candidato.nome}</Link>
                                <span className="text-xs text-cora-placeholder">{card.item.candidato.atributos?.cargo ?? FONTES[card.item.candidato.fonte] ?? card.item.candidato.fonte}</span>
                              </span>
                              <Nota valor={notaDe(card.decisao)} />
                            </span>
                            <span className="flex flex-wrap gap-1.5">
                              <span className={card.estilo}>{card.etiqueta}</span>
                              {card.nara && <span className={etiquetaSimulada}>Nara simulada</span>}
                              {card.item.candidato.simulado && <span className={etiquetaSimulada}>perfil sintético</span>}
                            </span>
                            {card.detalhe && (
                              <span className="flex items-center gap-1.5 text-xs text-cora-muted">
                                {card.vivo && <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-cora-accent" />}
                                {card.detalhe}
                              </span>
                            )}
                            {card.revisao && <RevisaoRh aoMudar={() => void atualizar()} item={card.item} vagaId={vagaId} />}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
                {descartados.length > 0 && (
                  <div className={`${cartao} flex flex-wrap items-center gap-x-4 gap-y-2.5 px-[18px] py-3.5`}>
                    <span className="text-[13px] font-semibold">Descartadas pelas regras ({descartados.length})</span>
                    {descartados.slice(0, 3).map((item) => (
                      <span className="inline-flex items-center gap-2 text-[13px]" key={item.candidato.id}>
                        <span className="font-medium">{item.candidato.nome}</span>
                        <span className={etiquetaCoral}>{traduzir(decisoes[item.candidato.id]?.regra ?? "") || "regra registrada"}</span>
                      </span>
                    ))}
                    <button className="ml-auto h-8 rounded-lg border-0 bg-transparent px-2.5 text-[13px] font-semibold text-cora-ink underline underline-offset-[3px]" onClick={() => setAba("lista")} type="button">Ver todas na lista</button>
                  </div>
                )}
              </div>
            )}

            {aba === "lista" && (
              <div className={`${cartao} overflow-hidden`}>
                <div className="relative overflow-x-auto">
                  <div aria-label="Pessoas da vaga" className="min-w-[900px]" role="table">
                    <div className="grid grid-cols-[1.6fr_0.5fr_1.3fr_1.2fr_1.9fr] gap-3.5 border-b border-[#EDF1EE] bg-cora-row px-[18px] py-2.5 text-xs font-medium text-cora-placeholder" role="row">
                      <span role="columnheader">Pessoa</span><span role="columnheader">Nota</span><span role="columnheader">Situação</span><span role="columnheader">Origem</span><span role="columnheader">Detalhe</span>
                    </div>
                    {lista.length === 0 && <p className="px-[18px] py-4 text-[13px] text-cora-placeholder">Ninguém encontrado ainda.</p>}
                    {lista.map((card) => (
                      <div className="cora-row grid grid-cols-[1.6fr_0.5fr_1.3fr_1.2fr_1.9fr] items-center gap-3.5 border-b border-cora-subtle px-[18px] py-3 text-[13px]" key={card.item.candidato.id} role="row">
                        <span className="flex min-w-0 flex-col" role="cell">
                          <Link className="font-semibold text-cora-ink no-underline hover:text-cora-primary" href={linkPessoa(card.item.candidato.id)}>{card.item.candidato.nome}</Link>
                          <span className="text-xs text-cora-placeholder">{card.item.candidato.atributos?.cargo ?? ""}</span>
                        </span>
                        <span role="cell"><Nota apagada={card.etiqueta === "Descartada"} valor={notaDe(card.decisao)} /></span>
                        <span role="cell"><span className={card.estilo}>{card.etiqueta}</span></span>
                        <span className="text-cora-muted" role="cell">{FONTES[card.item.candidato.fonte] ?? card.item.candidato.fonte}</span>
                        <span className="text-cora-muted" role="cell">{card.detalhe}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {aba === "conversas" && (
              <div className="grid gap-3">
                <p className="flex flex-wrap items-center gap-2 text-[13px] text-cora-muted">
                  O primeiro contato sai por e-mail com o link do WhatsApp; a conversa só começa quando a pessoa chama.
                  <SimuladoBadge simulado />
                </p>
                {convites.length ? (
                  convites.map((convite) => (
                    <Conversa aoMudar={() => void atualizar()} convite={convite} key={convite.id} nome={nomes[convite.candidato_id] ?? convite.candidato_id} vagaId={vagaId} whatsapp={conversasZap.find((c) => c.candidato_id === convite.candidato_id)} />
                  ))
                ) : (
                  <p className={`${cartao} px-[18px] py-4 text-[13px] text-cora-placeholder`}>Nenhum convite ainda.</p>
                )}
              </div>
            )}

            {aba === "nara" && (
              <div className="grid gap-4">
                <div className="grid gap-3">
                  <p className="flex flex-wrap items-center gap-2 text-[13px] text-cora-muted">
                    Quem aceita vai para a Nara com o porquê da indicação. A Nara agenda e entrevista; a CORA não agenda.
                    <span className={etiquetaSimulada}>Nara simulada</span>
                  </p>
                  {pacotes.length ? (
                    pacotes.map((pacote) => (
                      <article className={`${cartao} grid gap-3 p-[18px]`} key={pacote.candidato_id}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <Link className="font-semibold text-cora-ink no-underline hover:text-cora-primary" href={linkPessoa(pacote.candidato_id)}>{nomes[pacote.candidato_id] ?? pacote.candidato_id}</Link>
                          <BaixarDocumento candidatoId={pacote.candidato_id} vagaId={vagaId} />
                        </div>
                        <dl className="m-0 grid gap-1.5 text-[13px]">
                          {Object.entries(pacote.motivo_por_criterio).map(([criterio, motivo]) => (
                            <div className="grid gap-0.5 sm:grid-cols-[200px_1fr] sm:gap-3" key={criterio}>
                              <dt className="font-medium text-cora-ink">{criterio}</dt>
                              <dd className="m-0 text-cora-ink-2">“{motivo}”</dd>
                            </div>
                          ))}
                        </dl>
                        {pacote.pontos_a_aprofundar.length > 0 && <p className="text-[13px] text-cora-ink-2"><b>Para a Nara aprofundar:</b> {pacote.pontos_a_aprofundar.join("; ")}</p>}
                        {pacote.lacunas.length > 0 && <p className="text-[13px] text-cora-placeholder">Lacunas: {pacote.lacunas.join("; ")}</p>}
                      </article>
                    ))
                  ) : (
                    <p className={`${cartao} px-[18px] py-4 text-[13px] text-cora-placeholder`}>Ninguém aceitou ainda. Na aba Conversas, responda “Tenho interesse” num convite.</p>
                  )}
                </div>

                <div className={`${cartao} grid gap-3 p-[18px]`}>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="flex flex-col">
                      <span className="font-semibold">Depois da entrevista</span>
                      <span className="text-xs text-cora-placeholder">A Nara entrevista e decide. A CORA só avisa cada pessoa do resultado, uma vez, sem mostrar nota.</span>
                    </span>
                    <button className="cora-btn cora-btn-primary h-10" disabled={avisando || !pacotes.length} onClick={avisarResultados} type="button">
                      {avisando ? "Avisando…" : "A Nara terminou: avisar as pessoas"}
                    </button>
                  </div>
                  {comRetorno.length > 0 && (
                    <ul className="m-0 grid list-none gap-2 p-0 text-[13px]">
                      {comRetorno.map((convite) => (
                        <li className="flex flex-wrap items-center gap-2 border-t border-cora-subtle pt-2" key={convite.id}>
                          <b>{nomes[convite.candidato_id] ?? convite.candidato_id}</b>
                          <span className={convite.retorno?.aprovado ? etiquetaOk : etiquetaNeutra}>Nara: {convite.retorno?.aprovado ? "seguir" : "não seguir"}</span>
                          <span className={convite.retorno?.enviado ? "text-cora-muted" : "text-cora-coral-ink"}>{convite.retorno?.enviado ? "mensagem enviada" : "mensagem não saiu, tente de novo"}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {sugestao && (
                    <div className="rounded-lg border border-[#F1D58A] bg-[#FFF8E3] px-4 py-3 text-[13px] text-[#6B4A0C]">
                      <p className="font-semibold text-cora-ink">Sugestão para a próxima vaga (a CORA não muda nada sozinha)</p>
                      <p className="mt-1">{sugestao.motivo}.</p>
                      <p className="mt-1">Peso de “{sugestao.criterio}”: de {sugestao.peso_atual} para {sugestao.peso_sugerido}. Quem decide ajustar é o RH.</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {aba === "rastro" && (
              <div className={`${cartao} overflow-hidden`}>
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#EDF1EE] px-[18px] py-3.5">
                  <span className="flex flex-col">
                    <span className="font-semibold">Rastro da vaga</span>
                    <span className="text-xs text-cora-placeholder">Cada etapa do agente, com a regra aplicada e o custo. Mostra os 100 eventos mais recentes.</span>
                  </span>
                </div>
                <div className="relative overflow-x-auto">
                  <div aria-label="Eventos do rastro" className="min-w-[820px] text-[13px]" role="table">
                    <div className="grid grid-cols-[80px_130px_1fr_180px_100px] gap-3.5 border-b border-[#EDF1EE] bg-cora-row px-[18px] py-2.5 text-xs font-medium text-cora-placeholder" role="row">
                      <span role="columnheader">Hora</span><span role="columnheader">Etapa</span><span role="columnheader">O que aconteceu</span><span role="columnheader">Pessoa</span><span className="text-right" role="columnheader">Custo</span>
                    </div>
                    {[...eventos].reverse().map((evento, indice) => (
                      <div className="grid grid-cols-[80px_130px_1fr_180px_100px] items-center gap-3.5 border-b border-cora-subtle px-[18px] py-2.5" key={`${evento.momento}-${indice}`} role="row">
                        <span className="num font-mono text-xs text-cora-muted" role="cell">{evento.momento.slice(11, 19)}</span>
                        <span role="cell"><span className={etiquetaNeutra}>{evento.etapa}</span></span>
                        <span role="cell">{evento.mensagem}</span>
                        <span className="truncate text-xs text-cora-muted" role="cell">{evento.candidato_id ? nomes[evento.candidato_id] ?? evento.candidato_id : "–"}</span>
                        <span className="num text-right font-mono text-xs text-cora-muted" role="cell">{evento.custo_usd ? usd(evento.custo_usd, 4) : "–"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {aba === "criterios" && <Criterios vaga={vaga} />}
          </section>

          <section aria-labelledby="sec-registro" className="flex flex-col gap-3">
            <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-registro">Registro do agente</h2>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3">
              <div className={`${cartao} flex flex-col gap-3 p-[18px]`}>
                <span className="text-sm font-semibold">Fontes</span>
                <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-[13px]">
                  {Object.entries(contagemFontes).map(([fonte, total]) => (
                    <div className="contents" key={fonte}>
                      <dt className="text-cora-ink-2">{FONTES[fonte] ?? fonte}</dt>
                      <dd className="num m-0 font-semibold">{total}</dd>
                    </div>
                  ))}
                  {itens.length === 0 && <dt className="text-cora-placeholder">Nenhum perfil ainda</dt>}
                </dl>
                <span className="text-xs text-cora-placeholder">Cada perfil guarda de onde veio e quando foi atualizado.</span>
              </div>

              <div className={`${cartao} flex flex-col gap-3 p-[18px]`}>
                <span className="text-sm font-semibold">Descartes por regra</span>
                {descartados.length ? (
                  <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px] text-cora-ink-2">
                    {Object.entries(contagemDescartes).sort((a, b) => b[1] - a[1]).map(([motivo, quantidade]) => (
                      <li className="flex gap-2.5" key={motivo}><b className="num min-w-3 text-cora-ink">{quantidade}</b>{motivo || "sem motivo registrado"}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-[13px] text-cora-placeholder">Nenhum descarte ainda.</span>
                )}
              </div>

              <div className={`${cartao} flex flex-col gap-3 p-[18px]`}>
                <span className="text-sm font-semibold">Custo</span>
                <span className="num text-[22px] font-semibold tracking-[-0.02em]">
                  {usd(resumo.gasto_usd)}{" "}
                  {resumo.limite_gasto_usd ? <span className="text-[13px] font-medium text-cora-muted">de {usd(resumo.limite_gasto_usd)} de limite</span> : null}
                </span>
                <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-[13px]">
                  <dt className="text-cora-ink-2">Por pessoa analisada</dt>
                  <dd className="num m-0 font-semibold">{resumo.analisados ? usd(resumo.gasto_usd / resumo.analisados, 3) : "–"}</dd>
                  <dt className="text-cora-ink-2">Por pessoa indicada</dt>
                  <dd className="num m-0 font-semibold">{resumo.indicados ? usd(resumo.gasto_usd / resumo.indicados, 3) : "–"}</dd>
                  <dt className="text-cora-ink-2">Somado no rastro</dt>
                  <dd className="num m-0 font-semibold">{usd(custoTotal, 3)}</dd>
                </dl>
                <span className="text-xs text-cora-placeholder">
                  {resumo.gasto_usd === 0 ? "Demonstração sem modelo: não há gasto. " : ""}Passou do limite, a busca pausa sozinha.
                </span>
              </div>

              <div className={`${cartao} flex flex-col gap-3 p-[18px]`}>
                <span className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold">Qualidade medida</span>
                  {metricas?.exemplo_fixo && <span className={etiquetaSimulada}>exemplo ilustrativo</span>}
                </span>
                {metricas ? (
                  <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-[13px]">
                    <LinhaTaxa rotulo="Decididas sem revisão humana" taxa={metricas.sem_revisao} />
                    {Object.entries(metricas.erros_por_tipo).map(([tipo, taxa]) => (
                      <div className="contents" key={tipo}>
                        <LinhaTaxa rotulo={ERROS_MEDIDOS[tipo] ?? tipo} taxa={taxa} />
                      </div>
                    ))}
                  </dl>
                ) : (
                  <span className="text-[13px] text-cora-placeholder">Ainda sem medida.</span>
                )}
                <span className="text-xs text-cora-placeholder">Taxa, número de casos e intervalo de Wilson de 95%.</span>
              </div>

              <div className={`${cartao} flex flex-col gap-3 p-[18px]`}>
                <span className="text-sm font-semibold">Canais de contato</span>
                <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-[13px]">
                  <dt className="text-cora-ink-2">WhatsApp</dt>
                  <dd className="m-0">
                    {zap === null ? <span className="text-cora-placeholder">verificando…</span> : zap.ligado ? <span className={etiquetaOk}>real, ligado</span> : <span className={etiquetaSimulada}>simulado</span>}
                  </dd>
                  <dt className="text-cora-ink-2">Voz nas respostas</dt>
                  <dd className="m-0 text-cora-muted">{zap?.voz ?? "desligada"}</dd>
                  <dt className="text-cora-ink-2">Conversas reais</dt>
                  <dd className="num m-0 font-semibold">{conversasZap.length}</dd>
                </dl>
                <span className="text-xs text-cora-placeholder">Sem o WhatsApp real ligado na API, as conversas são simuladas no painel.</span>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function Criterios({ vaga }: { vaga: Vaga }) {
  return (
    <div className="overflow-hidden rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
      <div className="flex flex-wrap items-center justify-between gap-2.5 px-[18px] py-3.5">
        <span className="flex flex-col">
          <span className="font-semibold">Critérios aprovados</span>
          <span className="text-xs text-cora-placeholder">Eliminatórios rodam em código, nunca no modelo. Competências pontuam com evidência citada.</span>
        </span>
      </div>
      {vaga.descricao && <p className="border-t border-[#EDF1EE] px-[18px] py-3 text-[13px] text-cora-ink-2">{vaga.descricao}</p>}
      <div className="border-y border-[#EDF1EE] bg-cora-row px-[18px] py-2 text-[13px] font-semibold">Eliminatórios</div>
      {vaga.requisitos.length === 0 && <p className="px-[18px] py-3 text-[13px] text-cora-placeholder">Nenhum eliminatório: todas as pessoas analisadas vão para o RH.</p>}
      {vaga.requisitos.map((requisito, indice) => (
        <div className="grid grid-cols-[52px_1fr_auto] items-center gap-3 border-b border-cora-subtle px-[18px] py-3" key={requisito.id}>
          <span className="font-mono text-xs text-cora-ink-2">E-{String(indice + 1).padStart(2, "0")}</span>
          <span className="font-medium">{requisito.descricao}</span>
          <span className="font-mono text-xs text-cora-muted">{requisito.campo} = {requisito.valor_esperado}</span>
        </div>
      ))}
      <div className="border-b border-[#EDF1EE] bg-cora-row px-[18px] py-2 text-[13px] font-semibold">Desejáveis</div>
      {vaga.competencias.map((competencia, indice) => (
        <div className="grid grid-cols-[52px_1fr_auto] items-center gap-3 border-b border-cora-subtle px-[18px] py-3 last:border-b-0" key={competencia.nome}>
          <span className="font-mono text-xs text-cora-ink-2">D-{String(indice + 1).padStart(2, "0")}</span>
          <span className="font-medium">{competencia.nome}</span>
          <span className="num text-[13px] text-cora-muted">peso {competencia.peso}</span>
        </div>
      ))}
    </div>
  );
}
