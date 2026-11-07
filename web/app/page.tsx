"use client";

import { FormEvent, useState } from "react";

import { SimuladoBadge } from "../components/SimuladoBadge";
import { Navegacao } from "../components/Navegacao";
import { vagasIniciais } from "../lib/dados";
import type { Requisito, Vaga } from "../lib/tipos";

const REVISOR = "revisor.demo";

function criarVagaLocal(titulo: string, descricao: string, meta: number): Vaga {
  return {
    id: `vaga-demo-${Date.now()}`,
    empresa_id: "empresa-demo",
    titulo,
    descricao,
    requisitos: [],
    competencias: [],
    meta_candidatos: meta,
    prazo_dias: 7,
    max_tentativas_contato: 2,
    aprovada: false,
  };
}

export default function Home() {
  const [vagas, setVagas] = useState(vagasIniciais);
  const [titulo, setTitulo] = useState("");
  const [descricao, setDescricao] = useState("");
  const [meta, setMeta] = useState("5");

  function criarVaga(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    const tituloLimpo = titulo.trim();
    const descricaoLimpa = descricao.trim();
    const metaNumerica = Number(meta);

    if (
      !tituloLimpo ||
      !descricaoLimpa ||
      !Number.isInteger(metaNumerica) ||
      metaNumerica < 1
    ) {
      return;
    }

    setVagas((atuais) => [
      ...atuais,
      criarVagaLocal(tituloLimpo, descricaoLimpa, metaNumerica),
    ]);
    setTitulo("");
    setDescricao("");
    setMeta("5");
  }

  function aprovarVaga(id: string) {
    setVagas((atuais) =>
      atuais.map((vaga) => (vaga.id === id ? { ...vaga, aprovada: true } : vaga)),
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <Navegacao />
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-10 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.25em] text-cyan-300">
              Macaxeira Learning
            </p>
            <h1 className="text-4xl font-bold tracking-tight">Vagas</h1>
            <p className="mt-2 max-w-2xl text-slate-300">
              Configure a vaga e peça a aprovação explícita da pessoa revisora.
            </p>
          </div>
          <SimuladoBadge />
        </header>

        <section className="mb-8 rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <div className="mb-5">
            <h2 className="text-xl font-semibold">Criar nova vaga</h2>
            <p className="mt-1 text-sm text-slate-400">
              A vaga nasce sempre não aprovada e fica apenas neste estado local simulado.
            </p>
          </div>
          <form className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1.5fr)_140px_auto]" onSubmit={criarVaga}>
            <label className="grid gap-2 text-sm font-medium">
              Título
              <input
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400"
                value={titulo}
                onChange={(evento) => setTitulo(evento.target.value)}
                placeholder="Ex.: Pessoa desenvolvedora Go"
              />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              Descrição
              <input
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400"
                value={descricao}
                onChange={(evento) => setDescricao(evento.target.value)}
                placeholder="Responsabilidades da vaga"
              />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              Meta
              <input
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400"
                type="number"
                min="1"
                value={meta}
                onChange={(evento) => setMeta(evento.target.value)}
              />
            </label>
            <button
              className="self-end whitespace-nowrap rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950 transition hover:bg-cyan-300"
              type="submit"
            >
              Criar vaga
            </button>
          </form>
        </section>

        <section className="grid gap-5">
          {vagas.map((vaga) => (
            <article
              className="rounded-2xl border border-slate-800 bg-slate-900 p-6"
              key={vaga.id}
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-3 flex flex-wrap items-center gap-3">
                    <h2 className="text-2xl font-semibold">{vaga.titulo}</h2>
                    <SimuladoBadge />
                  </div>
                  <p className="max-w-3xl text-slate-300">{vaga.descricao}</p>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-sm font-semibold ${
                    vaga.aprovada
                      ? "bg-emerald-100 text-emerald-900"
                      : "bg-slate-700 text-slate-200"
                  }`}
                >
                  {vaga.aprovada ? "Aprovada" : "Aguardando aprovação"}
                </span>
              </div>

              <div className="mt-6 grid gap-5 border-t border-slate-800 pt-5 md:grid-cols-2">
                <div>
                  <h3 className="font-semibold text-cyan-300">Meta</h3>
                  <p className="mt-1 text-slate-200">
                    Entregar contexto de {vaga.meta_candidatos} candidato(s) em{" "}
                    {vaga.prazo_dias} dias.
                  </p>
                </div>
                <div>
                  <h3 className="font-semibold text-cyan-300">
                    Requisitos eliminatórios
                  </h3>
                  {vaga.requisitos.length ? (
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-slate-200">
                      {vaga.requisitos.map((requisito: Requisito) => (
                        <li key={requisito.id}>
                          {requisito.descricao}: {requisito.valor_esperado}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 text-slate-400">
                      Nenhum requisito informado ainda.
                    </p>
                  )}
                </div>
              </div>

              {!vaga.aprovada && (
                <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-5">
                  <p className="text-sm text-slate-400">
                    Ação humana necessária:{" "}
                    <strong className="text-slate-200">{REVISOR}</strong>
                  </p>
                  <button
                    className="rounded-lg border border-emerald-400 px-4 py-2 font-semibold text-emerald-300 transition hover:bg-emerald-400 hover:text-slate-950"
                    onClick={() => aprovarVaga(vaga.id)}
                    type="button"
                  >
                    Aprovar vaga
                  </button>
                </div>
              )}
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}
