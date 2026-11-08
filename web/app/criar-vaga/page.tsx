import { Suspense } from "react";

import { CriarVaga } from "../../components/CriarVaga";

// A landing manda a descrição digitada em ?descricao=; ela entra no campo para a CORA propor os critérios.
async function ComDescricao({ searchParams }: { searchParams: PageProps<"/criar-vaga">["searchParams"] }) {
  const vinda = (await searchParams).descricao;
  const descricao = (Array.isArray(vinda) ? vinda[0] : vinda)?.trim().slice(0, 4000) ?? "";
  return <CriarVaga descricaoInicial={descricao} />;
}

export default function CriarVagaPage({ searchParams }: PageProps<"/criar-vaga">) {
  return (
    <Suspense fallback={<CriarVaga />}>
      <ComDescricao searchParams={searchParams} />
    </Suspense>
  );
}
