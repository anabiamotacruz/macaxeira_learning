"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Sidebar } from "../components/Sidebar";
import { SimuladoBadge } from "../components/SimuladoBadge";
import { ApiError, listarVagas, modoReservaAtivo } from "../lib/api";
import { vagasIniciais } from "../lib/dados";
import type { Vaga } from "../lib/tipos";

const REVISOR = "revisor.demo";

function Icon({
  name,
  size = 18,
}: {
  name: "bell" | "briefcase" | "building" | "chevron" | "filter" | "grid" | "people" | "plus" | "search";
  size?: number;
}) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 1.8,
  };

  const paths = {
    bell: (
      <>
        <path {...common} d="M5 8.5a4 4 0 0 1 8 0c0 4 1.5 4 1.5 5H3.5c0-1 1.5-1 1.5-5Z" />
        <path {...common} d="M8 15.5a1.5 1.5 0 0 0 2.8 0" />
      </>
    ),
    briefcase: (
      <>
        <rect {...common} height="8" rx="1.5" width="13" x="2.5" y="5.5" />
        <path {...common} d="M6 5.5V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1.5M2.5 9h13M8 9v1.5h2V9" />
      </>
    ),
    building: <path {...common} d="M3 14V3.5L8 2v12M8 5h5v9M5 5.5h1M5 8h1M5 10.5h1M10 7h1M10 9.5h1M10 12h1M1.5 14h13" />,
    chevron: <path {...common} d="m6 4 4 4-4 4" />,
    filter: <path {...common} d="M3 4h10M5 8h6M7 12h2" />,
    grid: (
      <>
        <rect {...common} height="4" rx="1" width="4" x="2" y="2" />
        <rect {...common} height="4" rx="1" width="4" x="10" y="2" />
        <rect {...common} height="4" rx="1" width="4" x="2" y="10" />
        <rect {...common} height="4" rx="1" width="4" x="10" y="10" />
      </>
    ),
    people: (
      <>
        <circle {...common} cx="6" cy="5" r="2" />
        <circle {...common} cx="11" cy="5.5" r="1.6" />
        <path {...common} d="M2.5 13c.3-2 1.5-3 3.5-3s3.2 1 3.5 3M9 10.5c2.4-.7 4.2.3 4.5 2.5" />
      </>
    ),
    plus: <path {...common} d="M8 3v10M3 8h10" />,
    search: <circle {...common} cx="7" cy="7" r="4.3" />,
  };

  return (
    <svg aria-hidden="true" height={size} viewBox="0 0 16 16" width={size}>
      {paths[name]}
    </svg>
  );
}

function CoralMark() {
  return <img alt="Coral da CORA" className="h-10 w-10 shrink-0 object-contain" src="/coral.png" />;
  /*
  return (
    <svg
      aria-label="Ícone coral da CORA"
      className="h-10 w-10 shrink-0"
      fill="none"
      role="img"
      viewBox="0 0 48 48"
    >
      <path
        d="M7 29c4-5 5-11 5-17 0-2 2-3 3-1 3 4 3 8 3 12 2-7 5-14 9-19 1-2 4-1 4 2v12c2-5 5-9 9-12 2-1 4 0 3 3-2 7-5 12-10 17 4-2 7-3 11-2 2 0 2 3 1 4-5 5-10 7-16 7 2 2 3 5 2 7-1 2-3 2-5 0-3-3-5-6-6-10-3 3-7 5-11 6-2 0-3-2-2-4Z"
        fill="#fb3c0d"
      />
      <path
        d="M12 30c5-3 9-7 11-12 1-3 3-7 5-10-1 7 0 13 3 18-4 3-8 5-13 6-2 0-4 0-6-2Z"
        fill="#ed2e23"
        opacity=".55"
      />
    </svg>
  );
  */
}

function statusDaVaga(vaga: Vaga) {
  if (vaga.id === "vaga-referencia-buscando") {
    return { label: "Buscando", className: "bg-[#fff1cc] text-[#a06b13]" };
  }
  return vaga.aprovada
    ? { label: "Concluída", className: "bg-[#e3f3e8] text-[#377b5d]" }
    : { label: "Rascunho", className: "bg-[#edf0ef] text-[#788887]" };
}

