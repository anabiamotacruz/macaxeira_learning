import type { ReactNode } from "react";

type FeatureIcon = "search" | "message" | "clock" | "shield";

type Feature = {
  icon: FeatureIcon;
  title: string;
  text: string;
};

const features: Feature[] = [
  {
    icon: "search",
    title: "Triagem inteligente",
    text: "A vaga vira critérios claros. A CORA procura no banco de talentos e organiza cada perfil com evidências.",
  },
  {
    icon: "message",
    title: "Primeiro contato automatizado",
    text: "Mensagens respeitam autorização, limites e opt-out. Só continua a conversa quem demonstrou interesse.",
  },
  {
    icon: "clock",
    title: "Mais tempo para o time de RH",
    text: "Menos busca manual e mais tempo para conversar, decidir e cuidar da experiência de cada pessoa.",
  },
  {
    icon: "shield",
    title: "Regras que não mudam",
    text: "Requisitos eliminatórios, privacidade e equidade ficam em regras determinísticas, não no modelo.",
  },
];

function FeatureIcon({ icon }: { icon: FeatureIcon }) {
  const paths: Record<FeatureIcon, ReactNode> = {
    search: (
      <>
        <circle cx="11" cy="11" r="6.5" />
        <path d="m16 16 4 4" />
      </>
    ),
    message: (
      <>
        <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3v-3h0A2.5 2.5 0 0 1 4 12.5z" />
        <path d="M8 8h8M8 11h5" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    shield: (
      <>
        <path d="M12 3 19 6v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" />
        <path d="m9 12 2 2 4-4" />
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
            O que muda para o RH
          </p>
          <h2 className="mt-4 text-4xl font-semibold leading-tight tracking-[-.05em] text-[#163d42] sm:text-5xl">
            Recrutamento que deixa o trabalho mais claro.
          </h2>
          <p className="mt-5 max-w-xl text-lg leading-8 text-[#52716c]">
            A CORA cuida do trabalho operacional e mantém as pessoas no
            controle das decisões importantes.
          </p>
        </div>

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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

        <div className="mt-16 grid gap-8 rounded-[28px] bg-[#e5f0ec] p-7 sm:p-10 lg:grid-cols-[1fr_.8fr] lg:items-center">
          <div>
            <p className="text-xs font-bold uppercase tracking-[.2em] text-[#4c8885]">
              Contexto para a entrevista
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-.04em] text-[#163d42]">
              A Nara recebe o que precisa para investigar melhor.
            </h2>
          </div>
          <p className="text-sm leading-7 text-[#52716c]">
            Cada pessoa entregue vem com fontes, regras aplicadas e lacunas
            para aprofundar. A CORA não entrevista nem decide contratação:
            prepara o próximo passo para uma decisão humana.
          </p>
        </div>
      </div>
    </section>
  );
}
