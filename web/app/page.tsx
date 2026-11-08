"use client";

import Link from "next/link";
import { BriefcaseBusiness, ChevronRight, Filter, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Sidebar } from "../components/Sidebar";
import { SimuladoBadge } from "../components/SimuladoBadge";
import { ApiError, listarVagas, modoReservaAtivo, type ItemVagaCatalogo } from "../lib/api";
import type { EstadoVaga } from "../lib/tipos";

const REVISOR = "revisor.demo";

type Status = "Buscando" | "Rascunho" | "Concluída" | "Pausada";

type VagaExibida = ItemVagaCatalogo & {
  progresso: string;
  percentual: number;
  status: Status;
};

// Só aparecem com NEXT_PUBLIC_MODO_RESERVA=true, identificadas como dados locais de reserva.
const vagasDeReserva: ItemVagaCatalogo[] = [
  { id: "vaga-014", titulo: "Pessoa Desenvolvedora Backend Sênior", estado: "buscando", meta_candidatos: 5, analisados: 23, indicados: 1, descartados: 9, gasto_usd: 0.42 },
  { id: "vaga-013", titulo: "Product Designer Pleno", estado: "decidindo", meta_candidatos: 4, analisados: 17, indicados: 2, descartados: 6, gasto_usd: 0.31 },
  { id: "vaga-015", titulo: "Pessoa Engenheira de Plataforma", estado: "aguardando_mandato", meta_candidatos: 3, analisados: 0, indicados: 0, descartados: 0, gasto_usd: 0 },
  { id: "vaga-012", titulo: "Analista de Dados Pleno", estado: "concluida", meta_candidatos: 3, analisados: 31, indicados: 3, descartados: 12, gasto_usd: 0.57 },
];

function statusDoEstado(estado: EstadoVaga): Status {
  if (estado === "concluida") return "Concluída";
  if (estado === "pausada") return "Pausada";
  if (estado === "rascunho" || estado === "aguardando_mandato") return "Rascunho";
  return "Buscando";
}

function exibir(item: ItemVagaCatalogo): VagaExibida {
  const percentual = item.meta_candidatos > 0 ? Math.min(100, Math.round((item.indicados / item.meta_candidatos) * 100)) : 0;
  return {
    ...item,
    percentual,
    progresso: `${item.indicados} de ${item.meta_candidatos} indicados`,
    status: statusDoEstado(item.estado),
  };
}

const classesDoStatus: Record<Status, string> = {
  Buscando: "bg-[#eef2ef] text-[#2c4f55]",
  Concluída: "bg-[#e3f3e8] text-[#2f6e52]",
  Rascunho: "bg-[#fff1cc] text-[#855a0e]",
  Pausada: "bg-[#edf0ef] text-[#788887]",
};

const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD" });

