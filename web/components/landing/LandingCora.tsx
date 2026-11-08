import { ArrowUp, Plus } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { DemoConversa } from "./DemoConversa";
import { Hero } from "./Hero";
import { Situacoes } from "./Situacoes";

const BTN_PRIMARIO = "font-semibold hover:bg-cora-primary-hover";
const BTN_CONTORNO = "border-cora-line-2 bg-cora-surface text-cora-ink shadow-none hover:bg-cora-muted-bg dark:bg-cora-surface";

function Logo({ tamanho = 36 }: { tamanho?: number }) {
  return (
    <Image
      alt=""
      className="object-contain"
      height={Math.round(tamanho * 1.03)}
      src="/coral.png"
      style={{ width: tamanho, height: Math.round(tamanho * 1.03) }}
      width={tamanho}
    />
  );
}

function Cabecalho() {
  const links: Array<[string, string]> = [
    ["#como", "Como funciona"],
    ["#situacoes", "Situações"],
    ["#blacklist", "Blacklist"],
    ["#conversa", "Conversa"],
    ["#regras", "Regras"],
  ];
  return (
    <header className="border-b border-cora-line bg-white/70">
      <nav aria-label="Principal" className="mx-auto flex max-w-[1240px] items-center justify-between gap-4 px-6 py-3.5">
        <a className="flex items-center gap-2 no-underline" href="#topo">
          <Logo />
          <span className="flex flex-col">
            <span className="text-[21px] font-semibold leading-none tracking-[-0.03em]">CORA</span>
            <span className="mt-[3px] text-[10px] text-cora-placeholder max-sm:hidden">Recrutamento ativo</span>
          </span>
        </a>
        <div className="flex gap-[30px] text-sm max-[860px]:hidden">
          {links.map(([href, rotulo]) => (
            <a className="text-cora-muted no-underline hover:text-cora-primary" href={href} key={href}>
              {rotulo}
            </a>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Button asChild className={cn("h-10 max-sm:hidden", BTN_CONTORNO)} variant="outline">
            <Link href="/vagas">Entrar</Link>
          </Button>
          <Button asChild className={cn("h-10 shadow-[0_3px_7px_rgba(251,60,13,0.22)]", BTN_PRIMARIO)}>
            <Link href="/criar-vaga">
              <Plus aria-hidden />
              Criar vaga
            </Link>
          </Button>
        </div>
      </nav>
    </header>
  );
}

type CartaoQuadro = { nome: string; linha: string; nota?: string; destaque?: string; tom?: "verde" | "agente" | "texto"; foco?: boolean };

const COLUNAS: Array<{ titulo: string; total: string; cor: string; cartoes: CartaoQuadro[]; resto?: string }> = [
  {
    titulo: "Analisando",
    total: "62",
    cor: "bg-[#3A6F6C]",
    cartoes: [
      { nome: "Camila Nunes", linha: "Python, AWS · 6 anos", destaque: "Lendo evidências…", tom: "agente" },
      { nome: "Rafael Lima", linha: "Go, gRPC · 5 anos", destaque: "Revisor conferindo", tom: "agente" },
    ],
    resto: "+ 60 na fila",
  },
  {
    titulo: "Aguardando autorização",
    total: "9",
    cor: "bg-[#C98A12]",
    cartoes: [
      { nome: "Tiago Moura", nota: "87", linha: "Só recebeu o pedido de autorização" },
      { nome: "Júlia Prado", nota: "83", linha: "Autorização vencida · renovar" },
    ],
  },
  {
    titulo: "Em conversa",
    total: "4",
    cor: "bg-cora-accent",
    cartoes: [
      { nome: "Larissa Rocha", nota: "92", linha: "“Topo conversar. Remoto mesmo?”", destaque: "WhatsApp · agora", tom: "texto", foco: true },
      { nome: "André Sales", nota: "85", linha: "E-mail aberto · sem resposta" },
    ],
  },
  {
    titulo: "Entregue ao recrutador",
    total: "2",
    cor: "bg-[#377B5D]",
    cartoes: [
      { nome: "Marina Costa", nota: "90", linha: "Entrevista qui, 14h · dossiê enviado", tom: "verde" },
      { nome: "Pedro Alves", nota: "88", linha: "Entrevista sex, 10h · dossiê enviado", tom: "verde" },
    ],
  },
];

function Quadro() {
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[800px] grid-cols-4 gap-3">
        {COLUNAS.map((col) => (
          <div className="flex flex-col gap-2" key={col.titulo}>
            <span className="flex items-center gap-1.5 text-xs font-medium text-cora-muted">
              <span className={cn("size-[7px] rounded-full", col.cor)} />
              {col.titulo} <span className="num text-cora-placeholder">{col.total}</span>
            </span>
            {col.cartoes.map((c) => (
              <Card
                className={cn(
                  "gap-[3px] rounded-[10px] px-3 py-2.5 shadow-none",
                  c.foco && "gap-[5px] border-[#F0B5AA] shadow-[0_0_0_3px_#FFF1EE]",
                )}
                key={c.nome}
              >
                <span className="flex justify-between">
                  <span className="text-[13px] font-semibold">{c.nome}</span>
                  {c.nota && <span className="num text-[13px] font-bold text-cora-primary">{c.nota}</span>}
                </span>
                <span
                  className={cn(
                    "text-xs",
                    c.tom === "verde" ? "text-cora-ok-ink" : c.tom === "texto" ? "text-cora-ink-2" : "text-cora-placeholder",
                  )}
                >
                  {c.linha}
                </span>
                {c.destaque && (
                  <span className={cn(c.tom === "agente" ? "text-xs text-[#3A6F6C]" : "text-[11px] text-cora-placeholder")}>{c.destaque}</span>
                )}
              </Card>
            ))}
            {col.resto && (
              <div className="rounded-[10px] border border-dashed border-[#D0D9D4] px-3 py-2.5 text-xs text-cora-placeholder">{col.resto}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ProdutoAoVivo() {
  return (
    <section aria-label="A CORA trabalhando numa vaga" className="mx-auto max-w-[1240px] px-6 pb-[72px] pt-2" id="produto">
      <div className="rounded-2xl bg-[#E8EEEA] p-[clamp(10px,3vw,40px)]">
        <div className="flex min-h-[560px] flex-col overflow-hidden rounded-xl border border-[#DCE5E0] bg-cora-bg shadow-[0_30px_60px_-40px_rgba(11,48,56,0.5)]">
          <div className="flex h-14 items-center gap-4 border-b border-cora-line bg-white px-[18px]">
            <span className="flex items-center gap-1.5">
              <Logo tamanho={24} />
              <span className="text-base font-semibold tracking-[-0.03em]">CORA</span>
            </span>
            <span className="flex gap-0.5 text-[13px] max-[860px]:hidden">
              <span className="rounded-lg bg-cora-muted-bg px-[11px] py-[5px] font-semibold">Vagas</span>
              <span className="px-[11px] py-[5px] text-cora-muted">Banco de talentos</span>
              <span className="px-[11px] py-[5px] text-cora-muted">Empresa</span>
            </span>
            <span className="ml-auto flex h-8 w-[220px] items-center justify-between rounded-lg bg-cora-subtle px-2.5 text-xs text-cora-placeholder max-[860px]:hidden">
              Buscar pessoas ou vagas
              <span className="rounded border border-cora-line-2 bg-white px-1.5 py-px text-[11px]">⌘K</span>
            </span>
            <span className="inline-flex h-8 items-center rounded-lg bg-cora-primary px-3 text-[13px] font-semibold text-white max-[860px]:ml-auto">
              Criar vaga
            </span>
            <Avatar className="size-[30px]">
              <AvatarFallback className="bg-cora-ink text-[11px] font-semibold text-white">AR</AvatarFallback>
            </Avatar>
          </div>

          <div className="flex min-w-0 flex-1 flex-col gap-4 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-cora-placeholder">Vagas / Backend Sênior</span>
                <span className="text-[22px] font-semibold tracking-[-0.03em]">Pessoa Desenvolvedora Backend Sênior</span>
                <span className="text-[13px] text-cora-placeholder">Meta: 5 pessoas entregues ao recrutador em 7 dias · 2 de 5 entregues</span>
              </div>
              <Badge className="bg-cora-warn-bg px-2.5 py-[3px] font-semibold text-cora-warn-ink">
                <span className="size-1.5 rounded-full bg-[#C98A12]" />
                Buscando
              </Badge>
            </div>

            <div aria-label="Visualização" className="flex gap-[22px] border-b border-cora-line text-[13px]" role="tablist">
              {["Quadro", "Lista", "Rastro", "Critérios"].map((aba, i) => (
                <span
                  aria-selected={i === 0}
                  className={cn("pb-[9px]", i === 0 ? "-mb-px border-b-2 border-cora-accent font-semibold" : "text-cora-muted")}
                  key={aba}
                  role="tab"
                >
                  {aba}
                </span>
              ))}
            </div>

            <Quadro />

            <Card className="mt-auto gap-0 rounded-[10px] px-3.5 py-3 font-mono text-xs leading-[1.85] text-cora-ink-2 shadow-none">
              <span>
                <span className="text-cora-ok-ink">feito</span> · 1.284 perfis do banco lidos, 37 com autorização vencida saíram da busca
              </span>
              <span>
                <span className="text-cora-ok-ink">feito</span> · LinkedIn via Bright Data, 316 perfis
              </span>
              <span>
                <span className="text-cora-coral-ink">bloqueio</span> · 41 perfis ignorados pela blacklist: Vértice, Lumen, Orla
              </span>
              <span>
                <span className="text-cora-primary">agora</span> · analisando 62 perfis por critério, trabalhou por 47s
              </span>
            </Card>
            <div className="flex w-full max-w-[640px] items-center gap-2.5 self-center rounded-[14px] border border-cora-line-2 bg-white py-2 pl-3.5 pr-2 shadow-[0_12px_32px_-16px_rgba(11,48,56,0.35)]">
              <span className="min-w-0 flex-1 truncate text-[13px] text-cora-placeholder">Peça algo à CORA: “traga mais 3 pessoas de Recife”</span>
              <Badge className="bg-cora-coral-bg px-2.5 py-1 font-semibold text-cora-coral-ink">Agente</Badge>
              <span className="flex size-8 items-center justify-center rounded-full bg-cora-primary text-white">
                <ArrowUp aria-hidden className="size-3.5" />
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Integracoes() {
  return (
    <section aria-label="Integrações" className="mx-auto max-w-[1240px] px-6 pb-6">
      <div className="flex flex-col gap-[18px] rounded-[14px] border border-cora-line bg-[#EEF1EE] px-7 py-[26px]">
        <span className="text-center text-[13px] text-cora-placeholder">Conectada a</span>
        <div className="flex flex-wrap items-center justify-around gap-x-10 gap-y-[22px] text-[#6A7E7A]">
          <span className="text-[26px] font-bold tracking-[-0.04em]">
            tako<span className="ml-1.5 text-sm font-medium tracking-normal">Nara</span>
          </span>
          <span className="text-[23px] font-semibold tracking-[-0.02em]">Bright Data</span>
          <span className="text-2xl font-bold tracking-[-0.03em]">LinkedIn</span>
          <span className="text-[23px] font-semibold tracking-[-0.02em]">WhatsApp</span>
          <span className="text-[23px] font-medium tracking-[-0.02em]">e-mail</span>
          <span className="font-mono text-[23px] font-semibold tracking-[0.02em]">MCP</span>
        </div>
      </div>
    </section>
  );
}

function ComoFunciona() {
  const itens: Array<[string, string, string]> = [
    ["border-cora-accent", "Trabalha enquanto você entrevista", "Abra a vaga de manhã e volte com pessoas interessadas, cada uma com o porquê da escolha."],
    ["border-[#3A6F6C]", "Conversa como gente, não como robô", "E-mail pessoal, WhatsApp no tom da sua empresa e resposta em minutos, dentro dos horários de contato que você definir."],
    ["border-cora-ink", "Seu banco de talentos sempre em dia", "Quem quase entrou na vaga passada volta na próxima. Autorização vencida sai da busca, e quem pede para sair tem os dados apagados."],
  ];
  return (
    <section className="mx-auto flex max-w-[1240px] flex-col gap-[52px] px-6 pb-[104px] pt-28" id="como">
      <div className="flex items-end justify-between gap-8 max-[860px]:flex-col max-[860px]:items-start">
        <h2 className="m-0 max-w-[760px] text-[clamp(38px,5.2vw,68px)] font-semibold leading-none tracking-[-0.04em] text-balance">
          O amigo favorito do <span className="text-cora-accent">seu RH</span>.
        </h2>
        <p className="m-0 max-w-[380px] text-lg text-cora-muted">Ela caça, conversa e organiza. Você entrevista e decide.</p>
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(280px,100%),1fr))] gap-10">
        {itens.map(([borda, titulo, texto]) => (
          <div className={cn("flex flex-col gap-2.5 border-t-2 pt-5", borda)} key={titulo}>
            <h3 className="m-0 text-[26px] font-semibold leading-[1.15] tracking-[-0.03em]">{titulo}</h3>
            <p className="m-0 text-cora-muted">{texto}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Blacklist() {
  const linhas: Array<[string, string, boolean, string]> = [
    ["Vértice Pagamentos", "Não aliciamento", true, "03/2027"],
    ["Lumen Saúde", "Fidelidade", false, "11/2026"],
    ["Orla Logística", "Não aliciamento", true, "08/2027"],
  ];
  const grade = "grid grid-cols-[1.4fr_1fr_0.7fr] gap-3 px-[18px]";
  return (
    <section className="mx-auto flex max-w-[1240px] flex-wrap-reverse items-center gap-14 px-6 pb-[120px]" id="blacklist">
      <div className="min-w-0 flex-[1_1_520px] rounded-2xl bg-[#E8EEEA] p-[clamp(10px,3vw,32px)]">
        <Card className="gap-0 overflow-hidden rounded-xl border-cora-line-2 py-0 shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
          <div className="flex flex-wrap items-center justify-between gap-3 px-[18px] py-4">
            <span className="flex flex-col">
              <span className="font-semibold tracking-[-0.02em]">Blacklist de empresas</span>
              <span className="text-[13px] text-cora-placeholder">Ninguém destas empresas é coletado ou abordado</span>
            </span>
            <Button asChild className={cn("text-[13px]", BTN_CONTORNO)} variant="outline">
              <Link href="/empresa">
                <Plus aria-hidden className="size-3.5" />
                Adicionar empresa
              </Link>
            </Button>
          </div>
          <div className={cn(grade, "border-y border-[#EDF1EE] bg-cora-row py-2.5 text-xs font-medium text-cora-placeholder")}>
            <span>Empresa</span>
            <span>Contrato</span>
            <span className="text-right">Até</span>
          </div>
          {linhas.map(([empresa, contrato, coral, ate], i) => (
            <div className={cn(grade, "items-center py-[13px] text-sm", i < linhas.length - 1 && "border-b border-cora-subtle")} key={empresa}>
              <span className="font-medium">{empresa}</span>
              <span>
                <Badge
                  className={cn(
                    "rounded-md font-semibold",
                    coral ? "border-[#F0B5AA] bg-cora-coral-bg text-cora-coral-ink" : "border-cora-line-2 bg-cora-muted-bg text-cora-ink-2",
                  )}
                  variant="outline"
                >
                  {contrato}
                </Badge>
              </span>
              <span className="num text-right text-cora-muted">{ate}</span>
            </div>
          ))}
          <div className="border-t border-[#F0B5AA] bg-cora-coral-bg px-[18px] py-3 font-mono text-xs text-cora-coral-ink">
            conector.linkedin · 41 perfis não coletados · regra BL-03
          </div>
        </Card>
      </div>
      <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-[18px]">
        <h2 className="m-0 text-[clamp(32px,3.8vw,48px)] font-semibold leading-[1.04] tracking-[-0.04em] text-balance">
          Seus contratos valem mais que um bom perfil.
        </h2>
        <p className="m-0 max-w-[460px] text-lg text-cora-muted">
          Cliente com cláusula de não aliciamento ou contrato de fidelidade entra na blacklist. A CORA nem coleta o perfil de quem
          trabalha lá, e nunca aborda essas pessoas. É uma regra fixa: a IA não tem como ignorá-la.
        </p>
      </div>
    </section>
  );
}

function Dossie() {
  const blocos: Array<[string, string]> = [
    ["Por que ela", "Go em produção há cinco anos, com evidência em dois projetos públicos. Liderou a migração para Kafka."],
    ["O que ela contou", "Quer remoto, liderança técnica sem gestão e pode começar em 30 dias."],
    ["Para aprofundar", "Pausa de oito meses em 2023: pergunte, não penalize. Pouca experiência com observabilidade."],
  ];
  return (
    <section className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-14 px-6 py-[120px]">
      <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-[18px]">
        <h2 className="m-0 text-[clamp(32px,3.8vw,48px)] font-semibold leading-[1.04] tracking-[-0.04em] text-balance">
          A entrevista começa sabendo o que importa.
        </h2>
        <p className="m-0 max-w-[460px] text-lg text-cora-muted">
          Quando a pessoa agenda, a Nara recebe um dossiê: por que ela, as evidências com fonte, o que ela contou na conversa e as
          lacunas para investigar. Lacuna é pergunta, nunca defeito.
        </p>
      </div>
      <div className="min-w-0 flex-[1_1_520px] rounded-2xl bg-[#E8EEEA] p-[clamp(10px,3vw,40px)]">
        <article>
          <Card className="gap-[18px] rounded-md border-cora-line-2 p-[clamp(22px,4vw,44px)] shadow-[0_24px_48px_-32px_rgba(11,48,56,0.45)]">
            <div className="flex items-center justify-between gap-3 text-xs text-cora-placeholder">
              <span className="flex items-center gap-1.5">
                <Logo tamanho={18} />
                Dossiê para a entrevista · Vaga 014
              </span>
              <span>Para a Nara</span>
            </div>
            <h3 className="m-0 font-[family-name:var(--font-source-serif),Georgia,serif] text-[clamp(26px,3vw,34px)] font-semibold leading-[1.1] tracking-[-0.02em]">
              Larissa Rocha, Backend Sênior
            </h3>
            {blocos.map(([titulo, texto]) => (
              <div className="flex flex-col gap-1" key={titulo}>
                <span className="text-sm font-semibold text-cora-primary">{titulo}</span>
                <span className="font-[family-name:var(--font-source-serif),Georgia,serif] text-[17px] text-cora-ink-2">{texto}</span>
              </div>
            ))}
            <span className="border-t border-[#EDF1EE] pt-3 font-mono text-xs text-cora-placeholder">rastro a91f · autorizada até 05/2027</span>
          </Card>
        </article>
      </div>
    </section>
  );
}

function Regras() {
  const regras: Array<[string, string]> = [
    ["Requisito eliminatório não é opinião", "Eliminatórios, autorização e limites de contato são regras fixas. A IA não decide sobre eles."],
    ["Autorização vencida sai da busca", "Cada empresa tem o próprio banco. Nada de uma aparece para outra."],
    ["Nome e gênero não mudam a nota", "Atributo sensível não é critério, e isso é testado a cada versão."],
    ["Todo passo deixa rastro", "Cada decisão guarda evidência, regra aplicada e custo por candidato."],
  ];
  return (
    <section className="border-t border-cora-line" id="regras">
      <div className="mx-auto flex max-w-[1240px] flex-wrap gap-14 px-6 py-[120px]">
        <div className="flex min-w-0 flex-[1_1_360px] flex-col gap-[18px]">
          <h2 className="m-0 text-[clamp(32px,3.8vw,48px)] font-semibold leading-[1.04] tracking-[-0.04em] text-balance">
            Autonomia onde ajuda. Regra fixa onde importa.
          </h2>
          <p className="m-0 text-lg text-cora-muted">
            A CORA não agenda, não avalia a entrevista e não decide contratações. A Nara entrevista. Seu time decide.
          </p>
        </div>
        <div className="flex min-w-0 flex-[1.4_1_520px] flex-col max-sm:basis-full">
          {regras.map(([titulo, texto], i) => (
            <div
              className={cn(
                "grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-6 border-t border-[#DCE5E0] py-[22px] max-sm:grid-cols-1 max-sm:gap-2",
                i === regras.length - 1 && "border-b",
              )}
              key={titulo}
            >
              <span className="text-lg font-semibold tracking-[-0.02em]">{titulo}</span>
              <span className="text-cora-muted">{texto}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Acesso() {
  return (
    <section className="bg-cora-primary text-white" id="acesso">
      <div className="mx-auto flex max-w-[1240px] flex-col items-center gap-[22px] px-6 py-28 text-center">
        <h2 className="m-0 max-w-[900px] text-[clamp(40px,5.6vw,76px)] font-semibold leading-[0.98] tracking-[-0.04em] text-balance">
          Abra sua primeira vaga hoje.
        </h2>
        <div className="flex flex-wrap items-center justify-center gap-2.5">
          <Button asChild className="h-11 bg-white px-[18px] text-base font-semibold text-cora-ink hover:bg-cora-muted-bg">
            <Link href="/criar-vaga">Criar vaga</Link>
          </Button>
          <Button
            asChild
            className="h-11 border-white/70 bg-transparent px-[18px] text-base text-white shadow-none hover:bg-white/10 hover:text-white dark:bg-transparent"
            variant="outline"
          >
            <Link href="/vagas">Ver a demo</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

function Rodape() {
  return (
    <footer className="bg-cora-ink text-[#B4C7C3]">
      <div className="mx-auto flex max-w-[1240px] flex-wrap justify-between gap-8 px-6 pb-14 pt-10 text-sm">
        <div className="flex max-w-[340px] flex-col gap-2.5">
          <span className="flex items-center gap-2">
            <Logo tamanho={30} />
            <span className="text-[19px] font-semibold tracking-[-0.03em] text-white">CORA</span>
          </span>
          <span>Conexão de Oportunidade de Recrutamento Ativo. Feita no Converge Challenge, Desafio Tako.</span>
        </div>
        <div className="flex flex-wrap gap-14">
          <div className="flex flex-col gap-2">
            <span className="font-semibold text-white">Produto</span>
            <a className="text-[#B4C7C3] no-underline hover:text-white" href="#como">Como funciona</a>
            <a className="text-[#B4C7C3] no-underline hover:text-white" href="#blacklist">Blacklist</a>
            <a className="text-[#B4C7C3] no-underline hover:text-white" href="#regras">Regras</a>
          </div>
          <div className="flex flex-col gap-2">
            <span className="font-semibold text-white">Privacidade</span>
            <a className="text-[#B4C7C3] no-underline hover:text-white" href="#regras">Autorização e LGPD</a>
            <a className="text-[#B4C7C3] no-underline hover:text-white" href="#regras">Pedir remoção</a>
          </div>
        </div>
      </div>
    </footer>
  );
}

/** Landing da CORA (design de 08/11, commit a1d50aa), montada com shadcn/ui e os tokens CORA. */
export function LandingCora() {
  return (
    <div className="bg-cora-bg text-base leading-[1.55] text-cora-ink selection:bg-[#FFD3C6] selection:text-cora-ink">
      <Cabecalho />
      <Hero />
      <ProdutoAoVivo />
      <Integracoes />
      <ComoFunciona />
      <Situacoes />
      <Blacklist />
      <DemoConversa />
      <Dossie />
      <Regras />
      <Acesso />
      <Rodape />
    </div>
  );
}
