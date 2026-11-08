"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Sidebar } from "../../../components/Sidebar";
import { ApiError, ApiRecusa, assinarMandato, criarVaga, proporVaga, type ModeloDeVaga, type PoliticaMandato } from "../../../lib/api";

const ASSINANTE = "Pessoa do RH (fictícia)";
const LIMITE_GASTO_USD = 5;

function politicaPadrao(proposta: ModeloDeVaga): PoliticaMandato {
  return {
    limiar_verde: 0.7,
    piso_nota: 0.5,
    max_indicacoes: Math.min(50, Math.max(20, 10 * proposta.meta_candidatos)),
    max_ampliacoes: 1,
    aceitar_declarada: true,
  };
}

export default function PropostaDeVagaPage() {
  const router = useRouter();
  const [descricao, setDescricao] = useState("");
  const [proposta, setProposta] = useState<ModeloDeVaga | null>(null);
  const [pergunta, setPergunta] = useState("");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function pedir() {
    setOcupado(true);
    setErro("");
    setPergunta("");
    setProposta(null);
    try {
      const resultado = await proporVaga(descricao);
      setProposta(resultado.proposta);
      setPergunta(resultado.pergunta ?? "");
    } catch (erroApi) {
      setErro(erroApi instanceof ApiRecusa || erroApi instanceof ApiError ? erroApi.message : "Não foi possível pedir a proposta.");
    } finally {
      setOcupado(false);
    }
  }

  async function criar(soltarOAgente: boolean) {
    if (!proposta) return;
    setOcupado(true);
    setErro("");
    let vagaId: string;
    try {
      vagaId = (await criarVaga(proposta)).vaga.id;
    } catch (erroApi) {
      setErro(erroApi instanceof ApiError ? erroApi.message : "Não foi possível criar a vaga.");
      setOcupado(false);
      return;
    }
    if (soltarOAgente) {
      try {
        await assinarMandato(vagaId, ASSINANTE, politicaPadrao(proposta), LIMITE_GASTO_USD);
      } catch {
        // A vaga já existe: o painel mostra o formulário do mandato para assinar à mão.
      }
    }
    router.push(`/vagas/${encodeURIComponent(vagaId)}`);
  }

  return (
    <main className="min-h-screen bg-[#f7f8f5] text-[#0e3038]">
      <Sidebar active="criar" />
      <div>
        <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-5 py-8 sm:px-6 lg:px-6">
          <Link className="text-sm font-medium text-[#4c8885] hover:text-[#fb3c0d]" href="/criar-vaga">← Criar do zero</Link>
          <h1 className="mt-5 text-4xl font-semibold tracking-[-0.04em] text-[#0b3038]">Descreva a vaga. O agente faz o resto.</h1>
          <p className="mt-2 max-w-2xl text-sm text-[#718784]">
            Descreva a vaga como falaria a um recrutador, dizendo o que é obrigatório e o que é diferencial. O agente propõe os critérios; você aprova com um clique. Daí em diante ele busca no banco de talentos, analisa, explica cada escolha, convida as pessoas por e-mail, responde no WhatsApp e entrega quem aceitar à Nara, sozinho. Critério sensível não entra, e, na dúvida, o agente pergunta em vez de inventar.
          </p>
          <textarea
            className="mt-6 h-40 w-full rounded-xl border border-[#cbd8d2] bg-white p-4 text-sm"
            onChange={(e) => setDescricao(e.target.value)}
            placeholder="Ex.: Vaga de engenharia de software backend. Obrigatório: trabalhar presencialmente em São Paulo e ter experiência com software em produção. Valorizamos Python, sistemas distribuídos e experiência com cloud. Queremos 5 pessoas em 14 dias."
            value={descricao}
          />
          <button className="mt-3 rounded-lg bg-[#fb3c0d] px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={ocupado || !descricao.trim()} onClick={pedir} type="button">
            {ocupado && !proposta ? "Pensando…" : "Pedir a proposta ao agente"}
          </button>
          {erro && <p className="mt-4 rounded-lg border border-[#f0b5aa] bg-[#fff1ee] px-4 py-3 text-sm text-[#a43826]" role="alert">{erro}</p>}
          {pergunta && <p className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">O agente precisa de uma resposta antes de propor: {pergunta}</p>}
          {proposta && (
            <section className="mt-6 rounded-xl border border-[#dfe7e2] bg-white p-6">
              <h2 className="text-xl font-semibold text-[#0b3038]">{proposta.titulo}</h2>
              <div className="mt-3 grid gap-2 text-sm text-[#2c4f55]">
                <p><b>Eliminatório:</b> {proposta.requisitos.map((r) => r.descricao).join("; ") || "nenhum (sem requisito, o agente não indica ninguém sozinho)"}</p>
                <p><b>Pontua:</b> {proposta.competencias.map((c) => `${c.nome} (peso ${c.peso})`).join(", ")}</p>
                <p><b>Meta:</b> {proposta.meta_candidatos} pessoas em {proposta.prazo_dias} dias</p>
              </div>
              <div className="mt-4 rounded-lg border border-[#dfe7e2] bg-[#f7f8f5] px-4 py-3 text-sm text-[#2c4f55]">
                <p className="font-semibold text-[#0b3038]">O que o agente pode fazer sozinho</p>
                <p className="mt-1">
                  Indicar quem tiver nota a partir de 0,7, até {politicaPadrao(proposta).max_indicacoes} indicações, gastar até US$ {LIMITE_GASTO_USD} e ampliar a busca uma vez. Quem ficar abaixo, sem dado ou com perfil suspeito vai para o RH decidir. Ao aprovar, você assina este mandato como {ASSINANTE}.
                </p>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button className="rounded-lg bg-[#fb3c0d] px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={ocupado} onClick={() => criar(true)} type="button">
                  {ocupado ? "Soltando o agente…" : "Aprovar e soltar o agente"}
                </button>
                <button className="text-sm font-medium text-[#4c8885] hover:text-[#fb3c0d] disabled:opacity-40" disabled={ocupado} onClick={() => criar(false)} type="button">
                  Ajustar os limites antes
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
