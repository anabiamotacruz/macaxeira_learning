---
description: "Tarefas da feature de coleta e pseudonimização"
---

# Tarefas: coleta e pseudonimização

**Entrada**: `spec.md` e `plan.md` em `specs/004-coleta-e-pseudonimizacao/`

**Pré-requisitos**: base de código em `frente/agente-integracao` (`536b94e`). Nenhuma tarefa altera a feature 001.

**Testes**: o projeto exige teste antes do código. Cada tarefa aberta começa por um teste que falha. Os casos `O1`, `L1` e semelhantes vêm do apêndice da revisão independente, trazidos ao repositório em T001.

## Formato: `[Id] [P?] [História] [Frente] Descrição`

- **[X]**: existe na base lida **e** tem teste, que passou em 7/11/2026. Quando só parte de um requisito existe, a tarefa marcada descreve só essa parte.
- **[P]**: pode rodar em paralelo: arquivos diferentes, sem dependência.
- **[US1] a [US7]**: história da spec.
- **[F1] a [F4]**: frente responsável, conforme a pasta em `AGENTS.md`.
- **[CONTRATO]**: muda `backend/contratos` ou uma rota da API. Exige T002 antes.
- **[TIME]**: decisão ou trabalho de pessoas do time, **sem dono automático**. Não entra em `/speckit-implement` nem é feito por agente.

## Fase 1: preparação

**Objetivo**: transformar os achados em testes executáveis e avisar as frentes.

- [ ] T001 [F2] Trazer os casos do apêndice da revisão ligados a esta feature para `tests/fontes/test_revisao_coleta.py` e `tests/agente/test_revisao_coleta.py`, com `xfail(strict=True)` e o id do achado. Cada correção retira o `xfail` do próprio caso. Usar só dados sintéticos. A F1 cuida do arquivo em `tests/agente`.
- [ ] T002 [TIME] Avisar as quatro frentes das mudanças de contrato previstas em `plan.md` (T035, T037, T043, T045 e T054), antes de começar qualquer uma delas.

**Ponto de controle**: os casos rodam no CI como falha esperada.

---

## Fase 2: base (já existe)

**Objetivo**: o contrato de perfil, do qual as demais histórias dependem.

- [X] T003 [F1] Contrato `PerfilColetado`, `FatoColetado` e `ContatoColetado`, com esquema versionado e exemplo sintético, em `backend/contratos/modelos.py`, `backend/contratos/gerar_esquema_perfil.py` e `docs/contratos/`. Teste: `tests/contratos/test_perfil_coletado.py`.
- [X] T004 [F2] Conversão de perfil em `Candidato`, sem fato inferido nem contato não publicado, em `backend/fontes/perfis.py`. Teste: `tests/fontes/test_registro_fontes.py`.

**Ponto de controle**: concluído.

---

## Fase 3: História 1, escolher as fontes pela configuração (P1)

**Objetivo**: fontes, provedores e modo sintético controlados pela configuração, ligados ao sistema que roda.

**Teste independente**: montar a fonte com transporte falso e variar o ambiente.

### Já existe

- [X] T005 [P] [US1] [F2] Lista configurável de fontes em `backend/fontes/registro.py`. Teste: `tests/fontes/test_registro_fontes.py`.
- [X] T006 [P] [US1] [F2] Política de URL com bloqueio de domínios, encurtadores e endereços internos, em `backend/fontes/provedores/url_segura.py`. Teste: `tests/fontes/provedores/test_url_segura.py`.
- [X] T007 [P] [US1] [F2] Transporte com lista de hosts, teto de resposta e tempo total, em `backend/fontes/provedores/transporte.py`. Teste: `tests/fontes/provedores/test_transporte.py`.
- [X] T008 [P] [US1] [F2] Provedor Bright Data, com leitura pela zona de Web Unlocker e busca pela SERP API só quando habilitada de propósito, sem cookies nem opções de desbloqueio, em `backend/fontes/provedores/bright_data.py`. Teste: `tests/fontes/provedores/test_bright_data.py`.
- [X] T009 [P] [US1] [F2] Provedor People Data Labs, só com Person Enrichment, em `backend/fontes/provedores/people_data_labs.py`. Teste: `tests/fontes/provedores/test_people_data_labs.py`.
- [X] T010 [US1] [F2] Cadeia com ordem, troca registrada, repetição, disjuntor, orçamento, cache e supressão, em `backend/fontes/provedores/cadeia.py` e `controles.py`. Testes: `test_cadeia.py` e `test_controles.py`, em `tests/fontes/provedores/`.
- [X] T011 [US1] [F2] Ativação por chave, Brave primeiro, `MODO_DADOS` e recusa de valor inválido, em `backend/fontes/provedores/configuracao.py`. Teste: `tests/fontes/provedores/test_configuracao.py`.
- [X] T012 [US1] [F2] `FonteProvedores` com estado visível, modo sintético e guarda como pendente, em `backend/fontes/provedores/fonte.py`. Testes: `test_fonte.py` e `test_integracao_fluxo.py`, em `tests/fontes/provedores/`.
- [X] T073 [P] [US1] [F2] Provedor Brave Search, só para consultas de texto, com país BR, idioma `pt-br` e `offset` limitado, em `backend/fontes/provedores/brave.py`. Teste: `tests/fontes/provedores/test_brave.py`. Responde a Q2.

