"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  analisesIniciais,
  decisoesIniciais,
  resultadosNaraIniciais,
  vagasIniciais,
} from "../lib/dados";
import {
  ApiError,
  ApiRecusa,
  type ConversaWhatsApp,
  type ConviteDaVaga,
  type DestinoPessoa,
  type PacoteEntregue,
  listarConversasWhatsApp,
  listarConvitesDaVaga,
  listarPacotesEntregues,
  modoReservaAtivo,
  obterDecisaoCandidato,
  obterVaga,
  registrarDestino,
  responderConvite,
  reverterDecisao,
  revisarCandidato,
} from "../lib/api";
import type { Candidato, Decisao, TipoDecisao, TipoResposta, Vaga } from "../lib/tipos";
import { AppHeader, AppMain } from "./AppHeader";
import { SimuladoBadge } from "./SimuladoBadge";

/** Pessoa do RH que assina as ações humanas desta tela na demonstração. */
const RESPONSAVEL_RH = "Ana Ribeiro";

const ROTULO_DECISAO: Record<TipoDecisao, string> = {
  indicar: "Indicar para contato",
  descartar: "Descartar nesta vaga",
  pedir_humano: "Aguardando revisão humana",
};

const ROTULO_DESTINO: Record<DestinoPessoa, string> = {
  banco: "Banco de talentos",
  talent_garden: "Talent garden",
  contratada: "Contratada",
};

const ROTULO_ESTADO_BANCO: Record<Candidato["estado"], string> = {
  pendente: "Pendente",
  ativo: "Ativa no banco",
  desatualizado: "Desatualizada",
  expirado: "Autorização expirada",
  removido: "Removida",
};

const ROTULO_ESTADO_CONVITE: Record<string, string> = {
  a_enviar: "Convite a enviar",
  aguardando: "Aguardando resposta",
  aceito: "Aceitou o convite",
  encerrado: "Contato encerrado",
  cancelado: "Convite cancelado",
};

function erroLegivel(erro: unknown, padrao: string): string {
  if (erro instanceof ApiRecusa || erro instanceof ApiError) return erro.message;
  return padrao;
}

function lerJson<T>(texto: string | undefined, padrao: T): T {
  if (!texto) return padrao;
  try {
    return JSON.parse(texto) as T;
  } catch {
    return padrao;
  }
}

