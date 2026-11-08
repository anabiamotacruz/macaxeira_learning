"use client";

import Link from "next/link";
import { BriefcaseBusiness, ChevronRight, Filter, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Sidebar } from "../components/Sidebar";
import { SimuladoBadge } from "../components/SimuladoBadge";
import { ApiError, listarVagas, modoReservaAtivo } from "../lib/api";
import { vagasIniciais } from "../lib/dados";
import type { Vaga } from "../lib/tipos";

const REVISOR = "revisor.demo";

type VagaExibida = Vaga & {
  codigo: string;
  area: string;
  local: string;
  modelo: string;
  progresso: string;
  pessoas: string;
  criada: string;
  percentual: number;
  status: "Buscando" | "Rascunho" | "Concluída";
};

const vagaBase = vagasIniciais[0];
const vagasDaReferencia: VagaExibida[] = [
  { ...vagaBase, id: "vaga-014", codigo: "014", titulo: "Pessoa Desenvolvedora Backend Sênior", area: "Tecnologia", local: "Remoto", modelo: "Encontro mensal em Recife", progresso: "1 de 5 entregues à Nara", pessoas: "23", criada: "07/11/2026", percentual: 20, status: "Buscando", aprovada: true },
  { ...vagaBase, id: "vaga-013", codigo: "013", titulo: "Product Designer Pleno", area: "Produto", local: "Recife, PE", modelo: "Híbrido, 2 dias no escritório", progresso: "2 de 4 entregues à Nara", pessoas: "17", criada: "05/11/2026", percentual: 50, status: "Buscando", aprovada: true },
  { ...vagaBase, id: "vaga-015", codigo: "015", titulo: "Pessoa Engenheira de Plataforma", area: "Tecnologia", local: "Remoto", modelo: "Remoto", progresso: "Critérios aguardam sua aprovação", pessoas: "–", criada: "08/11/2026", percentual: 0, status: "Rascunho", aprovada: false },
  { ...vagaBase, id: "vaga-012", codigo: "012", titulo: "Analista de Dados Pleno", area: "Dados", local: "Remoto", modelo: "Remoto", progresso: "3 de 3 entregues à Nara", pessoas: "31", criada: "21/10/2026", percentual: 100, status: "Concluída", aprovada: true },
  { ...vagaBase, id: "vaga-011", codigo: "011", titulo: "Analista de People Ops", area: "Pessoas", local: "Recife, PE", modelo: "Presencial", progresso: "2 de 2 entregues à Nara", pessoas: "12", criada: "02/10/2026", percentual: 100, status: "Concluída", aprovada: true },
];

function statusDaVaga(vaga: Vaga) {
  if ("status" in vaga) {
    const exibida = vaga as VagaExibida;
    return exibida.status === "Buscando"
      ? { label: exibida.status, className: "bg-[#eef2ef] text-[#2c4f55]" }
      : exibida.status === "Concluída"
        ? { label: exibida.status, className: "bg-[#e3f3e8] text-[#2f6e52]" }
        : { label: exibida.status, className: "bg-[#fff1cc] text-[#855a0e]" };
  }
  if (vaga.id === "vaga-referencia-buscando") {
    return { label: "Buscando", className: "bg-[#fff1cc] text-[#a06b13]" };
  }
  return vaga.aprovada
    ? { label: "Concluída", className: "bg-[#e3f3e8] text-[#377b5d]" }
    : { label: "Rascunho", className: "bg-[#edf0ef] text-[#788887]" };
}