### Falta

- [ ] T013 [P] [US1] [F2] Testar que `TransporteHttp` e `LeitorSitePublico` ignoram proxy do ambiente (FR-E004), em `tests/fontes/provedores/test_transporte.py` e `tests/fontes/test_site_publico.py`. O código já usa `trust_env=False`; falta o teste.
- [ ] T014 [US1] [F1] Criar `montar_real` em `backend/agente/montagem.py`, escolhida pela configuração, com o catálogo de fontes de `registro.py`, `montar_fonte_externa`, `ClienteFeatherless`, `AnalisadorPorModelo`, `RevisorIndependente`, um único `Pseudonimizador`, cofre em arquivo e `reidentificador_do_cofre`. Recusar a subida se faltar uma peça. Teste: `tests/agente/test_montagem_real.py`, caso `O5`. Achado C-1. **Depende de T026 e T027.**
- [ ] T015 [US1] [F1] Fixar por teste que `montar_demo` é sempre sintética, com chaves no ambiente e com `MODO_DADOS` em branco (FR-E009), em `tests/agente/test_montagem_real.py`.
- [ ] T016 [US1] [F1] Expor o estado das fontes na API, em `backend/agente/api.py`, sem chave nem dado de pessoa (FR-E006).
- [ ] T017 [P] [US1] [F4] Mostrar na interface o estado das fontes e a etiqueta de simulação, em `web/` (FR-E006). **Depende de T016.**
- [ ] T018 [P] [US1] [F2] Ler o token do GitHub de variável de ambiente e usar cache por execução, em `backend/fontes/github_teste.py` e `backend/fontes/site_publico.py`. Achado B-4.
- [ ] T019 [P] [US1] [F2] Declarar `httpx2` em `pyproject.toml` e descrever `tesseract`, `MODO_DADOS` e a configuração só de busca nas instruções. Achado B-5, parte desta feature.

**Ponto de controle**: a API sobe em modo demo ou real pela configuração, e o caso `O5` passa.

---

## Fase 4: História 2, pseudonimizar antes do modelo e dos rastros (P1)

**Objetivo**: nenhum identificador conhecido chega ao modelo ou aos rastros.

**Teste independente**: modelo falso que guarda os prompts e captura de rastros.

### Já existe

Todos em `backend/fontes/anonimizador.py`, com teste em `tests/fontes/test_anonimizador.py`.

- [X] T020 [US2] [F2] `Pseudonimizador`, `PoliticaGeneralizacao` e relatório com custos, sem valores.
- [X] T021 [US2] [F2] `CofrePseudonimos` em arquivo próprio, por empresa e pessoa, sem listagem, com permissão restrita.
- [X] T022 [US2] [F2] `PerfilPseudonimizado`: confere o trecho citado e o leva até a fonte.
- [X] T023 [US2] [F2] `reidentificar_pacote`: só depois da decisão de indicar da mesma execução, com registro antes de revelar.
- [X] T024 [US2] [F2] Prompts e rastros sem dados identificáveis, e texto enviado igual ao trocar nome e gênero (`test_nada_identificavel_vai_ao_modelo_nem_aos_rastros`, `test_trocar_nome_e_genero_nao_muda_o_texto_enviado`).

### Falta

