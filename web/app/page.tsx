"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppHeader, AppMain } from "../components/AppHeader";
import { SimuladoBadge } from "../components/SimuladoBadge";
import { ApiError, listarPacotesEntregues, listarVagas, modoReservaAtivo, obterResumo, type ResumoVaga } from "../lib/api";
import { vagasIniciais } from "../lib/dados";
import type { EstadoVaga, Vaga } from "../lib/tipos";

const REVISOR = "Ana Ribeiro";

type Grupo = "buscando" | "concluida" | "rascunho";
type Filtro = "todas" | Grupo;

type Linha = { vaga: Vaga; estado: EstadoVaga; resumo: ResumoVaga | null; entregues: number | null };

const FILTROS: Array<[Filtro, string]> = [
  ["todas", "Todas"],
  ["buscando", "Buscando"],
  ["concluida", "Concluídas"],
  ["rascunho", "Rascunhos"],
];

const GRADE = "grid-cols-[minmax(280px,2.4fr)_1.3fr_1fr_1.5fr_0.7fr_0.8fr_36px]";

function grupoDoEstado(estado: EstadoVaga): Grupo {
  if (estado === "concluida") return "concluida";
  if (estado === "rascunho" || estado === "aguardando_mandato") return "rascunho";
  return "buscando";
}

function rotuloDoEstado(estado: EstadoVaga): string {
  if (estado === "concluida") return "Concluída";
  if (estado === "rascunho") return "Rascunho";
  if (estado === "aguardando_mandato") return "Aguarda mandato";
  if (estado === "pausada") return "Pausada";
  return "Buscando";
}

function estiloDoEstado(estado: EstadoVaga): string {
  const grupo = grupoDoEstado(estado);
  if (grupo === "concluida") return "border-[#CDE6D5] bg-cora-ok-bg text-cora-ok-ink";
  if (grupo === "rascunho" || estado === "pausada") return "border-[#F1D58A] bg-cora-warn-bg text-cora-warn-ink";
  return "border-cora-line-2 bg-cora-muted-bg text-cora-ink-2";
}

function progresso({ vaga, estado, resumo, entregues }: Linha): { pct: number; texto: string } {
  if (estado === "rascunho") return { pct: 0, texto: "Critérios aguardam sua aprovação" };
  if (estado === "aguardando_mandato") return { pct: 0, texto: "Mandato aguarda assinatura" };
  if (!resumo || entregues === null) return { pct: 0, texto: "Resumo indisponível" };
  const meta = Math.max(vaga.meta_candidatos, 1);
  const pct = Math.min(100, Math.round((entregues / meta) * 100));
  return { pct, texto: `${entregues} de ${vaga.meta_candidatos} entregues · ${resumo.indicados} indicadas` };
}

function IconeMaleta() {
  return (
    <svg aria-hidden="true" fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 16 16" width="18">
      <rect height="8" rx="1.5" width="13" x="1.5" y="5" />
      <path d="M5.5 5V3.8a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V5M1.5 8.5h13" />
    </svg>
  );
}

