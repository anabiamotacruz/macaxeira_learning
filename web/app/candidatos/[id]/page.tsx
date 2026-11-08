import { Suspense } from "react";

import { VagaCandidatoDetalhe } from "../../../components/VagaCandidatoDetalhe";

export const instant = false;

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ vaga?: string | string[] }>;
};

async function Detalhe({ params, searchParams }: Props) {
  const [{ id }, { vaga }] = await Promise.all([params, searchParams]);
  const vagaId = typeof vaga === "string" && vaga ? vaga : undefined;
  return <VagaCandidatoDetalhe candidatoId={id} vagaId={vagaId} />;
}

export default function CandidatoPage(props: Props) {
  return (
    <Suspense fallback={<main className="min-h-screen bg-[#f7f8f5] p-10 text-[#0b3038]">Carregando candidato…</main>}>
      <Detalhe {...props} />
    </Suspense>
  );
}