- [ ] T025 [US2] [F2] Fechar os casos `L1` (18) e `L2`, em `backend/fontes/anonimizador.py`: URL por forma genérica, valores conhecidos da pessoa sempre retirados, nome em qualquer sequência, caracteres de formato e homóglifos. Achado A-1. Registrar que detecção por regra reduz o risco, sem eliminá-lo.
- [ ] T026 [US2] [F2] Tornar o pseudonimizador obrigatório em `AnalisadorPorModelo`, `RevisorIndependente` e `perfil_de_documento`. Caso `Q3`. Achado M-2.
- [ ] T027 [US2] [F2] Cofre persistente e criptografado em repouso, com caminho por variável de ambiente, em `backend/fontes/anonimizador.py` (FR-E026). Recusar dado real sem criptografia. O arquivo não entra no repositório.
- [ ] T028 [P] [US2] [F1] Retirar `origem` identificável da decisão e limpá-la com os demais campos, em `backend/agente/regras.py` e `backend/agente/fluxo.py`. Caso `L3`. Achado A-6.
- [ ] T029 [P] [US2] [F1] Resposta própria da ferramenta MCP, sem nome nem contato, em `backend/agente/mcp.py`. Caso `L4`. Achado A-7.
- [ ] T030 [P] [US2] [F4] Conjunto sintético com pelo menos 50 currículos e medição de vazamento por categoria, com meta declarada, na pasta de avaliações (SC-E003). A pasta depende de T070.
- [ ] T031 [P] [US2] [F2] Filtrar marcador forjado depois de normalizar o texto, em `backend/fontes/anonimizador.py` e `backend/agente/prompts.py`. Caso `L5`. Achado B-3. `backend/agente/prompts.py` é da F1.

**Ponto de controle**: `L1`, `L2`, `L3`, `L4`, `L5` e `Q3` passam, e a medição foi publicada.

---

## Fase 5: História 3, perfil estruturado com prova em cada fato (P1)

**Objetivo**: toda fonte gera o mesmo JSON, e a prova chega à decisão.

**Teste independente**: um perfil por tipo de fonte, validado e seguido até a decisão.

### Já existe

- [X] T032 [P] [US3] [F2] `perfil_coletado` do GitHub, com repositório comprovado e bio declarada, em `backend/fontes/github_teste.py`. Teste: `tests/fontes/test_github_teste.py`.
- [X] T033 [P] [US3] [F2] `perfil_coletado` do site indicado, com fatos declarados, em `backend/fontes/site_publico.py`. Teste: `tests/fontes/test_site_publico.py`.
- [X] T034 [P] [US3] [F2] `perfil_de_documento`, com fatos declarados e alerta, em `backend/fontes/documentos.py`. Teste: `tests/fontes/test_documentos.py`.

### Falta

- [ ] T035 [US3] [F2] [CONTRATO] Gravar `PerfilColetado` por empresa e pessoa e ligar a evidência ao fato, para que decisão e pacote mostrem origem e data (FR-E020). A F1 cuida da leitura em `backend/agente`. **Depende de T002.**
- [ ] T036 [US3] [F2] Converter `ItemColetado` em `PerfilColetado`, sem nenhum fato comprovado, em `backend/fontes/provedores/fonte.py` (FR-E019). Teste em `tests/fontes/provedores/test_fonte.py`.
- [ ] T037 [US3] [F2] [CONTRATO] Levar alertas em campo próprio de `Candidato` e retirar a pessoa da faixa verde. Casos `M6` e `M7`. Achado A-2. A F1 cuida de `classificar_faixa` em `backend/agente/regras.py`. **Depende de T002.**
- [ ] T038 [US3] [F2] Gerar alerta para toda instrução apontada pelo modelo, ampliar o filtro e normalizar invisíveis antes dele, em `backend/fontes/analisador.py`. Casos `M4` e `M5`. Achado A-3.
- [ ] T039 [US3] [F2] Extrair por código os atributos comprovados de cada fonte, com origem, em `backend/fontes/perfis.py` e `github_teste.py`. Caso `O3`. Achado C-3. A definição de quais requisitos aceitam fato declarado é da F1, em `backend/agente/regras.py`.
- [ ] T040 [P] [US3] [F2] Impedir que contato de provedor vire canal e que e-mail de terceiro vire contato, em `backend/fontes/provedores/fonte.py` e `backend/fontes/site_publico.py` (FR-E013). Caso `X1`. Achado M-5. Avisar a F3.
- [ ] T041 [P] [US3] [F2] Não guardar telefone como canal e descartar CPF, RG, endereço, nascimento e foto na ingestão, em `site_publico.py`, `documentos.py` e `perfis.py` (FR-E014, FR-E016).

