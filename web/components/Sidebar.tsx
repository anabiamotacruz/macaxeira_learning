"use client";

import Image from "next/image";
import Link from "next/link";
import { Menu, Plus, Search, X } from "lucide-react";
import { useState } from "react";

type Props = {
  active?: "catalogo" | "banco" | "empresa" | "criar";
  count?: number;
};

const links = [
  { key: "catalogo", href: "/", label: "Vagas" },
  { key: "banco", href: "/banco", label: "Banco de talentos" },
  { key: "empresa", href: "/empresa", label: "Empresa" },
] as const;

export function Sidebar({ active }: Props) {
  const [menuAberto, setMenuAberto] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-[#e4e9e5] bg-white/95 backdrop-blur">
      <nav aria-label="Principal" className="mx-auto flex min-h-[60px] max-w-[1240px] flex-wrap items-center gap-5 px-5 sm:px-6">
        <Link className="flex shrink-0 items-center gap-2 text-[#0b3038]" href="/">
          <Image alt="Coral da CORA" className="h-7 w-7 object-contain" height={29} src="/coral.png" width={28} />
          <span className="text-lg font-semibold tracking-[-0.03em]">CORA</span>
        </Link>
        <div className="hidden items-center gap-1 min-[861px]:flex">
          {links.map((link) => (
            <Link
              aria-current={active === link.key ? "page" : undefined}
              className={`rounded-lg px-3 py-1.5 text-sm ${active === link.key ? "bg-[#eef2ef] font-semibold text-[#0b3038]" : "font-medium text-[#526c68] hover:bg-[#f1f4f2]"}`}
              href={link.href}
              key={link.key}
            >
              {link.label}
            </Link>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <label className="hidden h-9 w-[240px] items-center gap-2 rounded-lg bg-[#f1f4f2] px-2.5 text-[#526c68] min-[861px]:flex">
            <Search aria-hidden="true" size={15} />
            <span className="sr-only">Buscar pessoas ou vagas</span>
            <input aria-label="Buscar pessoas ou vagas" className="min-w-0 flex-1 bg-transparent text-[13px] text-[#0b3038] outline-none placeholder:text-[#5e7672]" placeholder="Buscar pessoas ou vagas" type="search" />
            <kbd className="rounded border border-[#dfe6e1] bg-white px-1.5 font-mono text-[11px]">⌘K</kbd>
          </label>
          <Link className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#dc3209] px-3.5 text-sm font-semibold text-white shadow-[0_3px_7px_rgba(251,60,13,.22)] hover:bg-[#c42c08]" href="/vagas/proposta">
            <Plus aria-hidden="true" size={15} />
            Criar vaga
          </Link>
          <button aria-label={menuAberto ? "Fechar menu" : "Abrir menu"} className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#dfe6e1] bg-white text-[#0b3038] min-[861px]:hidden" onClick={() => setMenuAberto((aberto) => !aberto)} type="button">
            {menuAberto ? <X size={18} /> : <Menu size={18} />}
          </button>
          <button aria-label="Conta de Ana Ribeiro" className="flex h-8 w-8 items-center justify-center rounded-full border-0 bg-[#0b3038] text-xs font-semibold text-white" type="button">AR</button>
        </div>
        {menuAberto && <div className="order-3 flex w-full flex-col gap-1 border-t border-[#edf1ee] py-3 min-[861px]:hidden">{links.map((link) => <Link className={`rounded-lg px-3 py-2 text-sm ${active === link.key ? "bg-[#eef2ef] font-semibold text-[#0b3038]" : "text-[#526c68]"}`} href={link.href} key={link.key} onClick={() => setMenuAberto(false)}>{link.label}</Link>)}</div>}
      </nav>
    </header>
  );
}
