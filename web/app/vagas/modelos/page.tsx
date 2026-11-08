"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Sidebar } from "../../../components/Sidebar";
import { ApiError, criarVaga, listarModelosDeVaga, type ModeloDeVaga } from "../../../lib/api";

export default function ModelosDeVagaPage() {
  const router = useRouter();
  const [modelos, setModelos] = useState<ModeloDeVaga[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [criando, setCriando] = useState<number | null>(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    listarModelosDeVaga()
      .then(setModelos)
      .catch((erroApi) => setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível carregar os modelos."))
      .finally(() => setCarregando(false));
  }, []);

  async function usar(indice: number) {
    setCriando(indice);
    setErro("");
    try {
      const resposta = await criarVaga(modelos[indice]);
      router.push(`/vagas/${encodeURIComponent(resposta.vaga.id)}`);
    } catch (erroApi) {
      setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível criar a vaga.");
      setCriando(null);
    }
  }

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="criar" />
      <div>
        <div className="mx-auto max-w-[1050px] px-5 py-8 sm:px-6 lg:px-6">
          <Link className="text-sm font-medium text-[#4c8885] hover:text-[#fb3c0d]" href="/criar-vaga">← Criar do zero</Link>
          <h1 className="mt-5 text-4xl font-semibold tracking-[-0.04em] text-[#0b3038]">Modelos de vaga</h1>
          <p className="mt-2 text-sm text-[#718784]">Vagas de exemplo com requisitos eliminatórios e competências, prontas para o agente trabalhar. Os dados são sintéticos.</p>
          {erro && <p className="mt-5 rounded-lg border border-[#f0b5aa] bg-[#fff1ee] px-4 py-3 text-sm text-[#a43826]" role="alert">{erro}</p>}
          {carregando && <p className="mt-8 text-[#718784]">Carregando modelos…</p>}
          <div className="mt-8 grid gap-4">
            {modelos.map((modelo, indice) => (
              <article className="rounded-xl border border-[#dfe7e2] bg-white p-6" key={`${modelo.titulo}-${indice}`}>
                <h2 className="text-xl font-semibold text-[#0b3038]">{modelo.titulo}</h2>
                <p className="mt-2 text-sm text-[#526c68]">{modelo.descricao}</p>
                <div className="mt-3 grid gap-1 text-sm text-[#2c4f55]">
                  <p><b>Eliminatório:</b> {modelo.requisitos.map((r) => r.descricao).join("; ") || "nenhum"}</p>
                  <p><b>Pontua:</b> {modelo.competencias.map((c) => c.nome).join(", ")}</p>
                  <p><b>Meta:</b> {modelo.meta_candidatos} pessoas em {modelo.prazo_dias} dias</p>
                </div>
                <button className="mt-4 rounded-lg bg-[#fb3c0d] px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={criando !== null} onClick={() => usar(indice)} type="button">
                  {criando === indice ? "Criando…" : "Usar este modelo"}
                </button>
              </article>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
