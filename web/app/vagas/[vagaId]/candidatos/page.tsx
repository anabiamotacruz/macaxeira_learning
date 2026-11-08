import Link from "next/link";
import { Suspense } from "react";

import { AppHeader, AppMain } from "../../../../components/AppHeader";
import { VagaCandidatos } from "../../../../components/VagaCandidatos";

export const instant = false;

export default async function VagaCandidatosPage({ params }: { params: Promise<{ vagaId: string }> }) {
  const { vagaId } = await params;
  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader ativo="vagas" />
      <AppMain>
        <nav aria-label="Caminho" className="flex flex-wrap items-center gap-1.5 text-[13px] text-cora-placeholder">
          <Link className="text-cora-placeholder no-underline hover:text-cora-ink" href="/">Vagas</Link>
          <span aria-hidden="true">/</span>
          <Link className="text-cora-placeholder no-underline hover:text-cora-ink" href={`/vagas/${encodeURIComponent(vagaId)}`}>{vagaId}</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page" className="text-cora-ink">Pessoas</span>
        </nav>
        <div className="flex flex-col gap-1.5">
          <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">Pessoas da vaga</h1>
          <p className="m-0 text-[15px] text-cora-muted">Todas as pessoas que a CORA analisou, com a decisão e o destino registrados.</p>
        </div>
        <Suspense fallback={<p className="m-0 text-cora-muted">Carregando candidatos…</p>}>
          <VagaCandidatos vagaId={vagaId} />
        </Suspense>
      </AppMain>
    </div>
  );
}
