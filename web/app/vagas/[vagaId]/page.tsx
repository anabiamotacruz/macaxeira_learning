import Link from "next/link";
import { Suspense } from "react";

import { PainelVaga } from "../../../components/PainelVaga";
import { Sidebar } from "../../../components/Sidebar";

export const instant = false;

async function Conteudo({ params }: { params: Promise<{ vagaId: string }> }) {
  const { vagaId } = await params;
  return <PainelVaga vagaId={vagaId} />;
}

export default function PainelDaVagaPage({ params }: { params: Promise<{ vagaId: string }> }) {
  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="catalogo" />
      <div>
        <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-5 py-8 sm:px-6 lg:px-6">
          <Link className="text-sm font-medium text-[#4c8885] hover:text-[#fb3c0d]" href="/">← Voltar ao catálogo</Link>
          <div className="mt-6">
            <Suspense fallback={<p className="text-[#718784]">Carregando a vaga…</p>}>
              <Conteudo params={params} />
            </Suspense>
          </div>
        </div>
      </div>
    </main>
  );
}
