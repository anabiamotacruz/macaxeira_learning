import { Suspense } from "react";

import { VagaCandidatoDetalhe } from "../../../../../components/VagaCandidatoDetalhe";

export const instant = false;

export default async function VagaCandidatoDetalhePage({ params }: { params: Promise<{ vagaId: string; id: string }> }) {
  const { vagaId, id } = await params;
  return (
    <Suspense fallback={<p className="p-10 text-cora-muted">Carregando a pessoa…</p>}>
      <VagaCandidatoDetalhe candidatoId={decodeURIComponent(id)} vagaId={vagaId} />
    </Suspense>
  );
}