**Ponto de controle**: `O3`, `M4`, `M5`, `M6`, `M7` e `X1` passam, e os fatos das quatro fontes seguem o mesmo esquema.

---

## Fase 6: História 4, reconhecer a mesma pessoa entre fontes (P2)

**Objetivo**: uma pessoa, várias fontes, sem juntar homônimos. Hoje o funil só junta registros com o mesmo `id`.

**Teste independente**: conjunto sintético de pares, sem modelo.

- [ ] T042 [US4] [F2] Escrever `tests/fontes/test_identidade.py` e o conjunto sintético de pares com prova, homônimos e sugestões (SC-E006). Os testes devem falhar antes de T043.
- [ ] T043 [US4] [F2] [CONTRATO] Criar `backend/fontes/identidade.py`: junção por URL normalizada, e-mail publicado e usuário; nome e cidade só geram sugestão; regra e fontes registradas; por empresa (FR-E033, FR-E034, FR-E036). **Depende de T002 e T036.**
- [ ] T044 [US4] [F1] Rodar a identidade antes do funil, em `backend/agente/fluxo.py`, e levar a sugestão a uma pessoa. Fazer bloqueio e opt-out valerem para todos os apelidos, com a F2 em `backend/fontes/funil.py` (FR-E035).

**Ponto de controle**: 100% dos pares com prova juntados e 0 homônimo sem prova juntado.

---

## Fase 7: História 5, a pessoa coletada chega à análise (P1)

**Objetivo**: o modo real produz análises. **Bloqueada por Q1 (T063).** Até lá, o corte `sem_autorizacao` continua.

**Teste independente**: fluxo pela montagem real, com peças falsas nas pontas.

- [ ] T045 [US5] [F1] [CONTRATO] Registrar a base legal por pessoa e empresa e adaptar o funil, conforme Q1 (FR-E037, FR-E038). **Depende de T002 e T063.**
- [ ] T046 [US5] [F2] Registrar consentimento e indicação por pessoa e empresa, com validade, em `ConfiguracaoGitHub` e `IndicacaoSite`. Casos `O1`, `O2` e `X2`. Achados C-2, M-6 e B-6 (FR-E015). **Depende de T063 para o caso sem consentimento.**
- [ ] T047 [P] [US5] [F2] Usar a mesma comparação do banco nas fontes e procurar também em bio e tópicos, sem contar esses textos como comprovados, em `backend/fontes/perfis.py`. Casos `Q1` e `Q2`. Achado M-4 (FR-E031).
- [ ] T048 [US5] [F1] Teste de ponta a ponta em `tests/agente/test_coleta_ponta_a_ponta.py`: cada fonte habilitada, montagem real, transporte e modelo falsos, dados sintéticos (SC-E007). **Depende de T014, T036, T039 e T046.**

**Ponto de controle**: `O1`, `O2`, `O3`, `O5`, `Q1`, `Q2` e `X2` passam.

---

## Fase 8: História 6, remover a pessoa de todos os lugares (P2)

**Objetivo**: exclusão completa, inclusive no cofre e nas cópias.

**Teste independente**: procurar os valores em todo o armazenamento depois de remover.

### Já existe

- [X] T049 [US6] [F2] Remoção apaga o perfil e a entrada do cofre, e grava bloqueio com resumos irreversíveis, em `backend/fontes/banco_talentos.py`. Testes: `tests/fontes/test_banco_talentos.py` e `test_remover_do_banco_apaga_a_entrada_do_cofre`.
- [X] T050 [US6] [F2] Supressão antes da consulta e ao receber, na cadeia de provedores, em `backend/fontes/provedores/cadeia.py`. Testes: `test_supressao_antes_de_consultar_nao_chama_nem_gasta` e `test_supressao_ao_receber_retira_a_pessoa_e_conta_sem_identificar`.

### Falta

