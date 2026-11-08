"use client";

import { useState } from "react";
import Link from "next/link";

const columns = [
  {
    title: "Analisando",
    count: "62",
    color: "#3a6f6c",
    candidates: [
      ["Camila Nunes", "Python, AWS · 6 anos", ""],
      ["Rafael Lima", "Go, gRPC · 5 anos", ""],
    ],
  },
  {
    title: "Autorização",
    count: "9",
    color: "#c98a12",
    candidates: [
      ["Tiago Moura", "Só recebeu o pedido", "87"],
      ["Júlia Prado", "Autorização a renovar", "83"],
    ],
  },
  {
    title: "Em conversa",
    count: "4",
    color: "#fb3c0d",
    candidates: [
      ["Larissa Rocha", "“Topo conversar”", "92"],
      ["André Sales", "E-mail aberto", "85"],
    ],
  },
  {
    title: "Entregue à Nara",
    count: "2",
    color: "#377b5d",
    candidates: [
      ["Marina Costa", "Dossiê enviado", "90"],
      ["Pedro Alves", "Dossiê enviado", "88"],
    ],
  },
] as const;

export function DemoVideo() {
  const [isPlaying, setIsPlaying] = useState(false);

  return (
    <section className="bg-[#173b40] px-6 py-16 text-white sm:py-20 lg:px-10 lg:py-28" id="demo">
      <div className="mx-auto max-w-[1240px]">
        <div className="mb-10 flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <p className="text-xs font-bold uppercase tracking-[.24em] text-[#ff9b80]">
              Demonstração
            </p>
            <h2 className="mt-3 max-w-2xl text-4xl font-semibold tracking-[-.05em] sm:text-5xl">
              Do briefing ao contexto entregue para a Nara.
            </h2>
          </div>
          <p className="max-w-sm text-sm leading-6 text-[#b8ceca]">
            Uma prévia visual do fluxo da CORA, com evidências, regras e
            decisões visíveis para o time.
          </p>
        </div>

        <div className="relative overflow-hidden rounded-[26px] border border-white/15 bg-[#244d51] shadow-[0_30px_90px_-45px_rgba(0,0,0,.8)]">
          <div className="aspect-video min-h-[360px] bg-[radial-gradient(circle_at_65%_35%,rgba(255,154,124,.32),transparent_30%),linear-gradient(135deg,#295b5b,#173b40)] p-4 sm:p-8 lg:p-10">
            <div className="flex h-full flex-col rounded-xl border border-white/15 bg-[#f7f8f5] text-[#0b3038] shadow-2xl">
              <div className="flex h-11 shrink-0 items-center gap-3 border-b border-[#e4e9e5] bg-white px-3">
                <span className="h-2.5 w-2.5 rounded-full bg-[#fb3c0d]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#e1b34b]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#6ca77e]" />
                <span className="ml-2 text-xs font-semibold text-[#526c68]">CORA · Vaga 014</span>
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3 sm:p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] text-[#5e7672]">Vagas / Backend Sênior</p>
                    <h3 className="mt-1 text-sm font-semibold sm:text-lg">
                      Pessoa Desenvolvedora Backend Sênior
                    </h3>
                  </div>
                  <span className="rounded-full bg-[#fff1cc] px-2 py-1 text-[10px] font-semibold text-[#855a0e]">
                    ● Buscando
                  </span>
                </div>
                <div className="grid min-h-0 flex-1 grid-cols-2 gap-2 overflow-hidden sm:grid-cols-4">
                  {columns.map((column) => (
                    <div className="min-w-0" key={column.title}>
                      <p className="mb-2 flex items-center gap-1 text-[10px] font-medium text-[#526c68]">
                        <i className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: column.color }} />
                        <span className="truncate">{column.title}</span>
                        <small>{column.count}</small>
                      </p>
                      <div className="space-y-2">
                        {column.candidates.map(([name, description, score]) => (
                          <div className="rounded-lg border border-[#e4e9e5] bg-white p-2" key={name}>
                            <p className="flex justify-between gap-1 text-[10px] font-semibold">
                              <span className="truncate">{name}</span>
                              {score ? <b className="text-[#dc3209]">{score}</b> : null}
                            </p>
                            <p className="mt-1 truncate text-[9px] text-[#5e7672]">{description}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="truncate rounded-lg border border-[#e4e9e5] bg-white px-3 py-2 font-mono text-[9px] text-[#2c4f55] sm:text-[10px]">
                  <b className="text-[#2f6e52]">feito</b> · evidência registrada · autorização validada · rastro a91f
                </p>
              </div>
            </div>
          </div>

          <button
            aria-label={isPlaying ? "Pausar prévia da demonstração" : "Reproduzir prévia da demonstração"}
            className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-[#fb3c0d] text-2xl text-white shadow-[0_0_0_12px_rgba(251,60,13,.18)] transition hover:scale-105"
            onClick={() => setIsPlaying((playing) => !playing)}
            type="button"
          >
            <span aria-hidden="true">{isPlaying ? "Ⅱ" : "▶"}</span>
          </button>
          {isPlaying ? (
            <span className="absolute bottom-4 left-4 rounded-full bg-[#0b3038]/85 px-3 py-1 text-xs text-white">
              Prévia em simulação
            </span>
          ) : null}
        </div>

        <div className="mt-8 flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
          <ol className="grid gap-3 text-sm text-[#d0e0dc] sm:grid-cols-4">
            {[
              "Defina o contexto",
              "Encontre evidências",
              "Revise a recomendação",
              "Entregue para a Nara",
            ].map((step, index) => (
              <li className="flex items-center gap-2" key={step}>
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold text-[#ffad95]">
                  {index + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
          <Link className="text-sm font-bold text-[#ffad95] transition hover:text-white" href="/">
            Abrir o painel →
          </Link>
        </div>
      </div>
    </section>
  );
}