export default function Home() {
  const reserva = modoReservaAtivo();
  const [vagas, setVagas] = useState<VagaExibida[]>(() => (reserva ? vagasDeReserva.map(exibir) : []));
  const [carregando, setCarregando] = useState(!reserva);
  const [erro, setErro] = useState("");
  const [busca, setBusca] = useState("");
  const [filtroAberto, setFiltroAberto] = useState(false);
  const [filtroStatus, setFiltroStatus] = useState<"todas" | "buscando" | "concluida" | "rascunho">("todas");

  useEffect(() => {
    if (reserva) return;
    let ativo = true;
    async function carregar() {
      try {
        const resposta = await listarVagas();
        if (ativo) setVagas(resposta.itens.map(exibir));
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
  }, [reserva]);

  const contagem = useMemo(() => {
    const por = (status: Status) => vagas.filter((vaga) => vaga.status === status).length;
    const buscando = vagas.filter((vaga) => vaga.status === "Buscando");
    return {
      buscando: por("Buscando"),
      concluidas: por("Concluída"),
      rascunhos: por("Rascunho"),
      analisados: buscando.reduce((soma, vaga) => soma + vaga.analisados, 0),
      indicados: buscando.reduce((soma, vaga) => soma + vaga.indicados, 0),
      meta: buscando.reduce((soma, vaga) => soma + vaga.meta_candidatos, 0),
      gasto: vagas.reduce((soma, vaga) => soma + vaga.gasto_usd, 0),
    };
  }, [vagas]);

  const vagasFiltradas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return vagas.filter((vaga) => {
      const combinaStatus = filtroStatus === "todas" || (filtroStatus === "buscando" ? vaga.status === "Buscando" : filtroStatus === "rascunho" ? vaga.status === "Rascunho" : vaga.status === "Concluída");
      return combinaStatus && (!termo || vaga.titulo.toLowerCase().includes(termo) || vaga.id.toLowerCase().includes(termo));
    });
  }, [busca, filtroStatus, vagas]);

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="catalogo" count={vagas.length} />

      <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-5 py-8 pb-14 sm:px-6">
          {reserva && (
            <p className="mb-5 rounded-lg border border-[#f1c36a] bg-[#fff7df] px-4 py-3 text-sm text-[#805d16]">
              Dados locais de reserva
            </p>
          )}
          {erro && (
            <p className="mb-5 rounded-lg border border-[#f0b5aa] bg-[#fff1ee] px-4 py-3 text-sm text-[#a43826]" role="alert">
              {erro}
            </p>
          )}
          <header className="flex flex-wrap items-end justify-between gap-5">
            <div>
              <h1 className="text-[30px] font-semibold leading-[1.15] tracking-[-0.04em] text-[#0b3038]">Vagas</h1>
              <p className="mt-1.5 text-[15px] text-[#526c68]">Acompanhe as buscas da sua empresa e o quanto falta para cada meta.</p>
            </div>
            <Link
              className="inline-flex h-9 items-center justify-center rounded-lg border border-[#dfe6e1] bg-white px-3.5 text-sm font-medium text-[#0b3038] transition hover:bg-[#eef2ef]"
              href="/vagas/modelos"
            >
              Criar a partir de um modelo
            </Link>
          </header>

          <section aria-label="Resumo" className="grid gap-3 md:grid-cols-4">
            <Metric label="Vagas buscando" value={String(contagem.buscando)} caption={`${contagem.rascunhos} rascunho(s) aguardam o mandato`} />
            <Metric label="Perfis analisados" value={String(contagem.analisados)} caption="nas vagas buscando, cada um com a origem" />
            <Metric label="Indicados" value={`${contagem.indicados} de ${contagem.meta}`} caption="soma das metas das vagas buscando" />
            <Metric label="Gasto com modelos" value={moeda.format(contagem.gasto)} caption="soma de todas as vagas da empresa" />
          </section>

          <section className="overflow-hidden rounded-xl border border-[#dfe7e2] bg-white shadow-[0_1px_2px_rgba(29,55,47,.02)]">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#e8eeea] p-4">
              <div className="flex flex-wrap gap-0.5 rounded-[9px] bg-[#eaf0ec] p-[3px]" role="tablist" aria-label="Filtrar por status">
                {([["todas", "Todas", vagas.length], ["buscando", "Buscando", contagem.buscando], ["concluida", "Concluídas", contagem.concluidas], ["rascunho", "Rascunhos", contagem.rascunhos]] as const).map(([valor, label, total]) => (
                  <button aria-selected={filtroStatus === valor} className={`rounded-md px-3 py-1.5 text-xs ${filtroStatus === valor ? "bg-white font-semibold text-[#0b3038] shadow-sm" : "font-medium text-[#526c68]"}`} key={valor} onClick={() => setFiltroStatus(valor)} role="tab" type="button">{label} <span className="ml-1">{total}</span></button>
                ))}
              </div>
              <div className="flex h-10 min-w-[250px] flex-1 items-center gap-3 rounded-lg border border-[#dce5e0] px-3 text-sm text-[#90a09c]">
                <Search aria-hidden="true" size={17} />
                <input
                  aria-label="Buscar por vaga"
                  className="w-full bg-transparent outline-none placeholder:text-[#9aa8a6]"
                  onChange={(evento) => setBusca(evento.target.value)}
                  placeholder="Buscar por vaga"
                  value={busca}
                />
              </div>
              <button
                className={`flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium transition ${filtroAberto ? "border-[#fb3c0d] bg-[#fff3ef] text-[#d83b18]" : "border-[#dce5e0] text-[#54706b] hover:bg-[#f7faf8]"}`}
                onClick={() => setFiltroAberto((aberto) => !aberto)}
                type="button"
              >
                <Filter aria-hidden="true" size={17} />
                Filtros
              </button>
            </div>
            {filtroAberto && (
              <div className="border-b border-[#e8eeea] bg-[#fbfcfa] px-4 py-3 text-xs text-[#718784]">
                Filtro visual ativo: digite o título ou o código da vaga.
              </div>
            )}
            <div className="hidden min-w-[980px] grid-cols-[minmax(280px,2.4fr)_1fr_1.5fr_.8fr_.8fr_36px] gap-4 border-b border-[#edf1ee] bg-[#fcfdfc] px-4 py-3 text-[10px] font-semibold uppercase tracking-wide text-[#80908d] md:grid">
              <span>Vaga</span>
              <span>Status</span>
              <span>Progresso da meta</span>
              <span>Analisados</span>
              <span>Gasto</span>
              <span />
            </div>
            {carregando ? (
              <p className="p-10 text-center text-sm text-[#81908d]">Carregando vagas…</p>
            ) : vagasFiltradas.length === 0 ? (
              <p className="p-10 text-center text-sm text-[#81908d]">Nenhuma vaga encontrada.</p>
            ) : (
              vagasFiltradas.map((vaga) => {
                return (
                  <article className="grid gap-3 border-b border-[#edf1ee] px-4 py-4 last:border-b-0 md:grid-cols-[minmax(280px,2.4fr)_1fr_1.5fr_.8fr_.8fr_36px] md:items-center md:gap-4" key={vaga.id}>
                    <div className="flex items-center gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#eaf4ef] text-[#83a39b]">
                        <BriefcaseBusiness aria-hidden="true" size={16} />
                      </span>
                      <div>
                        <h2 className="text-sm font-semibold text-[#113b43]"><Link className="hover:text-[#fb3c0d]" href={`/vagas/${encodeURIComponent(vaga.id)}`}>{vaga.titulo}</Link></h2>
                        <p className="mt-1 text-xs text-[#82918e]"><span className="font-mono">{vaga.id}</span> · {vaga.descartados} descartados</p>
                      </div>
                    </div>
                    <span className={`w-fit rounded-full px-3 py-1 text-[10px] font-semibold ${classesDoStatus[vaga.status]}`}>
                      <span className="mr-1">•</span>{vaga.status}
                    </span>
                    <div className="flex flex-col gap-1.5 text-xs text-[#58716d]"><span className="h-1.5 rounded-full bg-[#edf1ee]"><span className="block h-full rounded-full bg-[#fb3c0d]" style={{ width: `${vaga.percentual}%` }} /></span><span>{vaga.progresso}</span></div>
                    <p className="text-xs text-[#58716d]">{vaga.analisados}</p>
                    <p className="text-xs text-[#8b9996]">{moeda.format(vaga.gasto_usd)}</p>
                    <Link aria-label={`Ver candidatos de ${vaga.titulo}`} className="hidden md:block" href={`/vagas/${encodeURIComponent(vaga.id)}/candidatos`}>
                      <ChevronRight aria-hidden="true" size={17} />
                    </Link>
                  </article>
                );
              })
            )}
          </section>

          <div className="mt-5 flex items-center justify-between">
            <SimuladoBadge />
            <p className="text-[11px] text-[#8b9996]">Dados sintéticos · revisão humana: {REVISOR}</p>
          </div>
        </div>

    </main>
  );
}

function Metric({ label, value, caption }: { label: string; value: string; caption: string }) {
  return (
    <div className="rounded-xl border border-[#dfe7e2] bg-white p-5">
      <p className="text-xs text-[#718784]">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-tight text-[#0b3038]">{value}</p>
      <p className="mt-1 text-[11px] text-[#8b9996]">{caption}</p>
    </div>
  );
}
