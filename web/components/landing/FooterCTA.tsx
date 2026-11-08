import Image from "next/image";
import Link from "next/link";

export function FooterCTA() {
  return (
    <>
      <section className="bg-[#dc3209] px-6 py-24 text-white sm:py-28" id="regras">
        <div className="mx-auto flex max-w-[1100px] flex-col items-center gap-6 text-center">
          <p className="text-xs font-bold uppercase tracking-[.24em] text-[#ffd0c3]">
            Próximo passo
          </p>
          <h2 className="max-w-4xl text-[clamp(40px,5.6vw,76px)] font-semibold leading-[.98] tracking-[-.05em]">
            Abra sua primeira vaga hoje.
          </h2>
          <p className="max-w-xl text-lg leading-7 text-[#ffe3dc]">
            Comece com uma vaga e veja como a CORA transforma busca em
            contexto pronto para o time.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <Link
              className="rounded-lg bg-white px-5 py-3 font-semibold text-[#0b3038] transition hover:bg-[#fff1ea]"
              href="/criar-vaga"
            >
              Abra sua primeira vaga
            </Link>
            <Link
              className="rounded-lg border border-white/70 px-5 py-3 font-medium transition hover:bg-white/10"
              href="/"
            >
              Acessar o painel
            </Link>
          </div>
        </div>
      </section>

      <footer className="bg-[#0b3038] text-[#b4c7c3]">
        <div className="mx-auto flex max-w-[1240px] flex-col gap-8 px-6 py-10 text-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Image
              alt="Coral da CORA"
              className="h-8 w-8 object-contain"
              height={32}
              src="/coral.png"
              width={32}
            />
            <div>
              <p className="font-semibold text-white">CORA</p>
              <p className="text-xs">Recrutamento ativo</p>
            </div>
          </div>
          <p>Dados sintéticos · Simulação identificada · Decisão humana</p>
          <Link className="font-semibold transition hover:text-white" href="/">
            Acessar painel
          </Link>
        </div>
      </footer>
    </>
  );
}
