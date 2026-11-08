"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AppHeader, AppMain } from "./AppHeader";
import { ApiError, ApiRecusa, criarVaga, proporVaga } from "../lib/api";
import type { Competencia, Requisito } from "../lib/tipos";

type ItemEliminatorio = Requisito & { aprovado: boolean };
type ItemDesejavel = Competencia & { aprovado: boolean; manual: boolean };

const CARTAO = "rounded-xl border border-cora-line-2 bg-cora-surface shadow-[0_1px_2px_rgba(11,48,56,0.06)]";
const ROTULO = "flex flex-col gap-1.5 text-[13px] font-medium text-cora-ink-2";
const CAMPO = "h-10 box-border rounded-lg border border-cora-line-2 bg-cora-surface px-3 text-sm text-cora-ink";
const ID_CRITERIO = "rounded-[5px] bg-cora-muted-bg px-1.5 py-0.5 font-mono text-xs font-medium text-cora-ink-2";

function mensagemDeErro(erro: unknown, padrao: string): string {
  return erro instanceof ApiRecusa || erro instanceof ApiError ? erro.message : padrao;
}

function horaAgora(): string {
  const agora = new Date();
  return `${String(agora.getHours()).padStart(2, "0")}h${String(agora.getMinutes()).padStart(2, "0")}`;
}