- [ ] T051 [US6] [F1] Criar a operação única que apaga banco, cofre, progressos, análises e trechos citados e grava o bloqueio, venha a pessoa de onde vier, em `backend/agente/fluxo.py` e `backend/agente/persistencia.py`. Casos `V1` e `V3`. Achado A-5. A F2 cuida de `banco_talentos.py`.
- [ ] T052 [US6] [F2] Fazer `marcador` recusar pessoa removida, em `backend/fontes/anonimizador.py`. Caso `V2`.
- [ ] T053 [US6] [F1] Fazer `apagar_empresa` incluir o cofre, em `backend/agente/persistencia.py`.
- [ ] T054 [US6] [F1] [CONTRATO] Criar a rota de remoção da pessoa, em `backend/agente/api.py`. Caso `V4`. **Depende de T002 e T051.** Autenticação segue no achado C-6, fora desta feature.
- [ ] T055 [P] [US6] [F2] Conferir a supressão antes da coleta nas fontes de GitHub, site e documento (FR-E041).
- [ ] T056 [US6] [F2] Expirar perfis no prazo de retenção, com `hoje` recebido como parâmetro, em `backend/fontes/banco_talentos.py` (FR-E050). Valor inicial de 90 dias, até o parecer.

**Ponto de controle**: `V1` a `V4` passam, e 0 ocorrência é encontrada depois da remoção.

---

## Fase 9: História 7, conteúdo hostil (P3)

**Objetivo**: uma página ou arquivo não para a busca nem vira fato.

**Teste independente**: páginas e PDFs sintéticos, um por caso.

### Já existe

- [X] T057 [P] [US7] [F2] Leitor de site com SSRF, DNS fixado, `robots.txt`, encerramento em login ou CAPTCHA e bloqueio do LinkedIn, em `backend/fontes/site_publico.py`. Teste: `tests/fontes/test_site_publico.py`.
- [X] T058 [P] [US7] [F2] Leitura de documento com assinatura de conteúdo, limite de tamanho, páginas, pixels e caracteres, e OCR com tempo limite, em `backend/fontes/documentos.py`. Teste: `tests/fontes/test_documentos.py`.

### Falta

- [ ] T059 [P] [US7] [F2] Texto escondido em HTML e PDF não vira fato e gera alerta. Casos `H1` (7) e `H2`. Achado A-4.
- [ ] T060 [US7] [F2] Isolar cada indicação e pular contato vazio, em `backend/fontes/site_publico.py`. Casos `H6` e `H7`. Na F1, tratar erro inesperado de fonte como fonte indisponível, em `backend/agente/fluxo.py`, caso `H8`. Achado A-10.
- [ ] T061 [P] [US7] [F2] Comparar por posições, sem regex com curinga, e limitar o texto em todas as fontes. Casos `H4` e `H5`. Achado A-9. `backend/agente/neutralizacao.py` é da F1.
- [ ] T062 [P] [US7] [F2] Rodar a leitura de PDF em processo separado, com limite de tempo e memória (achado M-1), e recusar os blocos IPv6 e definir prazo total por página, em `site_publico.py` (achado M-9, caso `H9`). `url_segura.py` já recusa `64:ff9b::/96`.

**Ponto de controle**: `H1`, `H2` e `H4` a `H9` passam.

---

## Fase 10: responsabilidade do time, sem dono automático

**Objetivo**: o que depende de decisão, contrato comercial ou parecer. Estas tarefas não entram em `/speckit-implement` e não são feitas por agente. **Nenhuma delas pede para burlar login, CAPTCHA ou bloqueio.**

