import { Suspense } from "react";
import { VagaCandidatoDetalhe } from "../../../../../components/VagaCandidatoDetalhe";

export const instant = false;

export default async function VagaCandidatoDetalhePage({ params }: { params: Promise<{ vagaId: string; id: string }> }) {
  const { vagaId, id } = await params;
  return <Suspense fallback={<main className="min-h-screen bg-[#f7f8f5] p-10 text-[#0b3038]">Carregando candidato…</main>}><VagaCandidatoDetalhe candidatoId={id} vagaId={vagaId} /></Suspense>;
}
