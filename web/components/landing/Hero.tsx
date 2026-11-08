"use client";

import { ArrowRight, Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

import { IDEIAS } from "./dados";

/** Topo da landing: a descrição em linguagem natural vira o pedido de proposta em /criar-vaga. */
export function Hero() {
  const router = useRouter();
  const [descricao, setDescricao] = useState(IDEIAS[0].texto);

  function comecar(e: React.FormEvent) {
    e.preventDefault();
    const texto = descricao.trim();
    router.push(texto ? `/criar-vaga?descricao=${encodeURIComponent(texto)}` : "/criar-vaga");
  }

  return (
    <section className="mx-auto flex max-w-[1240px] flex-col items-center gap-[18px] px-6 pb-7 pt-[52px] text-center" id="topo">
      <h1 className="m-0 text-[clamp(42px,5.8vw,78px)] font-semibold leading-[0.98] tracking-[-0.04em] text-balance">
        Diga a vaga.
        <br />
        <span className="text-cora-accent">A CORA traz as pessoas.</span>
      </h1>
      <p className="m-0 max-w-[640px] text-[19px] text-cora-muted text-balance">
        A CORA procura no seu banco de talentos e no LinkedIn, explica por que escolheu cada pessoa, faz o primeiro contato e
        entrega quem topou pronto para a entrevista na Nara.
      </p>

      <Card className="mt-4 w-full max-w-[760px] gap-0 rounded-xl border-cora-line-2 py-0 text-left shadow-[0_1px_2px_rgba(11,48,56,0.06),0_16px_32px_-20px_rgba(11,48,56,0.28)]">
        <form onSubmit={comecar}>
          <label className="block px-4 pt-3.5 text-[13px] font-medium text-cora-muted" htmlFor="vaga">
            Descreva a vaga como falaria com alguém do time
          </label>
          <Textarea
            className="min-h-0 resize-none rounded-none border-0 bg-transparent px-4 pb-1.5 pt-2 text-lg leading-normal shadow-none focus-visible:ring-0 md:text-lg dark:bg-transparent"
            id="vaga"
            onChange={(e) => setDescricao(e.target.value)}
            rows={3}
            value={descricao}
          />
          <Separator className="bg-[#EDF1EE]" />
          <div className="flex flex-wrap items-center justify-between gap-3 py-2.5 pl-4 pr-2.5">
            <span className="flex items-center gap-2 text-[13px] text-cora-placeholder">
              <Lock aria-hidden className="size-3.5" />
              Nada começa antes de você aprovar os critérios
            </span>
            <Button className="h-10 px-4 font-semibold text-white! hover:bg-cora-primary-hover" type="submit">
              Começar hunting
              <ArrowRight aria-hidden />
            </Button>
          </div>
        </form>
      </Card>

      <div className="flex max-w-[900px] flex-wrap justify-center gap-2">
        {IDEIAS.map((ideia) => (
          <Button
            className="h-8 rounded-full border-cora-line-2 bg-cora-surface px-3 text-[13px] font-normal text-cora-muted! shadow-none hover:bg-cora-muted-bg dark:bg-cora-surface"
            key={ideia.rotulo}
            onClick={() => setDescricao(ideia.texto)}
            type="button"
            variant="outline"
          >
            {ideia.rotulo}
          </Button>
        ))}
      </div>
      <p className="mt-1 text-[13px] text-cora-placeholder">Entrega direto na Nara, da Tako</p>
    </section>
  );
}