- [ ] T063 [TIME] Responder Q1: como o legítimo interesse convive com o corte `sem_autorizacao` e com a constituição. Bloqueia T045 e parte de T046.
- [X] T064 [TIME] Responder Q2: a busca passa a usar a Brave Search API, por decisão do responsável pelo produto (código em T073). Falta só registrar a decisão na arquitetura, que está em `origin/main`.
- [ ] T074 [TIME] Responder Q4: contratar por escrito o direito de armazenar resultados da Brave, ou reduzir o que é guardado, antes de usar dados reais.
- [ ] T065 [TIME] **Dados do LinkedIn por provedor contratado.** Definir dono, forma da entrega (dataset ou API), termos e plano. A coleta é do provedor; a integração é implementação do time, revisada por pessoas, inclusive a relação com os bloqueios atuais em `url_segura.py`, `bright_data.py` e `people_data_labs.py`. O código atual, escrito pelo agente, não faz essa coleta. Responde a Q3.
- [ ] T066 [TIME] Obter o parecer jurídico sobre a base legal, o uso de pseudonimização, a camada 6 e o prazo de retenção, e escrever o teste de balanceamento (LIA) e, se pedido, o relatório de impacto (RIPD).
- [ ] T067 [TIME] Acertar entre as quatro frentes a emenda ao princípio VII da constituição e aos textos ligados a ela. Há um rascunho local 2.0.0, não commitado, que precisa de revisão antes de valer.
- [ ] T068 [TIME] Contratar e configurar os provedores: chaves fora do repositório e orçamentos. Antes de ligar `BRIGHTDATA_ZONA_WEB`, decidir o uso do Web Unlocker, que contorna bloqueios, e a configuração da zona no painel. Começar pela busca, com `BRAVE_API_KEY`.
- [ ] T069 [TIME] Conduzir a validação com fontes reais pelo protocolo da arquitetura, seção 13, com pessoa responsável, amostra definida antes e apagamento no prazo (FR-E049). Dados reais não entram no repositório, nas mensagens nem nos rastros compartilhados.
- [ ] T070 [TIME] Definir quem implementa as tarefas em `backend/fontes`, que o `AGENTS.md` atribui à Frente 2 e hoje recebe código das branches `frente/agente-*`, e qual é a pasta das avaliações (`avaliacoes/` ou `evals/`).

---

## Fase 11: acabamento

- [ ] T071 [F1] Rodar `pytest`, `pytest -m eval` e `ruff check .`, e conferir que nenhum dado real ou chave entrou no repositório (SC-E011, SC-E012).
- [ ] T072 [F1] Registrar em `plan.md` e na arquitetura o que foi resolvido na tabela de divergências, com aviso às frentes afetadas.

---

## Limites entre frentes

| Frente | Tarefas abertas | O que precisa entregar às outras |
| --- | --- | --- |
| **F1. Agente** | T014, T015, T016, T028, T029, T044, T045, T048, T051, T053, T054, T071, T072 | Montagem real e rotas para a F4; coordenação da integração |
| **F2. Fontes e dados** | T001, T013, T018, T019, T025, T026, T027, T031, T035 a T043, T046, T047, T052, T055, T056, T059 a T062 | `PerfilColetado` de toda fonte para a F1; contato publicado para a F3 |
| **F3. Contato e Nara** | Nenhuma tarefa de código aqui | Ajustar a origem no e-mail e o opt-out ao que T040 e T051 definirem, pela feature 002 |
| **F4. Produto e qualidade** | T017, T030 | Etiqueta de simulação e medição de vazamento |
| **Compartilhada** | T035, T037, T043, T045, T054 ([CONTRATO]) | Aviso às quatro frentes, por T002 |
| **Time** | T002, T063 a T070 | Decisões, parecer, contratos e dados do LinkedIn |

Quando uma tarefa da F2 toca `backend/agente`, ou o contrário, a descrição separa a parte de cada frente. Se a mudança não couber nessa divisão, pare e avise antes.

## Dependências e ordem

1. **T001 e T002** vêm primeiro.
2. **T026 e T027** antes de **T014**, para a montagem real já nascer com cofre único.
3. **T036** antes de **T043**, e **T043** antes de **T044**.
4. **T063** bloqueia **T045** e parte de **T046**. **T048** fecha a História 5.
5. **T051** antes de **T054**.
6. **T065** não bloqueia nenhuma tarefa de código desta lista.
7. Histórias 2, 3, 6 e 7 podem andar em paralelo, salvo os arquivos em comum: `anonimizador.py` (T025, T027, T031, T052) e `site_publico.py` (T040, T041, T046, T059, T060, T062).

## Estratégia

**Até 8/11, às 11h (demo sintética):** T001, T002, T015, T025, T026, T037, T040 e T060. Protegem a demo e dependem só do aviso às frentes. O restante fica para depois, salvo decisão do time.

**Modo real, depois das decisões:** T063 a T068, depois T014, T036, T039, T046 e T048. Validação pelo T069.

**Corte, se faltar tempo:** segue a ordem do `AGENTS.md`. GitHub real e aprendizado saem antes; demo sintética e proteção de dados ficam.

## Achados da revisão

Resultado dos casos no commit `536b94e`. "Falha" significa que o defeito continua.

### Nesta feature

