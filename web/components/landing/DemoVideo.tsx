import Image from "next/image";

type Scene = {
  time: string;
  title: string;
  details: ReadonlyArray<readonly [string, string]>;
  accent?: boolean;
};

const scenes: readonly Scene[] = [
  {
    time: "0:00 – 0:12",
    title: "1 · Abertura",
    details: [
      ["Tela", "fundo claro, uma frase digitada letra a letra."],
      ["Na tela", "“Encontrar a pessoa certa leva semanas. E se levasse uma tarde?”"],
      ["Corte", "o catálogo de vagas da CORA, com a recrutadora logada."],
    ],
  },
  {
    time: "0:12 – 0:35",
    title: "2 · Criar vaga",
    details: [
      ["Ação", "clica em “Criar vaga”, descreve a vaga em uma frase e aprova os critérios que a CORA propôs."],
      ["Destaque", "adiciona 3 empresas com contrato de fidelidade à blacklist."],
      ["Legenda", "“Clientes com contrato nunca são abordados.”"],
    ],
  },
  {
    time: "0:35 – 0:55",
    title: "3 · Hunting",
    details: [
      ["Tela", "painel da vaga com a CORA trabalhando: banco, LinkedIn, blacklist, eliminatórios."],
      ["Zoom", "“41 perfis ignorados pela blacklist”."],
      ["Legenda", "“Primeiro no seu banco. Depois no mercado.”"],
    ],
  },
  {
    time: "0:55 – 1:20",
    title: "4 · Perfis e nota",
    details: [
      ["Tela", "lista com e-mail, nota e situação: autorizada, aguardando, descartada."],
      ["Ação", "abre a Larissa e mostra a nota por critério e a evidência."],
      ["Legenda", "“Cada nota tem um porquê.”"],
    ],
  },
  {
    time: "1:20 – 1:38",
    title: "5 · Aprovação e e-mail",
    details: [
      ["Ação", "clica em “Aprovar 5 convites”. Corte para a caixa de entrada da Larissa."],
      ["Tela", "o e-mail chega com o porquê da escolha e o botão para o WhatsApp."],
      ["Legenda", "“Você aprova. A CORA escreve.”"],
    ],
  },
  {
    time: "1:38 – 2:05",
    title: "6 · Conversa",
    details: [
      ["Tela", "WhatsApp no celular. A Larissa pergunta, a CORA responde e anota o que importa."],
      ["Virada", "ela topa, recebe o link da Nara e o horário aparece marcado."],
      ["Legenda", "“Conversa como gente, não como robô.”"],
    ],
  },
  {
    time: "2:05 – 2:22",
    title: "7 · Dossiê",
    details: [
      ["Tela", "o dossiê que a Nara recebe para a entrevista de people."],
      ["Zoom", "“O que ela contou” e “Para aprofundar”."],
      ["Legenda", "“A entrevista começa sabendo o que importa.”"],
    ],
  },
  {
    time: "2:22 – 2:30",
    title: "8 · Encerramento",
    accent: true,
    details: [
      ["Tela", "fundo branco, o logo do coral cresce, nome e frase."],
      ["Na tela", "“Diga a vaga. A CORA traz as pessoas.”"],
      ["Rodapé", "Desafio Tako · cora-rh.vercel.app"],
    ],
  },
];

export function DemoVideo() {
  return (
    <section className="bg-[#f7f8f5] px-6 py-20 text-[#0b3038] lg:px-10 lg:py-28" id="conversa">
      <div className="mx-auto max-w-[1240px]">
        <div className="flex flex-col gap-7">
          <div className="flex flex-col items-start justify-between gap-6 lg:flex-row lg:items-end">
            <div className="flex items-center gap-4">
              <Image alt="" className="h-12 w-12 object-contain sm:h-14 sm:w-14" height={58} src="/coral.png" width={56} />
              <h2 className="max-w-3xl text-4xl font-semibold leading-[1.02] tracking-[-.05em] sm:text-5xl lg:text-[52px]">
                Da vaga à entrevista marcada, sem a recrutadora sair da cadeira.
              </h2>
            </div>
            <p className="max-w-[620px] text-base leading-7 text-[#526c68] lg:text-right">
              Vídeo de 2:30. Uma pessoa usa a CORA como recrutadora de verdade:
              cada cena é um clique dela e a CORA respondendo.
            </p>
          </div>

          <div aria-hidden="true" className="flex h-2 gap-1 overflow-hidden rounded-full">
            {scenes.map((scene, index) => (
              <span
                className="h-full"
                key={scene.title}
                style={{
                  backgroundColor: index === 0 || index === scenes.length - 1
                    ? "#0b3038"
                    : index < 4
                      ? "#fb3c0d"
                      : "#3a6f6c",
                  flex: index === 0 ? 12 : index === 1 ? 23 : index === 2 ? 20 : index === 3 ? 25 : index === 4 ? 18 : index === 5 ? 27 : index === 6 ? 17 : 8,
                }}
              />
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
            {scenes.map((scene) => (
              <article
                className={`flex min-h-[310px] flex-col gap-3 rounded-[14px] border p-5 ${
                  scene.accent
                    ? "border-[#f0b5aa] bg-[#fff1ee]"
                    : "border-[#dfe6e1] bg-white"
                }`}
                key={scene.title}
              >
                <span className={`font-mono text-xs ${scene.accent ? "text-[#a43826]" : "text-[#5e7672]"}`}>
                  {scene.time}
                </span>
                <h3 className="text-xl font-bold tracking-[-.03em]">{scene.title}</h3>
                <div className="flex flex-col gap-3 text-sm leading-6 text-[#2c4f55]">
                  {scene.details.map(([label, text]) => (
                    <p key={label}>
                      <b>{label}:</b> {text}
                    </p>
                  ))}
                </div>
              </article>
            ))}
          </div>

          <p className="text-xs text-[#5e7672]">
            Prévia visual · Dados sintéticos · Simulação identificada
          </p>
        </div>
      </div>
    </section>
  );
}
