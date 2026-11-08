import { Suspense } from "react";
import { VagaCandidatoDetalhe } from "../../../../../components/VagaCandidatoDetalhe";

export const instant = false;

export default async function VagaCandidatoDetalhePage({ params }: { params: Promise<{ vagaId: string; id: string }> }) {
  const { vagaId, id } = await params;
  return <Suspense fallback={<main className="min-h-screen bg-slate-950 p-10 text-slate-100">Carregando candidato…</main>}><VagaCandidatoDetalhe candidatoId={id} vagaId={vagaId} /></Suspense>;
}
