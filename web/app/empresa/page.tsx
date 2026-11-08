"use client";

import { useState } from "react";

import { AppHeader, AppMain } from "../../components/AppHeader";
import { ApiError, ApiRecusa, reiniciarSessao } from "../../lib/api";

const EMPRESA_ID = process.env.NEXT_PUBLIC_EMPRESA_ID || "empresa-exemplo";
const CHAVE = "macaxeira.perfil.empresa";

type Contrato = "Não aliciamento" | "Fidelidade";
type EmpresaBloqueada = { nome: string; contrato: Contrato; validoAte: string };

type PerfilEmpresa = {
  cultura: string;
  alinhamento: string;
  restricoes: string;
  blacklist?: EmpresaBloqueada[];
};

const vazio: PerfilEmpresa = { cultura: "", alinhamento: "", restricoes: "", blacklist: [] };

function lerPerfil(): PerfilEmpresa {
  if (typeof window === "undefined") return vazio;
  try {
    const armazenado = window.localStorage.getItem(CHAVE);
    return armazenado ? { ...vazio, ...(JSON.parse(armazenado) as PerfilEmpresa) } : vazio;
  } catch {
    return vazio;
  }
}

const REGRAS_FIXAS = [
  "Sem autorização, a pessoa recebe só o pedido de autorização, nunca a vaga.",
  "O primeiro lote de convites de cada vaga espera a aprovação do RH.",
  "Pedido de remoção ou “não quero contato” encerra tudo na hora.",
  "A CORA se apresenta como assistente, nunca como pessoa.",
  "A CORA não agenda entrevistas: quem agenda e avalia é a Nara.",
];

