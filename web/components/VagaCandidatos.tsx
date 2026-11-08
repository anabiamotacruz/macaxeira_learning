"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, listarCandidatos, modoReservaAtivo } from "../lib/api";
import type { Candidato } from "../lib/tipos";
import { SimuladoBadge } from "./SimuladoBadge";

const ROTULO_DECISAO: Record<string, { texto: string; classe: string }> = {
  indicar: { texto: "Indicada", classe: "cora-chip-ok" },
  descartar: { texto: "Descartada", classe: "cora-chip-neutral" },
  pedir_humano: { texto: "Revisão humana", classe: "cora-chip-warn" },
};

const ROTULO_DESTINO: Record<string, string> = {
  banco: "Banco de talentos",
  talent_garden: "Talent garden",
  contratada: "Contratada",
};

function iniciais(nome: string): string {
  const partes = nome.split(/\s+/).filter(Boolean);
  return ((partes[0]?.[0] ?? "") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
}

export function VagaCandidatos({ vagaId }: { vagaId: string }) {
  const [itens, setItens] = useState<Array<{ candidato: Candidato; decisao: string | null; destino: string | null }>>([]);
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
    return <p className="m-0 rounded-xl border border-[#F1D58A] bg-cora-warn-bg p-6 text-cora-warn-ink">Dados locais de reserva: candidatos por vaga não são carregados pela API.</p>;
  }
  if (carregando) return <p className="m-0 rounded-xl border border-cora-line bg-cora-surface p-8 text-center text-cora-muted">Carregando candidatos…</p>;
  if (erro) return <p className="m-0 rounded-xl border border-[#F6CFC5] bg-cora-coral-bg p-6 text-cora-coral-ink" role="alert">{erro}</p>;
  if (!itens.length) return <p className="m-0 rounded-xl border border-dashed border-cora-line-2 bg-cora-surface p-8 text-center text-cora-muted">Nenhum candidato encontrado para esta vaga.</p>;

  return (
    <section className="overflow-hidden rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
      <div className="flex items-center justify-between gap-3 border-b border-cora-line px-5 py-3">
        <span className="text-[13px] font-semibold">{total} pessoa(s) analisada(s)</span>
        <SimuladoBadge exemplo_fixo={exemploFixo} simulado={simulado} />
      </div>
      <ul className="m-0 list-none p-0">
        {itens.map(({ candidato, decisao, destino }) => {
          const selo = decisao ? ROTULO_DECISAO[decisao] : undefined;
          return (
            <li className="border-b border-cora-subtle last:border-b-0" key={candidato.id}>
              <Link className="cora-row flex items-center gap-4 px-5 py-3.5 text-cora-ink no-underline" href={`/vagas/${encodeURIComponent(vagaId)}/candidatos/${encodeURIComponent(candidato.id)}`}>
                <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-cora-muted-bg text-xs font-semibold">{iniciais(candidato.nome)}</span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold hover:text-cora-primary">{candidato.nome}</span>
                  <span className="truncate text-[13px] text-cora-muted">{candidato.perfil_texto}</span>
                </span>
                {destino && <span className="cora-chip cora-chip-coral hidden sm:inline-flex">{ROTULO_DESTINO[destino] ?? destino}</span>}
                <span className={`cora-chip ${selo?.classe ?? "cora-chip-neutral"}`}>{selo?.texto ?? "Sem decisão"}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="flex items-center justify-between border-t border-cora-line px-5 py-3 text-[13px] text-cora-muted">
        <span>Página {pagina} de {Math.max(1, Math.ceil(total / 20))}</span>
        <div className="flex gap-2">
          <button className="cora-btn cora-btn-outline h-8" disabled={pagina === 1} onClick={() => setPagina((valor) => valor - 1)} type="button">Anterior</button>
          <button className="cora-btn cora-btn-outline h-8" disabled={pagina * 20 >= total} onClick={() => setPagina((valor) => valor + 1)} type="button">Próxima</button>
        </div>
      </div>
    </section>
  );
}