export default function Home() {
  const [vagas, setVagas] = useState<VagaExibida[]>(vagasDaReferencia);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [busca, setBusca] = useState("");
  const [filtroAberto, setFiltroAberto] = useState(false);
  const [filtroStatus, setFiltroStatus] = useState<"todas" | "buscando" | "concluida" | "rascunho">("todas");

  useEffect(() => {
    let ativo = true;
    async function carregar() {
      try {
        const respostas = await listarVagas();
        if (!ativo) return;
        if (respostas.length > 0) setVagas(respostas.map((resposta) => ({ ...vagasDaReferencia[0], ...resposta.vaga, codigo: "API", area: "Tecnologia", local: "Não informado", modelo: "Não informado", progresso: "Em andamento", pessoas: "—", criada: "Hoje", percentual: 0, status: resposta.vaga.aprovada ? "Concluída" : "Rascunho" })));
      } catch (erroApi) {
        if (ativo && !(erroApi instanceof ApiError && erroApi.status === 0)) setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar as vagas.");
      } finally {
        if (ativo) setCarregando(false);
      }
    }
    void carregar();
    return () => {
      ativo = false;
    };
  }, []);

  const vagasFiltradas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return vagas.filter((vaga) => {
      const combinaStatus = filtroStatus === "todas" || (filtroStatus === "buscando" ? vaga.status === "Buscando" : filtroStatus === "rascunho" ? vaga.status === "Rascunho" : vaga.status === "Concluída");
      return combinaStatus && (!termo || vaga.titulo.toLowerCase().includes(termo) || vaga.descricao.toLowerCase().includes(termo));
    });
  }, [busca, filtroStatus, vagas]);

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="catalogo" count={vagas.length} />

      <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-5 py-8 pb-14 sm:px-6">
          {modoReservaAtivo() && (
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
            <Metric label="Vagas buscando" value="2" caption="1 rascunho aguarda aprovação dos critérios" />
            <Metric label="Perfis encontrados" value="40" caption="nas vagas buscando, cada um com a origem" />
            <Metric label="Aguardando autorização" value="5" caption="só são abordadas depois de autorizar" />
            <Metric label="Entregues à Nara" value="3 de 9" caption="soma das metas das vagas buscando" />
          </section>

          <section className="overflow-hidden rounded-xl border border-[#dfe7e2] bg-white shadow-[0_1px_2px_rgba(29,55,47,.02)]">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#e8eeea] p-4">
              <div className="flex flex-wrap gap-0.5 rounded-[9px] bg-[#eaf0ec] p-[3px]" role="tablist" aria-label="Filtrar por status">
                {([["todas", "Todas", 5], ["buscando", "Buscando", 2], ["concluida", "Concluídas", 2], ["rascunho", "Rascunhos", 1]] as const).map(([valor, label, total]) => (
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
                Filtro visual ativo: digite o título ou a descrição da vaga.
              </div>
            )}
            <div className="hidden min-w-[980px] grid-cols-[minmax(280px,2.4fr)_1.3fr_1fr_1.5fr_.7fr_.8fr_36px] gap-4 border-b border-[#edf1ee] bg-[#fcfdfc] px-4 py-3 text-[10px] font-semibold uppercase tracking-wide text-[#80908d] md:grid">
              <span>Vaga</span>
              <span>Local e modelo</span>
              <span>Status</span>
              <span>Progresso da meta</span>
              <span>Pessoas</span>
              <span>Criada em</span>
              <span />
            </div>
            {carregando ? (
              <p className="p-10 text-center text-sm text-[#81908d]">Carregando vagas…</p>
            ) : vagasFiltradas.length === 0 ? (
              <p className="p-10 text-center text-sm text-[#81908d]">Nenhuma vaga encontrada.</p>
            ) : (
              vagasFiltradas.map((vaga) => {
                const status = statusDaVaga(vaga);
                return (
                  <article className="grid gap-3 border-b border-[#edf1ee] px-4 py-4 last:border-b-0 md:grid-cols-[minmax(280px,2.4fr)_1.3fr_1fr_1.5fr_.7fr_.8fr_36px] md:items-center md:gap-4" key={vaga.id}>
                    <div className="flex items-center gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#eaf4ef] text-[#83a39b]">
                        <BriefcaseBusiness aria-hidden="true" size={16} />
                      </span>
                      <div>
                        <h2 className="text-sm font-semibold text-[#113b43]"><Link className="hover:text-[#fb3c0d]" href={`/vagas/${encodeURIComponent(vaga.id)}`}>{vaga.titulo}</Link></h2>
                        <p className="mt-1 text-xs text-[#82918e]"><span className="font-mono">vaga {(vaga as VagaExibida).codigo}</span> · {(vaga as VagaExibida).area}</p>
                      </div>
                    </div>
                    <div className="text-xs text-[#58716d]">
                      <span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-[#9aa7a4] md:hidden">Local</span>
                      <p>{(vaga as VagaExibida).local}</p>
                      <p className="mt-1 text-[10px] text-[#9aa7a4]">{(vaga as VagaExibida).modelo}</p>
                    </div>
                    <span className={`w-fit rounded-full px-3 py-1 text-[10px] font-semibold ${status.className}`}>
                      <span className="mr-1">•</span>{status.label}
                    </span>
                    <div className="flex flex-col gap-1.5 text-xs text-[#58716d]"><span className="h-1.5 rounded-full bg-[#edf1ee]"><span className="block h-full rounded-full bg-[#fb3c0d]" style={{ width: `${(vaga as VagaExibida).percentual}%` }} /></span><span>{(vaga as VagaExibida).progresso}</span></div>
                    <p className="text-xs text-[#58716d]">{(vaga as VagaExibida).pessoas}</p>
                    <p className="text-xs text-[#8b9996]">{(vaga as VagaExibida).criada}</p>
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