export function CriarVaga({ descricaoInicial = "" }: { descricaoInicial?: string }) {
  const router = useRouter();
  const [titulo, setTitulo] = useState("");
  const [area, setArea] = useState("");
  const [localizacao, setLocalizacao] = useState("");
  const [modelo, setModelo] = useState("Remoto");
  const [senioridade, setSenioridade] = useState("Pleno");
  const [descricao, setDescricao] = useState(descricaoInicial);
  const [eliminatorios, setEliminatorios] = useState<ItemEliminatorio[]>([]);
  const [desejaveis, setDesejaveis] = useState<ItemDesejavel[]>([]);
  const [novaCompetencia, setNovaCompetencia] = useState("");
  const [meta, setMeta] = useState("5");
  const [prazo, setPrazo] = useState("7");
  const [tentativas, setTentativas] = useState("2");
  const [pergunta, setPergunta] = useState("");
  const [propostaEm, setPropostaEm] = useState("");
  const [propondo, setPropondo] = useState(false);
  const [criando, setCriando] = useState(false);
  const [erro, setErro] = useState("");

  const total = eliminatorios.length + desejaveis.length;
  const feitos = eliminatorios.filter((c) => c.aprovado).length + desejaveis.filter((c) => c.aprovado).length;
  const pronto = total > 0 && feitos === total;


  async function pedirProposta() {
    if (!descricao.trim()) {
      setErro("Escreva a descrição da vaga para a CORA propor os critérios.");
      return;
    }
    setPropondo(true);
    setErro("");
    setPergunta("");
    try {
      const resultado = await proporVaga(descricao.trim());
      setPergunta(resultado.pergunta ?? "");
      const proposta = resultado.proposta;
      if (proposta) {
        if (!titulo.trim()) setTitulo(proposta.titulo);
        setEliminatorios(proposta.requisitos.map((r) => ({ ...r, aprovado: false })));
        setDesejaveis(proposta.competencias.map((c) => ({ ...c, aprovado: false, manual: false })));
        setMeta(String(proposta.meta_candidatos));
        setPrazo(String(proposta.prazo_dias));
        setTentativas(String(proposta.max_tentativas_contato));
        setPropostaEm(horaAgora());
      }
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível pedir a proposta."));
    } finally {
      setPropondo(false);
    }
  }

  function adicionarCompetencia() {
    const nome = novaCompetencia.trim();
    if (!nome) return;
    setDesejaveis((atual) => [...atual, { nome, peso: 3, aprovado: true, manual: true }]);
    setNovaCompetencia("");
  }

  function aprovarTodos() {
    setEliminatorios((atual) => atual.map((c) => ({ ...c, aprovado: true })));
    setDesejaveis((atual) => atual.map((c) => ({ ...c, aprovado: true })));
  }

  async function criar() {
    const metaN = Number(meta);
    const prazoN = Number(prazo);
    const tentativasN = Number(tentativas);
    if (!titulo.trim() || !descricao.trim()) {
      setErro("Preencha o título e a descrição da vaga.");
      return;
    }
    if (![metaN, prazoN, tentativasN].every((n) => Number.isInteger(n) && n >= 1)) {
      setErro("Meta, prazo e tentativas precisam ser números inteiros a partir de 1.");
      return;
    }
    if (desejaveis.length === 0) {
      setErro("A vaga precisa de pelo menos um critério desejável. Peça a proposta ou adicione um.");
      return;
    }
    setCriando(true);
    setErro("");
    try {
      const resposta = await criarVaga({
        titulo: titulo.trim(),
        descricao: [
          descricao.trim(),
          `Área: ${area.trim() || "Não informada"}.`,
          `Localização: ${localizacao.trim() || "Não informada"}.`,
          `Modelo de trabalho: ${modelo}.`,
          `Senioridade: ${senioridade}.`,
        ].join(" "),
        requisitos: eliminatorios.map(({ id, descricao: d, campo, valor_esperado }) => ({ id, descricao: d, campo, valor_esperado })),
        competencias: desejaveis.map(({ nome, peso }) => ({ nome, peso })),
        meta_candidatos: metaN,
        prazo_dias: prazoN,
        max_tentativas_contato: tentativasN,
      });
      router.push(`/vagas/${encodeURIComponent(resposta.vaga.id)}`);
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível criar a vaga."));
      setCriando(false);
    }
  }

  const rodape =
    total === 0
      ? "Peça a proposta à CORA ou adicione critérios para começar."
      : pronto
        ? "Tudo aprovado. A busca começa assim que você confirmar e assinar o mandato."
        : `Faltam ${total - feitos} critérios. A busca só começa com todos aprovados.`;

  return (
    <div className="min-h-screen bg-cora-bg text-cora-ink">
      <AppHeader ativo="vagas" />
      <AppMain>
        <div className="flex flex-col gap-2.5">
          <nav aria-label="Caminho" className="flex items-center gap-1.5 text-[13px] text-cora-placeholder">
            <Link className="text-cora-placeholder no-underline hover:text-cora-ink" href="/">Vagas</Link>
            <span aria-hidden="true">/</span>
            <span aria-current="page" className="text-cora-ink">Nova vaga</span>
          </nav>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="m-0 text-[30px] font-semibold leading-[1.15] tracking-[-0.04em]">Criar vaga</h1>
                <span className="inline-flex h-[22px] items-center rounded-md border border-[#F1D58A] bg-cora-warn-bg px-2 text-xs font-semibold text-cora-warn-ink">Rascunho</span>
              </div>
              <p className="m-0 max-w-[640px] text-[15px] text-cora-muted">
                Descreva a vaga como falaria a um recrutador. A CORA propõe os critérios, e nada é buscado antes da sua aprovação.
              </p>
            </div>
            <Link className="cora-btn cora-btn-outline" href="/vagas/modelos">Criar a partir de um modelo</Link>
          </div>
        </div>

        {erro && <p className="m-0 rounded-lg border border-[#F0B5AA] bg-cora-coral-bg px-4 py-3 text-sm text-cora-coral-ink" role="alert">{erro}</p>}

        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="flex min-w-0 flex-col gap-5">
            <section aria-labelledby="sec-sobre" className={`${CARTAO} flex flex-col gap-[18px] px-6 py-[22px]`}>
              <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-sobre">Sobre a oportunidade</h2>
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
                <label className={ROTULO}>Título da vaga<input className={CAMPO} onChange={(e) => setTitulo(e.target.value)} placeholder="Ex.: Pessoa Desenvolvedora Backend Sênior" type="text" value={titulo} /></label>
                <label className={ROTULO}>Área<input className={CAMPO} onChange={(e) => setArea(e.target.value)} placeholder="Ex.: Tecnologia" type="text" value={area} /></label>
                <label className={ROTULO}>Localização<input className={CAMPO} onChange={(e) => setLocalizacao(e.target.value)} placeholder="Ex.: Remoto, encontro mensal em Recife" type="text" value={localizacao} /></label>
                <label className={ROTULO}>Modelo de trabalho
                  <select className={CAMPO} onChange={(e) => setModelo(e.target.value)} value={modelo}><option>Remoto</option><option>Híbrido</option><option>Presencial</option></select>
                </label>
                <label className={ROTULO}>Senioridade
                  <select className={CAMPO} onChange={(e) => setSenioridade(e.target.value)} value={senioridade}><option>Júnior</option><option>Pleno</option><option>Sênior</option><option>Especialista</option></select>
                </label>
              </div>
            </section>

            <section aria-labelledby="sec-descricao" className={`${CARTAO} flex flex-col gap-3.5 px-6 py-[22px]`}>
              <div className="flex flex-col gap-1">
                <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-descricao">Descrição em linguagem natural</h2>
                <p className="m-0 text-[13px] text-cora-muted">Diga o que é obrigatório e o que é diferencial. Na dúvida, a CORA pergunta em vez de inventar.</p>
              </div>
              <label className={ROTULO}>
                <span className="sr-only">Descrição da vaga</span>
                <textarea
                  className="box-border w-full resize-y rounded-lg border border-cora-line-2 bg-cora-surface px-3.5 py-3 text-sm leading-relaxed text-cora-ink"
                  onChange={(e) => setDescricao(e.target.value)}
                  placeholder="Ex.: Backend sênior para o time de pagamentos. Obrigatório: experiência com software em produção e trabalhar presencialmente em São Paulo. Valorizamos Python, Kafka e AWS. Queremos 5 pessoas interessadas em 7 dias."
                  rows={5}
                  value={descricao}
                />
              </label>
              {pergunta && (
                <p className="m-0 rounded-lg border border-[#F1D58A] bg-cora-warn-bg px-3.5 py-2.5 text-[13px] text-cora-warn-ink" role="status">
                  A CORA precisa de uma resposta antes de propor: {pergunta}
                </p>
              )}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-cora-placeholder">
                  {propostaEm ? `Proposta gerada às ${propostaEm}` : "Nenhuma proposta ainda"}
                </span>
                <button className="cora-btn cora-btn-outline h-10" disabled={propondo || !descricao.trim()} onClick={pedirProposta} type="button">
                  <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 16 16" width="15"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v2.8h-2.8" /></svg>
                  {propondo ? "Pensando…" : propostaEm ? "Pedir nova proposta" : "Pedir proposta à CORA"}
                </button>
              </div>
            </section>

            <section aria-labelledby="sec-criterios" className={`${CARTAO} overflow-hidden`}>
              <div className="flex flex-wrap items-start justify-between gap-3 px-6 pb-4 pt-[22px]">
                <div className="flex min-w-0 flex-col gap-1">
                  <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-criterios">Critérios propostos pela CORA</h2>
                  <p className="m-0 max-w-[560px] text-[13px] text-cora-muted">
                    Eliminatórios são checados por regra em código, nunca pelo modelo. Desejáveis só mudam a nota. Atributos sensíveis, como idade, gênero e origem, nunca viram critério.
                  </p>
                </div>
                <span className={`num inline-flex h-6 items-center whitespace-nowrap rounded-md border px-[9px] text-xs font-semibold ${pronto ? "border-[#CDE6D5] bg-cora-ok-bg text-cora-ok-ink" : "border-[#F1D58A] bg-cora-warn-bg text-cora-warn-ink"}`}>
                  {feitos} de {total} aprovados
                </span>
              </div>

              <div className="border-y border-[#EDF1EE] bg-cora-row px-6 py-2.5 text-[13px] font-semibold">Eliminatórios</div>
              {eliminatorios.length === 0 && (
                <p className="m-0 border-b border-cora-subtle px-6 py-3.5 text-[13px] text-cora-muted">
                  Nenhum eliminatório. Sem requisito eliminatório, a CORA decide só pelas competências.
                </p>
              )}
              {eliminatorios.map((c, i) => (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-cora-subtle px-6 py-3.5" key={`${c.id}-${i}`}>
                  <span className={ID_CRITERIO}>E-{String(i + 1).padStart(2, "0")}</span>
                  <span className="flex min-w-0 flex-[1_1_260px] flex-col gap-0.5">
                    <span className="text-sm font-medium">{c.descricao}</span>
                    <span className="text-xs text-cora-placeholder">regra <span className="font-mono">{c.campo} = {c.valor_esperado}</span></span>
                  </span>
                  <BotaoAprovar aprovado={c.aprovado} onClick={() => setEliminatorios((a) => a.map((x, j) => (j === i ? { ...x, aprovado: !x.aprovado } : x)))} />
                  <BotaoRemover rotulo={`Remover critério E-${String(i + 1).padStart(2, "0")}`} onClick={() => setEliminatorios((a) => a.filter((_, j) => j !== i))} />
                </div>
              ))}

              <div className="flex justify-between gap-3 border-b border-[#EDF1EE] bg-cora-row px-6 py-2.5 text-[13px] font-semibold">
                <span>Desejáveis</span>
                <span className="font-medium text-cora-muted">peso de 1 a 5</span>
              </div>
              {desejaveis.map((c, i) => (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-cora-subtle px-6 py-3.5" key={`${c.nome}-${i}`}>
                  <span className={ID_CRITERIO}>D-{String(i + 1).padStart(2, "0")}</span>
                  <span className="flex min-w-0 flex-[1_1_260px] flex-col gap-0.5">
                    <span className="text-sm font-medium">{c.nome}</span>
                    <span className="text-xs text-cora-placeholder">{c.manual ? "Adicionado por você" : "Proposto a partir da descrição"}</span>
                  </span>
                  <label className="inline-flex items-center gap-2 text-[13px] text-cora-muted">
                    Peso
                    <input
                      className="box-border h-8 w-14 rounded-lg border border-cora-line-2 bg-cora-surface px-2 text-sm text-cora-ink"
                      max={5}
                      min={1}
                      onChange={(e) => {
                        const peso = Math.min(5, Math.max(1, Number(e.target.value) || 1));
                        setDesejaveis((a) => a.map((x, j) => (j === i ? { ...x, peso } : x)));
                      }}
                      type="number"
                      value={c.peso}
                    />
                  </label>
                  <BotaoAprovar aprovado={c.aprovado} onClick={() => setDesejaveis((a) => a.map((x, j) => (j === i ? { ...x, aprovado: !x.aprovado } : x)))} />
                  <BotaoRemover rotulo={`Remover critério D-${String(i + 1).padStart(2, "0")}`} onClick={() => setDesejaveis((a) => a.filter((_, j) => j !== i))} />
                </div>
              ))}
              <div className="flex flex-wrap items-end gap-3 px-6 py-3.5">
                <label className={`${ROTULO} flex-[2_1_200px]`}>
                  Adicionar desejável
                  <input
                    className={CAMPO}
                    onChange={(e) => setNovaCompetencia(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        adicionarCompetencia();
                      }
                    }}
                    placeholder="Ex.: Observabilidade"
                    type="text"
                    value={novaCompetencia}
                  />
                </label>
                <button className="cora-btn cora-btn-outline h-10" disabled={!novaCompetencia.trim()} onClick={adicionarCompetencia} type="button">
                  <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="15"><path d="M8 3v10M3 8h10" /></svg>
                  Adicionar
                </button>
              </div>
            </section>

            <section aria-labelledby="sec-meta" className={`${CARTAO} flex flex-col gap-[18px] px-6 py-[22px]`}>
              <div className="flex flex-col gap-1">
                <h2 className="m-0 text-lg font-semibold tracking-[-0.02em]" id="sec-meta">Meta e limites de contato</h2>
                <p className="m-0 text-[13px] text-cora-muted">A busca para quando a meta é atingida ou o prazo acaba. Limites de contato também ficam em código.</p>
              </div>
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
                <label className={ROTULO}>Pessoas entregues à Nara<input className={CAMPO} min={1} onChange={(e) => setMeta(e.target.value)} type="number" value={meta} /></label>
                <label className={ROTULO}>Prazo em dias<input className={CAMPO} min={1} onChange={(e) => setPrazo(e.target.value)} type="number" value={prazo} /></label>
                <label className={ROTULO}>Tentativas de contato por pessoa<input className={CAMPO} max={3} min={1} onChange={(e) => setTentativas(e.target.value)} type="number" value={tentativas} /></label>
              </div>
              <div className="flex items-start gap-3 rounded-[10px] border border-cora-line-2 bg-cora-bg px-4 py-3.5">
                <svg aria-hidden="true" className="mt-0.5 shrink-0 text-cora-ok-ink" fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 16 16" width="18"><path d="M8 1.8 13 4v4c0 3-2.2 5.2-5 6.2C5.2 13.2 3 11 3 8V4l5-2.2Z" /><path d="m5.8 8 1.6 1.6 3-3.2" /></svg>
                <span className="flex flex-col gap-0.5">
                  <span className="font-semibold">Nada começa sem o seu mandato</span>
                  <span className="text-[13px] text-cora-muted">Depois de criar, você assina o mandato no painel da vaga, com o limite de gasto e a política de indicação. Só então a CORA busca e convida.</span>
                </span>
              </div>
            </section>

            <div className={`${CARTAO} flex flex-wrap items-center justify-between gap-3 px-5 py-4`}>
              <span className="text-[13px] text-cora-muted">{rodape}</span>
              <div className="flex flex-wrap gap-2.5">
                {pronto || total === 0 ? (
                  <button className="cora-btn cora-btn-primary h-10 px-4" disabled={criando || total === 0} onClick={criar} type="button">
                    {criando ? "Criando…" : "Aprovar critérios e criar vaga"}
                  </button>
                ) : (
                  <button className="cora-btn cora-btn-primary h-10 px-4" onClick={aprovarTodos} type="button">Aprovar todos os critérios</button>
                )}
              </div>
            </div>
          </div>

          <aside aria-label="Resumo da vaga" className="flex min-w-0 flex-col gap-4">
            <section aria-labelledby="sec-depois" className={`${CARTAO} flex flex-col gap-3.5 p-5`}>
              <h2 className="m-0 text-base font-semibold tracking-[-0.02em]" id="sec-depois">Depois da sua aprovação</h2>
              <ol className="m-0 flex list-none flex-col gap-3 p-0 text-[13px] text-cora-ink-2">
                {[
                  "Você assina o mandato no painel da vaga: limite de gasto e política de indicação.",
                  "A CORA busca no banco de talentos da empresa e nas fontes configuradas.",
                  "Analisa cada perfil com nota por critério, evidência e fonte.",
                  "Convida quem passou no limiar. Sem autorização, sem contato.",
                  "Quem aceita vai para a Nara com o dossiê. A Nara agenda e entrevista; a CORA não agenda nem decide.",
                ].map((texto, i) => (
                  <li className="flex gap-2.5" key={i}>
                    <span className="num flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-cora-muted-bg text-xs font-semibold text-cora-ink">{i + 1}</span>
                    <span>{texto}</span>
                  </li>
                ))}
              </ol>
            </section>
            <section aria-labelledby="sec-custo" className={`${CARTAO} flex flex-col gap-3 p-5`}>
              <h2 className="m-0 text-base font-semibold tracking-[-0.02em]" id="sec-custo">Custo e rastro</h2>
              <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-[13px]">
                <dt className="text-cora-muted">Limite de gasto</dt><dd className="num m-0 font-semibold">definido no mandato</dd>
                <dt className="text-cora-muted">Modelo</dt><dd className="m-0 font-mono text-xs">GLM-5.2</dd>
              </dl>
              <p className="m-0 text-xs text-cora-placeholder">Toda chamada de modelo e ferramenta fica no rastro da vaga. Se o gasto passar do limite, a busca pausa.</p>
            </section>
            <section className={`${CARTAO} flex flex-col gap-2 p-5 text-[13px] text-cora-muted`}>
              <p className="m-0">Prefere outro caminho?</p>
              <Link className="font-medium text-cora-primary no-underline hover:underline" href="/vagas/modelos">Usar um modelo de vaga pronto</Link>
              <Link className="font-medium text-cora-primary no-underline hover:underline" href="/vagas/proposta">Só pedir a proposta ao agente</Link>
            </section>
          </aside>
        </div>
      </AppMain>
    </div>
  );
}

function BotaoAprovar({ aprovado, onClick }: { aprovado: boolean; onClick: () => void }) {
  return (
    <button
      aria-pressed={aprovado}
      className={`inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border px-3 text-[13px] font-semibold ${aprovado ? "border-[#CDE6D5] bg-cora-ok-bg text-cora-ok-ink" : "border-cora-line-2 bg-cora-surface text-cora-ink hover:bg-cora-muted-bg"}`}
      onClick={onClick}
      type="button"
    >
      {aprovado && <svg aria-hidden="true" fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 16 16" width="14"><path d="m3.5 8.5 3 3 6-7" /></svg>}
      {aprovado ? "Aprovado" : "Aprovar"}
    </button>
  );
}

function BotaoRemover({ rotulo, onClick }: { rotulo: string; onClick: () => void }) {
  return (
    <button
      aria-label={rotulo}
      className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg border border-cora-line-2 bg-cora-surface text-cora-muted hover:bg-cora-muted-bg"
      onClick={onClick}
      type="button"
    >
      <svg aria-hidden="true" fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 16 16" width="14"><path d="M4 4l8 8M12 4l-8 8" /></svg>
    </button>
  );
}
