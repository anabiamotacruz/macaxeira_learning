"use client";

import Link from "next/link";
import { BriefcaseBusiness, LayoutGrid, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Sidebar } from "../../components/Sidebar";
import { SimuladoBadge } from "../../components/SimuladoBadge";
import { candidatosIniciais, decisoesIniciais, vagasIniciais } from "../../lib/dados";
import { ApiError, listarPessoasDoBanco, modoReservaAtivo, type PessoaDoBanco } from "../../lib/api";
import type { EstadoBanco, TipoDecisao } from "../../lib/tipos";

const estados: Array<EstadoBanco | "todos"> = [
  "todos",
  "ativo",
  "pendente",
  "desatualizado",
  "expirado",
  "removido",
];

const rotuloDecisao: Record<TipoDecisao, string> = {
  indicar: "Indicado",
  descartar: "Descartado",
  pedir_humano: "Aguarda revisão humana",
};

// Só no modo reserva (NEXT_PUBLIC_MODO_RESERVA=true), identificado na tela.
function pessoasDeReserva(): PessoaDoBanco[] {
  return candidatosIniciais.map((candidato) => ({
    candidato,
    vagaId: vagasIniciais[0].id,
    vagaTitulo: vagasIniciais[0].titulo,
    decisao: decisoesIniciais.find((decisao) => decisao.candidato_id === candidato.id)?.tipo ?? null,
    nota: null,
    simulado: true,
  }));
}