| Achado | Gravidade | Casos | Situação | Tarefa |
| --- | --- | --- | --- | --- |
| C-1 | Crítica | `O5` | Falha | T014 |
| C-2 | Crítica | `O1`, `O2` | Falha | T045, T046 |
| C-3 | Crítica | `O3` | Falha | T039 |
| A-1 | Alta | `L1`, `L2` | Falha | T025 |
| A-2 | Alta | `M6`, `M7` | Falha | T037 |
| A-3 | Alta | `M4`, `M5` | Falha | T038 |
| A-4 | Alta | `H1`, `H2` | Falha | T059 |
| A-5 | Alta | `V1` a `V4` | Falha | T051 a T054 |
| A-6 | Alta | `L3` | Falha | T028 |
| A-7 | Alta | `L4` | Falha | T029 |
| A-9 | Alta | `H4`, `H5` | Falha | T061 |
| A-10 | Alta | `H6`, `H7`, `H8` | Falha | T060 |
| M-1 | Média | `H3` passa com limite de 20 s; os números altos vêm de medição à parte | Aberto, por leitura | T062 |
| M-2 | Média | `Q3` | Falha | T026 |
| M-4 | Média | `Q1`, `Q2` | Falha | T047 |
| M-5 | Média | `X1` | Falha | T040 |
| M-6 | Média | `X2` | Falha | T046 |
| M-9 | Média | `H9` | Falha | T062 |
| B-3 | Baixa | `L5` | Falha | T031 |
| B-4 | Baixa | Sem caso | Aberto, por leitura | T018 |
| B-5 | Baixa | Sem caso | Aberto, por leitura | T019 |
| B-6 | Baixa | Sem caso | Aberto, por leitura | T046 |

### Fora desta feature

Continuam abertos. Registrados para não se perderem; a decisão sobre onde tratá-los é do time.

| Achado | Tema | Casos |
| --- | --- | --- |
| C-4 | Rotas de fila, resposta e entrega | `O4` |
| C-5 | Evidência que sustenta o critério | `M1`, `M2`, `M3` |
| C-6 | Autenticação | `A1` |
| A-8 | Limite de gasto do modelo | `C1` a `C5` |
| A-11 | Limites vindos do cliente | `A2`, `A3` |
| A-12 | Medição ligada à autonomia | Sem caso |
| M-3 | Identificação no pacote | `A8` |
| M-7 | Pontos cegos da medição | `D1`, `D2` |
| M-8 | Autenticação do conector MCP | `Z1` |
| M-10 | Mandato e constituição | Sem caso nesta revisão |
| B-1 | Idempotência em paralelo | `A4` |
| B-2 | `simulado` fixo na saída | `A7` |
| B-7 | Disjuntor único de destino | Sem caso |

## Rastreabilidade

| Requisitos | Tarefas |
| --- | --- |
| FR-E001, FR-E002 | T005, T012 |
| FR-E003 | T008, T009, T010, T011 |
| FR-E004 | T007, T013 |
| FR-E005 | T011, T012 |
| FR-E006 | T012, T016, T017 |
| FR-E007 | T010 |
| FR-E008 | T014 |
| FR-E009 | T015 |
| FR-E010 | T006, T057, T062 |
| FR-E011 | T057 |
| FR-E012 | T008, T068 |
| FR-E013 | T004, T040 |
| FR-E014, FR-E016 | T041 |
| FR-E015 | T046 |
| FR-E017, FR-E018 | T003 |
| FR-E019 | T036 |
| FR-E020 | T035 |
| FR-E021 | T039 |
| FR-E022 | T037, T038 |
| FR-E023 | T020, T025 |
| FR-E024 | T025 |
| FR-E025 | T021 |
| FR-E026 | T027 |
| FR-E027 | T026 |
| FR-E028 | T022 |
| FR-E029 | T023 |
| FR-E030 | T020 |
| FR-E031 | T024, T047 |
| FR-E032 | T028, T029 |
| FR-E033, FR-E034, FR-E036 | T042, T043 |
| FR-E035 | T044 |
| FR-E037 | T045, T063 |
| FR-E038 | T045, T046, T048 |
| FR-E039 | T049, T051, T054 |
| FR-E040 | T052, T053 |
| FR-E041 | T050, T055 |
| FR-E042 | T059 |
| FR-E043 | T060 |
| FR-E044 | T061 |
| FR-E045 | T058, T062 |
| FR-E046 | T024 |
| FR-E047 | T065 |
| FR-E048 | T006, T065 |
| FR-E049 | T069 |
| FR-E050 | T056 |
