import { Suspense } from "react";

import { AppHeader, AppMain } from "../../../components/AppHeader";
import { PainelVaga } from "../../../components/PainelVaga";

export const instant = false;

async function Conteudo({ params }: { params: Promise<{ vagaId: string }> }) {
  const { vagaId } = await params;
  return <PainelVaga vagaId={vagaId} />;
}

export default function PainelDaVagaPage({ params }: { params: Promise<{ vagaId: string }> }) {
  return (
    <div className="flex min-h-screen flex-col bg-cora-bg text-cora-ink">
      <AppHeader ativo="vagas" />
      <AppMain>
        <Suspense fallback={<p className="text-cora-muted">Carregando a vaga…</p>}>
          <Conteudo params={params} />
        </Suspense>
      </AppMain>
    </div>
  );
}
