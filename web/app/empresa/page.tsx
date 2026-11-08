"use client";

import Link from "next/link";
import { useState } from "react";

import { Sidebar } from "../../components/Sidebar";

const EMPRESA_ID = process.env.NEXT_PUBLIC_EMPRESA_ID || "empresa-exemplo";
const CHAVE = "macaxeira.perfil.empresa";

type PerfilEmpresa = {
  cultura: string;
  alinhamento: string;
  restricoes: string;
};

const vazio: PerfilEmpresa = { cultura: "", alinhamento: "", restricoes: "" };

export default function EmpresaPage() {
  const [perfil, setPerfil] = useState<PerfilEmpresa>(() => {
    if (typeof window === "undefined") return vazio;
    try {
      const armazenado = window.localStorage.getItem(CHAVE);
      return armazenado ? (JSON.parse(armazenado) as PerfilEmpresa) : vazio;
    } catch {
      return vazio;
    }
  });
  const [salvo, setSalvo] = useState(false);

  function salvar() {
    try {
      window.localStorage.setItem(CHAVE, JSON.stringify(perfil));
      setSalvo(true);
    } catch {
      setSalvo(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="empresa" />
      <div className="md:pl-[238px]">
        <header className="flex h-[80px] items-center justify-between border-b border-[#e4e9e5] bg-white/80 px-5 sm:px-10 md:h-[94px]">
          <div className="flex items-center gap-2"><img alt="Coral da CORA" className="h-10 w-10 object-contain" src="/coral.png" /><div><p className="text-xl font-semibold leading-none tracking-tight text-[#0b3038]">CORA</p><p className="mt-1 text-[7px] font-medium uppercase tracking-wide text-[#718784]">Recrutamento ativo</p></div></div>
          <Link className="text-sm font-medium text-[#526c68] hover:text-[#fb3c0d]" href="/">Voltar ao catálogo</Link>
        </header>
        <div className="mx-auto max-w-[1050px] px-5 py-10 sm:px-8 lg:px-11">
          <header className="mb-8"><p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#4c8885]">Contexto da empresa</p><h1 className="text-4xl font-semibold tracking-[-0.04em] text-[#0b3038]">Perfil da empresa</h1><p className="mt-2 text-sm text-[#718784]">Esse contexto orienta a busca sem substituir decisões humanas.</p></header>
          {salvo && <p className="mb-5 rounded-lg border border-[#b9dfc5] bg-[#eef9f0] px-4 py-3 text-sm text-[#377b5d]" role="status">Perfil salvo neste navegador.</p>}
          <section className="mb-5 rounded-xl border border-[#dfe7e2] bg-white p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#4c8885]">Identificação</p>
            <h2 className="mt-2 text-2xl font-semibold">Empresa conectada</h2>
            <p className="mt-4 text-sm text-[#718784]">Identificador usado no cabeçalho <code className="rounded bg-[#edf5f0] px-1.5 py-0.5 text-[#365650]">X-Empresa-Id</code></p>
            <p className="mt-2 rounded-lg bg-[#f0f4f1] px-4 py-3 font-mono text-sm text-[#365650]">{EMPRESA_ID}</p>
          </section>
          <section className="rounded-xl border border-[#dfe7e2] bg-white p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#4c8885]">Contexto para o agente</p>
            <div className="mt-5 grid gap-5">
              <TextArea label="Valores da cultura" value={perfil.cultura} onChange={(valor) => setPerfil({ ...perfil, cultura: valor })} placeholder="Ex.: colaboração, transparência e aprendizado contínuo." />
              <TextArea label="Regras de alinhamento do agente" value={perfil.alinhamento} onChange={(valor) => setPerfil({ ...perfil, alinhamento: valor })} placeholder="Ex.: priorizar evidências verificáveis e pedir revisão humana em caso de dúvida." />
              <TextArea label="Restrições de contratação" value={perfil.restricoes} onChange={(valor) => setPerfil({ ...perfil, restricoes: valor })} placeholder="Registre restrições determinísticas e legítimas da vaga." />
            </div>
            <div className="mt-6 flex justify-end"><button className="rounded-lg bg-[#fb3c0d] px-6 py-3 text-sm font-semibold text-white shadow-[0_3px_7px_rgba(251,60,13,.22)]" onClick={salvar} type="button">Salvar perfil</button></div>
          </section>
          <p className="mt-5 text-xs text-[#8b9996]">Dados sintéticos · este perfil é salvo localmente e ainda não é enviado para a API.</p>
        </div>
      </div>
    </main>
  );
}

function TextArea({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="grid gap-2 text-sm font-medium text-[#365650]">{label}<textarea className="min-h-28 rounded-lg border border-[#dce5e0] px-3 py-2.5 text-[#0e3038] outline-none focus:border-[#fb3c0d]" value={value} onChange={(evento) => onChange(evento.target.value)} placeholder={placeholder} /></label>;
}
