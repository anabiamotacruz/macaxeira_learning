"use client";

import Image from "next/image";
import { ChevronLeft, Pause, Play, SendHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import { ANOTACOES, type Cargo, CARGOS, CONVERSAS, type Conversa, FASES } from "./dados";

type Passo = "email" | "reply" | "wa" | "fim";

function roteiro(d: Conversa): Passo[] {
  return ["email", "reply", ...d.wa.map(() => "wa" as const), "fim"];
}

function horaDaMensagem(base: string, i: number): string {
  return base.replace(/:(\d+)/, (_, mm: string) => `:${String(Math.min(59, Number(mm) + i)).padStart(2, "0")}`);
}

function EmailConvite({ d, passo }: { d: Conversa; passo: number }) {
  return (
    <Card className="gap-0 overflow-hidden rounded-[14px] border-0 py-0 text-[#202124] shadow-[0_30px_60px_-30px_rgba(0,0,0,0.5)]">
      <div className="flex items-start gap-3 px-[18px] pb-3 pt-4">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-cora-coral-bg">
          <Image alt="" className="h-[25px] w-6 object-contain" height={25} src="/coral.png" width={24} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-sm text-[#5F6368]">
            <b className="font-semibold text-[#202124]">CORA</b> &lt;no-reply@cora.com&gt;
          </span>
          <span className="text-xs text-[#5F6368]">para mim</span>
        </span>
        <span className="num whitespace-nowrap text-xs text-[#5F6368]">{d.hora1}</span>
      </div>
      <div className="bg-[#F4F5F2] p-[clamp(10px,2vw,20px)]">
        <div className="mx-auto max-w-[560px] overflow-hidden rounded-xl border border-[#E3E7E3] bg-white">
          <div className="flex items-center gap-3 bg-[#183038] px-6 py-5">
            <Image alt="" className="h-[35px] w-[34px] object-contain" height={35} src="/coral.png" width={34} />
            <span className="flex flex-col gap-1">
              <span className="text-2xl font-bold leading-none tracking-[-0.02em] text-white">CORA</span>
              <span className="text-[9px] font-medium tracking-[0.14em] text-[#CFE0DC]">CONEXÃO DE OPORTUNIDADE DE RECRUTAMENTO ATIVO</span>
            </span>
          </div>
          <div className="flex flex-col gap-3.5 px-6 py-[22px] text-[#183038]">
            <span className="text-[11px] font-bold tracking-[0.12em] text-[#3A6F6C]">NOVA OPORTUNIDADE</span>
            <span className="text-2xl font-bold leading-[1.15] tracking-[-0.02em]">{d.vaga}</span>
            <span className="text-[15px] leading-relaxed text-cora-ink-2">
              Olá, {d.primeiroNome}! A CORA tem uma vaga de <b className="text-[#183038]">{d.vaga}</b> e o seu perfil chamou a
              nossa atenção por:
            </span>
            <span className="flex flex-wrap gap-2">
              {d.chips.map((chip) => (
                <Badge className="border-[#F0C3B8] bg-[#FFF4F1] px-[13px] py-[5px] text-sm font-normal text-cora-coral-ink" key={chip} variant="outline">
                  {chip}
                </Badge>
              ))}
            </span>
            <span className="text-[15px] leading-relaxed text-cora-ink-2">Se tiver interesse, a próxima conversa é rápida e pelo WhatsApp:</span>
            <span
              className={cn(
                "self-start rounded-lg bg-cora-primary px-[22px] py-3 text-base font-bold text-white transition-shadow duration-200",
                passo === 1 && "shadow-[0_0_0_5px_#FFD3C6]",
              )}
            >
              Quero conversar sobre a vaga
            </span>
            <Separator className="my-1 bg-[#E6EAE7]" />
            <span className="text-[13px] leading-relaxed text-cora-muted">
              <b className="text-cora-ink-2">Por que você recebeu este e-mail:</b> encontramos o seu perfil profissional público em{" "}
              <span className="text-[#3A6F6C] underline underline-offset-2">{d.linkedin}</span> e ele combina com esta vaga.
              Guardamos só dados profissionais públicos para falar sobre ela.
            </span>
            <span className="text-[13px] leading-relaxed text-cora-muted">
              Não quer mais receber contatos?{" "}
              <span className="font-semibold text-cora-coral-ink underline underline-offset-2">Não quero mais contato</span> ou responda
              SAIR. O pedido vale para sempre, em todas as vagas.
            </span>
          </div>
          <div className="border-t border-[#E6EAE7] bg-cora-bg px-6 py-3 text-xs text-cora-placeholder">CORA · recrutamento ativo</div>
        </div>
      </div>
      {passo >= 1 && (
        <div className="flex items-center gap-2.5 border-t border-[#EDF1EE] px-[18px] py-3 text-[13px] text-cora-ink-2">
          <span className="size-2 shrink-0 rounded-full bg-cora-accent" />
          <span className="min-w-0 flex-1">
            <b className="text-cora-ink">{d.primeiroNome}</b> clicou em “Quero conversar sobre a vaga” · {d.hora2}
          </span>
          <span className="whitespace-nowrap font-semibold text-cora-ok-ink">abriu o WhatsApp</span>
        </div>
      )}
    </Card>
  );
}

function Celular({ d, passo, passos, tocando }: { d: Conversa; passo: number; passos: Passo[]; tocando: boolean }) {
  const msgs = d.wa
    .map(([de, txt], i) => ({ de, txt, idx: i + 2, hora: horaDaMensagem(d.hora2, i) }))
    .filter((m) => m.idx <= passo);
  const proxima = passos[passo + 1] === "wa" ? d.wa[passo + 1 - 2] : null;
  const digitando = !!proxima && tocando;
  const bolha = (de: "p" | "c") =>
    cn(
      "max-w-[82%] px-[9px] pb-1 pt-1.5 text-[#111B21] shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]",
      de === "c" ? "self-end rounded-[8px_0_8px_8px] bg-[#D9FDD3]" : "self-start rounded-[0_8px_8px_8px] bg-white",
    );
  return (
    <div className="mx-auto min-w-[280px] flex-[0_1_340px] rounded-[38px] bg-[#050F11] p-2.5 shadow-[0_30px_60px_-30px_rgba(0,0,0,0.6)] max-[360px]:min-w-0">
      <div className="flex h-[600px] flex-col overflow-hidden rounded-[30px] bg-[#EFEAE2]">
        <div className="flex items-center gap-2.5 bg-[#1F5F55] px-3.5 pb-2.5 pt-3.5 text-white">
          <ChevronLeft aria-hidden className="size-[18px]" />
          <span className="flex size-[34px] items-center justify-center rounded-full bg-white">
            <Image alt="" className="h-[23px] w-[22px] object-contain" height={23} src="/coral.png" width={22} />
          </span>
          <span className="flex flex-col leading-tight">
            <span className="text-[15px] font-semibold">CORA · Maré Tech</span>
            <span className="text-xs text-[#CFE6E0]">{digitando && proxima?.[0] === "c" ? "digitando…" : "online"}</span>
          </span>
        </div>
        <div aria-live="polite" className="flex flex-1 flex-col justify-end gap-1.5 overflow-hidden px-2.5 py-3 text-sm leading-[1.4]">
          <span className="self-center rounded-md bg-white px-2 py-[3px] text-[11px] text-[#54656F]">Hoje</span>
          {msgs.map((m) => (
            <span className={bolha(m.de)} key={m.idx}>
              {m.txt}
              <span className="mt-0.5 block text-right text-[10px] text-[#667781]">{m.hora}</span>
            </span>
          ))}
          {digitando && proxima && <span className={cn(bolha(proxima[0]), "italic text-[#667781]")}>digitando…</span>}
          {passos[passo] === "fim" && (
            <Badge className="mt-1.5 self-center px-2.5 py-1 font-semibold text-white" style={{ background: "var(--cora-accent)" }}>
              Entrevista marcada com a Nara · {d.entrevista}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 px-2.5 pb-3.5 pt-2">
          <span className="flex h-[38px] flex-1 items-center rounded-[19px] bg-white px-3.5 text-[13px] text-[#8696A0]">Mensagem</span>
          <span className="flex size-[38px] items-center justify-center rounded-full bg-[#1F5F55] text-white">
            <SendHorizontal aria-hidden className="size-4" />
          </span>
        </div>
      </div>
    </div>
  );
}

/** Seção escura "A conversa que nenhum recrutador tem tempo de ter": e-mail, clique e WhatsApp até a Nara. */
export function DemoConversa() {
  const [cargo, setCargo] = useState<Cargo>("python");
  const [passoBruto, setPasso] = useState(0);
  const [tocando, setTocando] = useState(true);

  const d: Conversa = CONVERSAS[cargo];
  const passos = useMemo(() => roteiro(d), [d]);
  const passo = Math.min(passoBruto, passos.length - 1);

  useEffect(() => {
    // Quem pede menos movimento vê a conversa já completa, sem animação.
    const timer = setTimeout(() => {
      try {
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          setTocando(false);
          setPasso(roteiro(CONVERSAS.python).length - 1);
        }
      } catch {
        // Sem matchMedia, a demo segue animada.
      }
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!tocando) return;
    let tamanho = 0;
    if (passo === 0) tamanho = 120;
    else if (passo === 1) tamanho = 50;
    else if (passos[passo] === "wa") tamanho = d.wa[passo - 2][1].length;
    const espera = passo >= passos.length - 1 ? 2600 : Math.min(3400, 1100 + tamanho * 18);
    const timer = setTimeout(() => setPasso((p) => (p + 1 >= passos.length + 1 ? 0 : p + 1)), espera);
    return () => clearTimeout(timer);
  }, [tocando, passo, passos, d]);

  const fimIdx = passos.length - 1;
  const faseAtual = passo === 0 ? 0 : passo === 1 ? 1 : passo < fimIdx ? 2 : 3;
  const anotacoes = ANOTACOES[cargo];
  const notas = anotacoes.filter(([, , em]) => em <= passo);

  return (
    <section className="bg-cora-ink text-[#F1F5F2]" id="conversa">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-[52px] px-6 py-[120px]">
        <div className="flex items-end justify-between gap-8 max-[860px]:flex-col max-[860px]:items-start">
          <h2 className="m-0 max-w-[720px] text-[clamp(34px,4.4vw,56px)] font-semibold leading-[1.02] tracking-[-0.04em] text-balance">
            A conversa que nenhum recrutador tem tempo de ter.
          </h2>
          <p className="m-0 max-w-[400px] text-[17px] text-[#B4C7C3]">
            Escolha um cargo e veja a CORA em ação: o e-mail chega, a pessoa responde e a conversa segue no WhatsApp até a
            entrevista com a Nara.
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <Tabs
            onValueChange={(v) => {
              setCargo(v as Cargo);
              setPasso(0);
              setTocando(true);
            }}
            value={cargo}
          >
            <TabsList aria-label="Cargo de exemplo" className="h-auto flex-wrap justify-start gap-0.5 group-data-[orientation=horizontal]/tabs:h-auto rounded-[10px] bg-white/[0.08] p-1">
              {CARGOS.map((k) => (
                <TabsTrigger
                  className="h-9 flex-none rounded-[7px] border-transparent! px-3.5 text-sm text-[#CFE0DC]! hover:text-white! data-[state=active]:bg-white data-[state=active]:font-semibold data-[state=active]:text-cora-ink! dark:text-[#CFE0DC] dark:data-[state=active]:bg-white dark:data-[state=active]:text-cora-ink"
                  key={k}
                  value={k}
                >
                  {CONVERSAS[k].label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <div className="flex items-center gap-2">
            <Button
              className="border-[#2B5A60] bg-transparent text-[13px] text-[#F1F5F2]! shadow-none hover:bg-white/10 hover:text-white dark:bg-transparent"
              onClick={() => setTocando((t) => !t)}
              type="button"
              variant="outline"
            >
              {tocando ? <Pause aria-hidden className="size-3.5" /> : <Play aria-hidden className="size-3.5" />}
              {tocando ? "Pausar" : "Reproduzir"}
            </Button>
            <Button
              className="border-[#2B5A60] bg-transparent text-[13px] text-[#F1F5F2]! shadow-none hover:bg-white/10 hover:text-white dark:bg-transparent"
              onClick={() => {
                setPasso(0);
                setTocando(true);
              }}
              type="button"
              variant="outline"
            >
              Recomeçar
            </Button>
          </div>
        </div>

        <ol aria-label="Etapas da demonstração" className="m-0 grid list-none grid-cols-4 gap-2.5 p-0">
          {FASES.map((label, i) => {
            const feita = i < faseAtual;
            const atual = i === faseAtual;
            return (
              <li className="flex min-w-0 flex-col gap-2" key={label}>
                <span className={cn("block h-1 rounded-sm", atual ? "bg-cora-accent" : feita ? "bg-[#F1F5F2]" : "bg-white/[0.18]")} />
                <span
                  className={cn(
                    "truncate text-[13px]",
                    atual ? "font-semibold text-white" : feita ? "text-[#CFE0DC]" : "text-[#9DB3AF]",
                  )}
                >
                  {label}
                </span>
              </li>
            );
          })}
        </ol>

        <div className="flex flex-wrap items-stretch gap-6">
          <div className="flex min-w-0 flex-[1.25_1_440px] flex-col gap-4 max-[500px]:basis-full">
            <EmailConvite d={d} passo={passo} />
            <div className="flex min-h-[150px] flex-1 flex-col gap-3 rounded-[14px] border border-[#1C4A50] px-5 py-[18px]">
              <span className="flex justify-between gap-3 text-[13px] text-[#B4C7C3]">
                <span>O que a CORA anotou para a entrevista</span>
                <span className="num">
                  {notas.length} de {anotacoes.length}
                </span>
              </span>
              {notas.length > 0 ? (
                <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-x-5 gap-y-2.5">
                  {notas.map(([rotulo, valor]) => (
                    <span className="flex flex-col gap-0.5" key={rotulo}>
                      <span className="text-xs text-[#9DB3AF]">{rotulo}</span>
                      <span className="text-[#F1F5F2]">{valor}</span>
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-sm text-[#9DB3AF]">Aparece aqui o que a pessoa contar na conversa.</span>
              )}
            </div>
          </div>
          <Celular d={d} passo={passo} passos={passos} tocando={tocando} />
        </div>
      </div>
    </section>
  );
}
