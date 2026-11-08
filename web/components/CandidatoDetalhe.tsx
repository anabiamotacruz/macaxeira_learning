"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  analisesIniciais,
  decisoesIniciais,
  resultadosNaraIniciais,
} from "../lib/dados";
import {
  ApiError,
  listarConvitesDaVaga,
  modoReservaAtivo,
  notaDaDecisao,
  obterDecisaoCandidato,
  responderConvite,
  type ConviteDaVaga,
} from "../lib/api";
import type { Candidato, Decisao, TipoDecisao, TipoResposta } from "../lib/tipos";
import { Sidebar } from "./Sidebar";
import { SimuladoBadge } from "./SimuladoBadge";

const REVISOR = "revisor.demo";

export function CandidatoDetalhe({ candidato, vagaId }: { candidato: Candidato; vagaId: string }) {
  const reserva = modoReservaAtivo();
  // Dados locais só no modo reserva (NEXT_PUBLIC_MODO_RESERVA=true); fora dele, tudo vem da API.
  const [decisao, setDecisao] = useState<Decisao | undefined>(
    reserva ? decisoesIniciais.find((item) => item.candidato_id === candidato.id) : undefined,
  );
  const resultadoReserva = reserva
    ? resultadosNaraIniciais.find((item) => item.candidato_id === candidato.id)
    : undefined;
  const analise = reserva ? analisesIniciais.find((item) => item.candidato_id === candidato.id) : undefined;
  const [decisaoApi, setDecisaoApi] = useState<Decisao>();
  const [convites, setConvites] = useState<ConviteDaVaga[]>([]);
  const [erroApi, setErroApi] = useState("");
  const [carregandoApi, setCarregandoApi] = useState(!reserva);
  const [respostaEnviada, setRespostaEnviada] = useState("");
  const [exemploFixo, setExemploFixo] = useState(false);
  const chavesResposta = useRef(new Map<string, string>());

  useEffect(() => {
    if (reserva) return;
    let ativo = true;
    const decisaoDaApi = obterDecisaoCandidato(candidato.id, vagaId)
      .then((resposta) => {
        if (!ativo) return;
        setDecisaoApi(resposta.decisao);
        setExemploFixo(resposta.exemplo_fixo === true);
      })
      .catch((erro) => {
        // 404: a pessoa ainda não tem decisão nesta vaga. Não é falha da tela.
        if (ativo && !(erro instanceof ApiError && erro.status === 404)) {
          setErroApi(erro instanceof ApiError ? erro.message : "Não foi possível carregar a decisão.");
        }
      });
    const convitesDaApi = listarConvitesDaVaga(vagaId)
      .then((itens) => {
        if (ativo) setConvites(itens.filter((convite) => convite.candidato_id === candidato.id));
      })
      .catch((erro) => {
        if (ativo) setErroApi(erro instanceof ApiError ? erro.message : "Não foi possível carregar os convites.");
      });
    void Promise.all([decisaoDaApi, convitesDaApi]).finally(() => {
      if (ativo) setCarregandoApi(false);
    });
    return () => {
      ativo = false;
    };
  }, [reserva, candidato, vagaId]);

  const decisaoExibida = decisaoApi || decisao;
  const nota = decisaoExibida ? notaDaDecisao(decisaoExibida) : null;
  const retorno = convites.find((convite) => convite.retorno)?.retorno ?? null;
  const resultado = resultadoReserva
    ? { aprovado: resultadoReserva.aprovado, notas: resultadoReserva.notas }
    : retorno
      ? { aprovado: retorno.aprovado, notas: {} as Record<string, number> }
      : undefined;
  const conviteEnviado = reserva ? decisao?.tipo === "indicar" : convites.length > 0;

  function registrarDecisao(tipo: TipoDecisao) {
    setDecisao({
      vaga_id: vagaId,
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
    <main className="min-h-screen bg-[#f7f8f5] text-[#0b3038]">
      <Sidebar active="banco" />
      {erroApi && <p className="mx-auto w-full max-w-[1240px] px-5 pt-6 text-[#a43826] sm:px-6" role="alert">{erroApi}</p>}
      <div className="mx-auto w-full max-w-[1240px] px-5 py-8 sm:px-6">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#4c8885]">
              Detalhe do candidato
            </p>
            <h1 className="text-3xl font-semibold tracking-[-0.04em]">{candidato.nome}</h1>
            <p className="mt-2 text-sm text-[#526c68]">
              Empresa: {candidato.empresa_id} · Fonte: {candidato.fonte}
            </p>
          </div>
          <SimuladoBadge simulado={candidato.simulado} exemplo_fixo={exemploFixo} />
        </header>

        <div className="grid gap-5">
          <section className="rounded-xl border border-[#dfe7e2] bg-white p-6 shadow-[0_1px_2px_rgba(11,48,56,.06)]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">Perfil e autorização</h2>
              <span className="rounded-full bg-[#eef2ef] px-3 py-1 text-sm text-[#526c68]">
                Estado: {candidato.estado}
              </span>
            </div>
            <p className="mt-4 leading-7 text-[#2c4f55]">{candidato.perfil_texto}</p>
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

          <section className="rounded-xl border border-[#dfe7e2] bg-white p-6 shadow-[0_1px_2px_rgba(11,48,56,.06)]">
            <h2 className="text-xl font-semibold">Experiência e competências</h2>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="font-semibold text-[#4c8885]">Histórico</h3>
                <ul className="mt-2 space-y-3">
                  {candidato.historico.map((item) => (
                    <li className="rounded-lg bg-[#f7f8f5] p-3" key={`${item.empresa}-${item.cargo}`}>
                      <strong>{item.cargo}</strong> · {item.empresa}
                      <p className="mt-1 text-sm text-[#718784]">{item.descricao}</p>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="font-semibold text-[#4c8885]">
                  Atributos registrados (competências)
                </h3>
                <dl className="mt-2 space-y-2">
                  {Object.entries(candidato.atributos).map(([nome, valor]) => (
                    <div className="flex justify-between gap-3 border-b border-[#e4e9e5] pb-2" key={nome}>
                      <dt>{nome}</dt>
                      <dd className="text-[#718784]">{valor}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-3 text-xs text-[#81908d]">
                  O contrato Candidato não possui campo `competencias`; a tela usa `atributos`.
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-[#dfe7e2] bg-white p-6 shadow-[0_1px_2px_rgba(11,48,56,.06)]">
            <h2 className="text-xl font-semibold">Análise</h2>
            {!analise ? (
              <p className="mt-3 text-[#718784]">
                {decisaoExibida ? "A explicação, a nota e as evidências estão na decisão abaixo." : "Ainda não analisado."}
              </p>
            ) : (
              <div className="mt-4 grid gap-5">
                <div>
                  <h3 className="font-semibold text-[#4c8885]">Explicação e evidências</h3>
                  {analise.evidencias.length ? (
                    <ul className="mt-2 space-y-3">
                      {analise.evidencias.map((evidencia) => (
                        <li className="rounded-lg bg-[#f7f8f5] p-3" key={`${evidencia.criterio}-${evidencia.trecho}`}>
                          <strong>{evidencia.criterio}</strong>
                          <p className="mt-1 text-[#2c4f55]">“{evidencia.trecho}”</p>
                          <p className="mt-1 text-xs text-[#81908d]">Fonte: {evidencia.fonte}</p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-[#718784]">Nenhuma evidência registrada.</p>
                  )}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h3 className="font-semibold text-[#4c8885]">Lacunas</h3>
                    <p className="mt-2 text-[#2c4f55]">{analise.lacunas.join(" ") || "Nenhuma lacuna registrada."}</p>
                  </div>
                  <div>
                    <h3 className="font-semibold text-[#4c8885]">Alertas</h3>
                    <p className="mt-2 text-amber-200">{analise.alertas.join(" ") || "Nenhum alerta registrado."}</p>
                  </div>
                </div>
              </div>
            )}
          </section>

          <section className="rounded-xl border border-[#dfe7e2] bg-white p-6 shadow-[0_1px_2px_rgba(11,48,56,.06)]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Decisão vigente</h2>
                <p className="mt-1 text-sm text-[#718784]">
                  Vaga: {vagaId}
                  {decisaoExibida ? ` · Responsável: ${decisaoExibida.responsavel}` : ""}
                </p>
              </div>
              <SimuladoBadge />
            </div>
            {carregandoApi ? (
              <p className="mt-4 text-[#718784]">Carregando decisão e evidências…</p>
            ) : decisaoExibida ? (
              <div className="mt-4 rounded-lg bg-[#f7f8f5] p-4">
                <p className="font-semibold">Resultado: {decisaoExibida.tipo}</p>
                <p className="mt-1 text-[#2c4f55]">{decisaoExibida.motivo}</p>
                <p className="mt-3 text-sm text-[#718784]">Regra aplicada: {decisaoExibida.regra}</p>
                {nota !== null && <p className="mt-1 text-sm text-[#718784]">Nota: {nota.toFixed(2)}</p>}
                <ul className="mt-3 space-y-2">
                  {decisaoExibida.evidencias.map((evidencia) => (
                    <li className="rounded bg-white p-3 text-sm" key={`${evidencia.criterio}-${evidencia.trecho}`}>
                      <strong>{evidencia.criterio}</strong><p className="mt-1 text-[#2c4f55]">{evidencia.trecho}</p><p className="mt-1 text-xs text-[#81908d]">Fonte: {evidencia.fonte}</p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="mt-4 text-[#718784]">Ainda não há decisão registrada nesta vaga.</p>
            )}
            {!reserva ? (
              <Link className="mt-5 inline-flex rounded-lg bg-[#0b3038] px-4 py-2 font-semibold text-white" href={`/vagas/${encodeURIComponent(vagaId)}`}>
                Revisar no painel da vaga
              </Link>
            ) : (
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                className="rounded-lg bg-[#dc3209] px-4 py-2 font-semibold text-white"
                onClick={() => registrarDecisao("indicar")}
                type="button"
              >
                Aprovar indicação
              </button>
              <button
                className="rounded-lg border border-[#d9a39a] px-4 py-2 font-semibold text-[#a43826]"
                onClick={() => registrarDecisao("descartar")}
                type="button"
              >
                Descartar
              </button>
            </div>
            )}
          </section>

          {!reserva && (
            <section className="rounded-xl border border-[#dfe7e2] bg-white p-6 shadow-[0_1px_2px_rgba(11,48,56,.06)]">
              <h2 className="text-xl font-semibold">Convites</h2>
              {convites.length === 0 ? <p className="mt-3 text-[#718784]">Nenhum convite disponível para este candidato.</p> : convites.map((convite) => (
                <div className="mt-4 rounded-lg bg-[#f7f8f5] p-4" key={convite.id}>
                  <p className="text-sm text-[#2c4f55]">{convite.mensagem}</p>
                  <button className="mt-3 rounded-lg bg-[#0b3038] px-4 py-2 font-semibold text-white" onClick={async () => {
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

          <section className="rounded-xl border border-[#cbd8d2] bg-[#eef5f1] p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Etapas do fluxo</h2>
                <p className="mt-1 text-sm text-[#526c68]">
                  A entrevista é conduzida pela Nara simulada; o painel não agenda reuniões.
                </p>
              </div>
              <SimuladoBadge />
            </div>
            <ol className="mt-5 grid gap-3 md:grid-cols-5">
              {[
                ["Analisado", Boolean(analise || decisaoApi)],
                ["Indicado para avançar", decisaoExibida?.tipo === "indicar"],
                ["Convite com link da Nara", conviteEnviado],
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
                      ? "border-[#2f6e52] bg-white text-[#0b3038]"
                      : "border-[#dfe7e2] bg-[#f7f8f5] text-[#81908d]"
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
            {conviteEnviado && (
              <p className="mt-5 rounded-lg bg-white p-4 text-[#2c4f55]">
                Contexto entregue à Nara (simulada).
              </p>
            )}
            {resultado && (
              <div className="mt-4 rounded-lg bg-white p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="font-semibold">ResultadoNara</h3>
                  <SimuladoBadge />
                </div>
                <p className="mt-3 text-sm text-[#526c68]">
                  Vaga: {vagaId} · Candidato: {candidato.id}
                </p>
                <p className="mt-2 text-[#2c4f55]">
                  Resultado: {resultado.aprovado ? "passou" : "não passou"}
                </p>
                <dl className="mt-3 flex flex-wrap gap-3">
                  {Object.entries(resultado.notas).map(([nome, nota]) => (
                    <div className="rounded bg-[#eef2ef] px-3 py-2 text-sm" key={nome}>
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
