"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Navegacao } from "../../components/Navegacao";
import { SimuladoBadge } from "../../components/SimuladoBadge";
import { candidatosIniciais } from "../../lib/dados";
import type { EstadoBanco } from "../../lib/tipos";

const estados: Array<EstadoBanco | "todos"> = [
  "todos",
  "ativo",
  "pendente",
  "desatualizado",
  "expirado",
  "removido",
];

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
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <Navegacao />
      <div className="mx-auto max-w-6xl px-6 py-10">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.25em] text-cyan-300">
              Catálogo sintético
            </p>
            <h1 className="text-4xl font-bold tracking-tight">Banco de talentos</h1>
            <p className="mt-2 text-slate-300">
              Perfis da empresa-demo, separados por estado e autorização.
            </p>
          </div>
          <SimuladoBadge />
        </header>
        <section className="mb-8 grid gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-5 md:grid-cols-[1fr_220px]">
          <label className="grid gap-2 text-sm font-medium">
            Buscar por nome ou competência
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 outline-none focus:border-cyan-400"
              value={busca}
              onChange={(evento) => setBusca(evento.target.value)}
              placeholder="Ex.: Python"
            />
          </label>
          <label className="grid gap-2 text-sm font-medium">
            Estado
            <select
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 outline-none focus:border-cyan-400"
              value={estado}
              onChange={(evento) => setEstado(evento.target.value as EstadoBanco | "todos")}
            >
              {estados.map((opcao) => (
                <option key={opcao} value={opcao}>
                  {opcao === "todos" ? "Todos" : opcao}
                </option>
              ))}
            </select>
          </label>
        </section>
        {candidatos.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-slate-700 p-8 text-center text-slate-400">
            Nenhum candidato encontrado com esses filtros.
          </p>
        ) : (
          <section className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {candidatos.map((candidato) => {
              const experiencia = candidato.historico.at(-1);
              return (
                <Link
                  className="group rounded-2xl border border-slate-800 bg-slate-900 p-5 transition hover:-translate-y-1 hover:border-cyan-400"
                  href={`/candidatos/${candidato.id}`}
                  key={candidato.id}
                >
                  <div className="flex items-start justify-between gap-3">
                    <h2 className="text-xl font-semibold">{candidato.nome}</h2>
                    <SimuladoBadge />
                  </div>
                  <p className="mt-3 text-sm text-cyan-300">
                    {experiencia?.cargo ?? "Experiência não informada"}
                  </p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {Object.keys(candidato.atributos).map((competencia) => (
                      <span className="rounded-full bg-slate-800 px-2.5 py-1 text-xs text-slate-200" key={competencia}>
                        {competencia}
                      </span>
                    ))}
                  </div>
                  <div className="mt-6 flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full bg-slate-800 px-2.5 py-1">Estado: {candidato.estado}</span>
                    <span className={`rounded-full px-2.5 py-1 font-semibold ${candidato.autorizou_contato ? "bg-emerald-100 text-emerald-900" : "bg-rose-100 text-rose-900"}`}>
                      {candidato.autorizou_contato ? "Autorizado para contato" : "Sem autorização"}
                    </span>
                  </div>
                </Link>
              );
            })}
          </section>
        )}
      </div>
    </main>
  );
}
