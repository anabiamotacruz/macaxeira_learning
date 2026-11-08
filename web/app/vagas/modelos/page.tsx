"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader, AppMain } from "../../../components/AppHeader";
import { ApiError, criarVaga, listarModelosDeVaga, type ModeloDeVaga } from "../../../lib/api";

export default function ModelosDeVagaPage() {
  const router = useRouter();
  const [modelos, setModelos] = useState<ModeloDeVaga[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [criando, setCriando] = useState<number | null>(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    listarModelosDeVaga()
      .then(setModelos)
      .catch((erroApi) => setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar os modelos."))
      .finally(() => setCarregando(false));
  }, []);

  async function usar(indice: number) {
    setCriando(indice);
    setErro("");
    try {
      const resposta = await criarVaga(modelos[indice]);
      router.push(`/vagas/${encodeURIComponent(resposta.vaga.id)}`);
    } catch (erroApi) {
      setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível criar a vaga.");
      setCriando(null);
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
            <span aria-current="page" className="text-cora-ink">Modelos</span>
          </nav>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex min-w-0 flex-col gap-1.5">
              <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">Modelos de vaga</h1>
              <p className="m-0 max-w-[680px] text-[15px] text-cora-muted">Vagas de exemplo com eliminatórios e desejáveis, prontas para a CORA trabalhar. Os dados são sintéticos.</p>
            </div>
            <Link className="cora-btn cora-btn-outline" href="/criar-vaga">Criar do zero</Link>
          </div>
        </div>

        {erro && <p className="m-0 rounded-lg border border-[#F0B5AA] bg-cora-coral-bg px-4 py-3 text-sm text-cora-coral-ink" role="alert">{erro}</p>}
        {carregando && <p className="m-0 text-cora-muted">Carregando modelos…</p>}
        <div className="grid gap-4 md:grid-cols-2">
          {modelos.map((modelo, indice) => (
            <article className="rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)] flex flex-col gap-4 px-6 py-[22px]" key={`${modelo.titulo}-${indice}`}>
              <div className="flex flex-col gap-1.5">
                <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]">{modelo.titulo}</h2>
                <p className="m-0 text-[13px] text-cora-muted">{modelo.descricao}</p>
              </div>
              <dl className="m-0 grid gap-x-4 gap-y-2 text-[13px] sm:grid-cols-[140px_1fr]">
                  <dt className="font-medium text-cora-muted">Eliminatórios</dt>
                  <dd className="m-0 text-cora-ink-2">{modelo.requisitos.map((r) => r.descricao).join("; ") || "nenhum (sem requisito, a CORA decide pelas competências)"}</dd>
                  <dt className="font-medium text-cora-muted">Desejáveis</dt>
                  <dd className="m-0 flex flex-wrap gap-1.5">{modelo.competencias.map((c) => <span className="cora-chip cora-chip-neutral" key={c.nome}>{c.nome} · peso {c.peso}</span>)}</dd>
                  <dt className="font-medium text-cora-muted">Meta</dt>
                  <dd className="num m-0 text-cora-ink-2">{modelo.meta_candidatos} pessoas em {modelo.prazo_dias} dias</dd>
                </dl>
              <div className="mt-auto flex justify-end border-t border-cora-subtle pt-4">
                <button className="cora-btn cora-btn-primary" disabled={criando !== null} onClick={() => usar(indice)} type="button">
                  {criando === indice ? "Criando…" : "Usar este modelo"}
                </button>
              </div>
            </article>
          ))}
        </div>
      </AppMain>
    </div>
  );
}
