"use client";

import { useEffect, useState } from "react";

import { ApiError, listarCandidatos } from "../lib/api";
import type { Candidato } from "../lib/tipos";
import { AppHeader, AppMain } from "./AppHeader";
import { CandidatoDetalhe } from "./CandidatoDetalhe";

export function VagaCandidatoDetalhe({ vagaId, candidatoId }: { vagaId: string; candidatoId: string }) {
  const [item, setItem] = useState<{ candidato: Candidato; destino: string | null }>();
  const [erro, setErro] = useState("");

  useEffect(() => {
    listarCandidatos(vagaId, 1, 100)
      .then((resposta) => {
        const achado = resposta.itens.find(({ candidato: valor }) => valor.id === candidatoId);
        if (achado) setItem({ candidato: achado.candidato, destino: achado.destino });
        else setErro("Pessoa não encontrada nesta vaga.");
      })
      .catch((erroApi) => setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar a pessoa."));
  }, [vagaId, candidatoId]);

  if (erro || !item) {
    return (
      <div className="flex min-h-screen flex-col">
        <AppHeader ativo="vagas" />
        <AppMain>
          {erro ? (
            <p className="m-0 rounded-xl border border-[#F6CFC5] bg-cora-coral-bg p-6 text-cora-coral-ink" role="alert">{erro}</p>
          ) : (
            <p className="m-0 rounded-xl border border-cora-line bg-cora-surface p-8 text-center text-cora-muted">Carregando a pessoa…</p>
          )}
        </AppMain>
      </div>
    );
  }
  return <CandidatoDetalhe candidato={item.candidato} destinoInicial={item.destino} vagaId={vagaId} />;
}
