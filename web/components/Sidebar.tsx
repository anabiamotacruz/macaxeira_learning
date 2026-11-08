import Image from "next/image";
import Link from "next/link";

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
  return (
    <header className="sticky top-0 z-30 border-b border-[#e4e9e5] bg-white/95 backdrop-blur">
      <nav aria-label="Principal" className="mx-auto flex h-[60px] max-w-[1240px] items-center gap-5 px-5 sm:px-6">
        <Link className="flex shrink-0 items-center gap-2 text-[#0b3038]" href="/">
          <Image alt="Coral da CORA" className="h-7 w-7 object-contain" height={29} src="/coral.png" width={28} />
          <span className="text-lg font-semibold tracking-[-0.03em]">CORA</span>
        </Link>
        <div className="hidden items-center gap-1 md:flex">
          {links.map((link) => (
            <Link
              className={`rounded-lg px-3 py-1.5 text-sm ${active === link.key ? "bg-[#eef2ef] font-semibold text-[#0b3038]" : "font-medium text-[#526c68] hover:bg-[#f1f4f2]"}`}
              href={link.href}
              key={link.key}
            >
              {link.label}
            </Link>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Link className="hidden h-9 items-center gap-1.5 rounded-lg bg-[#dc3209] px-3.5 text-sm font-semibold text-white shadow-[0_3px_7px_rgba(251,60,13,.22)] hover:bg-[#c42c08] sm:inline-flex" href="/criar-vaga">
            <span aria-hidden="true" className="text-base leading-none">+</span>
            Criar vaga
          </Link>
          <button aria-label="Conta de Ana Ribeiro" className="flex h-8 w-8 items-center justify-center rounded-full border-0 bg-[#0b3038] text-xs font-semibold text-white" type="button">AR</button>
        </div>
      </nav>
    </header>
  );
}
