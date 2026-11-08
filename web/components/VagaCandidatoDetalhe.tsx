"use client";

import { useEffect, useState } from "react";

import { ApiError, localizarCandidato, modoReservaAtivo } from "../lib/api";
import { candidatosIniciais } from "../lib/dados";
import type { Candidato } from "../lib/tipos";
import { AppHeader, AppMain } from "./AppHeader";
import { CandidatoDetalhe } from "./CandidatoDetalhe";

/** Carrega a pessoa pela API. Sem vaga informada, usa a primeira vaga em que a pessoa aparece. */
export function VagaCandidatoDetalhe({ vagaId, candidatoId }: { vagaId?: string; candidatoId: string }) {
  const reserva = modoReservaAtivo();
  const [item, setItem] = useState<{ candidato: Candidato; destino: string | null; vagaId: string }>();
  const [erro, setErro] = useState("");

  useEffect(() => {
    if (reserva) return;
    let ativo = true;
    localizarCandidato(candidatoId, vagaId)
      .then((achado) => {
        if (!ativo) return;
        if (achado) setItem(achado);
        else setErro(vagaId ? "Pessoa não encontrada nesta vaga." : "Pessoa não encontrada nas vagas desta empresa.");
      })
      .catch((erroApi) => {
        if (ativo) setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar a pessoa.");
      });
    return () => {
      ativo = false;
    };
  }, [reserva, vagaId, candidatoId]);

  if (reserva) {
    // Dados locais de reserva: só com NEXT_PUBLIC_MODO_RESERVA=true.
    const candidato = candidatosIniciais.find((valor) => valor.id === candidatoId);
    if (candidato) return <CandidatoDetalhe candidato={candidato} vagaId={vagaId} />;
  }
  if (reserva || erro || !item) {
    return (
      <div className="flex min-h-screen flex-col">
        <AppHeader ativo={vagaId ? "vagas" : "banco"} />
        <AppMain>
          {reserva ? (
            <p className="m-0 rounded-xl border border-[#F6CFC5] bg-cora-coral-bg p-6 text-cora-coral-ink" role="alert">Pessoa não encontrada nos dados locais de reserva.</p>
          ) : erro ? (
            <p className="m-0 rounded-xl border border-[#F6CFC5] bg-cora-coral-bg p-6 text-cora-coral-ink" role="alert">{erro}</p>
          ) : (
            <p className="m-0 rounded-xl border border-cora-line bg-cora-surface p-8 text-center text-cora-muted">Carregando a pessoa…</p>
          )}
        </AppMain>
      </div>
    );
  }
  return <CandidatoDetalhe candidato={item.candidato} destinoInicial={item.destino} vagaId={item.vagaId} />;
}
