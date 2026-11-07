import { notFound } from "next/navigation";

import { CandidatoDetalhe } from "../../../components/CandidatoDetalhe";
import { candidatosIniciais } from "../../../lib/dados";

type Props = {
  params: Promise<{ id: string }>;
};

export function generateStaticParams() {
  return candidatosIniciais.map((candidato) => ({ id: candidato.id }));
}

export default async function CandidatoPage({ params }: Props) {
  const { id } = await params;
  const candidato = candidatosIniciais.find((item) => item.id === id);

  if (!candidato) {
    notFound();
  }

  return <CandidatoDetalhe candidato={candidato} />;
}