export default function Home() {
  const [linhas, setLinhas] = useState<Linha[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [filtroAberto, setFiltroAberto] = useState(false);

  useEffect(() => {
    let ativo = true;
    async function carregar() {
      try {
        if (modoReservaAtivo()) {
          if (ativo) {
            setLinhas(
              vagasIniciais.map((vaga) => ({ vaga, estado: vaga.aprovada ? "buscando" : "rascunho", resumo: null, entregues: null })),
            );
          }
          return;
        }
        const respostas = await listarVagas();
        const comResumo = await Promise.all(
          respostas.map(async (r) => {
            let resumo: ResumoVaga | null = null;
            let entregues: number | null = null;
            try {
              resumo = await obterResumo(r.vaga.id);
              // Entregue é quem aceitou e teve o pacote passado ao recrutador, não só quem foi indicado.
              entregues = (await listarPacotesEntregues(r.vaga.id)).length;
            } catch {
              // Sem resumo, a linha mostra a vaga e o estado; os números ficam como indisponíveis.
            }
            return { vaga: r.vaga, estado: resumo?.estado ?? r.estado, resumo, entregues };
          }),
        );
        if (ativo) setLinhas(comResumo);
      } catch (erroApi) {
        if (ativo) setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar as vagas.");
      } finally {
        if (ativo) setCarregando(false);
      }
    }
    void carregar();
    return () => {
      ativo = false;
    };
  }, []);

  const totais = useMemo(() => {
    const buscando = linhas.filter((l) => grupoDoEstado(l.estado) === "buscando");
    return {
      buscando: buscando.length,
      rascunhos: linhas.filter((l) => grupoDoEstado(l.estado) === "rascunho").length,
      perfis: buscando.reduce((s, l) => s + (l.resumo?.analisados ?? 0), 0),
      fila: linhas.reduce((s, l) => s + (l.resumo?.na_fila_humana ?? 0), 0),
      entregues: buscando.reduce((s, l) => s + (l.entregues ?? 0), 0),
      metas: buscando.reduce((s, l) => s + l.vaga.meta_candidatos, 0),
      porGrupo: {
        todas: linhas.length,
        buscando: buscando.length,
        concluida: linhas.filter((l) => grupoDoEstado(l.estado) === "concluida").length,
        rascunho: linhas.filter((l) => grupoDoEstado(l.estado) === "rascunho").length,
      } as Record<Filtro, number>,
    };
  }, [linhas]);

  const visiveis = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return linhas.filter(
      (l) =>
        (filtro === "todas" || grupoDoEstado(l.estado) === filtro) &&
        (!termo || l.vaga.titulo.toLowerCase().includes(termo) || l.vaga.descricao.toLowerCase().includes(termo)),
    );
  }, [busca, filtro, linhas]);

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader aoBuscar={setBusca} ativo="vagas" />
      <AppMain>
        {modoReservaAtivo() && (
          <p className="rounded-lg border border-[#f1c36a] bg-[#fff7df] px-4 py-3 text-sm text-[#805d16]">
            Dados locais de reserva
          </p>
        )}
        {erro && (
          <p className="rounded-lg border border-[#f0b5aa] bg-cora-coral-bg px-4 py-3 text-sm text-cora-coral-ink" role="alert">
            {erro}
          </p>
        )}

        <div className="flex flex-wrap items-end justify-between gap-5">
          <div className="flex min-w-0 flex-col gap-1.5">
            <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">Vagas</h1>
            <p className="m-0 text-[15px] text-cora-muted">Acompanhe as buscas da sua empresa e o quanto falta para cada meta.</p>
          </div>
          <Link className="cora-btn cora-btn-outline" href="/vagas/modelos">
            Criar a partir de um modelo
          </Link>
        </div>

        <section aria-label="Resumo" className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-3">
          <Metrica
            legenda={`${totais.rascunhos} rascunho(s) aguardam aprovação dos critérios`}
            rotulo="Vagas buscando"
            valor={String(totais.buscando)}
          />
          <Metrica legenda="nas vagas buscando, cada um com a origem" rotulo="Perfis encontrados" valor={String(totais.perfis)} />
          <Metrica legenda="decisões esperando revisão humana" rotulo="Aguardando autorização" valor={String(totais.fila)} />
          <Metrica
            complemento={`de ${totais.metas}`}
            legenda="soma das metas das vagas buscando"
            rotulo="Entregues ao recrutador"
            valor={String(totais.entregues)}
          />
        </section>

        <section aria-label="Vagas" className="overflow-hidden rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
          <div className="flex flex-wrap items-center gap-3 border-b border-[#EDF1EE] px-4 py-3.5">
            <div aria-label="Filtrar por status" className="inline-flex flex-wrap gap-0.5 rounded-[9px] bg-[#EAF0EC] p-[3px]" role="tablist">
              {FILTROS.map(([chave, rotulo]) => {
                const ativo = filtro === chave;
                return (
                  <button
                    aria-selected={ativo}
                    className={`inline-flex h-8 items-center gap-1.5 rounded-[7px] border-0 px-3 text-[13px] ${
                      ativo ? "bg-cora-surface font-semibold text-cora-ink shadow-[0_1px_2px_rgba(11,48,56,0.1)]" : "bg-transparent font-medium text-cora-muted"
                    }`}
                    key={chave}
                    onClick={() => setFiltro(chave)}
                    role="tab"
                    type="button"
                  >
                    {rotulo} <span className="num text-xs font-medium text-cora-muted">{totais.porGrupo[chave]}</span>
                  </button>
                );
              })}
            </div>
            <label className="flex h-[38px] flex-[1_1_240px] items-center gap-2.5 rounded-lg border border-cora-line-2 px-3 text-cora-muted">
              <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="15"><circle cx="7" cy="7" r="4.3" /><path d="m10.4 10.4 3.1 3.1" /></svg>
              <span className="sr-only">Buscar por vaga</span>
              <input
                className="min-w-0 flex-1 border-0 bg-transparent text-sm text-cora-ink outline-none"
                onChange={(e) => setBusca(e.target.value)}
                placeholder="Buscar por vaga"
                type="search"
                value={busca}
              />
            </label>
            <button
              aria-expanded={filtroAberto}
              className="cora-btn cora-btn-outline h-[38px]"
              onClick={() => setFiltroAberto((v) => !v)}
              type="button"
            >
              <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="15"><path d="M3 4h10M5 8h6M7 12h2" /></svg>
              Filtros
            </button>
          </div>
          {filtroAberto && (
            <div className="border-b border-[#EDF1EE] bg-cora-row px-4 py-3 text-xs text-cora-muted">
              Filtre pelo status nas abas ou digite o título ou a descrição da vaga.
            </div>
          )}

          <div className="relative overflow-x-auto">
            <div aria-label="Lista de vagas" className="min-w-[980px]" role="table">
              <div className={`grid ${GRADE} gap-4 border-b border-[#EDF1EE] bg-cora-row px-4 py-2.5 text-xs font-medium text-cora-placeholder`} role="row">
                <span role="columnheader">Vaga</span>
                <span role="columnheader">Prazo e meta</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">Progresso da meta</span>
                <span role="columnheader">Pessoas</span>
                <span role="columnheader">Na revisão</span>
                <span role="columnheader"><span className="sr-only">Abrir</span></span>
              </div>
              {carregando ? (
                <p className="m-0 px-4 py-10 text-center text-cora-muted">Carregando vagas…</p>
              ) : visiveis.length === 0 ? (
                <p className="m-0 px-4 py-10 text-center text-cora-muted">
                  {linhas.length === 0 ? "Nenhuma vaga ainda. Crie a primeira em “Criar vaga”." : "Nenhuma vaga com esse status."}
                </p>
              ) : (
                visiveis.map((linha) => {
                  const { vaga, estado, resumo } = linha;
                  const href = `/vagas/${encodeURIComponent(vaga.id)}`;
                  const prog = progresso(linha);
                  const buscando = grupoDoEstado(estado) === "buscando" && estado !== "pausada";
                  return (
                    <div className={`cora-row grid ${GRADE} items-center gap-4 border-b border-cora-subtle px-4 py-3.5`} key={vaga.id} role="row">
                      <div className="flex min-w-0 items-center gap-3" role="cell">
                        <span aria-hidden="true" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[9px] bg-cora-muted-bg text-cora-ink-2">
                          <IconeMaleta />
                        </span>
                        <span className="flex min-w-0 flex-col">
                          <Link className="truncate text-sm font-semibold text-cora-ink no-underline hover:text-cora-primary" href={href}>
                            {vaga.titulo}
                          </Link>
                          <span className="truncate text-xs text-cora-placeholder">
                            <span className="font-mono">{vaga.id}</span>
                            {vaga.competencias[0] ? ` · ${vaga.competencias[0].nome}` : ""}
                          </span>
                        </span>
                      </div>
                      <div className="flex flex-col text-[13px]" role="cell">
                        <span>Prazo de {vaga.prazo_dias} dias</span>
                        <span className="text-xs text-cora-placeholder">Meta de {vaga.meta_candidatos} pessoas</span>
                      </div>
                      <div role="cell">
                        <span className={`inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-md border px-2 text-xs font-semibold ${estiloDoEstado(estado)}`}>
                          {buscando && <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-cora-accent" />}
                          {rotuloDoEstado(estado)}
                        </span>
                      </div>
                      <div className="flex flex-col gap-1.5" role="cell">
                        <span className="h-1.5 overflow-hidden rounded-[3px] bg-[#EDF1EE]">
                          <span
                            className={`block h-full rounded-[3px] ${estado === "concluida" ? "bg-cora-ok-ink" : "bg-cora-accent"}`}
                            style={{ width: `${prog.pct}%` }}
                          />
                        </span>
                        <span className="text-xs text-cora-muted">{prog.texto}</span>
                      </div>
                      <div className="num text-[13px]" role="cell">{resumo ? resumo.analisados : "–"}</div>
                      <div className="num text-[13px] text-cora-muted" role="cell">{resumo ? resumo.na_fila_humana : "–"}</div>
                      <div role="cell">
                        <Link
                          aria-label={`Abrir ${vaga.titulo}`}
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-cora-muted hover:bg-cora-subtle"
                          href={href}
                        >
                          <svg aria-hidden="true" fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 16 16" width="16"><path d="m6 4 4 4-4 4" /></svg>
                        </Link>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </section>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-cora-placeholder">
            Critérios e primeiro lote de convites de cada vaga passam por revisão humana: {REVISOR}
          </span>
          <SimuladoBadge />
        </div>
      </AppMain>
    </div>
  );
}

function Metrica({ rotulo, valor, legenda, complemento }: { rotulo: string; valor: string; legenda: string; complemento?: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-cora-line-2 bg-cora-surface px-5 py-[18px] shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
      <span className="text-[13px] text-cora-muted">{rotulo}</span>
      <span className="num text-[30px] font-semibold leading-[1.1] tracking-[-0.03em]">
        {valor}
        {complemento && <span className="ml-1 text-base font-medium text-cora-muted">{complemento}</span>}
      </span>
      <span className="text-xs text-cora-placeholder">{legenda}</span>
    </div>
  );
}