export default function Home() {
  const [vagas, setVagas] = useState<Vaga[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [busca, setBusca] = useState("");
  const [filtroAberto, setFiltroAberto] = useState(false);

  useEffect(() => {
    let ativo = true;
    async function carregar() {
      try {
        const respostas = await listarVagas();
        if (!ativo) return;
        setVagas(modoReservaAtivo() ? vagasIniciais : respostas.map((resposta) => resposta.vaga));
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

  const vagasFiltradas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    if (!termo) return vagas;
    return vagas.filter(
      (vaga) =>
        vaga.titulo.toLowerCase().includes(termo) ||
        vaga.descricao.toLowerCase().includes(termo),
    );
  }, [busca, vagas]);

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="catalogo" count={vagas.length} />

      <div className="md:pl-[238px]">
        <header className="flex h-[80px] items-center justify-between border-b border-[#e4e9e5] bg-white/80 px-5 sm:px-10 md:h-[94px]">
          <div className="flex items-center gap-2 md:hidden">
            <CoralMark />
            <div>
              <p className="text-xl font-semibold leading-none tracking-tight text-[#0b3038]">CORA</p>
              <p className="mt-1 text-[7px] font-medium uppercase leading-tight tracking-wide text-[#718784]">
                Recrutamento ativo
              </p>
            </div>
          </div>
          <div className="hidden h-10 w-full max-w-[320px] items-center gap-3 rounded-lg bg-[#f0f4f1] px-4 text-sm text-[#8b9b99] md:flex">
            <Icon name="search" size={17} />
            <input
              aria-label="Buscar vagas ou candidatos"
              className="w-full bg-transparent outline-none placeholder:text-[#9aa8a6]"
              onChange={(evento) => setBusca(evento.target.value)}
              placeholder="Buscar vagas ou candidatos"
              value={busca}
            />
            <span className="hidden rounded border border-[#d7dfdb] bg-white px-2 py-0.5 text-[10px] text-[#83918f] sm:inline">⌘ K</span>
          </div>
          <div className="ml-4 flex items-center gap-2 sm:gap-3">
            <button aria-label="Notificações" className="relative flex h-10 w-10 items-center justify-center rounded-lg border border-[#e0e7e2] bg-white text-[#67807d]" type="button">
              <Icon name="bell" />
              <span className="absolute right-2 top-1.5 h-1.5 w-1.5 rounded-full bg-[#fb7356]" />
            </button>
            <button className="hidden rounded-lg border border-[#e0e7e2] bg-white px-4 py-2.5 text-xs font-medium text-[#526c68] sm:block" type="button">
              Ajuda
            </button>
          </div>
        </header>

        <div className="mx-auto max-w-[1235px] px-5 py-10 sm:px-8 lg:px-11">
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
          <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
            <div>
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#4c8885]">Recrutamento inteligente</p>
              <h1 className="text-4xl font-semibold tracking-[-0.04em] text-[#0b3038] sm:text-[38px]">Catálogo de vagas</h1>
              <p className="mt-2 text-sm text-[#718784]">Acompanhe suas buscas e encontre os melhores perfis para cada oportunidade.</p>
            </div>
            <Link
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#fb3c0d] px-5 py-3 text-sm font-semibold text-white shadow-[0_3px_7px_rgba(251,60,13,.22)] transition hover:bg-[#e9360b] sm:w-auto"
              href="/criar-vaga"
            >
              <Icon name="plus" />
              Criar nova vaga
            </Link>
          </header>

          <section className="mb-5 grid gap-3 md:grid-cols-4">
            <Metric label="Vagas ativas" value={String(vagas.filter((vaga) => vaga.aprovada).length).padStart(2, "0")} caption={`${vagas.length} cadastrada(s)`} />
            <Metric label="Perfis encontrados" value="—" caption="A API não expõe total no catálogo" />
            <Metric label="Em avaliação" value={String(vagas.filter((vaga) => !vaga.aprovada).length)} caption="Aguardando retorno da API" />
            <div className="relative overflow-hidden rounded-xl border border-[#cce5a2] bg-[#f0f9df] p-5">
              <p className="text-xs text-[#728a62]">Taxa de aderência</p>
              <p className="mt-3 text-3xl font-semibold tracking-tight text-[#3d7c2d]">87%</p>
              <p className="mt-1 text-[11px] text-[#78966b]">12% acima da média</p>
              <span className="absolute -bottom-9 -right-7 h-20 w-20 rounded-full border-[10px] border-[#dceec4]" />
            </div>
          </section>

          <section className="overflow-hidden rounded-xl border border-[#dfe7e2] bg-white shadow-[0_1px_2px_rgba(29,55,47,.02)]">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#e8eeea] p-4">
              <div className="flex h-10 min-w-[250px] flex-1 items-center gap-3 rounded-lg border border-[#dce5e0] px-3 text-sm text-[#90a09c]">
                <Icon name="search" size={17} />
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
                <Icon name="filter" size={17} />
                Filtros
              </button>
            </div>
            {filtroAberto && (
              <div className="border-b border-[#e8eeea] bg-[#fbfcfa] px-4 py-3 text-xs text-[#718784]">
                Filtro visual ativo: digite o título ou a descrição da vaga.
              </div>
            )}
            <div className="hidden grid-cols-[2.4fr_1.2fr_1fr_1fr_1fr_24px] gap-4 border-b border-[#edf1ee] bg-[#fcfdfc] px-4 py-3 text-[10px] font-semibold uppercase tracking-wide text-[#80908d] md:grid">
              <span>Vaga</span>
              <span>Local e modelo</span>
              <span>Status</span>
              <span>Candidatos</span>
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
                  <article className="grid gap-3 border-b border-[#edf1ee] px-4 py-4 last:border-b-0 md:grid-cols-[2.4fr_1.2fr_1fr_1fr_1fr_24px] md:items-center md:gap-4" key={vaga.id}>
                    <div className="flex items-center gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#eaf4ef] text-[#83a39b]">
                        <Icon name="briefcase" />
                      </span>
                      <div>
                        <h2 className="text-sm font-semibold text-[#113b43]">{vaga.titulo}</h2>
                        <p className="mt-1 text-xs text-[#82918e]">{vaga.competencias[0]?.nome ?? "Tecnologia"}</p>
                      </div>
                    </div>
                    <div className="text-xs text-[#58716d]">
                      <span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-[#9aa7a4] md:hidden">Local</span>
                      <p>Empresa da sessão</p>
                      <p className="mt-1 text-[10px] text-[#9aa7a4]">Modelo não informado</p>
                    </div>
                    <span className={`w-fit rounded-full px-3 py-1 text-[10px] font-semibold ${status.className}`}>
                      <span className="mr-1">•</span>{status.label}
                    </span>
                    <p className="text-xs text-[#58716d]"><span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-[#9aa7a4] md:hidden">Candidatos</span>—</p>
                    <p className="text-xs text-[#8b9996]"><span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-[#9aa7a4] md:hidden">Criada em</span>—</p>
                    <Link aria-label={`Ver candidatos de ${vaga.titulo}`} className="hidden md:block" href={`/vagas/${encodeURIComponent(vaga.id)}/candidatos`}>
                      <Icon name="chevron" size={17} />
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
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-[#dfe7e2] bg-[#5b5b5b] px-2 py-2 text-[10px] text-[#d0d6d5] md:hidden">
        <Link className="flex flex-col items-center gap-1 rounded-lg px-1 py-2" href="#">
          <Icon name="grid" size={18} />
          Visão geral
        </Link>
        <Link className="flex flex-col items-center gap-1 rounded-lg px-1 py-2" href="/criar-vaga">
          <Icon name="plus" size={18} />
          Criar vaga
        </Link>
        <Link className="flex flex-col items-center gap-1 rounded-lg bg-[#fb3c0d] px-1 py-2 font-semibold text-white" href="/">
          <Icon name="briefcase" size={18} />
          Catálogo
        </Link>
        <Link className="flex flex-col items-center gap-1 rounded-lg px-1 py-2" href="/banco">
          <Icon name="people" size={18} />
          Banco
        </Link>
      </nav>

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
