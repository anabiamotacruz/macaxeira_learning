"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader, AppMain } from "../../components/AppHeader";
import { SimuladoBadge } from "../../components/SimuladoBadge";
import { ApiError, listarPessoasDoBanco, modoReservaAtivo, type PessoaDoBanco } from "../../lib/api";
import { candidatosIniciais, decisoesIniciais, vagasIniciais } from "../../lib/dados";
import type { Candidato, EstadoBanco, TipoDecisao } from "../../lib/tipos";

const EMPRESA_ID = process.env.NEXT_PUBLIC_EMPRESA_ID || "empresa-exemplo";
const POR_PAGINA = 8;
const DIA_MS = 24 * 60 * 60 * 1000;

type Filtro = "todas" | "autorizada" | "aguardando" | "fora";

const ABAS: Array<{ id: Filtro; rotulo: string; explicacao: string }> = [
  { id: "todas", rotulo: "Todas", explicacao: "Todas as pessoas do banco desta empresa, com a situação de cada uma." },
  { id: "autorizada", rotulo: "Autorizadas", explicacao: "Autorizaram o contato e a autorização está válida: a CORA pode analisar e convidar." },
  { id: "aguardando", rotulo: "Aguardando", explicacao: "Ainda não autorizaram. Recebem só o pedido de autorização, nunca a vaga." },
  { id: "fora", rotulo: "Fora da busca", explicacao: "Autorização vencida, pedido de remoção ou perfil removido: não entram em nenhuma busca." },
];

const ROTULO_ESTADO: Record<EstadoBanco, string> = {
  ativo: "Ativo",
  pendente: "Pendente",
  desatualizado: "Desatualizado",
  expirado: "Autorização vencida",
  removido: "Removido",
};

const ROTULO_DECISAO: Record<TipoDecisao, string> = {
  indicar: "Indicada",
  descartar: "Descartada",
  pedir_humano: "Aguarda revisão humana",
};

// Só no modo reserva (NEXT_PUBLIC_MODO_RESERVA=true), identificado na tela.
function pessoasDeReserva(): PessoaDoBanco[] {
  return candidatosIniciais.map((candidato) => ({
    candidato,
    vagaId: vagasIniciais[0].id,
    vagaTitulo: vagasIniciais[0].titulo,
    decisao: decisoesIniciais.find((decisao) => decisao.candidato_id === candidato.id)?.tipo ?? null,
    nota: null,
    simulado: true,
  }));
}

function situacao(c: Candidato): Exclude<Filtro, "todas"> {
  if (c.opt_out || c.estado === "removido" || c.estado === "expirado") return "fora";
  return c.autorizou_contato ? "autorizada" : "aguardando";
}

