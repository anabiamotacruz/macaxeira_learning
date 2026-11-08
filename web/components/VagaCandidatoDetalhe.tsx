"use client";

import { useEffect, useState } from "react";

import { ApiError, listarCandidatos } from "../lib/api";
import type { Candidato } from "../lib/tipos";
import { CandidatoDetalhe } from "./CandidatoDetalhe";

export function VagaCandidatoDetalhe({ vagaId, candidatoId }: { vagaId: string; candidatoId: string }) {
  const [candidato, setCandidato] = useState<Candidato>();
  const [erro, setErro] = useState("");

  useEffect(() => {
    listarCandidatos(vagaId, 1, 100)
      .then((resposta) => {
        const item = resposta.itens.find(({ candidato: valor }) => valor.id === candidatoId);
        if (item) setCandidato(item.candidato);
        else setErro("Candidato não encontrado nesta vaga.");
      })
      .catch((erroApi) => setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar o candidato."));
  }, [vagaId, candidatoId]);

  if (erro) return <main className="min-h-screen bg-slate-950 p-10 text-slate-100">{erro}</main>;
  if (!candidato) return <main className="min-h-screen bg-slate-950 p-10 text-slate-100">Carregando candidato…</main>;
  return <CandidatoDetalhe candidato={candidato} vagaId={vagaId} />;
}
