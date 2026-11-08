"use client";

import { useEffect, useState } from "react";

import { ApiError, localizarCandidato, modoReservaAtivo } from "../lib/api";
import { candidatosIniciais, vagasIniciais } from "../lib/dados";
import type { Candidato } from "../lib/tipos";
import { CandidatoDetalhe } from "./CandidatoDetalhe";

/** Carrega o candidato pela API. Sem vaga informada, usa a primeira vaga em que a pessoa aparece. */
export function VagaCandidatoDetalhe({ vagaId, candidatoId }: { vagaId?: string; candidatoId: string }) {
  const reserva = modoReservaAtivo();
  const [encontrado, setEncontrado] = useState<{ candidato: Candidato; vagaId: string }>();
  const [erro, setErro] = useState("");

  useEffect(() => {
    if (reserva) return;
    let ativo = true;
    localizarCandidato(candidatoId, vagaId)
      .then((resultado) => {
        if (!ativo) return;
        if (resultado) setEncontrado(resultado);
        else setErro("Candidato não encontrado nas vagas desta empresa.");
      })
      .catch((erroApi) => {
        if (ativo) setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar o candidato.");
      });
    return () => {
      ativo = false;
    };
  }, [reserva, vagaId, candidatoId]);

  if (reserva) {
    // Dados locais de reserva: só com NEXT_PUBLIC_MODO_RESERVA=true.
    const candidato = candidatosIniciais.find((item) => item.id === candidatoId);
    if (!candidato) return <main className="min-h-screen bg-[#f7f8f5] p-10 text-[#0b3038]">Candidato não encontrado nos dados locais de reserva.</main>;
    return <CandidatoDetalhe candidato={candidato} vagaId={vagaId ?? vagasIniciais[0].id} />;
  }
  if (erro) return <main className="min-h-screen bg-[#f7f8f5] p-10 text-[#a43826]" role="alert">{erro}</main>;
  if (!encontrado) return <main className="min-h-screen bg-[#f7f8f5] p-10 text-[#0b3038]">Carregando candidato…</main>;
  return <CandidatoDetalhe candidato={encontrado.candidato} vagaId={encontrado.vagaId} />;
}