function iniciais(nome: string): string {
  const partes = nome.split(/\s+/).filter(Boolean);
  return ((partes[0]?.[0] ?? "") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
}

function data(valor: string | null | undefined): string {
  if (!valor) return "—";
  const d = new Date(valor.length === 10 ? `${valor}T12:00:00` : valor);
  return Number.isNaN(d.getTime()) ? valor : d.toLocaleDateString("pt-BR");
}

function Cartao({ titulo, descricao, children, id, className = "" }: { titulo: string; descricao?: string; children: React.ReactNode; id?: string; className?: string }) {
  return (
    <section aria-labelledby={id ? `${id}-titulo` : undefined} className={`flex flex-col gap-3.5 rounded-xl border border-cora-line-2 bg-cora-surface p-5 shadow-[0_1px_2px_rgba(11,48,56,0.06)] ${className}`} id={id}>
      <div className="flex flex-col gap-1">
        <h2 className="m-0 text-base font-semibold tracking-[-0.02em]" id={id ? `${id}-titulo` : undefined}>{titulo}</h2>
        {descricao && <p className="m-0 text-[13px] text-cora-muted">{descricao}</p>}
      </div>
      {children}
    </section>
  );
}

function Selo({ tom, children }: { tom: "ok" | "warn" | "coral" | "neutral"; children: React.ReactNode }) {
  const cores = {
    ok: "border-[#CDE6D5] bg-cora-ok-bg text-cora-ok-ink",
    warn: "border-[#F1D58A] bg-cora-warn-bg text-cora-warn-ink",
    coral: "border-[#F6CFC5] bg-cora-coral-bg text-cora-coral-ink",
    neutral: "border-cora-line-2 bg-cora-muted-bg text-cora-ink-2",
  }[tom];
  return <span className={`inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-md border px-2 text-xs font-semibold ${cores}`}>{children}</span>;
}

function Etiqueta({ children }: { children: React.ReactNode }) {
  return <span className="rounded-[5px] bg-cora-muted-bg px-1.5 py-0.5 font-mono text-[11px] text-cora-ink-2">{children}</span>;
}

type Props = {
  candidato: Candidato;
  /** Com vagaId, a tela lê a decisão, a vaga, os convites e a entrega na API. Sem ele, usa os dados fixos. */
  vagaId?: string;
  destinoInicial?: string | null;
};

export function CandidatoDetalhe({ candidato, vagaId, destinoInicial = null }: Props) {
  const usaApi = Boolean(vagaId) && !modoReservaAtivo();
  const vagaFixa = vagasIniciais[0];
  const [vagaApi, setVagaApi] = useState<Vaga>();
  const vaga = vagaApi ?? (usaApi ? undefined : vagaFixa);
  const idVaga = vagaId ?? vagaFixa.id;

  const [decisaoLocal, setDecisaoLocal] = useState<Decisao | undefined>(
    usaApi ? undefined : decisoesIniciais.find((item) => item.candidato_id === candidato.id),
  );
  const [decisaoApi, setDecisaoApi] = useState<Decisao>();
  const [convites, setConvites] = useState<ConviteDaVaga[]>([]);
  const [pacote, setPacote] = useState<PacoteEntregue>();
  const [conversas, setConversas] = useState<ConversaWhatsApp[]>([]);
  const [destino, setDestino] = useState<string | null>(destinoInicial);
  const [erroApi, setErroApi] = useState("");
  const [aviso, setAviso] = useState("");
  const [carregandoApi, setCarregandoApi] = useState(usaApi);
  const [exemploFixo, setExemploFixo] = useState(false);
  const [aba, setAba] = useState<"visao" | "contato">("visao");
  const [motivoReversao, setMotivoReversao] = useState("");
  const [motivoRevisao, setMotivoRevisao] = useState("");
  const [enviando, setEnviando] = useState(false);
  const chavesResposta = useRef(new Map<string, string>());

  useEffect(() => {
    if (!usaApi || !vagaId) return;
    let ativo = true;
    Promise.all([
      obterDecisaoCandidato(candidato.id, vagaId),
      listarConvitesDaVaga(vagaId),
      obterVaga(vagaId),
    ])
      .then(([decisaoResposta, convitesResposta, vagaResposta]) => {
        if (!ativo) return;
        setDecisaoApi(decisaoResposta.decisao);
        setConvites(convitesResposta);
        setVagaApi(vagaResposta.vaga);
        setExemploFixo(decisaoResposta.exemplo_fixo === true);
      })
      .catch((erro) => {
        if (ativo) setErroApi(erroLegivel(erro, "Não foi possível carregar decisão e convites."));
      })
      .finally(() => {
        if (ativo) setCarregandoApi(false);
      });
    // Entrega e WhatsApp são complementares: sem eles a tela segue.
    listarPacotesEntregues(vagaId)
      .then((pacotes) => ativo && setPacote(pacotes.find((p) => p.candidato_id === candidato.id)))
      .catch(() => undefined);
    listarConversasWhatsApp(vagaId).then((lista) => ativo && setConversas(lista.filter((c) => c.candidato_id === candidato.id)));
    return () => {
      ativo = false;
    };
  }, [candidato.id, usaApi, vagaId]);

  const analise = usaApi ? undefined : analisesIniciais.find((item) => item.candidato_id === candidato.id);
  const resultado = usaApi ? undefined : resultadosNaraIniciais.find((item) => item.candidato_id === candidato.id);
  const decisao = decisaoApi ?? decisaoLocal;
  // Reversão e revisão criam uma decisão nova sem as notas: a nota por critério segue a da análise original.
  const [entradaAnalise, setEntradaAnalise] = useState<Record<string, string>>();
  if (decisao?.entrada.nota !== undefined && entradaAnalise !== decisao.entrada && !entradaAnalise?.nota) {
    setEntradaAnalise(decisao.entrada);
  }
  const meusConvites = convites.filter((c) => c.candidato_id === candidato.id);

  // Nota por critério: a decisão da API guarda as notas e os requisitos que usou; os dados fixos vêm da análise.
  const criterios = useMemo(() => {
    const entrada = entradaAnalise ?? decisao?.entrada ?? {};
    const notasUsadas = lerJson<Record<string, number>>(entrada.notas_usadas, analise?.notas ?? {});
    const requisitosApi = lerJson<Record<string, string>>(entrada.requisitos, {});
    const nota = entrada.nota !== undefined ? Number(entrada.nota) : undefined;
    const eliminatorios = (vaga?.requisitos ?? []).map((r) => {
      const situacao = requisitosApi[r.id] ?? (analise ? (analise.requisitos_ok[r.id] ? "atende" : "nao_atende") : undefined);
      return { id: r.id, descricao: r.descricao, situacao };
    });
    const desejaveis = (vaga?.competencias ?? []).map((c) => ({ nome: c.nome, peso: c.peso, nota: notasUsadas[c.nome] }));
    const notaGeral =
      nota ??
      (desejaveis.some((d) => d.nota !== undefined)
        ? desejaveis.reduce((s, d) => s + (d.nota ?? 0) * d.peso, 0) / Math.max(desejaveis.reduce((s, d) => s + d.peso, 0), 1)
        : undefined);
    return { eliminatorios, desejaveis, notaGeral };
  }, [entradaAnalise, decisao, analise, vaga]);

  const lacunas = pacote?.lacunas ?? analise?.lacunas ?? [];
  const aprofundar = pacote?.pontos_a_aprofundar ?? analise?.pontos_a_aprofundar ?? [];
  const alertas = analise?.alertas ?? [];
  const conviteAtual = meusConvites[meusConvites.length - 1];

  function registrarDecisaoLocal(tipo: TipoDecisao) {
    setDecisaoLocal({
      vaga_id: idVaga,
      candidato_id: candidato.id,
      tipo,
      regra: "decisao_humana_revisor_demo",
      motivo:
        tipo === "indicar"
          ? "Pessoa revisora aprovou a indicação após conferir as evidências."
          : "Pessoa revisora não aprovou a indicação nesta rodada.",
      responsavel: RESPONSAVEL_RH,
      rastro_id: `rastro-local-${candidato.id}`,
      entrada: { origem: candidato.origem },
      evidencias: analise?.evidencias ?? [],
      momento: new Date().toISOString(),
    });
  }

  async function revisar(tipo: "indicar" | "descartar") {
    if (!usaApi || !vagaId) return registrarDecisaoLocal(tipo);
    setEnviando(true);
    setErroApi("");
    try {
      const resposta = await revisarCandidato(candidato.id, {
        vaga_id: vagaId,
        decisao: tipo,
        motivo: motivoRevisao.trim() || (tipo === "indicar" ? "Evidências conferidas pelo RH." : "Não atende ao que a vaga pede, segundo o RH."),
        responsavel: RESPONSAVEL_RH,
      });
      setDecisaoApi(resposta.decisao);
      setMotivoRevisao("");
      setAviso(`Decisão humana registrada por ${RESPONSAVEL_RH}.`);
    } catch (erro) {
      setErroApi(erroLegivel(erro, "Não foi possível registrar a revisão."));
    } finally {
      setEnviando(false);
    }
  }

  async function reverter() {
    if (!usaApi || !vagaId || !motivoReversao.trim()) return;
    setEnviando(true);
    setErroApi("");
    try {
      const resposta = await reverterDecisao(candidato.id, { vaga_id: vagaId, motivo: motivoReversao.trim(), responsavel: RESPONSAVEL_RH });
      setDecisaoApi(resposta.decisao_nova);
      setMotivoReversao("");
      setAviso("A decisão voltou para a fila humana. A original fica guardada no rastro.");
    } catch (erro) {
      setErroApi(erroLegivel(erro, "Não foi possível reverter a decisão."));
    } finally {
      setEnviando(false);
    }
  }

  async function definirDestino(valor: DestinoPessoa) {
    if (!usaApi || !vagaId) return;
    setEnviando(true);
    setErroApi("");
    try {
      const resposta = await registrarDestino(candidato.id, { vaga_id: vagaId, destino: valor, responsavel: RESPONSAVEL_RH });
      setDestino(resposta.destino);
      setAviso(`Destino registrado por ${RESPONSAVEL_RH}: ${ROTULO_DESTINO[resposta.destino]}.`);
    } catch (erro) {
      setErroApi(erroLegivel(erro, "Não foi possível registrar o destino."));
    } finally {
      setEnviando(false);
    }
  }

  async function responder(conviteId: string) {
    const pedido = { vaga_id: idVaga, tipo: "duvida" as TipoResposta, texto: "Resposta registrada pelo painel." };
    const fingerprint = `${conviteId}|${pedido.vaga_id}|${pedido.tipo}|${pedido.texto}`;
    const chave = chavesResposta.current.get(fingerprint) || crypto.randomUUID();
    chavesResposta.current.set(fingerprint, chave);
    try {
      await responderConvite(conviteId, { ...pedido, chave_idempotencia: chave });
      chavesResposta.current.delete(fingerprint);
      setAviso("Resposta enviada. Uma nova tentativa reutiliza a mesma chave de idempotência.");
    } catch (erro) {
      setErroApi(erro instanceof ApiError ? erro.message : "Não foi possível responder ao convite.");
    }
  }

  const etapas: Array<[string, boolean]> = [
    ["Analisada pela CORA", Boolean(decisao || analise)],
    ["Autorizou o contato", candidato.autorizou_contato],
    ["Indicada para contato", decisao?.tipo === "indicar"],
    ["Convite com link da Nara", Boolean(conviteAtual) || (!usaApi && decisao?.tipo === "indicar")],
    ["Aceitou e foi entregue ao recrutador", Boolean(pacote) || conviteAtual?.estado === "aceito"],
    [
      resultado ? `Entrevista na Nara: ${resultado.aprovado ? "passou" : "não passou"}` : conviteAtual?.retorno ? `Retorno: ${conviteAtual.retorno.aprovado ? "aprovada" : "não aprovada"}` : "Resultado da entrevista (Nara)",
      Boolean(resultado || conviteAtual?.retorno),
    ],
  ];

  const nota100 = criterios.notaGeral !== undefined ? Math.round(criterios.notaGeral * 100) : undefined;
  const cargo = candidato.atributos.cargo ?? candidato.historico[0]?.cargo;
  const email = candidato.atributos.email;

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader ativo="vagas" />
      <AppMain>
        <nav aria-label="Caminho" className="-mb-1 flex flex-wrap items-center gap-1.5 text-[13px] text-cora-placeholder">
          <Link className="text-cora-placeholder no-underline hover:text-cora-ink" href="/">Vagas</Link>
          <span aria-hidden="true">/</span>
          {vagaId ? (
            <Link className="text-cora-placeholder no-underline hover:text-cora-ink" href={`/vagas/${encodeURIComponent(vagaId)}`}>{vaga?.titulo ?? vagaId}</Link>
          ) : (
            <span>{vaga?.titulo}</span>
          )}
          <span aria-hidden="true">/</span>
          <span aria-current="page" className="text-cora-ink">{candidato.nome}</span>
        </nav>

        {erroApi && <p className="m-0 rounded-lg border border-[#F6CFC5] bg-cora-coral-bg px-4 py-3 text-sm text-cora-coral-ink" role="alert">{erroApi}</p>}
        {aviso && <p className="m-0 rounded-lg border border-[#CDE6D5] bg-cora-ok-bg px-4 py-3 text-sm text-cora-ok-ink" role="status">{aviso}</p>}

        <section aria-label="Resumo da pessoa" className="flex flex-wrap items-center justify-between gap-5 rounded-xl border border-cora-line-2 bg-cora-surface px-6 py-[22px] shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
          <div className="flex min-w-0 items-center gap-4">
            <span aria-hidden="true" className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-cora-muted-bg text-lg font-semibold">{iniciais(candidato.nome)}</span>
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">{candidato.nome}</h1>
                {candidato.opt_out ? <Selo tom="coral">Pediu para sair</Selo> : candidato.autorizou_contato ? <Selo tom="ok">Autorizada</Selo> : <Selo tom="warn">Sem autorização</Selo>}
                {decisao && (
                  <Selo tom="neutral">
                    <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-cora-accent" />
                    {conviteAtual ? ROTULO_ESTADO_CONVITE[conviteAtual.estado] ?? conviteAtual.estado : ROTULO_DECISAO[decisao.tipo]}
                  </Selo>
                )}
                <SimuladoBadge exemplo_fixo={exemploFixo} simulado={candidato.simulado} />
              </div>
              <span className="break-words text-sm text-cora-muted [overflow-wrap:anywhere]">
                {[cargo, candidato.historico[0]?.empresa, email].filter(Boolean).join(" · ")}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-5">
            <div className="flex flex-col items-end">
              <span className="num text-[44px] font-bold leading-none tracking-[-0.04em] text-cora-primary">{nota100 ?? "—"}</span>
              <span className="mt-1 text-xs text-cora-placeholder">{vaga ? `nota para ${vaga.titulo}` : "nota para a vaga"}</span>
            </div>
            <a className="cora-btn cora-btn-outline h-10" href="#decisao-rh" onClick={() => setAba("visao")}>Registrar decisão do RH</a>
          </div>
        </section>

        <div aria-label="Seções da pessoa" className="flex gap-5 border-b border-cora-line" role="tablist">
          {([["visao", "Visão geral"], ["contato", `Contato${meusConvites.length ? ` (${meusConvites.length})` : ""}`]] as const).map(([valor, rotulo]) => (
            <button
              aria-selected={aba === valor}
              className={`-mb-px border-b-2 bg-transparent px-0.5 pb-2.5 pt-1 text-sm ${aba === valor ? "border-cora-primary font-semibold text-cora-ink" : "border-transparent font-medium text-cora-muted hover:text-cora-ink"}`}
              key={valor}
              onClick={() => setAba(valor)}
              role="tab"
              type="button"
            >
              {rotulo}
            </button>
          ))}
        </div>

        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex min-w-0 flex-col gap-5">
            {aba === "visao" ? (
              <>
                <section aria-labelledby="sec-nota" className="overflow-hidden rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
                  <div className="flex flex-wrap items-start justify-between gap-2.5 px-[22px] pb-3.5 pt-5">
                    <div className="flex flex-col gap-1">
                      <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-nota">Nota por critério</h2>
                      <p className="m-0 text-[13px] text-cora-muted">Eliminatórios não somam nota: ou atende, ou a pessoa é descartada. A nota é a média ponderada dos desejáveis.</p>
                    </div>
                    <Selo tom="neutral">Troca de nome e gênero: mesma nota</Selo>
                  </div>
                  {carregandoApi ? (
                    <p className="m-0 px-[22px] pb-5 text-cora-muted">Carregando a análise…</p>
                  ) : (
                    <>
                      <div className="border-y border-[#EDF1EE] bg-cora-row px-[22px] py-[9px] text-[13px] font-semibold">Eliminatórios</div>
                      {criterios.eliminatorios.length === 0 && <p className="m-0 px-[22px] py-3 text-[13px] text-cora-muted">A vaga não tem requisito eliminatório.</p>}
                      {criterios.eliminatorios.map((r, i) => (
                        <div className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-x-3.5 border-b border-cora-subtle px-[22px] py-3" key={r.id}>
                          <span className="font-mono text-xs text-cora-ink-2">E-{String(i + 1).padStart(2, "0")}</span>
                          <span className="font-medium">{r.descricao}</span>
                          {r.situacao === "atende" ? <Selo tom="ok">Atende</Selo> : r.situacao && r.situacao !== "sem_dado" ? <Selo tom="coral">Não atende</Selo> : <Selo tom="neutral">Sem dado</Selo>}
                        </div>
                      ))}
                      <div className="flex justify-between border-b border-[#EDF1EE] bg-cora-row px-[22px] py-[9px] text-[13px] font-semibold">
                        <span>Desejáveis</span>
                        <span className="font-medium text-cora-muted">nota de 0 a 100</span>
                      </div>
                      <div className="flex flex-col gap-3.5 px-[22px] pb-[18px] pt-3.5">
                        {criterios.desejaveis.map((d) => {
                          const valor = d.nota !== undefined ? Math.round(d.nota * 100) : undefined;
                          return (
                            <div className="grid grid-cols-[1fr_auto_36px] items-center gap-x-3 gap-y-1.5 sm:grid-cols-[minmax(110px,1fr)_64px_minmax(100px,2fr)_36px]" key={d.nome}>
                              <span className="min-w-0 font-medium">{d.nome}</span>
                              <span className="text-xs text-cora-muted">peso {d.peso}</span>
                              <span className="col-span-3 row-start-2 h-1.5 overflow-hidden rounded-[3px] bg-[#EDF1EE] sm:col-span-1 sm:row-start-auto">
                                <span className="block h-full rounded-[3px] bg-cora-accent" style={{ width: `${valor ?? 0}%` }} />
                              </span>
                              <span className="num col-start-3 row-start-1 text-right font-bold text-cora-primary sm:col-start-auto sm:row-start-auto">{valor ?? "—"}</span>
                            </div>
                          );
                        })}
                      </div>
                    </>
                  )}
                </section>

                <Cartao descricao="Trechos citados do perfil. Texto do perfil é dado, nunca instrução para a CORA." id="sec-evid" titulo="Evidências com fonte">
                  {(decisao?.evidencias ?? analise?.evidencias ?? []).length === 0 ? (
                    <p className="m-0 text-[13px] text-cora-muted">Nenhuma evidência registrada.</p>
                  ) : (
                    <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
                      {(decisao?.evidencias ?? analise?.evidencias ?? []).map((ev) => (
                        <li className="flex flex-col gap-2 rounded-[10px] border border-[#EDF1EE] bg-cora-row px-4 py-3.5" key={`${ev.criterio}-${ev.trecho}`}>
                          <span className="flex flex-wrap gap-1.5"><Etiqueta>{ev.criterio}</Etiqueta></span>
                          <q className="text-sm">{ev.trecho}</q>
                          <span className="text-xs text-cora-placeholder">Fonte: {ev.fonte}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Cartao>

                <section aria-labelledby="sec-lacunas" className="grid gap-5 rounded-xl border border-cora-line-2 bg-cora-surface px-[22px] py-5 shadow-[0_1px_2px_rgba(11,48,56,0.06)] sm:grid-cols-2">
                  <h2 className="sr-only" id="sec-lacunas">Lacunas e pontos a aprofundar</h2>
                  <div className="flex flex-col gap-2.5">
                    <span className="text-[15px] font-semibold">Lacunas</span>
                    {lacunas.length ? <ul className="m-0 flex flex-col gap-1.5 pl-[18px] text-cora-ink-2">{lacunas.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="m-0 text-[13px] text-cora-muted">{usaApi && !pacote ? "Aparecem quando a pessoa é entregue ao recrutador." : "Nenhuma lacuna registrada."}</p>}
                  </div>
                  <div className="flex flex-col gap-2.5">
                    <span className="text-[15px] font-semibold">Para a Nara aprofundar</span>
                    {aprofundar.length ? <ul className="m-0 flex flex-col gap-1.5 pl-[18px] text-cora-ink-2">{aprofundar.map((p) => <li key={p}>{p}</li>)}</ul> : <p className="m-0 text-[13px] text-cora-muted">Nenhum ponto registrado.</p>}
                  </div>
                  {alertas.length > 0 && (
                    <p className="m-0 rounded-[10px] border border-[#F1D58A] bg-[#FFF8E3] px-3.5 py-3 text-[13px] text-[#6B4A0C] sm:col-span-2">{alertas.join(" ")}</p>
                  )}
                </section>

                <Cartao descricao={candidato.perfil_texto} id="sec-historico" titulo="Experiência">
                  <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
                    {candidato.historico.map((item) => (
                      <li className="rounded-[10px] border border-[#EDF1EE] bg-cora-row px-4 py-3" key={`${item.empresa}-${item.cargo}-${item.inicio}`}>
                        <span className="font-semibold">{item.cargo}</span> <span className="text-cora-muted">· {item.empresa} · {data(item.inicio)} até {item.fim ? data(item.fim) : "hoje"}</span>
                        <p className="m-0 mt-1 text-[13px] text-cora-ink-2">{item.descricao}</p>
                      </li>
                    ))}
                  </ul>
                </Cartao>
              </>
            ) : (
              <Cartao descricao="Convites enviados e respostas. Mensagens e envios são simulados na demonstração." id="sec-contato" titulo="Histórico de contato">
                {!usaApi ? (
                  <p className="m-0 text-[13px] text-cora-muted">Os convites aparecem quando a pessoa é vista dentro de uma vaga.</p>
                ) : meusConvites.length === 0 ? (
                  <p className="m-0 text-[13px] text-cora-muted">Nenhum convite para esta pessoa nesta vaga.</p>
                ) : (
                  meusConvites.map((convite) => (
                    <div className="flex flex-col gap-3" key={convite.id}>
                      <div className="overflow-hidden rounded-[10px] border border-cora-line-2">
                        <div className="flex flex-col gap-0.5 border-b border-[#EDF1EE] bg-cora-row px-4 py-3 text-[13px]">
                          <span className="flex flex-wrap justify-between gap-2"><span><b>CORA</b>, por {convite.canal === "email" ? "e-mail" : convite.canal}</span><Selo tom="neutral">{ROTULO_ESTADO_CONVITE[convite.estado] ?? convite.estado}</Selo></span>
                          <span className="text-cora-muted">Para: {email ?? candidato.nome} · Tentativa {convite.tentativa}{vaga ? ` de ${vaga.max_tentativas_contato}` : ""}</span>
                        </div>
                        <p className="m-0 px-4 py-3.5 text-sm text-cora-ink-2">{convite.mensagem}</p>
                        {convite.link_destino && <p className="m-0 px-4 pb-3.5 text-xs text-cora-muted">Link da Nara (simulado): <span className="font-mono">{convite.link_destino}</span></p>}
                      </div>
                      {convite.duvidas.map((d) => (
                        <div className="flex flex-col gap-2" key={`${d.momento}-${d.pergunta}`}>
                          <div className="flex max-w-[80%] flex-col gap-1 self-end rounded-[10px] border border-cora-line-2 bg-cora-bg px-4 py-3">
                            <span className="text-xs text-cora-muted">{candidato.nome} perguntou</span>
                            <span className="text-sm">{d.pergunta}</span>
                          </div>
                          <div className="flex max-w-[80%] flex-col gap-1 rounded-[10px] border border-cora-line-2 bg-cora-surface px-4 py-3">
                            <span className="text-xs text-cora-muted">{d.encaminhada_a_pessoa ? `Encaminhada a ${RESPONSAVEL_RH}, do RH` : "CORA respondeu"}</span>
                            <span className="text-sm">{d.resposta ?? "Aguardando resposta de uma pessoa do RH."}</span>
                          </div>
                        </div>
                      ))}
                      {convite.retorno && (
                        <p className="m-0 rounded-[10px] border border-cora-line-2 bg-cora-row px-4 py-3 text-sm">Retorno da entrevista: {convite.retorno.mensagem}</p>
                      )}
                      <button className="cora-btn cora-btn-outline self-start" onClick={() => responder(convite.id)} type="button">Registrar resposta simulada</button>
                    </div>
                  ))
                )}
                {conversas.map((conversa) => (
                  <div className="flex flex-col gap-2 rounded-[10px] bg-[#F3F6F4] p-3.5" key={conversa.codigo}>
                    <span className="text-xs font-semibold text-cora-ink-2">WhatsApp · {conversa.numero_mascarado}{conversa.simulado ? " · simulado" : ""}</span>
                    {conversa.mensagens.map((m) => (
                      <div className={`flex max-w-[80%] flex-col gap-0.5 ${m.direcao === "saida" ? "self-start" : "self-end items-end"}`} key={m.id}>
                        <span className={`rounded-[10px] px-3 py-2 text-sm ${m.direcao === "saida" ? "bg-cora-surface" : "bg-[#DCF3E3]"}`}>{m.texto}</span>
                        <span className="num text-[11px] text-cora-muted">{new Date(m.momento).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
                      </div>
                    ))}
                  </div>
                ))}
                <p className="m-0 flex items-start gap-2.5 rounded-[10px] border border-[#F1D58A] bg-[#FFF8E3] px-3.5 py-3 text-[13px] text-[#6B4A0C]">
                  Dúvidas fora do material da vaga vão para uma pessoa do RH. O horário da entrevista quem marca é a Nara.
                </p>
              </Cartao>
            )}
          </div>

          <aside aria-label="Situação e entrega" className="flex min-w-0 flex-col gap-5">
            <Cartao id="sec-situacao" titulo="Situação e autorização">
              <dl className="m-0 flex flex-col gap-2.5 text-[13px]">
                {([
                  ["Situação", ROTULO_ESTADO_BANCO[candidato.estado] ?? candidato.estado],
                  ["Contato", candidato.opt_out ? "Pediu para sair" : candidato.autorizou_contato ? "Autorizado" : "Sem autorização"],
                  ["Válida até", data(candidato.autorizacao_valida_ate)],
                  ["Origem", `${candidato.fonte} (${candidato.origem})`],
                  ["Atualizado em", data(candidato.atualizado_em)],
                ] as const).map(([rotulo, valor]) => (
                  <div className="flex justify-between gap-3" key={rotulo}>
                    <dt className="text-cora-muted">{rotulo}</dt>
                    <dd className="m-0 text-right font-medium">{valor}</dd>
                  </div>
                ))}
              </dl>
            </Cartao>

            <Cartao id="decisao-rh" titulo="Decisão registrada">
              {carregandoApi ? (
                <p className="m-0 text-[13px] text-cora-muted">Carregando decisão…</p>
              ) : decisao ? (
                <>
                  <p className="m-0 text-[13px] text-cora-ink-2"><b>{ROTULO_DECISAO[decisao.tipo]}.</b> {decisao.motivo}</p>
                  <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
                    <dt className="text-cora-muted">Regra</dt><dd className="m-0 break-all font-mono">{decisao.regra}</dd>
                    <dt className="text-cora-muted">Responsável</dt><dd className="m-0 break-words">{decisao.responsavel.startsWith("agente:") ? "CORA, dentro do mandato" : decisao.responsavel}</dd>
                    <dt className="text-cora-muted">Rastro</dt><dd className="m-0 truncate font-mono" title={decisao.rastro_id}>{decisao.rastro_id}</dd>
                  </dl>
                </>
              ) : (
                <p className="m-0 text-[13px] text-cora-muted">Ainda não há decisão registrada.</p>
              )}

              <div className="flex flex-col gap-2.5 border-t border-cora-line pt-3.5">
                <p className="m-0 text-xs text-cora-muted">Decisões sobre pessoas ficam com humanos. Cada ação é registrada no nome de {RESPONSAVEL_RH}, do RH.</p>
                {(!usaApi || decisao?.tipo === "pedir_humano") && (
                  <>
                    {usaApi && (
                      <label className="flex flex-col gap-1">
                        <span className="cora-label">Motivo da revisão</span>
                        <textarea className="cora-input" onChange={(e) => setMotivoRevisao(e.target.value)} rows={2} value={motivoRevisao} />
                      </label>
                    )}
                    <div className="flex flex-wrap gap-2">
                      <button className="cora-btn cora-btn-primary" disabled={enviando} onClick={() => revisar("indicar")} type="button">Aprovar indicação</button>
                      <button className="cora-btn cora-btn-outline" disabled={enviando} onClick={() => revisar("descartar")} type="button">Descartar</button>
                    </div>
                  </>
                )}
                {usaApi && decisao && decisao.tipo !== "pedir_humano" && (
                  <>
                    <label className="flex flex-col gap-1">
                      <span className="cora-label">Devolver à fila humana</span>
                      <textarea className="cora-input" onChange={(e) => setMotivoReversao(e.target.value)} placeholder="Por que a decisão da CORA deve ser revista?" rows={2} value={motivoReversao} />
                    </label>
                    <button className="cora-btn cora-btn-outline self-start" disabled={enviando || !motivoReversao.trim()} onClick={reverter} type="button">Reverter decisão</button>
                  </>
                )}
              </div>
            </Cartao>

            {usaApi && (
              <Cartao descricao="Para onde a pessoa vai depois desta vaga. Quem decide é o RH, nunca a CORA." id="sec-destino" titulo="Destino da pessoa">
                <div className="flex flex-wrap gap-2">
                  {(Object.keys(ROTULO_DESTINO) as DestinoPessoa[]).map((valor) => (
                    <button
                      aria-pressed={destino === valor}
                      className={`cora-btn ${destino === valor ? "cora-btn-primary" : "cora-btn-outline"}`}
                      disabled={enviando}
                      key={valor}
                      onClick={() => definirDestino(valor)}
                      type="button"
                    >
                      {ROTULO_DESTINO[valor]}
                    </button>
                  ))}
                </div>
                <p className="m-0 text-xs text-cora-muted">{destino ? `Destino atual: ${ROTULO_DESTINO[destino as DestinoPessoa] ?? destino}.` : "Nenhum destino registrado."}</p>
              </Cartao>
            )}

            <Cartao descricao="A entrevista é conduzida pela Nara (simulada); a CORA não agenda reuniões." id="sec-etapas" titulo="Etapas">
              <ol className="m-0 flex list-none flex-col gap-3 p-0 text-[13px]">
                {etapas.map(([rotulo, feita]) => (
                  <li className={`flex items-center gap-2.5 ${feita ? "" : "text-cora-placeholder"}`} key={rotulo}>
                    <span aria-hidden="true" className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${feita ? "bg-cora-ok-bg text-cora-ok-ink" : "border border-cora-line-2 bg-cora-surface"}`}>
                      {feita && <svg fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 16 16" width="12"><path d="m3.5 8.5 3 3 6-7" /></svg>}
                    </span>
                    {rotulo}
                    <span className="sr-only">{feita ? ", concluída" : ", pendente"}</span>
                  </li>
                ))}
              </ol>
              {resultado && (
                <dl className="m-0 flex flex-wrap gap-2 text-xs">
                  {Object.entries(resultado.notas).map(([nome, n]) => <div className="rounded-md bg-cora-muted-bg px-2 py-1" key={nome}>{nome}: {n}</div>)}
                </dl>
              )}
            </Cartao>
          </aside>
        </div>
      </AppMain>
    </div>
  );
}
