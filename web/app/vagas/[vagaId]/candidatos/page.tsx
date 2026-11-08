import Link from "next/link";
import { Suspense } from "react";

import { VagaCandidatos } from "../../../../components/VagaCandidatos";
import { Sidebar } from "../../../../components/Sidebar";

export const instant = false;

export default async function VagaCandidatosPage({ params }: { params: Promise<{ vagaId: string }> }) {
  const { vagaId } = await params;
  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="catalogo" />
      <div className="mx-auto w-full max-w-[1240px] px-5 py-8 sm:px-6">
        <Link className="text-sm text-[#4c8885]" href="/">← Voltar ao catálogo</Link>
        <h1 className="mt-5 text-4xl font-semibold">Candidatos da vaga</h1>
        <p className="mt-2 text-sm text-[#718784]">Vaga: {vagaId}</p>
        <div className="mt-8"><Suspense fallback={<p>Carregando candidatos…</p>}><VagaCandidatos vagaId={vagaId} /></Suspense></div>
      </div>
    </main>
  );
}
