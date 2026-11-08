import Image from "next/image";
import Link from "next/link";

import { DemoVideo } from "@/components/landing/DemoVideo";
import { FeaturesSection } from "@/components/landing/FeaturesSection";
import { FooterCTA } from "@/components/landing/FooterCTA";
import { HeroSection } from "@/components/landing/HeroSection";

const navigation = [
  ["Como funciona", "#como"],
  ["Situações", "#situacoes"],
  ["Blacklist", "#blacklist"],
  ["Conversa", "#conversa"],
  ["Regras", "#regras"],
] as const;

const columns = [
  ["Analisando", "62", "#3a6f6c", ["Camila Nunes", "Rafael Lima"]],
  ["Aguardando autorização", "9", "#c98a12", ["Tiago Moura", "Júlia Prado"]],
  ["Em conversa", "4", "#fb3c0d", ["Larissa Rocha", "André Sales"]],
  ["Entregue à Nara", "2", "#377b5d", ["Marina Costa", "Pedro Alves"]],
] as const;

export default function LandingPage() {
  return (
    <main className="bg-[#f7f8f5] text-[#0b3038]">
      <header className="border-b border-[#e4e9e5] bg-white/70">
        <nav aria-label="Principal" className="mx-auto flex max-w-[1240px] items-center justify-between gap-4 px-6 py-3.5">
          <Link className="flex items-center gap-2" href="#topo">
            <Image alt="" className="h-9 w-9 object-contain" height={37} src="/coral.png" width={36} />
            <span className="flex flex-col"><span className="text-[21px] font-semibold leading-none tracking-[-.03em]">CORA</span><span className="mt-1 text-[10px] text-[#5e7672]">Recrutamento ativo</span></span>
          </Link>
          <div className="hidden gap-7 text-sm text-[#526c68] lg:flex">
            {navigation.map(([label, href]) => <a className="transition hover:text-[#dc3209]" href={href} key={href}>{label}</a>)}
          </div>
          <div className="flex items-center gap-2">
            <Link className="hidden h-10 items-center rounded-lg border border-[#dfe6e1] bg-white px-3.5 text-sm font-medium sm:inline-flex" href="#acesso">Entrar</Link>
            <Link className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-[#dc3209] px-3.5 text-sm font-semibold text-white shadow-[0_3px_7px_rgba(251,60,13,.22)]" href="/criar-vaga"><span aria-hidden="true" className="text-lg leading-none">+</span>Criar vaga</Link>
          </div>
        </nav>
      </header>

      <HeroSection />
      <ProductPreview />
      <section className="mx-auto max-w-[1240px] px-6 pb-6" aria-label="Integrações">
        <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 border-t border-[#e4e9e5] py-5 text-xs text-[#5e7672]">
          <span>Conectado ao seu fluxo</span><b className="text-[#0b3038]">LinkedIn</b><b className="text-[#0b3038]">WhatsApp</b><b className="text-[#0b3038]">E-mail</b><span>com rastreabilidade em cada passo</span>
        </div>
      </section>
      <FeaturesSection />
      <BlacklistSection />
      <DemoVideo />
      <DossierSection />
      <FooterCTA />
    </main>
  );
}

function ProductPreview() {
  return (
    <section aria-label="A CORA trabalhando numa vaga" className="mx-auto max-w-[1240px] px-6 pb-[72px] pt-2" id="produto">
      <div className="rounded-2xl bg-[#e8eeea] p-[clamp(10px,3vw,40px)]">
        <div className="overflow-hidden rounded-xl border border-[#dce5e0] bg-[#f7f8f5] shadow-[0_30px_60px_-40px_rgba(11,48,56,.5)]">
          <div className="flex h-14 items-center gap-4 border-b border-[#e4e9e5] bg-white px-[18px]">
            <span className="flex items-center gap-1.5 text-base font-semibold"><Image alt="" height={25} src="/coral.png" width={24} />CORA</span>
            <span className="hidden gap-0.5 text-[13px] md:flex"><span className="rounded-lg bg-[#eef2ef] px-3 py-1.5 font-semibold">Vagas</span><span className="px-3 py-1.5 text-[#526c68]">Banco de talentos</span><span className="px-3 py-1.5 text-[#526c68]">Empresa</span></span>
            <span className="ml-auto hidden h-8 w-[220px] items-center justify-between rounded-lg bg-[#f1f4f2] px-2.5 text-xs text-[#5e7672] md:flex">Buscar pessoas ou vagas <kbd className="rounded border border-[#dfe6e1] bg-white px-1.5 text-[11px]">⌘K</kbd></span>
            <Link className="hidden rounded-lg bg-[#dc3209] px-3 py-2 text-[13px] font-semibold text-white sm:inline" href="/criar-vaga">Criar vaga</Link>
          </div>
          <div className="flex flex-col gap-4 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs text-[#5e7672]">Vagas / Backend Sênior</p><h2 className="mt-1 text-[22px] font-semibold tracking-[-.03em]">Pessoa Desenvolvedora Backend Sênior</h2><p className="text-[13px] text-[#5e7672]">Meta: 5 pessoas interessadas na Nara em 7 dias · 2 de 5 entregues</p></div><span className="rounded-full bg-[#fff1cc] px-2.5 py-1 text-xs font-semibold text-[#855a0e]">● Buscando</span></div>
            <div className="flex gap-5 border-b border-[#e4e9e5] text-[13px]"><span className="border-b-2 border-[#fb3c0d] pb-2 font-semibold">Quadro</span><span className="pb-2 text-[#526c68]">Lista</span><span className="pb-2 text-[#526c68]">Rastro</span><span className="pb-2 text-[#526c68]">Critérios</span></div>
            <div className="grid min-w-[760px] grid-cols-4 gap-3 overflow-x-auto">
              {columns.map(([title, count, color, names]) => <div className="flex flex-col gap-2" key={title}><span className="flex items-center gap-1.5 text-xs font-medium text-[#526c68]"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />{title} <small>{count}</small></span>{names.map((name, index) => <div className="rounded-[10px] border border-[#e4e9e5] bg-white p-2.5" key={name}><span className="flex justify-between text-[13px] font-semibold">{name}<b className="text-[#dc3209]">{index === 0 && title !== "Analisando" ? 87 + index * 3 : ""}</b></span><span className="mt-1 block text-xs text-[#5e7672]">{title === "Analisando" ? "Lendo evidências…" : title === "Em conversa" ? "Conversa em andamento" : title === "Entregue à Nara" ? "Dossiê enviado" : "Autorização pendente"}</span></div>)}</div>)}
            </div>
            <div className="flex flex-col rounded-[10px] border border-[#e4e9e5] bg-white p-3 font-mono text-xs leading-7 text-[#2c4f55]"><span><b className="text-[#2f6e52]">feito</b> · critérios definidos e evidências registradas</span><span><b className="text-[#2f6e52]">feito</b> · autorização validada antes do contato</span><span><b className="text-[#a43826]">bloqueio</b> · blacklist aplicada nesta busca</span><span><b className="text-[#dc3209]">agora</b> · análise em andamento</span></div>
          </div>
        </div>
      </div>
    </section>
  );
}

function BlacklistSection() {
  return (
    <section className="mx-auto flex max-w-[1240px] flex-wrap-reverse items-center gap-14 px-6 pb-[120px]" id="blacklist">
      <div className="min-w-[320px] flex-1 rounded-2xl bg-[#e8eeea] p-8"><div className="overflow-hidden rounded-xl border border-[#dfe6e1] bg-white shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3 p-5"><div><b>Blacklist de empresas</b><p className="text-[13px] text-[#5e7672]">Ninguém destas empresas é coletado ou abordado</p></div><span className="rounded-lg border border-[#dfe6e1] px-3 py-2 text-[13px]">＋ Adicionar empresa</span></div><div className="grid grid-cols-[1.4fr_1fr_.7fr] gap-3 border-y border-[#edf1ee] bg-[#fafbf9] px-5 py-2.5 text-xs font-medium text-[#5e7672]"><span>Empresa</span><span>Contrato</span><span className="text-right">Até</span></div>{[["Vértice Pagamentos","Não aliciamento","03/2027"],["Lumen Saúde","Fidelidade","11/2026"],["Orla Logística","Não aliciamento","08/2027"]].map(([company, contract, date]) => <div className="grid grid-cols-[1.4fr_1fr_.7fr] items-center gap-3 border-b border-[#f1f4f2] px-5 py-3 text-sm" key={company}><b className="font-medium">{company}</b><span className="text-xs text-[#a43826]">{contract}</span><span className="text-right text-[#526c68]">{date}</span></div>)}<p className="bg-[#fff1ee] px-5 py-3 font-mono text-xs text-[#a43826]">conector.linkedin · perfis não coletados · regra BL-03</p></div></div>
      <div className="min-w-[320px] flex-1"><h2 className="text-[clamp(32px,3.8vw,48px)] font-semibold leading-[1.04] tracking-[-.04em]">Seus contratos valem mais que um bom perfil.</h2><p className="mt-[18px] max-w-[460px] text-lg leading-7 text-[#526c68]">Cliente com cláusula de não aliciamento ou contrato de fidelidade entra na blacklist. É uma regra fixa: a IA não tem como ignorá-la.</p></div>
    </section>
  );
}

function DossierSection() {
  return (
    <><section className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-14 px-6 py-[120px]" id="evidencias"><div className="min-w-[320px] flex-1"><h2 className="text-[clamp(32px,3.8vw,48px)] font-semibold leading-[1.04] tracking-[-.04em]">A entrevista começa sabendo o que importa.</h2><p className="mt-[18px] max-w-[460px] text-lg leading-7 text-[#526c68]">Quando a pessoa agenda, a Nara recebe um dossiê: por que ela, as evidências com fonte e as lacunas para investigar. Lacuna é pergunta, nunca defeito.</p></div><div className="min-w-[320px] flex-[1.35] rounded-2xl bg-[#e8eeea] p-8"><article className="flex flex-col gap-[18px] rounded-md border border-[#dfe6e1] bg-white p-8 shadow-[0_24px_48px_-32px_rgba(11,48,56,.45)]"><span className="text-xs text-[#5e7672]">🌊 Dossiê para a entrevista · Vaga 014 <span className="float-right">Para a Nara</span></span><h3 className="font-serif text-[34px] font-semibold leading-tight">Larissa Rocha, Backend Sênior</h3><Info title="Por que ela">Go em produção há cinco anos, com evidência em dois projetos públicos.</Info><Info title="O que ela contou">Quer remoto, liderança técnica sem gestão e pode começar em 30 dias.</Info><Info title="Para aprofundar">Pausa de oito meses em 2023: pergunte, não penalize.</Info><span className="border-t border-[#edf1ee] pt-3 font-mono text-xs text-[#5e7672]">revisor aprovou · rastro a91f</span></article></div></section><section className="border-t border-[#e4e9e5]" id="regras"><div className="mx-auto flex max-w-[1240px] flex-wrap gap-14 px-6 py-[120px]"><div className="min-w-[320px] flex-1"><h2 className="text-[clamp(32px,3.8vw,48px)] font-semibold leading-[1.04] tracking-[-.04em]">Autonomia onde ajuda. Regra fixa onde importa.</h2><p className="mt-[18px] text-lg text-[#526c68]">A CORA não agenda, não avalia a entrevista e não decide contratações. A Nara entrevista. Seu time decide.</p></div><div className="min-w-[320px] flex-[1.4]">{[["Requisito eliminatório não é opinião","Eliminatórios, autorização e limites de contato são regras fixas."],["Autorização vencida sai da busca","Cada empresa tem o próprio banco. Nada de uma aparece para outra."],["Nome e gênero não mudam a nota","Atributo sensível não é critério."],["Todo passo deixa rastro","Cada decisão guarda evidência, regra aplicada e motivo."]].map(([title, text]) => <div className="grid gap-5 border-t border-[#dce5e0] py-[22px] sm:grid-cols-[1fr_1.3fr]" key={title}><b className="text-lg">{title}</b><span className="text-[#526c68]">{text}</span></div>)}</div></div></section></>
  );
}

function Info({ title, children }: { title: string; children: string }) {
  return <div className="flex flex-col gap-1"><b className="text-sm text-[#dc3209]">{title}</b><span className="font-serif text-[17px] text-[#2c4f55]">{children}</span></div>;
}
