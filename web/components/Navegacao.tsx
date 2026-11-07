import Link from "next/link";

import { SimuladoBadge } from "./SimuladoBadge";

export function Navegacao() {
  return (
    <nav className="border-b border-slate-800 bg-slate-950">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
        <Link className="font-bold tracking-tight text-slate-100" href="/">
          Macaxeira Learning
        </Link>
        <div className="flex flex-wrap items-center gap-4 text-sm font-medium">
          <Link className="text-slate-300 hover:text-cyan-300" href="/">
            Vagas
          </Link>
          <Link className="text-slate-300 hover:text-cyan-300" href="/banco">
            Banco de talentos
          </Link>
          <Link className="text-slate-300 hover:text-cyan-300" href="/candidatos">
            Candidatos da vaga
          </Link>
          <SimuladoBadge />
        </div>
      </div>
    </nav>
  );
}
