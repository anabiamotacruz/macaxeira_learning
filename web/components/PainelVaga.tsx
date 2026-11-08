"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  ApiRecusa,
  assinarMandato,
  avisarResultadosDasEntrevistas,
  listarCandidatos,
  listarConversasWhatsApp,
  listarConvitesDaVaga,
  listarEventosRecentes,
  listarPacotesEntregues,
  obterAudioWhatsApp,
  obterDecisao,
  obterDocumentoDeEntrega,
  obterSugestaoDeAjuste,
  obterResumo,
  obterVaga,
  responderConvite,
  revisarCandidato,
  type ConversaWhatsApp,
  type ConviteDaVaga,
  type PacoteEntregue,
  type ResumoVaga,
  type SugestaoAjuste,
} from "../lib/api";
import type { Candidato, Decisao, EventoFluxo, TipoResposta, Vaga } from "../lib/tipos";
import { SimuladoBadge } from "./SimuladoBadge";

// Texto que vem da API é dado: o React o escapa, e nada aqui o interpreta como instrução.

const ESTADOS: Record<string, string> = {
  rascunho: "Rascunho",
  aguardando_mandato: "Aguardando o mandato",
  buscando: "Buscando pessoas",
  analisando: "Analisando perfis",
  revisando: "Revisando as análises",
  decidindo: "Decidindo",
  meta_em_risco: "Meta em risco",
  convidando: "Convidando",
  entregando: "Entregando à Nara",
  concluida: "Concluída",
  pausada: "Pausada",
};
const ATIVOS = new Set(["buscando", "analisando", "revisando", "decidindo"]);

const MOTIVOS: Record<string, string> = {
  alem_do_teto_do_mandato: "Passou do teto de segurança de indicações do mandato",
  perfil_desatualizado: "Perfil desatualizado: confirmar os dados com a pessoa",
  alerta: "Perfil com texto suspeito (instrução escondida)",
  requisito_sem_dado: "Falta informação sobre um requisito eliminatório",
  sem_evidencia_competencia: "Sem evidência de uma competência",
  sem_evidencia_comprovada: "Requisito só autodeclarado",
  nota_abaixo_do_limiar: "Nota abaixo do limiar do mandato",
  abaixo_do_piso: "Nota abaixo do piso",
  vaga_sem_requisitos: "A vaga não tem requisito eliminatório",
  requisito_nao_confirmado: "Requisito não confirmado no perfil",
  faixa_verde: "Dentro da faixa verde do mandato",
  ressalva_do_revisor: "O revisor fez uma ressalva",
  inferencia: "Parte da evidência foi inferida, não citada",
  requisito_nao_atendido: "Não atende um requisito eliminatório",
  requisito_eliminatorio: "Não atende um requisito eliminatório",
  opt_out: "Pediu para não ser contatada",
  autorizacao_vencida: "Autorização de contato vencida",
  sem_autorizacao: "Sem autorização de contato",
  duplicata: "Registro duplicado",
};

function traduzir(regra: string): string {
  const partes = regra.split(/[,|]\s*/).map((parte) => parte.trim()).filter(Boolean);
  const frases = partes.map((parte) => {
    const chave = Object.keys(MOTIVOS).find((nome) => parte.includes(nome));
    return chave ? MOTIVOS[chave] : parte;
  });
  return [...new Set(frases)].join("; ");
}

const cartao = "rounded-xl border border-[#dfe7e2] bg-white p-5";
const botao =
  "rounded-lg border border-[#cbd8d2] bg-white px-3 py-1.5 text-sm font-medium text-[#0b3038] transition hover:border-[#fb3c0d] disabled:opacity-40";
const botaoPrincipal =
  "rounded-lg bg-[#fb3c0d] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#d9320a] disabled:opacity-40";
const campo = "rounded-lg border border-[#cbd8d2] bg-white px-3 py-1.5 text-sm text-[#0b3038]";

type Item = { candidato: Candidato; decisao: Decisao["tipo"] | null };

function mensagemDeErro(erro: unknown, padrao: string): string {
  if (erro instanceof ApiRecusa || erro instanceof ApiError) return erro.message;
  return padrao;
}