export default function BancoPage() {
  const reserva = modoReservaAtivo();
  const [pessoas, setPessoas] = useState<PessoaDoBanco[]>(() => (reserva ? pessoasDeReserva() : []));
  const [carregando, setCarregando] = useState(!reserva);
  const [erro, setErro] = useState("");
  const [busca, setBusca] = useState("");
  const [estado, setEstado] = useState<EstadoBanco | "todos">("todos");

  useEffect(() => {
    if (reserva) return;
    let ativo = true;
    listarPessoasDoBanco()
      .then((lista) => {
        if (ativo) setPessoas(lista);
      })
      .catch((erroApi) => {
        if (ativo) setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar o banco de talentos.");
      })
      .finally(() => {
        if (ativo) setCarregando(false);
      });
    return () => {
      ativo = false;
    };
  }, [reserva]);

  const filtradas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return pessoas.filter(({ candidato }) => {
      const combinaBusca =
        !termo ||
        candidato.nome.toLowerCase().includes(termo) ||
        Object.keys(candidato.atributos).some((competencia) =>
          competencia.toLowerCase().includes(termo),
        );
      return combinaBusca && (estado === "todos" || candidato.estado === estado);
    });
  }, [busca, estado, pessoas]);

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="banco" />

      <div className="mx-auto max-w-[1240px] px-5 py-8 sm:px-6 lg:px-6">
          <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
            <div>
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#4c8885]">Recrutamento inteligente</p>
              <h1 className="text-4xl font-semibold tracking-[-0.04em] text-[#0b3038] sm:text-[38px]">Banco de talentos</h1>
              <p className="mt-2 text-sm text-[#718784]">Consulte perfis por estado e autorização de contato.</p>
            </div>
            <SimuladoBadge />
          </header>

          {reserva && (
            <p className="mb-5 rounded-lg border border-[#f1c36a] bg-[#fff7df] px-4 py-3 text-sm text-[#805d16]">
              Dados locais de reserva
            </p>
          )}
          {erro && (
            <p className="mb-5 rounded-lg border border-[#f0b5aa] bg-[#fff1ee] px-4 py-3 text-sm text-[#a43826]" role="alert">
              {erro}
            </p>
          )}
          <section className="mb-5 grid gap-3 rounded-xl border border-[#dfe7e2] bg-white p-5 md:grid-cols-[1fr_220px]">
            <label className="grid gap-2 text-sm font-medium text-[#526c68]">
              Buscar por nome ou competência
              <input
                className="rounded-lg border border-[#dce5e0] bg-white px-3 py-2 text-[#0e3038] outline-none focus:border-[#fb3c0d]"
                value={busca}
                onChange={(evento) => setBusca(evento.target.value)}
                placeholder="Ex.: Python"
              />
            </label>
            <label className="grid gap-2 text-sm font-medium text-[#526c68]">
              Estado
              <select
                className="rounded-lg border border-[#dce5e0] bg-white px-3 py-2 text-[#0e3038] outline-none focus:border-[#fb3c0d]"
                value={estado}
                onChange={(evento) => setEstado(evento.target.value as EstadoBanco | "todos")}
              >
                {estados.map((opcao) => (
                  <option key={opcao} value={opcao}>{opcao === "todos" ? "Todos" : opcao}</option>
                ))}
              </select>
            </label>
          </section>
          {carregando ? (
            <p className="rounded-xl border border-[#dfe7e2] bg-white p-8 text-center text-sm text-[#81908d]">Carregando banco de talentos…</p>
          ) : erro ? null : filtradas.length === 0 ? (
            <p className="rounded-xl border border-dashed border-[#cbd8d2] bg-white p-8 text-center text-sm text-[#81908d]">
              {pessoas.length === 0 ? "Nenhuma pessoa nas vagas desta empresa ainda." : "Nenhum candidato encontrado com esses filtros."}
            </p>
          ) : (
            <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filtradas.map(({ candidato, vagaId, vagaTitulo, decisao, nota, simulado }) => {
                const experiencia = candidato.historico.at(-1);
                return (
                  <Link
                    className="group rounded-xl border border-[#dfe7e2] bg-white p-5 shadow-[0_1px_2px_rgba(29,55,47,.02)] transition hover:-translate-y-1 hover:border-[#fb3c0d]"
                    href={`/candidatos/${encodeURIComponent(candidato.id)}?vaga=${encodeURIComponent(vagaId)}`}
                    key={candidato.id}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <h2 className="text-lg font-semibold text-[#113b43]">{candidato.nome}</h2>
                      <SimuladoBadge simulado={simulado} />
                    </div>
                    <p className="mt-3 text-sm text-[#4c8885]">{experiencia?.cargo ?? "Experiência não informada"}</p>
                    <p className="mt-1 text-xs text-[#718784]">
                      Fonte: {candidato.fonte} · {simulado ? "sintético" : "real"}
                    </p>
                    <div className="mt-5 flex flex-wrap gap-2">
                      {Object.keys(candidato.atributos).map((competencia) => (
                        <span className="rounded-full bg-[#edf5f0] px-2.5 py-1 text-xs text-[#526c68]" key={competencia}>{competencia}</span>
                      ))}
                    </div>
                    <p className="mt-5 text-xs text-[#526c68]">
                      Última decisão: <strong>{decisao ? rotuloDecisao[decisao] : "ainda não registrada"}</strong>
                      {nota !== null && <> · nota {nota.toFixed(2)}</>}
                    </p>
                    <p className="mt-1 text-[11px] text-[#8b9996]">Vaga: {vagaTitulo}</p>
                    <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded-full bg-[#edf0ef] px-2.5 py-1 text-[#526c68]">Estado: {candidato.estado}</span>
                      <span className={`rounded-full px-2.5 py-1 font-semibold ${candidato.autorizou_contato ? "bg-[#e3f3e8] text-[#377b5d]" : "bg-[#fff1ee] text-[#a43826]"}`}>
                        {candidato.autorizou_contato ? "Autorizado para contato" : "Sem autorização"}
                      </span>
                    </div>
                  </Link>
                );
              })}
            </section>
          )}

          <div className="mt-5 flex items-center justify-between">
            <SimuladoBadge />
            <p className="text-[11px] text-[#8b9996]">Dados sintéticos · revisão humana</p>
          </div>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-[#dfe7e2] bg-[#5b5b5b] px-2 py-2 text-[10px] text-[#d0d6d5] md:hidden">
        <Link className="flex flex-col items-center gap-1 rounded-lg px-1 py-2" href="/">
          <BriefcaseBusiness aria-hidden="true" size={18} />
          Catálogo
        </Link>
        <Link className="flex flex-col items-center gap-1 rounded-lg bg-[#fb3c0d] px-1 py-2 font-semibold text-white" href="/banco">
          <Users aria-hidden="true" size={18} />
          Banco
        </Link>
        <Link className="flex flex-col items-center gap-1 rounded-lg px-1 py-2" href="/candidatos">
          <LayoutGrid aria-hidden="true" size={18} />
          Candidatos
        </Link>
      </nav>
    </main>
  );
}
