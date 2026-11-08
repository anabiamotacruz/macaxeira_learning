"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, listarCandidatos, modoReservaAtivo } from "../lib/api";
import type { Candidato } from "../lib/tipos";
import { SimuladoBadge } from "./SimuladoBadge";

export function VagaCandidatos({ vagaId }: { vagaId: string }) {
  const [itens, setItens] = useState<Array<{ candidato: Candidato; decisao: string | null }>>([]);
  const [pagina, setPagina] = useState(1);
  const [total, setTotal] = useState(0);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [simulado, setSimulado] = useState(true);
  const [exemploFixo, setExemploFixo] = useState(false);

  useEffect(() => {
    let ativo = true;
    listarCandidatos(vagaId, pagina, 20)
      .then((resposta) => {
        if (!ativo) return;
        setItens(resposta.itens);
        setTotal(resposta.total);
        setSimulado(resposta.simulado !== false);
        setExemploFixo(resposta.exemplo_fixo === true);
      })
      .catch((erroApi) => {
        if (ativo) setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar os candidatos.");
      })
      .finally(() => {
        if (ativo) setCarregando(false);
      });
    return () => {
      ativo = false;
    };
  }, [vagaId, pagina]);

  if (modoReservaAtivo()) {
    return <p className="rounded-xl border border-amber-300 bg-amber-50 p-6 text-amber-900">Dados locais de reserva: candidatos por vaga não são carregados pela API.</p>;
  }
  if (carregando) return <p className="rounded-xl border border-[#dfe7e2] bg-white p-8 text-center text-[#718784]">Carregando candidatos…</p>;
  if (erro) return <p className="rounded-xl border border-[#f0b5aa] bg-[#fff1ee] p-6 text-[#a43826]" role="alert">{erro}</p>;
  if (!itens.length) return <p className="rounded-xl border border-dashed border-[#cbd8d2] bg-white p-8 text-center text-[#81908d]">Nenhum candidato encontrado para esta vaga.</p>;

  return (
    <section className="grid gap-4">
      {itens.map(({ candidato, decisao }) => (
        <Link className="rounded-xl border border-[#dfe7e2] bg-white p-5 transition hover:border-[#fb3c0d]" href={`/candidatos/${encodeURIComponent(candidato.id)}?vaga=${encodeURIComponent(vagaId)}`} key={candidato.id}>
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-lg font-semibold text-[#113b43]">{candidato.nome}</h2>
            <SimuladoBadge simulado={simulado && candidato.simulado} exemplo_fixo={exemploFixo} />
          </div>
          <p className="mt-2 text-sm text-[#4c8885]">{candidato.perfil_texto}</p>
          <p className="mt-4 text-xs text-[#718784]">Decisão preliminar: {decisao || "ainda não registrada"}</p>
        </Link>
      ))}
      <div className="flex items-center justify-between text-sm text-[#718784]">
        <span>{total} candidato(s)</span>
        <div className="flex gap-2">
          <button className="rounded border border-[#dce5e0] px-3 py-1 disabled:opacity-40" disabled={pagina === 1} onClick={() => setPagina((valor) => valor - 1)} type="button">Anterior</button>
          <button className="rounded border border-[#dce5e0] px-3 py-1 disabled:opacity-40" disabled={pagina * 20 >= total} onClick={() => setPagina((valor) => valor + 1)} type="button">Próxima</button>
        </div>
      </div>
    </section>
  );
}
