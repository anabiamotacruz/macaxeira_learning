import Image from "next/image";
import Link from "next/link";

import { DemoVideo } from "@/components/landing/DemoVideo";
import { FeaturesSection } from "@/components/landing/FeaturesSection";
import { FooterCTA } from "@/components/landing/FooterCTA";
import { HeroSection } from "@/components/landing/HeroSection";

const navigation = [
  { label: "Como funciona", href: "#como-funciona" },
  { label: "Demonstração", href: "#demo" },
  { label: "Evidências", href: "#evidencias" },
  { label: "Regras", href: "#regras" },
];

export default function LandingPage() {
  return (
    <main className="bg-[#f7f8f5] text-[#0b3038]">
      <header className="border-b border-[#e4e9e5] bg-white/80">
        <nav className="mx-auto flex max-w-[1240px] items-center justify-between gap-4 px-6 py-3.5">
          <Link className="flex items-center gap-2" href="/landing">
            <Image
              alt="Coral da CORA"
              className="h-9 w-9 object-contain"
              height={37}
              src="/coral.png"
              width={36}
            />
            <span className="flex flex-col">
              <span className="text-[21px] font-semibold leading-none tracking-[-.03em]">
                CORA
              </span>
              <span className="mt-1 text-[10px] text-[#5e7672]">
                Recrutamento ativo
              </span>
            </span>
          </Link>

          <div className="hidden gap-7 text-sm text-[#526c68] lg:flex">
            {navigation.map((item) => (
              <a className="transition hover:text-[#dc3209]" href={item.href} key={item.href}>
                {item.label}
              </a>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <Link
              className="hidden h-10 items-center rounded-lg border border-[#dfe6e1] bg-white px-3.5 text-sm font-medium transition hover:border-[#b8cbc4] sm:inline-flex"
              href="/"
            >
              Entrar
            </Link>
            <Link
              className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-[#dc3209] px-3.5 text-sm font-semibold text-white shadow-[0_3px_7px_rgba(251,60,13,.22)] transition hover:bg-[#c42c08]"
              href="/criar-vaga"
            >
              <span aria-hidden="true" className="text-lg leading-none">+</span>
              Criar vaga
            </Link>
          </div>
        </nav>
      </header>

      <HeroSection />
      <DemoVideo />
      <FeaturesSection />
      <FooterCTA />
    </main>
  );
}
