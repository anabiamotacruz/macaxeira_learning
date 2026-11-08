"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { Sidebar } from "../../components/Sidebar";
import { ApiError, criarVaga } from "../../lib/api";

export default function CriarVagaPage() {
  const router = useRouter();
  const [titulo, setTitulo] = useState("");
  const [area, setArea] = useState("");
  const [localizacao, setLocalizacao] = useState("");
  const [modelo, setModelo] = useState("Remoto");
  const [contexto, setContexto] = useState("");
  const [competencias, setCompetencias] = useState("");
  const [senioridade, setSenioridade] = useState("Pleno");
  const [meta, setMeta] = useState("5");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");
  const [sucesso, setSucesso] = useState("");

  async function enviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    const tags = competencias.split(",").map((tag) => tag.trim()).filter(Boolean);
    const metaNumerica = Number(meta);
    if (!titulo.trim() || !contexto.trim() || !Number.isInteger(metaNumerica) || metaNumerica < 1) {
      setErro("Preencha o título, o contexto e uma meta válida de candidatos.");
      return;
    }

    setEnviando(true);
    setErro("");
    setSucesso("");
    try {
      const resposta = await criarVaga({
        titulo: titulo.trim(),
        descricao: [
          contexto.trim(),
          `Área: ${area.trim() || "Não informada"}.`,
          `Localização: ${localizacao.trim() || "Não informada"}.`,
          `Modelo de trabalho: ${modelo}.`,
          `Senioridade: ${senioridade}.`,
        ].join(" "),
        requisitos: [],
        competencias: tags.map((nome, indice) => ({ nome, peso: Math.max(1, 5 - indice) })),
        meta_candidatos: metaNumerica,
        prazo_dias: 7,
        max_tentativas_contato: 2,
      });
      setSucesso(`Vaga "${resposta.vaga.titulo}" criada. Abrindo o painel para assinar o mandato…`);
      router.push(`/vagas/${encodeURIComponent(resposta.vaga.id)}`);
    } catch (erroApi) {
      setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível criar a vaga.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="criar" />
      <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-5 py-8 sm:px-6 lg:px-6">
          <header className="mb-8">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#4c8885]">Nova oportunidade</p>
            <h1 className="text-4xl font-semibold tracking-[-0.04em] text-[#0b3038]">Criar vaga</h1>
            <p className="mt-2 text-sm text-[#718784]">Defina o contexto para iniciar uma busca responsável.</p>
            <p className="mt-2 text-sm text-[#718784]">Quer testar o fluxo completo? <Link className="font-medium text-[#fb3c0d] hover:underline" href="/vagas/modelos">Crie a partir de um modelo de vaga</Link>, que já vem com requisitos eliminatórios, ou <Link className="font-medium text-[#fb3c0d] hover:underline" href="/vagas/proposta">peça ao agente para propor os critérios</Link>.</p>
          </header>
          {erro && <p className="mb-5 rounded-lg border border-[#f0b5aa] bg-[#fff1ee] px-4 py-3 text-sm text-[#a43826]" role="alert">{erro}</p>}
          {sucesso && <p className="mb-5 rounded-lg border border-[#b9dfc5] bg-[#eef9f0] px-4 py-3 text-sm text-[#377b5d]" role="status">{sucesso}</p>}
          <form className="grid gap-5" onSubmit={enviar}>
            <section className="rounded-xl border border-[#dfe7e2] bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#4c8885]">Bloco 01</p>
              <h2 className="mt-2 text-2xl font-semibold text-[#0b3038]">Sobre a oportunidade</h2>
              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <Field label="Título da vaga" value={titulo} onChange={setTitulo} placeholder="Ex.: Pessoa engenheira Python sênior" />
                <Field label="Área" value={area} onChange={setArea} placeholder="Ex.: Tecnologia" />
                <Field label="Localização" value={localizacao} onChange={setLocalizacao} placeholder="Ex.: Recife, PE" />
                <label className="grid gap-2 text-sm font-medium text-[#365650]">Modelo de trabalho<select className="rounded-lg border border-[#dce5e0] px-3 py-2.5 outline-none focus:border-[#fb3c0d]" value={modelo} onChange={(evento) => setModelo(evento.target.value)}><option>Remoto</option><option>Híbrido</option><option>Presencial</option></select></label>
              </div>
            </section>
            <section className="rounded-xl border border-[#dfe7e2] bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#4c8885]">Bloco 02</p>
              <h2 className="mt-2 text-2xl font-semibold text-[#0b3038]">Critérios de busca</h2>
              <div className="mt-5 grid gap-4">
                <label className="grid gap-2 text-sm font-medium text-[#365650]">Responsabilidades e contexto<textarea className="min-h-32 rounded-lg border border-[#dce5e0] px-3 py-2.5 outline-none focus:border-[#fb3c0d]" value={contexto} onChange={(evento) => setContexto(evento.target.value)} placeholder="Conte o que essa pessoa fará e em qual contexto." /></label>
                <Field label="Competências essenciais (separadas por vírgula)" value={competencias} onChange={setCompetencias} placeholder="Ex.: Python, APIs, produto" />
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="grid gap-2 text-sm font-medium text-[#365650]">Senioridade<select className="rounded-lg border border-[#dce5e0] px-3 py-2.5 outline-none focus:border-[#fb3c0d]" value={senioridade} onChange={(evento) => setSenioridade(evento.target.value)}><option>Júnior</option><option>Pleno</option><option>Sênior</option><option>Especialista</option></select></label>
                  <label className="grid gap-2 text-sm font-medium text-[#365650]">Limite de perfis / meta de candidatos<input className="rounded-lg border border-[#dce5e0] px-3 py-2.5 outline-none focus:border-[#fb3c0d]" min="1" type="number" value={meta} onChange={(evento) => setMeta(evento.target.value)} /></label>
                </div>
              </div>
            </section>
            <aside className="rounded-xl border border-[#cce5a2] bg-[#f0f9df] p-5">
              <h2 className="font-semibold text-[#3d7c2d]">Busca responsável ativada</h2>
              <p className="mt-2 text-sm leading-6 text-[#597548]">Usaremos somente dados autorizados e sintéticos nesta demonstração. A coleta é discriminada e decisões sobre pessoas continuam com uma pessoa revisora.</p>
            </aside>
            <div className="flex justify-end">
              <button className="rounded-lg bg-[#fb3c0d] px-6 py-3 text-sm font-semibold text-white shadow-[0_3px_7px_rgba(251,60,13,.22)] disabled:cursor-not-allowed disabled:opacity-60" disabled={enviando} type="submit">{enviando ? "Criando..." : "Criar vaga e iniciar busca"}</button>
            </div>
          </form>
        </div>
    </main>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="grid gap-2 text-sm font-medium text-[#365650]">{label}<input className="rounded-lg border border-[#dce5e0] px-3 py-2.5 outline-none focus:border-[#fb3c0d]" value={value} onChange={(evento) => onChange(evento.target.value)} placeholder={placeholder} /></label>;
}
