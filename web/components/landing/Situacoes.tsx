"use client";

import { useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import { type ChaveSituacao, SITUACOES, type Situacao, type Tom } from "./dados";

const CHAVES = Object.keys(SITUACOES) as ChaveSituacao[];

const TOM_CRITERIO: Record<Tom, { rotulo: string; texto: string; barra: string }> = {
  atende: { rotulo: "atende", texto: "text-cora-ok-ink", barra: "bg-[#377B5D]" },
  parcial: { rotulo: "parcial", texto: "text-cora-warn-ink", barra: "bg-[#C98A12]" },
  lacuna: { rotulo: "lacuna", texto: "text-cora-placeholder", barra: "bg-[#9AA7A4]" },
  nao: { rotulo: "não atende", texto: "text-cora-coral-ink", barra: "bg-cora-accent" },
};

const TOM_BADGE: Record<Situacao["tom"], string> = {
  ok: "border-[#CDE6D5] bg-cora-ok-bg text-cora-ok-ink",
  warn: "border-[#F1D58A] bg-cora-warn-bg text-cora-warn-ink",
  coral: "border-[#F0B5AA] bg-cora-coral-bg text-cora-coral-ink",
};

function Ficha({ s }: { s: Situacao }) {
  return (
    <Card className="gap-4 rounded-xl border-cora-line-2 p-[22px] shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar className="size-11">
            <AvatarFallback className="bg-cora-coral-bg font-semibold text-cora-coral-ink">{s.iniciais}</AvatarFallback>
          </Avatar>
          <span className="flex min-w-0 flex-col">
            <span className="text-[17px] font-semibold tracking-[-0.02em]">{s.nome}</span>
            <span className="text-[13px] break-words text-cora-placeholder">{s.email}</span>
          </span>
        </div>
        <span className="flex shrink-0 flex-col items-end gap-1.5">
          <span className="num text-[40px] font-bold leading-none tracking-[-0.04em] text-cora-primary">{s.nota}</span>
          <Badge className={cn("rounded-md font-semibold", TOM_BADGE[s.tom])} variant="outline">
            {s.label === "Aguardando autorização" ? "Aguardando" : s.label}
          </Badge>
        </span>
      </div>
      <div className="flex flex-col gap-3 text-sm">
        {s.criterios.map((c) => {
          const tom = TOM_CRITERIO[c.tom];
          return (
            <div className="grid grid-cols-[1fr_80px] items-center gap-x-3 gap-y-1.5" key={c.nome}>
              <span>{c.nome}</span>
              <span className={cn("text-right text-[13px]", tom.texto)}>{tom.rotulo}</span>
              <span className="col-span-2 h-1.5 rounded-[3px] bg-[#EDF1EE]">
                <span className={cn("block h-1.5 rounded-[3px] transition-[width] duration-500", tom.barra)} style={{ width: `${c.pct}%` }} />
              </span>
            </div>
          );
        })}
      </div>
      <div className="rounded-lg border border-[#EDF1EE] bg-cora-bg px-3.5 py-3 text-sm text-cora-ink-2">
        <span className="font-semibold text-cora-ink">{s.notaTitulo}</span> {s.notaTexto}
      </div>
      <span className="font-mono text-xs text-cora-placeholder">{s.rastro}</span>
    </Card>
  );
}

/** Seção "Cada nota tem um porquê": abas de situação e a ficha correspondente. */
export function Situacoes() {
  const [situ, setSitu] = useState<ChaveSituacao>("autorizada");
  return (
    <section className="mx-auto max-w-[1240px] px-6 pb-[120px]" id="situacoes">
      <Tabs className="flex-wrap items-center gap-14 data-[orientation=horizontal]:flex-row" onValueChange={(v) => setSitu(v as ChaveSituacao)} value={situ}>
        <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-[18px]">
          <h2 className="m-0 text-[clamp(32px,3.8vw,48px)] font-semibold leading-[1.04] tracking-[-0.04em] text-balance">
            Cada nota tem um porquê. Cada pessoa, uma situação.
          </h2>
          <p className="m-0 max-w-[460px] text-lg text-cora-muted">
            Nota por critério, evidência com fonte e as lacunas que valem uma pergunta. A situação diz o que a CORA pode fazer
            com cada pessoa.
          </p>
          <TabsList aria-label="Situação da pessoa" className="h-auto flex-wrap justify-start gap-0.5 group-data-[orientation=horizontal]/tabs:h-auto rounded-[10px] bg-[#EAF0EC] p-1">
            {CHAVES.map((k) => (
              <TabsTrigger
                className="h-[34px] flex-none rounded-[7px] border-transparent! px-3.5 text-sm text-cora-muted! data-[state=active]:font-semibold data-[state=active]:text-cora-ink! data-[state=active]:shadow-[0_1px_2px_rgba(11,48,56,0.12)] dark:data-[state=active]:bg-cora-surface"
                key={k}
                value={k}
              >
                {SITUACOES[k].label}
              </TabsTrigger>
            ))}
          </TabsList>
          <p className="m-0 min-h-12 max-w-[460px] text-[15px] text-cora-ink-2">{SITUACOES[situ].texto}</p>
        </div>
        <div className="min-w-0 flex-[1_1_520px] rounded-2xl bg-[#E8EEEA] p-[clamp(10px,3vw,32px)]">
          {CHAVES.map((k) => (
            <TabsContent key={k} value={k}>
              <Ficha s={SITUACOES[k]} />
            </TabsContent>
          ))}
        </div>
      </Tabs>
    </section>
  );
}
