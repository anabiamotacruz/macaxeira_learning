"use client";

import Link from "next/link";
import { useState } from "react";

import { SimuladoBadge } from "./SimuladoBadge";

export type SecaoApp = "vagas" | "banco" | "empresa";

const LINKS: Array<{ secao: SecaoApp; href: string; rotulo: string }> = [
  { secao: "vagas", href: "/", rotulo: "Vagas" },
  { secao: "banco", href: "/banco", rotulo: "Banco de talentos" },
  { secao: "empresa", href: "/empresa", rotulo: "Empresa" },
];

/** Cabeçalho do app no design CORA: logo, navegação em pílulas, busca e "Criar vaga". */
export function AppHeader({ ativo, aoBuscar }: { ativo?: SecaoApp; aoBuscar?: (termo: string) => void }) {
  const [menuAberto, setMenuAberto] = useState(false);
  return (
    <header className="sticky top-0 z-10 h-[60px] border-b border-cora-line bg-cora-surface">
      <div className="mx-auto flex h-full max-w-[1240px] items-center gap-3 px-4 sm:gap-5 sm:px-6">
        <Link className="flex shrink-0 items-center gap-2 text-cora-ink no-underline" href="/">
          <img alt="" className="h-[29px] w-7 object-contain" height={29} src="/coral.png" width={28} />
          <span className="text-lg font-semibold tracking-[-0.03em]">CORA</span>
        </Link>
        <nav aria-label="Principal" className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <Link
              aria-current={ativo === l.secao ? "page" : undefined}
              className={`rounded-lg px-3 py-1.5 text-sm no-underline ${
                ativo === l.secao
                  ? "bg-cora-muted-bg font-semibold text-cora-ink"
                  : "font-medium text-cora-muted hover:bg-cora-subtle"
              }`}
              href={l.href}
              key={l.secao}
            >
              {l.rotulo}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2.5">
          <span className="hidden sm:inline-flex"><SimuladoBadge /></span>
          {aoBuscar && (
            <label className="hidden h-9 w-60 items-center gap-2 rounded-lg bg-cora-subtle pl-2.5 pr-2 text-cora-muted md:flex">
              <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="15"><circle cx="7" cy="7" r="4.3" /><path d="m10.4 10.4 3.1 3.1" /></svg>
              <span className="sr-only">Buscar pessoas ou vagas</span>
              <input
                className="min-w-0 flex-1 border-0 bg-transparent text-[13px] text-cora-ink outline-none"
                onChange={(e) => aoBuscar(e.target.value)}
                placeholder="Buscar pessoas ou vagas"
                type="search"
              />
            </label>
          )}
          <Link className="cora-btn cora-btn-primary" href="/criar-vaga">
            <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="15"><path d="M8 3v10M3 8h10" /></svg>
            <span className="hidden sm:inline">Criar vaga</span>
            <span className="sr-only sm:hidden">Criar vaga</span>
          </Link>
          <button
            aria-expanded={menuAberto}
            aria-label="Abrir menu"
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-cora-line-2 bg-cora-surface md:hidden"
            onClick={() => setMenuAberto((v) => !v)}
            type="button"
          >
            <svg aria-hidden="true" fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="18"><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" /></svg>
          </button>
          <span aria-label="Conta de Ana Ribeiro" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-cora-ink text-xs font-semibold text-white" role="img">AR</span>
        </div>
      </div>
      {menuAberto && (
        <nav aria-label="Principal (celular)" className="border-b border-cora-line bg-cora-surface px-6 py-2 md:hidden">
          {LINKS.map((l) => (
            <Link className="block rounded-lg px-3 py-2 text-sm text-cora-ink" href={l.href} key={l.secao} onClick={() => setMenuAberto(false)}>
              {l.rotulo}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

/** Corpo padrão das telas: largura máxima de 1240px e espaçamento do design. */
export function AppMain({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-6 pb-14 pt-8">{children}</main>;
}
