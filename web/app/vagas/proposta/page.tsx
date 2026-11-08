"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AppHeader, AppMain } from "../../../components/AppHeader";
import { ApiError, ApiRecusa, criarVaga, proporVaga, type ModeloDeVaga } from "../../../lib/api";

export default function PropostaDeVagaPage() {
  const router = useRouter();
  const [descricao, setDescricao] = useState("");
  const [proposta, setProposta] = useState<ModeloDeVaga | null>(null);
  const [pergunta, setPergunta] = useState("");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function pedir() {
    setOcupado(true);
    setErro("");
    setPergunta("");
    setProposta(null);
    try {
      const resultado = await proporVaga(descricao);
      setProposta(resultado.proposta);
      setPergunta(resultado.pergunta ?? "");
    } catch (erroApi) {
      setErro(erroApi instanceof ApiRecusa || erroApi instanceof ApiError ? erroApi.message : "Não foi possível pedir a proposta.");
    } finally {
      setOcupado(false);
    }
  }

  async function criar() {
    if (!proposta) return;
    setOcupado(true);
    setErro("");
    try {
      const resposta = await criarVaga(proposta);
      router.push(`/vagas/${encodeURIComponent(resposta.vaga.id)}`);
    } catch (erroApi) {
      setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível criar a vaga.");
      setOcupado(false);
    }
  }

  return (
    <div className="min-h-screen bg-cora-bg text-cora-ink">
      <AppHeader ativo="vagas" />
      <AppMain>
        <div className="flex flex-col gap-2.5">
          <nav aria-label="Caminho" className="flex items-center gap-1.5 text-[13px] text-cora-placeholder">
            <Link className="text-cora-placeholder no-underline hover:text-cora-ink" href="/vagas">Vagas</Link>
            <span aria-hidden="true">/</span>
            <Link className="text-cora-placeholder no-underline hover:text-cora-ink" href="/criar-vaga">Nova vaga</Link>
            <span aria-hidden="true">/</span>
            <span aria-current="page" className="text-cora-ink">Proposta da CORA</span>
          </nav>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex min-w-0 flex-col gap-1.5">
              <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">A CORA propõe a vaga</h1>
              <p className="m-0 max-w-[680px] text-[15px] text-cora-muted">Descreva a vaga como falaria a um recrutador, dizendo o que é obrigatório e o que é diferencial. A CORA propõe eliminatórios, desejáveis e meta; você revisa antes de criar. Critério sensível não entra e, na dúvida, a CORA pergunta em vez de inventar.</p>
            </div>
            <Link className="cora-btn cora-btn-outline" href="/criar-vaga">Criar do zero</Link>
          </div>
        </div>

        {erro && <p className="m-0 rounded-lg border border-[#F0B5AA] bg-cora-coral-bg px-4 py-3 text-sm text-cora-coral-ink" role="alert">{erro}</p>}
        <section aria-labelledby="sec-descricao" className="rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)] flex flex-col gap-3.5 px-6 py-[22px]">
          <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-descricao">Descrição em linguagem natural</h2>
          <label className="flex flex-col gap-1.5">
            <span className="sr-only">Descrição da vaga</span>
            <textarea
              className="box-border h-40 w-full resize-y rounded-lg border border-cora-line-2 bg-cora-surface px-3.5 py-3 text-sm leading-relaxed text-cora-ink"
              onChange={(e) => setDescricao(e.target.value)}
              placeholder="Ex.: Vaga de engenharia de software backend. Obrigatório: trabalhar presencialmente em São Paulo e ter experiência com software em produção. Valorizamos Python, sistemas distribuídos e experiência com cloud. Queremos 5 pessoas em 14 dias."
              value={descricao}
            />
          </label>
          {pergunta && <p className="m-0 rounded-lg border border-[#F1D58A] bg-cora-warn-bg px-3.5 py-2.5 text-[13px] text-cora-warn-ink" role="status">A CORA precisa de uma resposta antes de propor: {pergunta}</p>}
          <div className="flex justify-end">
            <button className="cora-btn cora-btn-primary h-10" disabled={ocupado || !descricao.trim()} onClick={pedir} type="button">
              {ocupado && !proposta ? "Pensando…" : "Pedir a proposta à CORA"}
            </button>
          </div>
        </section>
        {proposta && (
          <section aria-labelledby="sec-proposta" className="rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)] flex flex-col gap-4 px-6 py-[22px]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-proposta">{proposta.titulo}</h2>
              <span className="cora-chip cora-chip-warn">Aguardando sua revisão</span>
            </div>
            <dl className="m-0 grid gap-x-4 gap-y-2 text-[13px] sm:grid-cols-[140px_1fr]">
                  <dt className="font-medium text-cora-muted">Eliminatórios</dt>
                  <dd className="m-0 text-cora-ink-2">{proposta.requisitos.map((r) => r.descricao).join("; ") || "nenhum (sem requisito, a CORA decide pelas competências)"}</dd>
                  <dt className="font-medium text-cora-muted">Desejáveis</dt>
                  <dd className="m-0 flex flex-wrap gap-1.5">{proposta.competencias.map((c) => <span className="cora-chip cora-chip-neutral" key={c.nome}>{c.nome} · peso {c.peso}</span>)}</dd>
                  <dt className="font-medium text-cora-muted">Meta</dt>
                  <dd className="num m-0 text-cora-ink-2">{proposta.meta_candidatos} pessoas em {proposta.prazo_dias} dias</dd>
                </dl>
            <div className="flex justify-end border-t border-cora-subtle pt-4">
              <button className="cora-btn cora-btn-primary h-10" disabled={ocupado} onClick={criar} type="button">
                {ocupado ? "Criando…" : "Criar esta vaga e ir para o mandato"}
              </button>
            </div>
          </section>
        )}
      </AppMain>
    </div>
  );
}
