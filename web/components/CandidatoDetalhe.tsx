"use client";

import { useEffect, useRef, useState } from "react";

import {
  analisesIniciais,
  decisoesIniciais,
  resultadosNaraIniciais,
  vagasIniciais,
} from "../lib/dados";
import { ApiError, listarConvites, modoReservaAtivo, obterDecisaoCandidato, responderConvite } from "../lib/api";
import type { Candidato, Convite, Decisao, TipoDecisao, TipoResposta } from "../lib/tipos";
import { Navegacao } from "./Navegacao";
import { SimuladoBadge } from "./SimuladoBadge";

const REVISOR = "revisor.demo";

export function CandidatoDetalhe({ candidato, vagaId = vagasIniciais[0].id }: { candidato: Candidato; vagaId?: string }) {
  const vaga = vagasIniciais[0];
  const [decisao, setDecisao] = useState<Decisao | undefined>(
    candidato ? decisoesIniciais.find((item) => item.candidato_id === candidato.id) : undefined,
  );
  const resultado = resultadosNaraIniciais.find(
    (item) => item.candidato_id === candidato?.id,
  );
  const [decisaoApi, setDecisaoApi] = useState<Decisao>();
  const [convites, setConvites] = useState<Convite[]>([]);
  const [erroApi, setErroApi] = useState("");
  const [carregandoApi, setCarregandoApi] = useState(!modoReservaAtivo());
  const [respostaEnviada, setRespostaEnviada] = useState("");
  const [exemploFixo, setExemploFixo] = useState(false);
  const chavesResposta = useRef(new Map<string, string>());

  useEffect(() => {
    if (modoReservaAtivo()) return;
    let ativo = true;
    Promise.all([
      obterDecisaoCandidato(candidato.id, vagaId),
      listarConvites(vagaId),
    ])
      .then(([decisaoResposta, convitesResposta]) => {
        if (!ativo) return;
        setDecisaoApi(decisaoResposta.decisao);
        setConvites(convitesResposta.itens);
        setExemploFixo(decisaoResposta.exemplo_fixo === true);
      })
      .catch((erro) => {
        if (ativo) setErroApi(erro instanceof ApiError ? erro.message : "Não foi possível carregar decisão e convites.");
      })
      .finally(() => {
        if (ativo) setCarregandoApi(false);
      });
    return () => {
      ativo = false;
    };
  }, [candidato, vagaId]);

  const analise = analisesIniciais.find((item) => item.candidato_id === candidato.id);
  const decisaoExibida = decisaoApi || decisao;

  function registrarDecisao(tipo: TipoDecisao) {
    setDecisao({
      vaga_id: vaga.id,
      candidato_id: candidato.id,
      tipo,
      regra: "decisao_humana_revisor_demo",
      motivo:
        tipo === "indicar"
          ? "Pessoa revisora aprovou a indicação após conferir as evidências."
          : "Pessoa revisora não aprovou a indicação nesta rodada.",
      responsavel: REVISOR,
      rastro_id: `rastro-local-${candidato.id}`,
      entrada: { origem: candidato.origem },
      evidencias: analise?.evidencias ?? [],
      momento: new Date().toISOString(),
    });
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <Navegacao />
      {erroApi && <p className="mx-auto max-w-5xl px-6 pt-6 text-rose-300" role="alert">{erroApi}</p>}
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.25em] text-cyan-300">
              Detalhe do candidato
            </p>
            <h1 className="text-4xl font-bold tracking-tight">{candidato.nome}</h1>
            <p className="mt-2 text-slate-300">
              Empresa: {candidato.empresa_id} · Fonte: {candidato.fonte}
            </p>
          </div>
          <SimuladoBadge simulado={candidato.simulado} exemplo_fixo={exemploFixo} />
        </header>

        <div className="grid gap-5">
          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">Perfil e autorização</h2>
              <span className="rounded-full bg-slate-800 px-3 py-1 text-sm">
                Estado: {candidato.estado}
              </span>
            </div>
            <p className="mt-4 leading-7 text-slate-300">{candidato.perfil_texto}</p>
            <p className="mt-4 text-sm">
              Autorização de contato:{" "}
              <strong className={candidato.autorizou_contato ? "text-emerald-300" : "text-rose-300"}>
                {candidato.autorizou_contato ? "autorizado" : "sem autorização"}
              </strong>
              {candidato.autorizacao_valida_ate
                ? ` · válida até ${candidato.autorizacao_valida_ate}`
                : ""}
            </p>
          </section>

          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-xl font-semibold">Experiência e competências</h2>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="font-semibold text-cyan-300">Histórico</h3>
                <ul className="mt-2 space-y-3">
                  {candidato.historico.map((item) => (
                    <li className="rounded-lg bg-slate-950 p-3" key={`${item.empresa}-${item.cargo}`}>
                      <strong>{item.cargo}</strong> · {item.empresa}
                      <p className="mt-1 text-sm text-slate-400">{item.descricao}</p>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="font-semibold text-cyan-300">
                  Atributos registrados (competências)
                </h3>
                <dl className="mt-2 space-y-2">
                  {Object.entries(candidato.atributos).map(([nome, valor]) => (
                    <div className="flex justify-between gap-3 border-b border-slate-800 pb-2" key={nome}>
                      <dt>{nome}</dt>
                      <dd className="text-slate-400">{valor}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-3 text-xs text-slate-500">
                  O contrato Candidato não possui campo `competencias`; a tela usa `atributos`.
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-xl font-semibold">Análise</h2>
            {!analise ? (
              <p className="mt-3 text-slate-400">Ainda não analisado.</p>
            ) : (
              <div className="mt-4 grid gap-5">
                <div>
                  <h3 className="font-semibold text-cyan-300">Explicação e evidências</h3>
                  {analise.evidencias.length ? (
                    <ul className="mt-2 space-y-3">
                      {analise.evidencias.map((evidencia) => (
                        <li className="rounded-lg bg-slate-950 p-3" key={`${evidencia.criterio}-${evidencia.trecho}`}>
                          <strong>{evidencia.criterio}</strong>
                          <p className="mt-1 text-slate-300">“{evidencia.trecho}”</p>
                          <p className="mt-1 text-xs text-slate-500">Fonte: {evidencia.fonte}</p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-slate-400">Nenhuma evidência registrada.</p>
                  )}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h3 className="font-semibold text-cyan-300">Lacunas</h3>
                    <p className="mt-2 text-slate-300">{analise.lacunas.join(" ") || "Nenhuma lacuna registrada."}</p>
                  </div>
                  <div>
                    <h3 className="font-semibold text-cyan-300">Alertas</h3>
                    <p className="mt-2 text-amber-200">{analise.alertas.join(" ") || "Nenhum alerta registrado."}</p>
                  </div>
                </div>
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Decisão da pessoa revisora</h2>
                <p className="mt-1 text-sm text-slate-400">
                  Decisão final humana, nunca automática. Responsável: {REVISOR}.
                </p>
              </div>
              <SimuladoBadge />
            </div>
            {carregandoApi ? (
              <p className="mt-4 text-slate-400">Carregando decisão e evidências…</p>
            ) : decisaoExibida ? (
              <div className="mt-4 rounded-lg bg-slate-950 p-4">
                <p className="font-semibold">Resultado: {decisaoExibida.tipo}</p>
                <p className="mt-1 text-slate-300">{decisaoExibida.motivo}</p>
                <p className="mt-3 text-sm text-slate-400">Regra aplicada: {decisaoExibida.regra}</p>
                <ul className="mt-3 space-y-2">
                  {decisaoExibida.evidencias.map((evidencia) => (
                    <li className="rounded bg-slate-900 p-3 text-sm" key={`${evidencia.criterio}-${evidencia.trecho}`}>
                      <strong>{evidencia.criterio}</strong><p className="mt-1 text-slate-300">{evidencia.trecho}</p><p className="mt-1 text-xs text-slate-500">Fonte: {evidencia.fonte}</p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="mt-4 text-slate-400">Ainda não há decisão humana registrada.</p>
            )}
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                className="rounded-lg bg-emerald-400 px-4 py-2 font-semibold text-slate-950"
                onClick={() => registrarDecisao("indicar")}
                type="button"
              >
                Aprovar indicação
              </button>
              <button
                className="rounded-lg border border-rose-400 px-4 py-2 font-semibold text-rose-300"
                onClick={() => registrarDecisao("descartar")}
                type="button"
              >
                Descartar
              </button>
            </div>
          </section>

          {!modoReservaAtivo() && (
            <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
              <h2 className="text-xl font-semibold">Convites</h2>
              {convites.length === 0 ? <p className="mt-3 text-slate-400">Nenhum convite disponível para este candidato.</p> : convites.filter((convite) => convite.candidato_id === candidato.id).map((convite) => (
                <div className="mt-4 rounded-lg bg-slate-950 p-4" key={convite.id}>
                  <p className="text-sm text-slate-300">{convite.mensagem}</p>
                  <button className="mt-3 rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950" onClick={async () => {
                    const pedido = { vaga_id: vagaId, tipo: "duvida" as TipoResposta, texto: "Resposta registrada pelo painel." };
                    const fingerprint = `${convite.id}|${pedido.vaga_id}|${pedido.tipo}|${pedido.texto}`;
                    const chave = chavesResposta.current.get(fingerprint) || crypto.randomUUID();
                    chavesResposta.current.set(fingerprint, chave);
                    try {
                      await responderConvite(convite.id, { ...pedido, chave_idempotencia: chave });
                      chavesResposta.current.delete(fingerprint);
                      setRespostaEnviada("Resposta enviada. Uma nova tentativa reutiliza a mesma chave de idempotência.");
                    } catch (erro) {
                      setErroApi(erro instanceof ApiError ? erro.message : "Não foi possível responder ao convite.");
                    }
                  }} type="button">Responder convite</button>
                </div>
              ))}
              {respostaEnviada && <p className="mt-3 text-sm text-emerald-300">{respostaEnviada}</p>}
            </section>
          )}

          <section className="rounded-2xl border border-cyan-800 bg-cyan-950/40 p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Etapas do fluxo</h2>
                <p className="mt-1 text-sm text-slate-300">
                  A entrevista é conduzida pela Nara simulada; o painel não agenda reuniões.
                </p>
              </div>
              <SimuladoBadge />
            </div>
            <ol className="mt-5 grid gap-3 md:grid-cols-5">
              {[
                ["Analisado", Boolean(analise)],
                ["Aprovado pela pessoa revisora para avançar", decisao?.tipo === "indicar"],
                ["Convite com link da Nara", decisao?.tipo === "indicar"],
                ["Entrevista na Nara (simulada)", Boolean(resultado)],
                [
                  resultado
                    ? `Resultado: ${resultado.aprovado ? "passou" : "não passou"}`
                    : "Resultado",
                  Boolean(resultado),
                ],
              ].map(([etapa, concluida]) => (
                <li
                  className={`rounded-lg border p-3 ${
                    concluida
                      ? "border-cyan-400 bg-slate-950 text-slate-100"
                      : "border-slate-700 bg-slate-900/60 text-slate-500"
                  }`}
                  key={String(etapa)}
                >
                  <span className="flex items-start justify-between gap-2 text-sm font-semibold">
                    {etapa}
                    <SimuladoBadge />
                  </span>
                </li>
              ))}
            </ol>
            {decisao?.tipo === "indicar" && (
              <p className="mt-5 rounded-lg bg-slate-950/60 p-4 text-slate-200">
                Contexto entregue à Nara (simulada).
              </p>
            )}
            {resultado && (
              <div className="mt-4 rounded-lg bg-slate-950/60 p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="font-semibold">ResultadoNara</h3>
                  <SimuladoBadge />
                </div>
                <p className="mt-3 text-sm text-slate-300">
                  Vaga: {resultado.vaga_id} · Candidato: {resultado.candidato_id}
                </p>
                <p className="mt-2 text-slate-200">
                  Resultado: {resultado.aprovado ? "passou" : "não passou"}
                </p>
                <dl className="mt-3 flex flex-wrap gap-3">
                  {Object.entries(resultado.notas).map(([nome, nota]) => (
                    <div className="rounded bg-slate-800 px-3 py-2 text-sm" key={nome}>
                      {nome}: {nota}
                    </div>
                  ))}
                </dl>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
