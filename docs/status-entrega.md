# Status da entrega

Atualizado em 8/11/2026, por volta das 4h10, horário de Fortaleza. A `main` está em `c51ac27` (merge da #122).

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

## Branches novas deste turno (sem PR aberta)

| Branch | O que faz | Testes |
| --- | --- | --- |
| `frente/agente/campanha-assercao` | Corrige o teste da #102 (`ENCAMINHAR_APERTADO = 1`) | 4 ok; a mutação "excesso vira descarte" faz o teste falhar |
| `frente/agente/feedback-quem-passou` | Feedback a pedido para quem passou: critérios sustentados, com trecho, sem nota. Com `ResultadoEntrevista`, diz se segue ou não. Não muda contrato. | `test_feedback`, `test_jornada_pre_triagem` e `test_decisao_final`: 155 ok |
| `frente/agente/seguranca-fontes` | Traz para cima da `main` as 9 correções de `frente/agente-sistema-fontes`, que nunca tiveram PR: pseudonimizador obrigatório, filtro de instrução, site e PDF endurecidos, pares de viés, credencial do MCP em cabeçalho. O conflito em `conector_mcp.py` foi resolvido mantendo `DestinoPorEmpresa`. | conector MCP, destino por empresa e Nara: 106 ok; suíte completa em andamento |
| `frente/produto/t4-3-deploy` | Dockerfile, `render.yaml` e `docs/deploy.md` | sem Docker aqui; o `render.yaml` foi conferido |

## Falta

| # | Item | Tamanho | Observação |
| --- | --- | --- | --- |
| 1 | Abrir PRs das branches acima e mesclar #107, #103, #102, #92 e #106 | P | Precisa do João, porque não há `gh` nesta máquina |
| 2 | Deploy: criar conta e serviço no Render ou Railway e na Vercel | P | Passo a passo em `docs/deploy.md` |
| 3 | Link de agendamento só depois do aceite (proposta abaixo) | M | Decisão de produto, com o Bruno |
| 4 | Ligar o feedback a uma rota ou ao WhatsApp | G | Hoje existe como função e testes |
| 5 | "Não agora", Talent Garden e o e-mail com `wa.me` na demo da API | G | Hoje rodam só como cenário de teste da Frente 3 |
| 6 | #68 | P | `test_avaliacao_v3_eval.py` chama `priorizar()` sem os argumentos novos. Quebra com `-m eval`. |
| 7 | #95, #69, #77 | P | Fora do caminho crítico |
| 8 | #67 | — | A T3.5 saiu do escopo. Fechar. |
| 9 | `frente/agente-consolidado` | — | Substituída pela `main` (10 conflitos). Descartar. |

## Proposta: link de agendamento só depois do aceite

Hoje `fluxo.py:1921` pede o link ao destino quando cria o convite, e o link vai na primeira mensagem (`fluxo.py:1936`). O escopo (etapa 5) diz que o link só sai quando três condições fecham: aceite, momento e cobertura do que a vaga pede.

Mudança mínima, sem contrato novo:

1. Em `_criar_convite`, gravar `link=None` e não chamar `_link_de_agendamento`.
2. Em `registrar_resposta`, quando a pessoa aceitar e a decisão for `indicar`, pedir o link ao destino e enviar uma segunda mensagem com ele.
3. Ajustar os testes da demo que esperam o link no primeiro convite.

Não foi aplicada porque muda a demonstração ao vivo e o texto do convite da Frente 3. Precisa do João e do Bruno.