function Secao({ numero, titulo, children, simulado = false }: {
  numero: number;
  titulo: string;
  children: React.ReactNode;
  simulado?: boolean;
}) {
  return (
    <section className="grid gap-4">
      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#0b3038] text-sm font-semibold text-white">{numero}</span>
        <h2 className="text-xl font-semibold text-[#0b3038]">{titulo}</h2>
        {simulado && <SimuladoBadge simulado />}
      </div>
      {children}
    </section>
  );
}

function FormMandato({ vaga, aoAssinar }: { vaga: Vaga; aoAssinar: () => void }) {
  const [assinante, setAssinante] = useState("Pessoa do RH (fictícia)");
  const [limiar, setLimiar] = useState("0.7");
  const [maxIndicacoes, setMaxIndicacoes] = useState(String(Math.min(50, Math.max(20, 10 * vaga.meta_candidatos))));
  const [declarada, setDeclarada] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");

  async function assinar() {
    const limiarVerde = Number(limiar.replace(",", "."));
    const maximo = Number(maxIndicacoes);
    if (!assinante.trim() || !(limiarVerde > 0 && limiarVerde <= 1) || !Number.isInteger(maximo) || maximo < 1) {
      setErro("Preencha quem assina, um limiar entre 0 e 1 e um número inteiro de indicações.");
      return;
    }
    setEnviando(true);
    setErro("");
    try {
      await assinarMandato(vaga.id, assinante.trim(), {
        limiar_verde: limiarVerde,
        piso_nota: Math.min(0.5, limiarVerde),
        max_indicacoes: maximo,
        max_ampliacoes: 1,
        aceitar_declarada: declarada,
      });
      aoAssinar();
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível assinar o mandato."));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className={`${cartao} grid gap-4`}>
      <p className="text-sm text-[#526c68]">
        O mandato é a autonomia que a empresa dá ao agente. Ele busca, analisa e convida sozinho só dentro destes limites; fora deles, a pessoa vai para o RH.
      </p>
      {vaga.requisitos.length === 0 && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Esta vaga não tem requisito eliminatório. Sem ele, o agente não indica ninguém sozinho e todas as pessoas analisadas vão para o RH. Para testar o fluxo completo, crie a vaga a partir de um modelo.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm text-[#526c68]">Quem assina
          <input className={campo} onChange={(e) => setAssinante(e.target.value)} value={assinante} />
        </label>
        <label className="grid gap-1 text-sm text-[#526c68]">Teto de segurança de indicações (não é a meta)
          <input className={campo} inputMode="numeric" onChange={(e) => setMaxIndicacoes(e.target.value)} value={maxIndicacoes} />
        </label>
        <label className="grid gap-1 text-sm text-[#526c68]">Nota mínima para indicar sozinho (0 a 1)
          <input className={campo} inputMode="decimal" onChange={(e) => setLimiar(e.target.value)} value={limiar} />
          <span className="text-xs text-[#81908d]">Com o modelo de verdade, as notas ficam entre 0,6 e 0,9: 0,7 é um bom começo.</span>
        </label>
        <label className="flex items-start gap-2 text-sm text-[#526c68]">
          <input checked={declarada} className="mt-1" onChange={(e) => setDeclarada(e.target.checked)} type="checkbox" />
          <span>Aceitar o que a própria pessoa declarou (currículo e banco de talentos) como evidência. Sem isso, só vale fonte verificável, como GitHub.</span>
        </label>
      </div>
      {erro && <p className="text-sm text-[#a43826]" role="alert">{erro}</p>}
      <div><button className={botaoPrincipal} disabled={enviando} onClick={assinar} type="button">{enviando ? "Assinando…" : "Assinar o mandato e entregar ao agente"}</button></div>
    </div>
  );
}

function CartaoCandidato({ item, decisao, children, cor, vagaId }: {
  item: Item;
  vagaId: string;
  decisao?: Decisao;
  children?: React.ReactNode;
  cor: string;
}) {
  const humano = decisao?.responsavel.startsWith("humano:");
  return (
    <article className={`${cartao} border-l-4`} style={{ borderLeftColor: cor }}>
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold text-[#113b43]">
          <Link className="hover:text-[#fb3c0d] hover:underline" href={`/candidatos/${encodeURIComponent(item.candidato.id)}?vaga=${encodeURIComponent(vagaId)}`}>
            {item.candidato.nome}
          </Link>
        </h3>
        <SimuladoBadge simulado={item.candidato.simulado} />
      </div>
      {decisao && (
        <p className="mt-1 text-sm text-[#526c68]">
          {humano ? `Decidido por ${decisao.responsavel.slice(7)}: ${decisao.motivo}` : traduzir(decisao.regra === "fora_da_faixa_verde" ? decisao.motivo : decisao.regra)}
        </p>
      )}
      {decisao && decisao.evidencias.length > 0 && (
        <ul className="mt-3 grid gap-1 text-sm text-[#2c4f55]">
          {decisao.evidencias.slice(0, 6).map((evidencia, indice) => (
            <li key={`${evidencia.criterio}-${indice}`}><b>{evidencia.criterio}:</b> “{evidencia.trecho}”</li>
          ))}
        </ul>
      )}
      {decisao && <p className="mt-3 font-mono text-[11px] text-[#9aa7a4]">Rastro: {decisao.rastro_id}</p>}
      {children}
    </article>
  );
}

function RevisaoRh({ item, vagaId, responsavel, aoMudar }: {
  item: Item;
  vagaId: string;
  responsavel: string;
  aoMudar: () => void;
}) {
  const [motivo, setMotivo] = useState("Conferi o perfil.");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function decidir(decisao: "indicar" | "descartar") {
    setEnviando(true);
    setErro("");
    try {
      await revisarCandidato(item.candidato.id, { vaga_id: vagaId, decisao, motivo, responsavel });
      aoMudar();
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível registrar a decisão."));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="mt-4 grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label="Motivo" className={`${campo} min-w-[220px] flex-1`} onChange={(e) => setMotivo(e.target.value)} value={motivo} />
        <button className={botao} disabled={enviando} onClick={() => decidir("indicar")} type="button">Indicar para contato</button>
        <button className={botao} disabled={enviando} onClick={() => decidir("descartar")} type="button">Descartar</button>
      </div>
      {erro && <p className="text-sm text-[#a43826]" role="alert">O agente recusou: {erro}</p>}
    </div>
  );
}

const URL_NO_TEXTO = /(https?:\/\/[^\s)]+)/g;

/** Texto com os links clicáveis, como o wa.me do convite e o link da Nara. */
function ComLinks({ texto }: { texto: string }) {
  return (
    <>
      {texto.split(URL_NO_TEXTO).map((parte, indice) =>
        indice % 2 === 1 ? (
          <a className="break-all underline" href={parte} key={indice} rel="noreferrer" target="_blank">{parte}</a>
        ) : (
          <span key={indice}>{parte}</span>
        ),
      )}
    </>
  );
}

function AudioDaResposta({ vagaId, audioId }: { vagaId: string; audioId: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let ativo = true;
    let criada = "";
    obterAudioWhatsApp(vagaId, audioId)
      .then((u) => {
        criada = u;
        if (ativo) setUrl(u);
      })
      .catch(() => undefined);
    return () => {
      ativo = false;
      if (criada) URL.revokeObjectURL(criada);
    };
  }, [vagaId, audioId]);
  if (!url) return null;
  return <audio aria-label="Resposta em voz gerada por IA" className="h-8 w-full max-w-xs" controls src={url} />;
}

function ConversaNoWhatsApp({ conversa, vagaId }: { conversa: ConversaWhatsApp; vagaId: string }) {
  const balaoAgente = "max-w-[85%] rounded-2xl rounded-tl-sm bg-[#dcf8c6] px-4 py-2 text-sm text-[#0b3038]";
  const balaoPessoa = "ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-[#075e54] px-4 py-2 text-sm text-white";
  return (
    <div className="grid gap-2 rounded-xl border border-[#cfe6d8] bg-[#f4fbf6] p-3">
      <p className="text-xs font-semibold text-[#075e54]">
        WhatsApp real · {conversa.numero_mascarado} · código {conversa.codigo}
        {conversa.encerrada ? " · pediu para sair" : ""}
      </p>
      <p className="text-[11px] text-[#5d7a6b]">Canal e voz reais. O perfil do convite é fictício (dados de demonstração). A voz é gerada por IA.</p>
      {conversa.mensagens.map((mensagem) => (
        <div className="grid gap-1" key={mensagem.id}>
          <p className={mensagem.direcao === "entrada" ? balaoPessoa : balaoAgente}>
            <ComLinks texto={mensagem.texto} />
          </p>
          {mensagem.audio_id && <AudioDaResposta audioId={mensagem.audio_id} vagaId={vagaId} />}
          {!mensagem.enviada && <p className="text-xs text-[#a43826]">Não saiu pelo WhatsApp. Veja se o celular está pareado.</p>}
        </div>
      ))}
    </div>
  );
}

function Conversa({ convite, nome, vagaId, aoMudar, whatsapp }: {
  convite: ConviteDaVaga;
  nome: string;
  vagaId: string;
  aoMudar: () => void;
  whatsapp?: ConversaWhatsApp;
}) {
  const [texto, setTexto] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function responder(tipo: TipoResposta, conteudo = "") {
    setEnviando(true);
    setErro("");
    try {
      await responderConvite(convite.id, { vaga_id: vagaId, tipo, texto: conteudo });
      if (tipo === "duvida") setTexto("");
      aoMudar();
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível registrar a resposta."));
    } finally {
      setEnviando(false);
    }
  }

  const balaoAgente = "max-w-[85%] rounded-2xl rounded-tl-sm bg-[#eef4f2] px-4 py-2 text-sm text-[#0b3038]";
  const balaoPessoa = "ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-[#0b3038] px-4 py-2 text-sm text-white";
  return (
    <article className={`${cartao} grid gap-3`}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold text-[#113b43]">{nome}</h3>
        <span className="text-xs uppercase tracking-wide text-[#718784]">{convite.estado} · {convite.canal}</span>
      </div>
      <p className={balaoAgente}><ComLinks texto={convite.mensagem} /></p>
      {whatsapp && <ConversaNoWhatsApp conversa={whatsapp} vagaId={vagaId} />}
      {convite.duvidas.map((duvida, indice) => (
        <div className="grid gap-2" key={`${duvida.momento}-${indice}`}>
          <p className={balaoPessoa}>{duvida.pergunta}</p>
          {duvida.resposta ? (
            <p className={balaoAgente}>{duvida.resposta}</p>
          ) : (
            <p className="text-xs text-[#a46a00]">Sem resposta segura no material da vaga: a dúvida foi para uma pessoa do RH.</p>
          )}
        </div>
      ))}
      {convite.retorno && <p className={balaoAgente}>{convite.retorno.mensagem}</p>}
      {convite.estado === "aguardando" && (
        <div className="grid gap-2 border-t border-[#eef2ef] pt-3">
          <p className="text-xs text-[#81908d]">Você faz o papel da pessoa convidada.</p>
          <div className="flex gap-2">
            <input className={`${campo} flex-1`} onChange={(e) => setTexto(e.target.value)} placeholder="Escreva uma dúvida, como a pessoa…" value={texto} />
            <button className={botao} disabled={enviando || !texto.trim()} onClick={() => responder("duvida", texto)} type="button">Enviar dúvida</button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={botao} disabled={enviando} onClick={() => responder("aceite")} type="button">Tenho interesse</button>
            <button className={botao} disabled={enviando} onClick={() => responder("recusa")} type="button">Não tenho interesse</button>
            <button className={botao} disabled={enviando} onClick={() => responder("silencio")} type="button">Não respondeu</button>
            <button className={botao} disabled={enviando} onClick={() => responder("opt_out")} type="button">Não quero mais contato</button>
          </div>
        </div>
      )}
      {erro && <p className="text-sm text-[#a43826]" role="alert">{erro}</p>}
    </article>
  );
}

function BaixarDocumento({ vagaId, candidatoId }: { vagaId: string; candidatoId: string }) {
  const [erro, setErro] = useState("");

  async function baixar() {
    setErro("");
    try {
      const texto = await obterDocumentoDeEntrega(vagaId, candidatoId);
      const url = URL.createObjectURL(new Blob([texto], { type: "text/markdown;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `contexto-${candidatoId.replace(/[^\w.-]+/g, "_")}.md`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível gerar o documento."));
    }
  }

  return (
    <div className="mt-3">
      <button className={botao} onClick={baixar} type="button">Baixar documento (Markdown)</button>
      {erro && <p className="mt-1 text-sm text-[#a43826]" role="alert">{erro}</p>}
    </div>
  );
}

export function PainelVaga({ vagaId }: { vagaId: string }) {
  const [vaga, setVaga] = useState<Vaga | null>(null);
  const [resumo, setResumo] = useState<ResumoVaga | null>(null);
  const [itens, setItens] = useState<Item[]>([]);
  const [decisoes, setDecisoes] = useState<Record<string, Decisao>>({});
  const [convites, setConvites] = useState<ConviteDaVaga[]>([]);
  const [conversasZap, setConversasZap] = useState<ConversaWhatsApp[]>([]);
  const [pacotes, setPacotes] = useState<PacoteEntregue[]>([]);
  const [eventos, setEventos] = useState<EventoFluxo[]>([]);
  const [erro, setErro] = useState("");
  const [responsavel, setResponsavel] = useState("Ana do RH (fictícia)");
  const [avisando, setAvisando] = useState(false);
  const [sugestao, setSugestao] = useState<SugestaoAjuste | null>(null);
  const cacheDecisoes = useRef<Record<string, Decisao>>({});
  const ocupado = useRef(false);

  const atualizar = useCallback(async () => {
    if (ocupado.current) return;
    ocupado.current = true;
    try {
      const dadosVaga = await obterVaga(vagaId);
      setVaga(dadosVaga.vaga);
      if (dadosVaga.estado === "rascunho" || dadosVaga.estado === "aguardando_mandato") {
        setResumo(null);
        return;
      }
      const [novoResumo, candidatos, novosConvites, novosPacotes, novosEventos, novasConversas] = await Promise.all([
        obterResumo(vagaId),
        listarCandidatos(vagaId, 1, 100),
        listarConvitesDaVaga(vagaId),
        listarPacotesEntregues(vagaId),
        listarEventosRecentes(vagaId),
        listarConversasWhatsApp(vagaId),
      ]);
      const faltando = candidatos.itens.filter(
        (item) => item.decisao && cacheDecisoes.current[item.candidato.id]?.tipo !== item.decisao,
      );
      const lidas = await Promise.all(
        faltando.map((item) => obterDecisao(item.candidato.id, vagaId).then((r) => r.decisao).catch(() => null)),
      );
      for (const decisao of lidas) if (decisao) cacheDecisoes.current[decisao.candidato_id] = decisao;
      setResumo(novoResumo);
      setItens(candidatos.itens);
      setDecisoes({ ...cacheDecisoes.current });
      setConvites(novosConvites);
      setConversasZap(novasConversas);
      setPacotes(novosPacotes);
      setEventos(novosEventos);
      setErro("");
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível carregar a vaga."));
    } finally {
      ocupado.current = false;
    }
  }, [vagaId]);

  useEffect(() => {
    const primeira = window.setTimeout(() => void atualizar(), 0);
    const intervalo = window.setInterval(() => void atualizar(), 4000);
    return () => {
      window.clearTimeout(primeira);
      window.clearInterval(intervalo);
    };
  }, [atualizar]);

  async function avisarResultados() {
    setAvisando(true);
    try {
      await avisarResultadosDasEntrevistas(vagaId);
      await atualizar();
      setSugestao(await obterSugestaoDeAjuste(vagaId).catch(() => null));
    } catch (erroApi) {
      setErro(mensagemDeErro(erroApi, "Não foi possível buscar os resultados das entrevistas."));
    } finally {
      setAvisando(false);
    }
  }

  if (!vaga) {
    return erro ? <p className="rounded-xl border border-[#f0b5aa] bg-[#fff1ee] p-6 text-[#a43826]" role="alert">{erro}</p> : <p className="text-[#718784]">Carregando a vaga…</p>;
  }

  const nomes = Object.fromEntries(itens.map((item) => [item.candidato.id, item.candidato.nome]));
  const grupo = (tipo: string) => itens.filter((item) => item.decisao === tipo);
  const indicados = grupo("indicar");
  const fila = grupo("pedir_humano");
  const descartados = grupo("descartar");
  const contagemDescartes: Record<string, number> = {};
  for (const item of descartados) {
    const motivo = traduzir(decisoes[item.candidato.id]?.regra ?? "");
    contagemDescartes[motivo] = (contagemDescartes[motivo] ?? 0) + 1;
  }
  const semMandato = !resumo;
  const andamento = eventos.filter((evento) => evento.etapa !== "decisao").slice(-8).reverse();
  const comRetorno = convites.filter((convite) => convite.retorno);

  return (
    <div className="grid gap-10">
      <header className="grid gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-[-0.03em] text-[#0b3038]">{vaga.titulo}</h1>
          <span className="rounded-full bg-[#eef4f2] px-3 py-1 text-xs font-semibold text-[#2c4f55]">
            {ESTADOS[resumo?.estado ?? "aguardando_mandato"] ?? resumo?.estado}
            {resumo && ATIVOS.has(resumo.estado) ? "…" : ""}
          </span>
        </div>
        <p className="max-w-3xl text-sm text-[#526c68]">{vaga.descricao}</p>
        <div className="mt-2 grid gap-1 text-sm text-[#2c4f55] sm:grid-cols-2">
          <div><b>Eliminatório:</b> {vaga.requisitos.length ? vaga.requisitos.map((r) => r.descricao).join("; ") : "nenhum"}</div>
          <div><b>Pontua:</b> {vaga.competencias.map((c) => c.nome).join(", ")}</div>
        </div>
        {erro && <p className="text-sm text-[#a43826]" role="alert">{erro}</p>}
      </header>

      <Secao numero={1} titulo="Mandato">
        {semMandato ? (
          <FormMandato aoAssinar={() => void atualizar()} vaga={vaga} />
        ) : (
          <div className="grid gap-1 text-sm text-[#526c68]">
            <p>Mandato assinado. Gasto do agente até aqui: US$ {resumo.gasto_usd.toFixed(2)}{resumo.limite_gasto_usd ? ` de US$ ${resumo.limite_gasto_usd.toFixed(2)}` : ""}.</p>
            {resumo.analisados > 0 && (
              <p>
                Custo por pessoa analisada: US$ {(resumo.gasto_usd / resumo.analisados).toFixed(3)}
                {resumo.indicados > 0 ? ` · por indicado: US$ ${(resumo.gasto_usd / resumo.indicados).toFixed(3)}` : ""}
                {resumo.gasto_usd === 0 ? " (demonstração sem modelo: não há gasto)" : ""}
              </p>
            )}
          </div>
        )}
      </Secao>

      {resumo && (
        <>
          <Secao numero={2} titulo="Busca e triagem">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["encontrados", itens.length],
                ["analisados", resumo.analisados],
                ["indicados", resumo.indicados],
                ["para o RH", resumo.na_fila_humana],
              ].map(([rotulo, valor]) => (
                <div className={cartao} key={rotulo}>
                  <p className="text-3xl font-semibold text-[#0b3038]">{valor}</p>
                  <p className="text-xs uppercase tracking-wide text-[#718784]">{rotulo}</p>
                </div>
              ))}
            </div>
            {resumo.estado === "pausada" && (
              <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                A vaga pausou. Isso acontece quando o agente manda gente demais para o RH, passa do limite de gasto ou um serviço cai. Resolva a fila do RH abaixo.
              </p>
            )}
            {andamento.length > 0 && (
              <ul className="grid gap-1 text-sm text-[#526c68]">
                {andamento.map((evento, indice) => (
                  <li key={`${evento.momento}-${indice}`}>
                    <span className="mr-2 font-mono text-xs text-[#81908d]">{evento.momento.slice(11, 19)}</span>
                    {evento.candidato_id && nomes[evento.candidato_id] ? `${nomes[evento.candidato_id]}: ` : ""}
                    {evento.mensagem}
                  </li>
                ))}
              </ul>
            )}
          </Secao>

          <Secao numero={3} titulo="Indicados pelo agente, e por quê">
            {indicados.length ? (
              <div className="grid gap-3">
                {indicados.map((item) => (
                  <CartaoCandidato vagaId={vagaId} cor="#2f9e6e" decisao={decisoes[item.candidato.id]} item={item} key={item.candidato.id} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#81908d]">{ATIVOS.has(resumo.estado) ? "O agente ainda está analisando." : "Ninguém indicado."}</p>
            )}
          </Secao>

          <Secao numero={4} titulo="Para o RH decidir">
            <p className="text-sm text-[#526c68]">
              O agente não decide sozinho quando falta dado, quando o perfil é suspeito ou quando a pessoa ficou fora dos limites do mandato. Você decide como
              <input aria-label="Pessoa do RH" className={`${campo} mx-2`} onChange={(e) => setResponsavel(e.target.value)} value={responsavel} />
              — indicar leva ao convite; descartar encerra.
            </p>
            {fila.length ? (
              <div className="grid gap-3">
                {fila.map((item) => (
                  <CartaoCandidato vagaId={vagaId} cor="#e0a100" decisao={decisoes[item.candidato.id]} item={item} key={item.candidato.id}>
                    <RevisaoRh aoMudar={() => void atualizar()} item={item} responsavel={responsavel} vagaId={vagaId} />
                  </CartaoCandidato>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#81908d]">Nada para o RH agora.</p>
            )}
            {descartados.length > 0 && (
              <details className="text-sm text-[#526c68]">
                <summary className="cursor-pointer">Descartados pelas regras ({descartados.length})</summary>
                <ul className="mt-2 grid gap-1">
                  {Object.entries(contagemDescartes).map(([motivo, quantidade]) => (
                    <li key={motivo}>{quantidade} × {motivo || "sem motivo registrado"}</li>
                  ))}
                </ul>
              </details>
            )}
          </Secao>

          <Secao numero={5} simulado titulo="Contato com as pessoas">
            {convites.length ? (
              <div className="grid gap-3">
                {convites.map((convite) => (
                  <Conversa aoMudar={() => void atualizar()} convite={convite} key={convite.id} nome={nomes[convite.candidato_id] ?? convite.candidato_id} vagaId={vagaId} whatsapp={conversasZap.find((c) => c.candidato_id === convite.candidato_id)} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#81908d]">Nenhum convite ainda.</p>
            )}
          </Secao>

          <Secao numero={6} simulado titulo="Contexto entregue à Nara">
            <p className="text-sm text-[#526c68]">Quem aceita vai para a Nara com o porquê da indicação. A Nara agenda e entrevista; o agente não agenda.</p>
            {pacotes.length ? (
              <div className="grid gap-3">
                {pacotes.map((pacote) => (
                  <article className={cartao} key={pacote.candidato_id}>
                    <h3 className="font-semibold text-[#113b43]">{nomes[pacote.candidato_id] ?? pacote.candidato_id}</h3>
                    <ul className="mt-2 grid gap-1 text-sm text-[#2c4f55]">
                      {Object.entries(pacote.motivo_por_criterio).map(([criterio, motivo]) => (
                        <li key={criterio}><b>{criterio}:</b> “{motivo}”</li>
                      ))}
                    </ul>
                    {pacote.pontos_a_aprofundar.length > 0 && <p className="mt-2 text-sm text-[#526c68]">Para a Nara aprofundar: {pacote.pontos_a_aprofundar.join("; ")}</p>}
                    {pacote.lacunas.length > 0 && <p className="mt-1 text-sm text-[#81908d]">Lacunas: {pacote.lacunas.join("; ")}</p>}
                    <BaixarDocumento candidatoId={pacote.candidato_id} vagaId={vagaId} />
                  </article>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#81908d]">Ninguém aceitou ainda. Responda “Tenho interesse” num convite acima.</p>
            )}
          </Secao>

          <Secao numero={7} simulado titulo="Depois da entrevista">
            <p className="text-sm text-[#526c68]">A Nara entrevista e decide. O agente só avisa cada pessoa do resultado, uma vez, sem mostrar nota.</p>
            <div><button className={botaoPrincipal} disabled={avisando || !pacotes.length} onClick={avisarResultados} type="button">{avisando ? "Avisando…" : "A Nara terminou as entrevistas: avisar as pessoas"}</button></div>
            {comRetorno.length > 0 && (
              <ul className="grid gap-2 text-sm">
                {comRetorno.map((convite) => (
                  <li className={cartao} key={convite.id}>
                    <b>{nomes[convite.candidato_id] ?? convite.candidato_id}</b> · Nara: {convite.retorno?.aprovado ? "seguir" : "não seguir"} · {convite.retorno?.enviado ? "mensagem enviada" : "mensagem não saiu, tente de novo"}
                  </li>
                ))}
              </ul>
            )}
            {sugestao && (
              <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                <p className="font-semibold">Sugestão para a próxima vaga (o agente não muda nada sozinho)</p>
                <p className="mt-1">{sugestao.motivo}.</p>
                <p className="mt-1">Peso de “{sugestao.criterio}”: de {sugestao.peso_atual} para {sugestao.peso_sugerido}. Quem decide ajustar é o RH.</p>
              </div>
            )}
          </Secao>
        </>
      )}
    </div>
  );
}
