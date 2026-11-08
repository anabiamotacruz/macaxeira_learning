# Status da entrega

Atualizado em 8/11/2026, por volta das 5h40, horário de Fortaleza. A `main` está em `c51ac27` (merge da #122).

Os testes rodaram localmente, no Windows, com o `uv.lock`. Lá aparece **1 falha que só acontece no Windows**: `tests/fontes/test_anonimizador.py::test_cofre_e_arquivo_proprio_e_so_abre_com_a_empresa_certa` confere `st_mode & 0o077`, e o Windows não tem permissão POSIX. No CI, que roda em Linux, ela deve passar.

## Validação

| Árvore | ruff | pytest | web (`pnpm build` + `lint`) |
| --- | --- | --- | --- |
| `main` (`c51ac27`) | ok | 3781 ok, 1 falha só no Windows | não roda sem `web/lib` (vem com a #107) |
| `main` + #103 + #92 + #106 + #107 + correção da #102 | ok | 3802 ok, 1 falha só no Windows | build ok, lint ok (5 avisos de `<img>`) |

As cinco entram juntas, sem conflito.

## Já está na `main`

Pipeline e demonstração: mandato, busca, decisão, convite, dúvida, aceite, opt-out e entrega. Também:

| Item | PR |
| --- | --- |
| Rotina do banco | #108 |
| Avaliação pela pessoa de RH | #109 |
| Aprendizado | #110 |
| Segurança da API | #111 |
| Ponta a ponta | #112 |
| Documento de ingestão | #113 |
| Proposta de vaga a partir da descrição | #118 a #120 |
| Sugestão de ajuste | #117 |
| Roteiros da demo | #116, #121, #122 |

## Pronto para entrar (validado acima)

| PR ou branch | O que é | Dono |
| --- | --- | --- |
| #107 | Painel inteiro ligado à API. Inclui a #96 e corrige `web/lib`. **Sem ela, o web da `main` não compila.** | Sofia e João |
| #103 | Voz simulada e validação de e-mail e link no WhatsApp | João |
| #102 + `frente/agente/campanha-assercao` | Teste da campanha. A branch corrige a asserção que nunca falhava; conferido com mutação. | João |
| #92 | Auditoria de injeção no recontato | Bruno |
| #106 | Aviso de simulação do contato numa constante só | Bruno |

## Branches novas (sem PR aberta)

Ordem para mesclar: cada uma parte da anterior.

| Ordem | Branch | O que faz | Testes |
| --- | --- | --- | --- |
| 1 | `frente/agente/campanha-assercao` | Corrige o teste da #102 (`ENCAMINHAR_APERTADO = 1`). | 4 ok, conferido com mutação |
| 2 | `frente/agente/feedback-quem-passou` | Feedback a pedido para quem passou: critérios sustentados, com trecho, sem nota. Com `ResultadoEntrevista`, diz se a pessoa segue. | 155 ok |
| 3 | `frente/agente/link-apos-aceite` | O convite sai sem link. No aceite, o agente pede o link à Nara, guarda no convite (`link_destino`) e manda numa segunda mensagem. | suíte completa ok |
| 4 | `frente/agente/talent-garden` (sobre a 3) | "Agora não" e quem passou do número de encaminhamento viram sugestão de Talent Garden. O RH confirma por `/candidatos/{id}/destino`. Rota nova: `GET /vagas/{id}/talent-garden`. | suíte completa ok |
| 5 | `frente/agente/garden-campanha` (sobre a 4) | Numa campanha nova, `GET /vagas/{id}/talent-garden/sugestoes` mostra o Talent Garden das outras vagas da empresa. `POST /vagas/{id}/talent-garden/convites` manda o convite especial pelo canal do primeiro contato, com o RH como responsável. | suíte completa ok |
| 6 | `frente/agente/painel-garden` (sobre a #107 e a 5) | Seção 8 do painel com o Talent Garden e o convite especial, o botão "agora não" na conversa e o link depois do aceite. | build, lint e `tsc` ok; testado no navegador |
| 7 | `frente/agente/interpretar-conversa` (sobre a 5) | A mensagem livre da pessoa é interpretada em seguir, não seguir ou agora não, também depois do aceite. Regras primeiro; o que sobra vai a um classificador da Featherless (Simple Jev, `featherless-ai/Qwen3.5-4B-classifier`), ao Jev da TypeSafe ou a uma LLM. Comparador em `evals/comparar_modelos_interpretacao.py`. | suíte ok; só regras: 30/41, zero erros perigosos; rodada com modelo pendente da chave |
| 8 | `frente/agente/feedback-api` (sobre a 7 e a 2) | `POST /candidatos/{id}/feedback`: a pessoa pergunta por quê e recebe os critérios, sem nota. Contestação vai para uma pessoa. | suíte ok |
| 9 | `frente/agente/convite-whatsapp` (sobre a 8) | O convite da demo é o e-mail inicial da Frente 3: `wa.me` com o código da vaga, origem do contato e link de exclusão, tudo sintético. | suíte ok (3888) |
| — | `frente/produto/t4-3-deploy` | Dockerfile, `render.yaml`, `docs/deploy.md` e este quadro. | — |

A branch local `frente/agente/seguranca-fontes` ficou parada: deu 33 falhas e não é prioridade do MVP. Ela não foi enviada.

## Falta

| # | Item | Tamanho | Observação |
| --- | --- | --- | --- |
| 1 | Abrir PRs das branches acima e mesclar #107, #103, #102, #92 e #106 | P | Precisa do João, porque não há `gh` nesta máquina |
| 2 | Deploy: criar conta e serviço no Render ou Railway e na Vercel | P | Passo a passo em `docs/deploy.md` |
| 3 | Link de agendamento só depois do aceite | — | Feito na branch 3 |
| 4 | Ligar o feedback a uma rota | — | Feito na branch 8; falta o botão no painel |
| 5 | E-mail com `wa.me` na demo da API | — | Feito na branch 9 |
| 6 | #68 | P | `test_avaliacao_v3_eval.py` chama `priorizar()` sem os argumentos novos. Quebra com `-m eval`. |
| 7 | #95, #69, #77 | P | Fora do caminho crítico |
| 8 | #67 | — | A T3.5 saiu do escopo. Fechar. |
| 9 | `frente/agente-consolidado` | — | Substituída pela `main` (10 conflitos). Descartar. |

## Talent Garden: como funciona na demo

1. Na conversa, a pessoa responde "Agora não, mais para frente". O agente responde com SAIR e sugere o Talent Garden.
2. Na seção 8, o RH clica em "Guardar no Talent Garden". O destino é sempre do RH.
3. Numa vaga nova da mesma empresa, a seção 8 lista o Talent Garden das outras vagas. O RH marca as pessoas e clica em "Mandar convite especial".
4. A pessoa aceita e recebe o link de agendamento da Nara.

Limite conhecido: quem entra pelo convite especial recebe o link de agendamento, mas não gera o pacote de contexto para a Nara, porque não passou pela análise desta vaga.
