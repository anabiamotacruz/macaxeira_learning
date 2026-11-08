import Link from "next/link";

type Props = {
  active?: "catalogo" | "banco" | "empresa" | "criar";
  count?: number;
};

function Icon({ name }: { name: "grid" | "briefcase" | "people" | "building" | "plus" }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 1.8,
  };
  if (name === "building") {
    return <svg aria-hidden="true" className="h-[18px] w-[18px]" viewBox="0 0 16 16"><path {...common} d="M3 14V3.5L8 2v12M8 5h5v9M5 5.5h1M5 8h1M5 10.5h1M10 7h1M10 9.5h1M10 12h1M1.5 14h13" /></svg>;
  }
  if (name === "plus") {
    return <svg aria-hidden="true" className="h-[18px] w-[18px]" viewBox="0 0 16 16"><path {...common} d="M8 3v10M3 8h10" /></svg>;
  }
  if (name === "briefcase") {
    return <svg aria-hidden="true" className="h-[18px] w-[18px]" viewBox="0 0 16 16"><rect {...common} height="8" rx="1.5" width="13" x="2.5" y="5.5" /><path {...common} d="M6 5.5V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1.5M2.5 9h13" /></svg>;
  }
  if (name === "people") {
    return <svg aria-hidden="true" className="h-[18px] w-[18px]" viewBox="0 0 16 16"><circle {...common} cx="6" cy="5" r="2" /><circle {...common} cx="11" cy="5.5" r="1.6" /><path {...common} d="M2.5 13c.3-2 1.5-3 3.5-3s3.2 1 3.5 3M9 10.5c2.4-.7 4.2.3 4.5 2.5" /></svg>;
  }
  return <svg aria-hidden="true" className="h-[18px] w-[18px]" viewBox="0 0 16 16"><rect {...common} height="4" rx="1" width="4" x="2" y="2" /><rect {...common} height="4" rx="1" width="4" x="10" y="2" /><rect {...common} height="4" rx="1" width="4" x="2" y="10" /><rect {...common} height="4" rx="1" width="4" x="10" y="10" /></svg>;
}

function Item({ href, label, icon, active, count }: { href: string; label: string; icon: Parameters<typeof Icon>[0]["name"]; active: boolean; count?: number }) {
  return <Link className={`flex items-center gap-4 rounded-lg px-4 py-3 text-sm ${active ? "bg-[#fb3c0d] font-semibold text-white shadow-[0_0_0_2px_rgba(255,255,255,.9)]" : "text-[#d0d6d5] hover:bg-white/10"}`} href={href}><Icon name={icon} />{label}{count !== undefined && <span className="ml-auto rounded-full bg-white/20 px-2 py-0.5 text-[11px]">{count}</span>}</Link>;
}

export function Sidebar({ active, count }: Props) {
  return <aside className="fixed inset-y-0 left-0 z-20 hidden w-[238px] flex-col bg-[#5b5b5b] text-white md:flex">
    <div className="px-7 pb-10 pt-8"><div className="flex items-start gap-2"><img alt="Coral da CORA" className="h-10 w-10 shrink-0 object-contain" src="/coral.png" /><div><p className="text-[22px] font-semibold leading-none tracking-tight">CORA</p><p className="mt-1 max-w-[145px] text-[7px] font-medium uppercase leading-[1.25] tracking-wide text-[#d3d5d3]">Conexão de Oportunidade<br />de Recrutamento Ativo</p></div></div></div>
    <nav className="space-y-1 px-2">
      <Item active={active === "catalogo"} count={count} href="/" icon="briefcase" label="Catálogo de vagas" />
      <Item active={active === "criar"} href="/criar-vaga" icon="plus" label="Criar vaga" />
      <Item active={active === "banco"} href="/banco" icon="people" label="Banco de talentos" />
      <Item active={active === "empresa"} href="/empresa" icon="building" label="Perfil da empresa" />
    </nav>
    <div className="mt-auto px-3 pb-5"><div className="rounded-xl border border-[#d47c68]/50 bg-[#6b5b5a] px-4 py-3"><p className="flex items-center gap-2 text-xs font-semibold"><span className="text-[#ff6a46]">✓</span> Busca responsável</p><p className="mt-1 pl-5 text-[10px] text-[#c5c6c5]">Privacidade por padrão</p></div><div className="mt-4 flex items-center gap-3 border-t border-white/10 pt-4"><span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#fb3c0d] text-[11px] font-bold">AR</span><div><p className="text-xs font-semibold">Ana Ribeiro</p><p className="mt-1 text-[10px] text-[#c6ccca]">People Partner</p></div><span className="ml-auto text-lg text-[#b8c0bd]">•••</span></div></div>
  </aside>;
}