export default function EmpresaPage() {
  const [perfil, setPerfil] = useState<PerfilEmpresa>(lerPerfil);
  const [salvo, setSalvo] = useState(false);
  const [nova, setNova] = useState<EmpresaBloqueada>({ nome: "", contrato: "Não aliciamento", validoAte: "" });
  const [reinicio, setReinicio] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [reiniciando, setReiniciando] = useState(false);

  const blacklist = perfil.blacklist ?? [];

  function alterar(parcial: Partial<PerfilEmpresa>) {
    setPerfil((p) => ({ ...p, ...parcial }));
    setSalvo(false);
  }

  function salvar() {
    try {
      window.localStorage.setItem(CHAVE, JSON.stringify(perfil));
      setSalvo(true);
    } catch {
      setSalvo(false);
    }
  }

  function adicionarEmpresa() {
    const nome = nova.nome.trim();
    if (!nome) return;
    alterar({ blacklist: [...blacklist, { ...nova, nome, validoAte: nova.validoAte.trim() }] });
    setNova({ nome: "", contrato: "Não aliciamento", validoAte: "" });
  }

  async function reiniciar() {
    if (!window.confirm("Reiniciar os dados de demonstração desta empresa? As vagas e decisões sintéticas voltam ao estado inicial.")) return;
    setReiniciando(true);
    setReinicio(null);
    try {
      const resposta = await reiniciarSessao();
      setReinicio({ tipo: resposta.dados_recarregados ? "ok" : "erro", texto: resposta.mensagem });
    } catch (erro) {
      setReinicio({
        tipo: "erro",
        texto: erro instanceof ApiRecusa || erro instanceof ApiError ? erro.message : "Não foi possível reiniciar os dados.",
      });
    } finally {
      setReiniciando(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader ativo="empresa" />
      <AppMain>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1.5">
            <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">Perfil da empresa</h1>
            <p className="m-0 max-w-[620px] text-[15px] text-cora-muted">
              O que vale para todas as vagas da empresa. Este contexto orienta a CORA, mas não substitui decisões humanas.
            </p>
          </div>
        </div>

        <section aria-labelledby="sec-id" className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-cora-line-2 bg-cora-surface px-6 py-5 shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
          <div className="flex min-w-0 items-center gap-3.5">
            <span aria-hidden="true" className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[10px] bg-cora-muted-bg text-cora-ink">
              <svg fill="none" height="22" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6" viewBox="0 0 16 16" width="22"><path d="M3 14V3.5L8 2v12M8 5h5v9M5 5.5h1M5 8h1M5 10.5h1M10 7h1M10 9.5h1M10 12h1M1.5 14h13" /></svg>
            </span>
            <div className="flex flex-col gap-0.5">
              <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-id">Empresa conectada</h2>
              <span className="text-[13px] text-cora-muted">
                Identificador no cabeçalho <span className="font-mono">X-Empresa-Id</span>: <span className="font-mono text-cora-ink">{EMPRESA_ID}</span>
              </span>
            </div>
          </div>
          <div className="flex flex-wrap gap-6 text-[13px]">
            <span className="flex max-w-[220px] flex-col">
              <span className="text-cora-muted">Banco</span>
              <span className="font-medium">Isolado: nada aparece para outra empresa</span>
            </span>
          </div>
        </section>

        <section aria-labelledby="sec-blacklist" className="overflow-hidden rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
          <div className="flex flex-wrap items-start justify-between gap-3 px-6 pb-4 pt-5">
            <div className="flex min-w-0 flex-col gap-1">
              <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-blacklist">Blacklist de empresas</h2>
              <p className="m-0 max-w-[620px] text-[13px] text-cora-muted">
                Empresas com contrato de não aliciamento ou fidelidade. Quem trabalha hoje nelas não deve ser abordado. Por
                enquanto a lista fica salva neste navegador, junto com o perfil.
              </p>
            </div>
            <span className="cora-chip cora-chip-neutral num font-semibold">{blacklist.length} {blacklist.length === 1 ? "ativa" : "ativas"}</span>
          </div>
          <div className="overflow-x-auto">
            <div aria-label="Empresas na blacklist" className="min-w-[640px]" role="table">
              <div className="grid grid-cols-[1.4fr_1fr_1.1fr_80px] gap-3.5 border-y border-[#edf1ee] bg-cora-row px-6 py-2.5 text-xs font-medium text-cora-placeholder" role="row">
                <span role="columnheader">Empresa</span>
                <span role="columnheader">Contrato</span>
                <span role="columnheader">Válido até</span>
                <span role="columnheader"><span className="sr-only">Ações</span></span>
              </div>
              {blacklist.length === 0 ? (
                <p className="px-6 py-5 text-[13px] text-cora-muted">Nenhuma empresa na blacklist.</p>
              ) : (
                blacklist.map((e, i) => (
                  <div className="grid grid-cols-[1.4fr_1fr_1.1fr_80px] items-center gap-3.5 border-b border-cora-subtle px-6 py-3" key={`${e.nome}-${i}`} role="row">
                    <span className="font-medium" role="cell">{e.nome}</span>
                    <span role="cell">
                      <span className={`cora-chip font-semibold ${e.contrato === "Fidelidade" ? "cora-chip-neutral" : "cora-chip-coral"}`}>{e.contrato}</span>
                    </span>
                    <span className="num text-cora-ink-2" role="cell">{e.validoAte || "—"}</span>
                    <span role="cell">
                      <button
                        aria-label={`Remover ${e.nome}`}
                        className="flex h-8 w-8 items-center justify-center rounded-lg border border-cora-line-2 bg-cora-surface text-cora-muted hover:bg-cora-muted-bg"
                        onClick={() => alterar({ blacklist: blacklist.filter((_, j) => j !== i) })}
                        type="button"
                      >
                        <svg aria-hidden="true" fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="14"><path d="M4 4l8 8M12 4l-8 8" /></svg>
                      </button>
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3 px-6 pb-5 pt-4">
            <label className="cora-label flex flex-[2_1_220px] flex-col gap-1.5">
              Empresa
              <input className="cora-input !h-10" onChange={(e) => setNova({ ...nova, nome: e.target.value })} placeholder="Nome da empresa" type="text" value={nova.nome} />
            </label>
            <label className="cora-label flex flex-[1_1_160px] flex-col gap-1.5">
              Contrato
              <select className="cora-input !h-10" onChange={(e) => setNova({ ...nova, contrato: e.target.value as Contrato })} value={nova.contrato}>
                <option>Não aliciamento</option>
                <option>Fidelidade</option>
              </select>
            </label>
            <label className="cora-label flex flex-[1_1_120px] flex-col gap-1.5">
              Válido até
              <input className="cora-input !h-10" onChange={(e) => setNova({ ...nova, validoAte: e.target.value })} placeholder="MM/AAAA" type="text" value={nova.validoAte} />
            </label>
            <button className="cora-btn cora-btn-outline !h-10" disabled={!nova.nome.trim()} onClick={adicionarEmpresa} type="button">Adicionar empresa</button>
          </div>
        </section>

        <section aria-labelledby="sec-contato" className="flex flex-col gap-4 rounded-xl border border-cora-line-2 bg-cora-surface px-6 py-5 shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
          <div className="flex flex-col gap-1">
            <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-contato">Regras de contato</h2>
            <p className="m-0 text-[13px] text-cora-muted">
              Estas regras rodam em código. O modelo de IA não consegue mudar nenhuma delas, nem a pedido de um candidato.
            </p>
          </div>
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <div className="flex flex-col rounded-[10px] border border-[#edf1ee] bg-cora-row p-3">
              <span className="font-medium">E-mail</span>
              <span className="text-xs text-cora-placeholder">Primeiro contato e pedido de autorização são sempre por e-mail.</span>
            </div>
            <div className="flex flex-col rounded-[10px] border border-[#edf1ee] bg-cora-row p-3">
              <span className="font-medium">WhatsApp</span>
              <span className="text-xs text-cora-placeholder">Só abre quando a pessoa chama pelo link do e-mail.</span>
            </div>
          </div>
          <div className="flex flex-col gap-2.5 rounded-[10px] border border-cora-line-2 bg-cora-bg px-[18px] py-4">
            <span className="text-[13px] font-semibold">Sempre valem, para qualquer vaga</span>
            <ul className="m-0 flex flex-col gap-1.5 pl-5 text-[13px] text-cora-ink-2">
              {REGRAS_FIXAS.map((r) => <li key={r}>{r}</li>)}
            </ul>
          </div>
        </section>

        <section aria-labelledby="sec-contexto" className="flex flex-col gap-4 rounded-xl border border-cora-line-2 bg-cora-surface px-6 py-5 shadow-[0_1px_2px_rgba(11,48,56,0.06)]">
          <div className="flex flex-col gap-1">
            <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-contexto">Contexto para o agente</h2>
            <p className="m-0 text-[13px] text-cora-muted">Usado para escrever mensagens e explicar a vaga. Não vira critério de busca.</p>
          </div>
          <CampoTexto label="Valores da cultura" linhas={3} onChange={(v) => alterar({ cultura: v })} placeholder="Ex.: colaboração, transparência e aprendizado contínuo." value={perfil.cultura} />
          <CampoTexto label="Regras de alinhamento do agente" linhas={3} onChange={(v) => alterar({ alinhamento: v })} placeholder="Ex.: priorizar evidências verificáveis e pedir revisão humana em caso de dúvida." value={perfil.alinhamento} />
          <CampoTexto label="Restrições de contratação" linhas={2} onChange={(v) => alterar({ restricoes: v })} placeholder="Registre restrições legítimas e verificáveis." value={perfil.restricoes} />
        </section>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-[13px] text-cora-muted">Dados sintéticos · o perfil é salvo neste navegador e ainda não é enviado para a API.</span>
          <div className="flex gap-2">
            <button className="cora-btn cora-btn-outline" onClick={() => { setPerfil(lerPerfil()); setSalvo(false); }} type="button">Descartar alterações</button>
            <button className="cora-btn cora-btn-primary" onClick={salvar} type="button">Salvar perfil</button>
          </div>
        </div>
        {salvo && <p className="cora-chip cora-chip-ok self-end" role="status">Perfil salvo neste navegador.</p>}

        <section aria-labelledby="sec-demo" className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-dashed border-cora-line-2 bg-cora-surface px-6 py-5">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="m-0 text-base font-semibold tracking-[-0.02em]" id="sec-demo">Dados de demonstração</h2>
            <p className="m-0 max-w-[620px] text-[13px] text-cora-muted">
              Volta as vagas, decisões e convites sintéticos desta empresa ao estado inicial, para repetir a demonstração.
            </p>
            {reinicio && (
              <p className={`m-0 mt-1 text-[13px] ${reinicio.tipo === "ok" ? "text-cora-ok-ink" : "text-cora-warn-ink"}`} role="status">{reinicio.texto}</p>
            )}
          </div>
          <button className="cora-btn cora-btn-outline" disabled={reiniciando} onClick={reiniciar} type="button">
            {reiniciando ? "Reiniciando…" : "Reiniciar dados de demonstração"}
          </button>
        </section>
      </AppMain>
    </div>
  );
}

function CampoTexto({ label, value, onChange, placeholder, linhas }: { label: string; value: string; onChange: (v: string) => void; placeholder: string; linhas: number }) {
  return (
    <label className="cora-label flex flex-col gap-1.5">
      {label}
      <textarea className="cora-input resize-y" onChange={(e) => onChange(e.target.value)} placeholder={placeholder} rows={linhas} value={value} />
    </label>
  );
}
