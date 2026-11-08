import Link from "next/link";

const suggestedBriefings = [
  "Backend sênior remoto",
  "Designer em Recife",
  "Reativar o banco",
  "Dados com dbt",
];

export function HeroSection() {
  return (
    <section className="bg-[#f7f8f5]" id="inicio">
      <div className="mx-auto flex max-w-[1240px] flex-col items-center gap-5 px-6 pb-12 pt-16 text-center sm:pt-20 lg:pb-20 lg:pt-24">
        <p className="text-xs font-bold uppercase tracking-[.24em] text-[#dc3209]">
          Sourcing ativo para times de RH
        </p>
        <h1 className="max-w-5xl text-[clamp(42px,6vw,78px)] font-semibold leading-[.98] tracking-[-.05em] text-[#0b3038]">
          Diga a vaga.
          <br />
          <span className="text-[#fb3c0d]">A CORA traz as pessoas.</span>
        </h1>
        <p className="max-w-[680px] text-lg leading-8 text-[#526c68] sm:text-xl">
          Reduza o trabalho manual do recrutamento: a CORA encontra perfis,
          explica cada escolha, faz o primeiro contato e entrega à Nara o
          contexto para a entrevista.
        </p>

        <div className="mt-3 w-full max-w-[760px] rounded-xl border border-[#dfe6e1] bg-white text-left shadow-[0_1px_2px_rgba(11,48,56,.06),0_20px_40px_-24px_rgba(11,48,56,.28)]">
          <label
            className="block px-4 pt-4 text-sm font-medium text-[#526c68]"
            htmlFor="briefing"
          >
            Descreva a vaga como falaria com alguém do time
          </label>
          <textarea
            className="block min-h-[112px] w-full resize-none border-0 bg-transparent px-4 py-2 text-lg leading-7 text-[#0b3038] outline-none placeholder:text-[#9aada8]"
            id="briefing"
            placeholder="Ex.: Busco uma pessoa engenheira backend sênior..."
          />
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#edf1ee] px-4 py-3">
            <span className="text-xs text-[#5e7672]">
              Você aprova os critérios antes de qualquer contato
            </span>
            <Link
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#dc3209] px-4 text-sm font-semibold text-white transition hover:bg-[#c42c08]"
              href="/vagas/proposta"
            >
              Abra sua primeira vaga <span aria-hidden="true">→</span>
            </Link>
          </div>
        </div>

        <div className="flex max-w-[900px] flex-wrap justify-center gap-2">
          {suggestedBriefings.map((briefing) => (
            <Link
              className="rounded-full border border-[#dfe6e1] bg-white px-3 py-1.5 text-xs text-[#526c68] transition hover:bg-[#eef2ef]"
              href="/vagas/proposta"
              key={briefing}
            >
              {briefing}
            </Link>
          ))}
        </div>
        <p className="text-xs text-[#5e7672]">
          Dados sintéticos e simulação identificada nesta demonstração
        </p>
      </div>
    </section>
  );
}
