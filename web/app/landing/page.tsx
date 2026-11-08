import type { Metadata } from "next";
import { Source_Serif_4 } from "next/font/google";

import { LandingCora } from "../../components/landing/LandingCora";

const serifa = Source_Serif_4({ variable: "--font-source-serif", subsets: ["latin"], weight: ["400", "600"] });

export const metadata: Metadata = {
  title: "CORA · Diga a vaga. A CORA traz as pessoas.",
  description:
    "A CORA procura no seu banco de talentos e no LinkedIn, explica cada escolha, faz o primeiro contato e entrega quem topou pronto para a entrevista na Nara.",
};

export default function PaginaLanding() {
  return (
    <div className={serifa.variable}>
      <LandingCora />
    </div>
  );
}
