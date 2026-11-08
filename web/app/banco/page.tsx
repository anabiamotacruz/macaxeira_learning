"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Sidebar } from "../../components/Sidebar";
import { SimuladoBadge } from "../../components/SimuladoBadge";
import { candidatosIniciais } from "../../lib/dados";
import { modoReservaAtivo } from "../../lib/api";
import type { EstadoBanco } from "../../lib/tipos";

const estados: Array<EstadoBanco | "todos"> = [
  "todos",
  "ativo",
  "pendente",
  "desatualizado",
  "expirado",
  "removido",
];

function Icon({
  name,
  size = 18,
}: {
  name: "bell" | "briefcase" | "grid" | "people" | "search";
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
        d="M7 29c4-5 5-11 5-17 0-2 2-3 3-1 3 4 3 8 3 12 2-7 5-14 9-19 1-2 4-1 4 2v12c2-5 5-9 9-12 2-1 4 0 3 3-2 7-5 12-10 17 4-2 7-3 11-2 2 0 3 3 1 4-5 5-10 7-16 7 2 2 3 5 2 7-1 2-3 2-5 0-3-3-5-6-6-10-3 3-7 5-11 6-2 0-3-2-2-4Z"
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

export default function BancoPage() {
  const [busca, setBusca] = useState("");
  const [estado, setEstado] = useState<EstadoBanco | "todos">("todos");
  const candidatos = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return candidatosIniciais.filter((candidato) => {
      const combinaBusca =
        !termo ||
        candidato.nome.toLowerCase().includes(termo) ||
        Object.keys(candidato.atributos).some((competencia) =>
          competencia.toLowerCase().includes(termo),
        );
      return combinaBusca && (estado === "todos" || candidato.estado === estado);
    });
  }, [busca, estado]);

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="banco" />

      <div className="mx-auto max-w-[1240px] px-5 py-8 sm:px-6 lg:px-6">
          <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
            <div>
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#4c8885]">Recrutamento inteligente</p>
              <h1 className="text-4xl font-semibold tracking-[-0.04em] text-[#0b3038] sm:text-[38px]">Banco de talentos</h1>
              <p className="mt-2 text-sm text-[#718784]">Consulte perfis por estado e autorização de contato.</p>
            </div>
            <SimuladoBadge />
          </header>

          {modoReservaAtivo() && (
            <p className="mb-5 rounded-lg border border-[#f1c36a] bg-[#fff7df] px-4 py-3 text-sm text-[#805d16]">
              Dados locais de reserva
            </p>
          )}
          {!modoReservaAtivo() ? (
            <p className="mb-5 rounded-xl border border-[#dfe7e2] bg-white p-8 text-center text-sm text-[#718784]">
              O banco geral ainda não possui uma rota na API. Abra os candidatos a partir de uma vaga.
            </p>
          ) : (
            <>
              <section className="mb-5 grid gap-3 rounded-xl border border-[#dfe7e2] bg-white p-5 md:grid-cols-[1fr_220px]">
                <label className="grid gap-2 text-sm font-medium text-[#526c68]">
                  Buscar por nome ou competência
                  <input
                    className="rounded-lg border border-[#dce5e0] bg-white px-3 py-2 text-[#0e3038] outline-none focus:border-[#fb3c0d]"
                    value={busca}
                    onChange={(evento) => setBusca(evento.target.value)}
                    placeholder="Ex.: Python"
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium text-[#526c68]">
                  Estado
                  <select
                    className="rounded-lg border border-[#dce5e0] bg-white px-3 py-2 text-[#0e3038] outline-none focus:border-[#fb3c0d]"
                    value={estado}
                    onChange={(evento) => setEstado(evento.target.value as EstadoBanco | "todos")}
                  >
                    {estados.map((opcao) => (
                      <option key={opcao} value={opcao}>{opcao === "todos" ? "Todos" : opcao}</option>
                    ))}
                  </select>
                </label>
              </section>
              {candidatos.length === 0 ? (
                <p className="rounded-xl border border-dashed border-[#cbd8d2] bg-white p-8 text-center text-sm text-[#81908d]">
                  Nenhum candidato encontrado com esses filtros.
                </p>
              ) : (
                <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                  {candidatos.map((candidato) => {
                    const experiencia = candidato.historico.at(-1);
                    return (
                      <Link
                        className="group rounded-xl border border-[#dfe7e2] bg-white p-5 shadow-[0_1px_2px_rgba(29,55,47,.02)] transition hover:-translate-y-1 hover:border-[#fb3c0d]"
                        href={`/candidatos/${candidato.id}`}
                        key={candidato.id}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <h2 className="text-lg font-semibold text-[#113b43]">{candidato.nome}</h2>
                          <SimuladoBadge />
                        </div>
                        <p className="mt-3 text-sm text-[#4c8885]">{experiencia?.cargo ?? "Experiência não informada"}</p>
                        <div className="mt-5 flex flex-wrap gap-2">
                          {Object.keys(candidato.atributos).map((competencia) => (
                            <span className="rounded-full bg-[#edf5f0] px-2.5 py-1 text-xs text-[#526c68]" key={competencia}>{competencia}</span>
                          ))}
                        </div>
                        <div className="mt-6 flex flex-wrap items-center gap-2 text-xs">
                          <span className="rounded-full bg-[#edf0ef] px-2.5 py-1 text-[#526c68]">Estado: {candidato.estado}</span>
                          <span className={`rounded-full px-2.5 py-1 font-semibold ${candidato.autorizou_contato ? "bg-[#e3f3e8] text-[#377b5d]" : "bg-[#fff1ee] text-[#a43826]"}`}>
                            {candidato.autorizou_contato ? "Autorizado para contato" : "Sem autorização"}
                          </span>
                        </div>
                      </Link>
                    );
                  })}
                </section>
              )}
            </>
          )}

          <div className="mt-5 flex items-center justify-between">
            <SimuladoBadge />
            <p className="text-[11px] text-[#8b9996]">Dados sintéticos · revisão humana</p>
          </div>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-[#dfe7e2] bg-[#5b5b5b] px-2 py-2 text-[10px] text-[#d0d6d5] md:hidden">
        <Link className="flex flex-col items-center gap-1 rounded-lg px-1 py-2" href="/">
          <Icon name="briefcase" size={18} />
          Catálogo
        </Link>
        <Link className="flex flex-col items-center gap-1 rounded-lg bg-[#fb3c0d] px-1 py-2 font-semibold text-white" href="/banco">
          <Icon name="people" size={18} />
          Banco
        </Link>
        <Link className="flex flex-col items-center gap-1 rounded-lg px-1 py-2" href="/candidatos">
          <Icon name="grid" size={18} />
          Candidatos
        </Link>
      </nav>
    </main>
  );
}