function iniciais(nome: string): string {
  return nome
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

function data(iso: string | null): string {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

function chipSituacao(c: Candidato) {
  const s = situacao(c);
  if (s === "autorizada") return <span className="cora-chip cora-chip-ok">Autorizada</span>;
  if (s === "aguardando") return <span className="cora-chip cora-chip-warn">Aguardando autorização</span>;
  return <span className="cora-chip cora-chip-coral">{c.opt_out ? "Pediu remoção" : ROTULO_ESTADO[c.estado]}</span>;
}

export default function BancoPage() {
  const reserva = modoReservaAtivo();
  const [pessoas, setPessoas] = useState<PessoaDoBanco[]>(() => (reserva ? pessoasDeReserva() : []));
  const [carregando, setCarregando] = useState(!reserva);
  const [erro, setErro] = useState("");
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [estado, setEstado] = useState<EstadoBanco | "todos">("todos");
  const [pagina, setPagina] = useState(1);

  useEffect(() => {
    if (reserva) return;
    let ativo = true;
    listarPessoasDoBanco()
      .then((lista) => {
        if (ativo) setPessoas(lista);
      })
      .catch((erroApi) => {
        if (ativo) setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar o banco de talentos.");
      })
      .finally(() => {
        if (ativo) setCarregando(false);
      });
    return () => {
      ativo = false;
    };
  }, [reserva]);

  const candidatos = useMemo(() => pessoas.map((p) => p.candidato), [pessoas]);
  const temSimulado = reserva || pessoas.some((p) => p.simulado);

  const contagem = useMemo(() => {
    const base: Record<Filtro, number> = { todas: candidatos.length, autorizada: 0, aguardando: 0, fora: 0 };
    for (const c of candidatos) base[situacao(c)] += 1;
    return base;
  }, [candidatos]);

  const filtrados = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return pessoas.filter(({ candidato: c }) => {
      const combinaBusca =
        !termo ||
        c.nome.toLowerCase().includes(termo) ||
        Object.keys(c.atributos).some((k) => k.toLowerCase().includes(termo));
      return (
        combinaBusca &&
        (filtro === "todas" || situacao(c) === filtro) &&
        (estado === "todos" || c.estado === estado)
      );
    });
  }, [busca, filtro, estado, pessoas]);

  const totalPaginas = Math.max(1, Math.ceil(filtrados.length / POR_PAGINA));
  const paginaAtual = Math.min(pagina, totalPaginas);
  const visiveis = filtrados.slice((paginaAtual - 1) * POR_PAGINA, paginaAtual * POR_PAGINA);

  const remocoes = candidatos.filter((c) => c.opt_out || c.estado === "removido");
  const hoje = new Date("2026-11-08").getTime();
  const vencendo = candidatos.filter((c) => {
    if (!c.autorizacao_valida_ate || !c.autorizou_contato) return false;
    const fim = new Date(c.autorizacao_valida_ate).getTime();
    return fim >= hoje && fim - hoje <= 30 * DIA_MS;
  });
  const vencidas = candidatos.filter((c) => c.estado === "expirado");

  const explicacao = ABAS.find((a) => a.id === filtro)?.explicacao ?? "";

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader ativo="banco" />
      <AppMain>
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">Banco de talentos</h1>
              {temSimulado && <span className="cora-chip cora-chip-warn font-semibold">Dados sintéticos</span>}
            </div>
            <p className="m-0 text-[15px] text-cora-muted">
              As pessoas da empresa, de onde cada uma veio e o que a CORA pode fazer com ela.
            </p>
          </div>
        </div>

        {reserva && (
          <p className="rounded-lg border border-[#f1c36a] bg-[#fff7df] px-4 py-3 text-sm text-[#805d16]">Dados locais de reserva</p>
        )}
        {erro && (
          <p className="m-0 rounded-xl border border-[#F6CFC5] bg-cora-coral-bg px-4 py-3 text-[13px] text-cora-coral-ink" role="alert">{erro}</p>
        )}
        <p className="rounded-lg border border-cora-line-2 bg-cora-muted-bg px-4 py-3 text-[13px] text-cora-ink-2">
          As pessoas que apareceram nas vagas desta empresa, sem repetição, com a última decisão da CORA e a nota.
        </p>

        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <section aria-label="Pessoas do banco" className="overflow-hidden rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
            <div className="flex flex-col gap-3.5 border-b border-[#edf1ee] px-[18px] py-4">
              <div aria-label="Situação" className="inline-flex flex-wrap gap-0.5 self-start rounded-[10px] bg-[#eaf0ec] p-1" role="tablist">
                {ABAS.map((aba) => {
                  const sel = filtro === aba.id;
                  return (
                    <button
                      aria-selected={sel}
                      className={`h-8 rounded-lg px-3 text-[13px] ${sel ? "bg-cora-surface font-semibold text-cora-ink shadow-[0_1px_2px_rgba(11,48,56,0.08)]" : "font-medium text-cora-ink-2 hover:bg-white/60"}`}
                      key={aba.id}
                      onClick={() => {
                        setFiltro(aba.id);
                        setPagina(1);
                      }}
                      role="tab"
                      type="button"
                    >
                      {aba.rotulo} <span className="num text-xs font-medium text-cora-muted">{contagem[aba.id]}</span>
                    </button>
                  );
                })}
              </div>
              <p className="m-0 text-[13px] text-cora-ink-2">{explicacao}</p>
              <div className="flex flex-wrap gap-3">
                <label className="flex h-[38px] flex-[2_1_240px] items-center gap-2.5 rounded-lg border border-cora-line-2 px-3 text-cora-muted">
                  <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="15"><circle cx="7" cy="7" r="4.3" /><path d="m10.4 10.4 3.1 3.1" /></svg>
                  <span className="sr-only">Buscar por nome ou competência</span>
                  <input
                    className="min-w-0 flex-1 border-0 bg-transparent text-sm text-cora-ink outline-none"
                    onChange={(e) => {
                      setBusca(e.target.value);
                      setPagina(1);
                    }}
                    placeholder="Buscar por nome ou competência"
                    type="search"
                    value={busca}
                  />
                </label>
                <label className="flex flex-[1_1_200px] items-center gap-2 text-[13px] text-cora-muted">
                  Estado
                  <select
                    className="h-[38px] flex-1 rounded-lg border border-cora-line-2 bg-cora-surface px-2.5 text-sm text-cora-ink"
                    onChange={(e) => {
                      setEstado(e.target.value as EstadoBanco | "todos");
                      setPagina(1);
                    }}
                    value={estado}
                  >
                    <option value="todos">Todos os estados</option>
                    {(Object.keys(ROTULO_ESTADO) as EstadoBanco[]).map((e) => (
                      <option key={e} value={e}>{ROTULO_ESTADO[e]}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="overflow-x-auto">
              <div aria-label="Pessoas" className="min-w-[820px]" role="table">
                <div className="grid grid-cols-[1.5fr_1.5fr_1.3fr_1.3fr_1.1fr_0.6fr] gap-3.5 border-b border-[#edf1ee] bg-cora-row px-[18px] py-2.5 text-xs font-medium text-cora-placeholder" role="row">
                  <span role="columnheader">Pessoa</span>
                  <span role="columnheader">Situação</span>
                  <span role="columnheader">Última decisão</span>
                  <span role="columnheader">Origem</span>
                  <span role="columnheader">Autorização</span>
                  <span role="columnheader">Competências</span>
                </div>
                {carregando ? (
                  <p className="px-[18px] py-8 text-center text-sm text-cora-muted">Carregando o banco de talentos…</p>
                ) : visiveis.length === 0 ? (
                  <p className="px-[18px] py-8 text-center text-sm text-cora-muted">
                    {pessoas.length === 0 ? "Nenhuma pessoa nas vagas desta empresa ainda." : "Nenhuma pessoa encontrada com esses filtros."}
                  </p>
                ) : (
                  visiveis.map(({ candidato: c, vagaId, vagaTitulo, decisao, nota, simulado }) => {
                    const fora = situacao(c) === "fora";
                    return (
                      <div className="cora-row grid grid-cols-[1.5fr_1.5fr_1.3fr_1.3fr_1.1fr_0.6fr] items-center gap-3.5 border-b border-cora-subtle px-[18px] py-3 text-[13px]" key={c.id} role="row">
                        <span className="flex min-w-0 items-center gap-2.5" role="cell">
                          <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-cora-muted-bg text-xs font-semibold text-cora-ink">{iniciais(c.nome)}</span>
                          <span className="flex min-w-0 flex-col">
                            <Link className="truncate font-semibold text-cora-ink no-underline hover:text-cora-primary" href={`/candidatos/${encodeURIComponent(c.id)}?vaga=${encodeURIComponent(vagaId)}`}>{c.nome}</Link>
                            <span className="truncate text-xs text-cora-placeholder">{c.historico.at(-1)?.cargo ?? "Experiência não informada"}</span>
                          </span>
                        </span>
                        <span className="flex flex-col items-start gap-1" role="cell">
                          {chipSituacao(c)}
                          {fora && <span className="text-xs text-cora-coral-ink">Sai da busca e não recebe contato</span>}
                        </span>
                        <span className="flex flex-col" role="cell">
                          <span className="font-medium">{decisao ? ROTULO_DECISAO[decisao] : "Sem decisão"}</span>
                          <span className="num truncate text-xs text-cora-placeholder" title={vagaTitulo}>
                            {nota !== null ? `nota ${nota.toFixed(2)} · ` : ""}{vagaTitulo}
                          </span>
                        </span>
                        <span className="flex flex-col items-start gap-1" role="cell">
                          <span className="flex items-center gap-1.5">
                            <span className="capitalize">{c.fonte}</span>
                            {simulado ? <SimuladoBadge simulado /> : <span className="cora-chip cora-chip-ok">Real</span>}
                          </span>
                          <span className="text-xs text-cora-placeholder">{c.origem}</span>
                          <span className="num text-xs text-cora-placeholder">atualizado {data(c.atualizado_em)}</span>
                        </span>
                        <span className={`num ${c.estado === "expirado" ? "font-semibold text-cora-coral-ink" : c.autorizou_contato ? "text-cora-ink-2" : "text-cora-warn-ink"}`} role="cell">
                          {c.autorizou_contato ? `até ${data(c.autorizacao_valida_ate)}` : "Não autorizada"}
                        </span>
                        <span className="truncate font-mono text-xs text-cora-muted" role="cell" title={Object.keys(c.atributos).join(", ")}>
                          {Object.keys(c.atributos).slice(0, 2).join(", ")}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2.5 px-[18px] py-3 text-[13px] text-cora-muted">
              <span className="num">
                {filtrados.length === 0
                  ? "0 pessoas"
                  : `${(paginaAtual - 1) * POR_PAGINA + 1}–${Math.min(paginaAtual * POR_PAGINA, filtrados.length)} de ${filtrados.length} pessoas`}
              </span>
              <div className="flex gap-2">
                <button className="cora-btn cora-btn-outline !h-8 !px-3 text-[13px]" disabled={paginaAtual <= 1} onClick={() => setPagina(paginaAtual - 1)} type="button">Anterior</button>
                <button className="cora-btn cora-btn-outline !h-8 !px-3 text-[13px]" disabled={paginaAtual >= totalPaginas} onClick={() => setPagina(paginaAtual + 1)} type="button">Próxima</button>
              </div>
            </div>
          </section>

          <aside aria-label="Privacidade" className="flex min-w-0 flex-col gap-4">
            <section aria-labelledby="sec-remocao" className="flex flex-col gap-3 rounded-xl border border-cora-line-2 bg-cora-surface p-[18px] shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
              <div className="flex items-center justify-between gap-2.5">
                <h2 className="m-0 text-base font-semibold tracking-[-0.02em]" id="sec-remocao">Pedidos de remoção</h2>
                <span className="cora-chip cora-chip-warn num font-semibold">{remocoes.length} {remocoes.length === 1 ? "pedido" : "pedidos"}</span>
              </div>
              <p className="m-0 text-[13px] text-cora-muted">Quem pede remoção sai da busca na hora e não recebe novo contato.</p>
              {remocoes.length === 0 ? (
                <p className="m-0 rounded-[10px] border border-[#edf1ee] bg-cora-row p-3 text-[13px] text-cora-muted">Nenhum pedido de remoção nesta base.</p>
              ) : (
                remocoes.map((c) => (
                  <div className="flex flex-col gap-1.5 rounded-[10px] border border-[#edf1ee] bg-cora-row p-3" key={c.id}>
                    <span className="flex justify-between gap-2">
                      <span className="font-semibold">{c.nome}</span>
                      <span className="cora-chip cora-chip-ok font-semibold">{c.estado === "removido" ? "Removido" : "Fora da busca"}</span>
                    </span>
                  </div>
                ))
              )}
            </section>

            <section aria-labelledby="sec-validade" className="flex flex-col gap-3 rounded-xl border border-cora-line-2 bg-cora-surface p-[18px] shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
              <h2 className="m-0 text-base font-semibold tracking-[-0.02em]" id="sec-validade">Autorizações vencendo</h2>
              <p className="m-0 text-[13px] text-cora-muted">Autorização vencida tira a pessoa da busca. Estas vencem nos próximos 30 dias.</p>
              {vencendo.length === 0 ? (
                <p className="m-0 text-[13px] text-cora-ink-2">Nenhuma autorização vence nos próximos 30 dias.</p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[13px]">
                  {vencendo.map((c) => (
                    <li className="flex justify-between gap-2.5" key={c.id}>
                      <span>{c.nome}</span>
                      <span className="num font-semibold text-cora-warn-ink">{data(c.autorizacao_valida_ate)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {vencidas.length > 0 && (
                <>
                  <h3 className="m-0 mt-1 text-[13px] font-semibold">Já vencidas</h3>
                  <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[13px]">
                    {vencidas.map((c) => (
                      <li className="flex justify-between gap-2.5" key={c.id}>
                        <span>{c.nome}</span>
                        <span className="num font-semibold text-cora-coral-ink">{data(c.autorizacao_valida_ate)}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>

            <section aria-labelledby="sec-isolado" className="flex flex-col gap-2 rounded-xl border border-cora-line-2 bg-cora-muted-bg p-[18px]">
              <h2 className="m-0 text-sm font-semibold" id="sec-isolado">Banco só desta empresa</h2>
              <p className="m-0 text-[13px] text-cora-ink-2">Nenhuma pessoa daqui aparece para outra empresa, nem a CORA cruza bancos.</p>
              <span className="font-mono text-xs text-cora-ink-2">empresa_id {EMPRESA_ID}</span>
            </section>
          </aside>
        </div>
      </AppMain>
    </div>
  );
}
