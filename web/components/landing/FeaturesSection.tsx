import type { ReactNode } from "react";

type FeatureIcon = "spark" | "message" | "database";

type Feature = {
  icon: FeatureIcon;
  title: string;
  text: string;
};

const features: Feature[] = [
  {
    icon: "spark",
    title: "Trabalha enquanto você entrevista",
    text: "Enquanto você conversa com uma pessoa, a CORA busca outras, compara evidências e mantém a vaga andando.",
  },
  {
    icon: "message",
    title: "Conversa como gente, não como robô",
    text: "A CORA faz o primeiro contato, responde dúvidas e entrega para a Nara quem realmente quer conversar.",
  },
  {
    icon: "database",
    title: "Seu banco de talentos sempre em dia",
    text: "Cada autorização, conversa e evidência volta para o banco. A próxima vaga começa mais inteligente.",
  },
];

function FeatureIcon({ icon }: { icon: FeatureIcon }) {
  const paths: Record<FeatureIcon, ReactNode> = {
    spark: (
      <>
        <path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z" />
        <path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z" />
      </>
    ),
    message: (
      <>
        <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3v-3h0A2.5 2.5 0 0 1 4 12.5z" />
        <path d="M8 8h8M8 11h5" />
      </>
    ),
    database: (
      <>
        <ellipse cx="12" cy="6" rx="7.5" ry="3" />
        <path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
      </>
    ),
  };

  return (
    <svg aria-hidden="true" className="h-6 w-6" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24">
      {paths[icon]}
    </svg>
  );
}

export function FeaturesSection() {
  return (
    <section className="bg-[#f7f8f3] px-6 py-20 lg:px-10 lg:py-28" id="como-funciona">
      <div className="mx-auto max-w-[1240px]">
        <div className="max-w-2xl">
          <p className="text-xs font-bold uppercase tracking-[.24em] text-[#dc3209]">
            O amigo favorito do seu RH
          </p>
          <h2 className="mt-4 text-4xl font-semibold leading-tight tracking-[-.05em] text-[#163d42] sm:text-5xl">
            A CORA fica trabalhando enquanto seu time faz o que só gente pode fazer.
          </h2>
          <p className="mt-5 max-w-xl text-lg leading-8 text-[#52716c]">
            Menos busca manual, mais contexto e decisões melhores no momento
            certo.
          </p>
        </div>

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {features.map((feature) => (
            <article className="rounded-2xl border border-[#dfe8e2] bg-white p-6 transition hover:-translate-y-1 hover:shadow-[0_16px_30px_-24px_rgba(11,48,56,.55)]" key={feature.title}>
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#e8eeea] text-[#dc3209]">
                <FeatureIcon icon={feature.icon} />
              </span>
              <h3 className="mt-8 text-lg font-semibold leading-tight text-[#23484c]">
                {feature.title}
              </h3>
              <p className="mt-3 text-sm leading-6 text-[#718783]">{feature.text}</p>
            </article>
          ))}
        </div>

      </div>
    </section>
  );
}
