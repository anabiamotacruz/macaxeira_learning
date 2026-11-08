---

description: "Lista de tarefas da feature 005: medição e autonomia"
---

# Tarefas: medição e autonomia do agente

**Entrada**: documentos de `specs/005-medicao-e-autonomia/`

**Pré-requisitos**: `plan.md` e `spec.md`

**Testes**: obrigatórios. Pelas regras do projeto, cada tarefa escreve o teste antes do código. `[x]` marca só o que existe na base `frente/agente-integracao` e tem teste, conferido com `pytest tests/agente/test_medicao.py tests/agente/test_auditoria.py tests/modelos/test_cliente.py tests/agente/test_decisao_final.py tests/agente/test_api.py`.

**Organização**: tarefas agrupadas por história, cada uma testável por conta própria. **Frente N** no início da descrição diz quem faz.

## Formato: `[ID] [P?] [Story] Descrição`

- **[P]**: pode rodar em paralelo, porque usa arquivos diferentes e não depende de tarefa incompleta
- **[Story]**: história da `spec.md` (US1 a US7)
- **(P1) a (P5)**: a tarefa só começa depois de confirmada a proposta da `spec.md`
- **(contrato)**: exige aviso às quatro frentes antes de alterar `backend/contratos`

## Fase 1: preparação

**Objetivo**: decisões e dados que destravam o resto.

- [ ] T001 Usuário: responder às propostas P1 a P5 e às premissas "a confirmar" em `specs/005-medicao-e-autonomia/spec.md`, incluindo a decisão R3 do `plan.md`
- [ ] T002 Frente 1: avisar as quatro frentes das mudanças propostas em `backend/contratos/modelos.py`, conforme a tabela do `plan.md`, antes de qualquer alteração (contrato)
- [ ] T003 Frente 2: concluir a PR #54 e levar `dados/sinteticos/` à `main`, sabendo que esses dados não certificam 95%
- [ ] T004 Frente 1: atualizar a base da branch com a `main` remota, para ter `dados/`, `web/` e `evals/`, e confirmar com a Frente 4 se a pasta das avaliações é `evals/` ou `avaliacoes/`

---

## Fase 2: base

**Objetivo**: o que todas as histórias usam. As tarefas marcadas já existem.

- [x] T005 Contratos de medição (`TipoErro`, `TaxaMedida`, `CasoAvaliacao`, `ResultadoCaso`, `MetricasMedicao`, `ResultadoProva`, `RelatorioMedicao`) em `backend/contratos/modelos.py`, com `test_metricas_exigem_os_seis_tipos_de_erro` em `tests/agente/test_medicao.py`
- [x] T006 [P] Intervalo de Wilson e taxa nula sem casos em `backend/agente/medicao.py`, com `test_intervalo_bate_com_valores_calculados_a_mao` e `test_medir_taxa_sem_casos_e_nula`
- [x] T007 [P] Versão imutável de um prompt em `backend/agente/medicao.py`, com `test_prompt_tem_versao_e_hash`
- [x] T008 [P] `max_tokens` padrão de 8000, ajustável por `MAX_TOKENS_MODELO` e com mínimo de 1000, em `backend/modelos/cliente.py`, com `test_max_tokens_pode_ser_ajustado_pelo_ambiente` e `test_max_tokens_minimo_1000`
- [x] T009 [P] Contagem de respostas cortadas, maior saída, tokens, custo e tempo por etapa em `backend/modelos/cliente.py`, com `test_mede_resposta_cortada_e_maior_saida` e `test_resposta_cortada_gera_aviso_sem_expor_o_texto`
- [ ] T010 Frente 1: criar `VersaoAvaliada`, com hash de prompts, modelo, parâmetros, limiar e gerador, e usá-la em `rodar`, no cache e em `rodar_prova`, em `backend/agente/medicao.py` e `backend/contratos/modelos.py`, com teste em `tests/agente/test_medicao.py` (contrato)
- [ ] T011 Frente 1: levar `faltas`, consumo e `cortada` a `RespostaAgente` e `ResultadoCaso`, em `backend/contratos/modelos.py`, com teste em `tests/agente/test_medicao.py` (contrato)

**Ponto de controle**: versão composta e campos novos prontos. Depende do aviso da T002.

---

## Fase 3: História 1, dados fortes e suficiência (P1), MVP

**Objetivo**: dados capazes de sustentar a meta e um aviso que evita gasto inútil.

**Teste independente**: ler um conjunto, sem chamar modelo, e conferir partições, casos independentes e maior limite possível.

### Já existe

- [x] T012 [P] [US1] Gabarito derivado por regra em `backend/agente/medicao.py`, com `test_gabarito_derivado_de_cada_cenario` e `test_gabarito_nao_depende_da_resposta_do_agente`
- [x] T013 [P] [US1] Partições reproduzíveis por pessoa, vaga, texto e par em `backend/agente/medicao.py`, com `test_particoes_nao_dividem_pessoa_vaga_nem_texto` e `test_particionar_e_reprodutivel_e_nao_depende_da_ordem`
- [x] T014 [P] [US1] Leitura que recusa incoerência e resumo de casos independentes em `backend/agente/medicao.py`, com `test_leitura_recusa_dados_incoerentes` e `test_resumo_conta_casos_independentes`

### Falta

- [ ] T015 [US1] Frente 2: ampliar `dados/gerador.py` para gerar textos variados e mais de uma função por partição, com testes em `tests/dados/test_cobertura_gerador.py`
- [ ] T016 [US1] Frente 2: incluir pares de viés que só mudam nome ou gênero, `dificuldade` e fontes compatíveis com a política de evidência em `dados/gerador.py` e `dados/sinteticos/respostas_certas.json`, com testes em `tests/dados/test_cobertura_gerador.py`
- [ ] T017 [US1] Frente 2: gerar a prova com o volume da fórmula do FR-M007 e combinar com a Frente 4 o arquivo selado fora do repositório, em `dados/`
- [ ] T018 [P] [US1] Frente 1: ler `dificuldade` em `_CasoArquivo` e `_montar_caso`, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T019 [US1] Frente 1: criar `relatorio_de_suficiencia`, com o maior limite em registros e em casos independentes, por partição e sob a política de evidência, em `backend/agente/medicao.py`, com `test_suficiencia_avisa_que_a_prova_nao_alcanca_a_meta` em `tests/agente/test_medicao.py`
- [ ] T020 [US1] Frente 1: registrar e conferir o hash do conjunto de prova antes da abertura, em `backend/agente/medicao.py`, com `test_prova_recusa_conjunto_com_hash_diferente` em `tests/agente/test_medicao.py`

**Ponto de controle**: o conjunto forte é aceito pelo relatório de suficiência.

---

## Fase 4: História 2, medir uma rodada completa (P1)

**Objetivo**: medir o caminho real de decisão, com erros, alcance, revisão, viés, custo e tempo.

**Teste independente**: rodar o ajuste com modelo simulado e comparar com uma conta feita à mão.

### Já existe

- [x] T021 [P] [US2] Rodada que não entrega gabarito, conta falhas e gera rastro em `backend/agente/medicao.py`, com `test_rodada_nao_entrega_gabarito_ao_agente`, `test_rodada_conta_excecao_como_falha_e_continua` e `test_rodada_gera_rastro_de_cada_chamada_e_de_cada_falha`
- [x] T022 [P] [US2] Seis tipos de erro, cobertura, revisão e falhas em `backend/agente/medicao.py`, com `test_calcula_tipos_de_erro`, `test_cobertura_revisao_e_falhas_somam_um` e `test_mudanca_de_nome_ou_genero_conta_por_par`
- [x] T023 [P] [US2] Cache por versão e entrada em `backend/agente/medicao.py`, com `test_mesma_versao_e_caso_nao_chama_o_modelo_de_novo` e `test_prompt_novo_invalida_o_cache`
- [x] T024 [P] [US2] Relatório só com agregados e limites declarados em `backend/agente/medicao.py`, com `test_relatorio_identifica_dados_sinteticos` e `test_relatorio_declara_quantos_casos_sao_independentes`

### Falta

- [ ] T025 [US2] Frente 1: criar o agente avaliado sobre analisador, revisor e decisão do fluxo, com limiar zero para calibrar e sem busca nem contato, em `backend/agente/medicao_fluxo.py`, com teste em `tests/agente/test_medicao_fluxo.py`
- [ ] T026 [US2] Frente 1: calcular precisão das aprovações e seu limite em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py` (contrato)
- [ ] T027 [US2] Frente 1: calcular alcance automático e final, separando o teto do mandato, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py` (contrato)
- [ ] T028 [US2] Frente 1: calcular revisão sobre todos e sobre quem passou das regras, com motivos, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py` (contrato)
- [ ] T029 [US2] Frente 1: registrar a direção da mudança nos pares de viés e medir faixa além da decisão, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T030 [US2] Frente 1: alinhar `_limiar_viavel` a `passa_no_portao`, para que zero sem medida também barre, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T031 [US2] Frente 1: incluir tokens, custo, tempo, custo por decisão, respostas cortadas e maior saída no relatório da rodada, em `backend/agente/medicao_fluxo.py`, com teste em `tests/agente/test_medicao_fluxo.py` (contrato)
- [ ] T032 [US2] Frente 1: criar o comando `suficiencia`, `rodar` e `relatorio` em `backend/agente/medicao_cli.py`, com teste em `tests/agente/test_medicao_cli.py`
- [ ] T033 [US2] Frente 1: rodada real de cerca de 50 casos de ajuste, com limite de gasto, marcada como `eval`, em `tests/agente/test_rodada_real.py`, publicando custo e respostas cortadas, e rever `MAX_TOKENS_MODELO` se houver cortes

**Ponto de controle**: rodada real de 50 casos publicada, com todas as métricas.

---

## Fase 5: História 3, certificar com prova de abertura única (P1)

**Objetivo**: um resultado único sobre 95% com 95% de confiança.

**Teste independente**: com agente simulado, 0 erros em 59 certificam pelo limite exato, 1 em 59 não certifica, e a segunda abertura é recusada.

### Já existe

- [x] T034 [P] [US3] Prova de abertura única por versão, persistente e só com agregados, em `backend/agente/medicao.py`, com `test_prova_so_abre_uma_vez_por_versao`, `test_segunda_abertura_e_registrada_e_vale_depois_de_reiniciar`, `test_prova_so_devolve_agregados` e `test_falha_na_prova_conta_e_gasta_a_abertura`
- [x] T035 [P] [US3] Limiar congelado na prova e aplicação do limiar em `backend/agente/medicao.py`, com `test_prova_aplica_o_limiar_congelado` e `test_limiar_nulo_nao_deixa_ninguem_na_faixa_verde`
- [x] T036 [P] [US3] Escolha de limiar só no ajuste, com teto de Wilson, devolvendo nulo sem limiar viável, em `backend/agente/medicao.py`, com `test_escolhe_limiar_com_maior_cobertura_dentro_da_meta` e `test_sem_limiar_viavel_devolve_nulo_nunca_o_menos_pior`
- [x] T037 [P] [US3] Portão que barra qualquer piora em `backend/agente/medicao.py`, com `test_portao_barra_piora_em_qualquer_regua` e `test_regua_que_precisa_ser_zero_sem_medida_barra`

### Falta

- [ ] T038 [US3] Frente 1: isolar o método do limite em uma função, com Wilson como valor vigente, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T039 [US3] Frente 1: criar `limite_binomial_exato` em `backend/agente/medicao.py`, com `test_numeros_conferidos_59_100_200_400` em `tests/agente/test_medicao.py` (P2)
- [ ] T040 [US3] Frente 1: permitir 3 limiares fixados antes, com correção, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py` (P3)
- [ ] T041 [US3] Frente 1: criar `certificar`, que exige limite de 95%, zeros medidos, primeira abertura e casos independentes suficientes, em `backend/agente/medicao.py` e `backend/contratos/modelos.py`, com `test_nao_certifica_em_segunda_abertura` e `test_nao_certifica_sem_casos_independentes` em `tests/agente/test_medicao.py` (contrato)
- [ ] T042 [US3] Frente 1: invalidar o certificado quando mudar prompt, modelo, parâmetro, limiar ou gerador, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T043 [US3] Frente 1: levar o escopo "vale para o gerador, não para candidatos reais" a `_limites` e ao certificado, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T044 [US3] Frente 1: acrescentar o comando `prova` em `backend/agente/medicao_cli.py`, com confirmação explícita, e teste em `tests/agente/test_medicao_cli.py`
- [ ] T045 [US3] Usuário e Frente 1: fazer a única abertura com o conjunto forte, por `backend/agente/medicao_cli.py`, e publicar o resultado, qualquer que seja

**Ponto de controle**: certificado emitido ou "não certificado" publicado, sem segunda tentativa.

---

## Fase 6: História 4, avaliação às cegas pela pessoa de RH (P1)

**Objetivo**: confrontar o gabarito do gerador com um julgamento humano independente.

**Teste independente**: gerar fichas, importar respostas fictícias e conferir a concordância, sem modelo.

- [ ] T046 [US4] Usuário: confirmar data e disponibilidade da pessoa de RH, cerca de 1h15 a 1h50 para 34 fichas, e registrar em `specs/005-medicao-e-autonomia/plan.md`
- [ ] T047 [US4] Frente 1: criar `gerar_fichas` em `backend/agente/avaliacao_rh.py`, com `test_ficha_nao_mostra_gabarito_nem_resposta_do_agente` e `test_selecao_e_reproduzivel_e_respeita_as_particoes` em `tests/agente/test_avaliacao_rh.py` (contrato)
- [ ] T048 [US4] Frente 1: criar `importar_avaliacoes` em `backend/agente/avaliacao_rh.py`, com `test_importacao_guarda_decisao_e_motivo` e `test_resposta_incompleta_e_recusada` em `tests/agente/test_avaliacao_rh.py`
- [ ] T049 [US4] Frente 1: criar `medir_concordancia`, com kappa, intervalo, ponte e duplicatas, em `backend/agente/avaliacao_rh.py`, com `test_mede_concordancia_por_tipo_de_caso`, `test_duplicatas_medem_consistencia` e `test_discordancias_da_prova_nao_saem_caso_a_caso` em `tests/agente/test_avaliacao_rh.py`
- [ ] T050 [US4] Frente 4: criar o formulário da ficha em `web/`, sem campos ocultos, com teste na mesma pasta
- [ ] T051 [US4] Frente 1: permitir que `gerar_relatorio` registre a avaliação realizada, em vez do valor fixo `gabarito_validado_por_recrutador=False`, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T052 [US4] Usuário e pessoa de RH: fixar o limite de discordância antes, aplicar a sessão e, se ele for ultrapassado, pedir à Frente 2 a revisão de `dados/gerador.py`

**Ponto de controle**: concordância publicada, com o limite de ser uma pessoa em dados sintéticos.

---

## Fase 7: História 5, decidir sozinho dentro do mandato (P2)

**Objetivo**: a decisão e a API mostram o que foi medido e certificado.

**Teste independente**: criar uma vaga pela API com medição injetada, com e sem certificado.

### Já existe

- [x] T053 [P] [US5] Amostra reproduzível que inclui descartes e cobre cada vaga em `backend/agente/auditoria.py`, com `test_amostra_auditada_e_reproduzivel`, `test_amostra_inclui_descartes_mesmo_raros` e `test_amostra_cobre_cada_vaga`
- [x] T054 [P] [US5] Pausa por erro na amostra em `backend/agente/auditoria.py`, com `test_erro_na_amostra_pausa_decisoes_automaticas` e `test_pausa_nao_impede_mandar_para_humano`
- [x] T055 [P] [US5] Métricas de autonomia, sem intervalo e sem chamador fora dos testes, em `backend/agente/auditoria.py`, com `test_metricas_de_autonomia`
- [x] T056 [P] [US5] Selo igual a certificado só com limiar certificado igual ao do mandato, em `backend/agente/decisao_final.py`, com `test_selo_so_muda_com_o_limiar_certificado_igual_ao_do_mandato`
- [x] T057 [P] [US5] Provedor de métricas injetável na API, em `backend/agente/servico.py` e `backend/agente/api.py`, com `test_metricas_injetadas_deixam_de_ser_exemplo_fixo` em `tests/agente/test_api.py`

### Falta

- [ ] T058 [US5] Frente 1: ligar o certificado ao fluxo, com evento e selo em `Decisao.entrada`, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T059 [US5] Frente 1: guardar a versão avaliada em cada decisão, em `backend/agente/fluxo.py` e `backend/contratos/modelos.py`, com teste em `tests/agente/test_fluxo.py` (contrato)
- [ ] T060 [US5] Frente 1: acrescentar intervalo e `TaxaMedida` a `metricas_autonomia`, em `backend/agente/auditoria.py`, com teste em `tests/agente/test_auditoria.py`
- [ ] T061 [US5] Frente 1: injetar o provedor de métricas em `backend/agente/montagem.py`, com teste em `tests/agente/test_montagem.py`
- [ ] T062 [US5] Frente 1: criar `GET /vagas/{id}/certificacao` em `backend/agente/api.py`, com isolamento por empresa e teste em `tests/agente/test_api.py`
- [ ] T063 [US5] Frente 1: ligar o sorteio da amostra e a pausa ao fim da decisão, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T064 [US5] Frente 1: usar 5% como padrão e registrar a probabilidade para ponderar, em `backend/agente/auditoria.py`, com teste em `tests/agente/test_auditoria.py` (P4)
- [ ] T065 [US5] Frente 4: mostrar selo, número de casos, limite inferior, escopo e marca de exemplo fixo em `web/`, com teste na mesma pasta

**Ponto de controle**: painel e API mostram números medidos e selo verdadeiro.

---

## Fase 8: História 6, auto-improve de prompt e de limiar (P2)

**Objetivo**: candidatos a partir dos erros de ajuste, barrados por qualquer piora.

**Teste independente**: um ciclo com modelo simulado, com candidato barrado, aguardando aprovação e revertido.

- [ ] T066 [US6] Frente 1: separar trechos fixos e ajustáveis em `backend/agente/prompts.py`, com teste em `tests/agente/test_aprendizado.py`
- [ ] T067 [US6] Frente 1: criar `resumir_erros`, só com ajuste e sem atributos sensíveis, em `backend/agente/aprendizado.py`, com `test_erros_agrupados_por_motivo_e_armadilha` em `tests/agente/test_aprendizado.py`
- [ ] T068 [US6] Frente 1: criar `propor_prompt`, com propositor sem texto de candidato e recusa fora dos trechos ajustáveis, em `backend/agente/aprendizado.py`, com `test_candidato_de_prompt_passa_pelo_portao`, `test_proposta_fora_dos_trechos_e_rejeitada` e `test_propositor_nao_recebe_texto_do_candidato` em `tests/agente/test_aprendizado.py`
- [ ] T069 [US6] Frente 1: criar `propor_limiar`, com limiar menor exigindo nova certificação, em `backend/agente/aprendizado.py`, com `test_limiar_menor_exige_certificacao` em `tests/agente/test_aprendizado.py`
- [ ] T070 [US6] Frente 1: guardar versões imutáveis por empresa e o ponteiro da ativa em `backend/agente/persistencia.py`, com `test_prompt_de_uma_empresa_nao_afeta_outra` e `test_execucao_em_andamento_mantem_versao` em `tests/agente/test_persistencia.py` (contrato)
- [ ] T071 [US6] Frente 1: criar `reverter` idempotente em `backend/agente/aprendizado.py`, com `test_reverter_restaura_hash_anterior` e `test_reverter_duas_vezes_nao_muda_estado` em `tests/agente/test_aprendizado.py`
- [ ] T072 [US6] Frente 1: manter o candidato parado sem aprovação em `backend/agente/aprendizado.py`, com `test_nao_aplica_sem_aprovacao` em `tests/agente/test_aprendizado.py`
- [ ] T073 [US6] Frente 1: aplicar limiar por novo termo do mandato em `backend/agente/servico.py`, com teste em `tests/agente/test_aprendizado.py`
- [ ] T074 [US6] Frente 1: criar a aprovação de um clique por pessoa nomeada em `backend/agente/api.py` e `backend/agente/aprendizado.py`, com teste em `tests/agente/test_api.py` (P1)
- [ ] T075 [US6] Frente 4: mostrar o antes e o depois e o botão de aprovação em `web/`, com teste na mesma pasta (P1)

**Ponto de controle**: um ciclo disparado por comando, sem laço contínuo.

---

## Fase 9: História 7, motivos de revisão e portões (P2)

**Objetivo**: atacar o maior gargalo sem gastar modelo.

**Teste independente**: reprocessar decisões registradas e conferir a contagem por motivo.

### Já existe

- [x] T076 [P] [US7] Decisão com portões, sinais e nota baixa sem recusa, ainda fora do fluxo, em `backend/agente/decisao_final.py`, com `test_nota_baixa_nunca_recusa`, `test_trecho_inexistente_em_requisito_e_portao_duro` e `test_ressalva_grave_e_portao_e_leve_so_reduz`

### Falta

- [ ] T077 [US7] Frente 1: criar o diagnóstico sem modelo, com motivos por pessoa, teto do mandato e política de evidência, em `backend/agente/medicao_fluxo.py`, com `test_diagnostico_nao_chama_modelo` em `tests/agente/test_medicao_fluxo.py`
- [ ] T078 [US7] Frente 1: rodar o diagnóstico nos resultados da primeira rodada real e registrar o resultado em `specs/005-medicao-e-autonomia/plan.md`
- [ ] T079 [US7] Usuário: decidir, em `specs/005-medicao-e-autonomia/spec.md`, se evidência declarada em currículo pode cumprir requisito, porque hoje 62 dos 83 indicáveis da PR #54 ficam fora da faixa verde por causa disso
- [ ] T080 [US7] Frente 1: trocar `regras.decidir` por `classificar_destino` no fluxo, mantendo eliminatórios e autorização em código, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py` (P5)
- [ ] T081 [US7] Frente 1: medir o antes e o depois da troca na validação, pelo portão, em `tests/agente/test_medicao_fluxo.py` (P5)

**Ponto de controle**: gargalo principal identificado, com números.

---

## Fase final: acabamento

- [ ] T082 Frente 4: ligar `medicao.py` a `pytest -m eval` e ao relatório do painel, na pasta confirmada pela T004
- [ ] T083 Frente 4: escrever a frase da demo, com número de casos, limite inferior e escopo do gerador, em `docs/pitch/`
- [ ] T084 Frente 1: rodar `pytest` e `ruff check .` em todo o repositório e registrar o resumo no PR
- [ ] T085 Frente 1: conferir os casos de borda da `spec.md` contra os testes, em `tests/agente/test_medicao.py`

---

## Dependências e ordem

- **Fase 1** vem primeiro. A T001 define o que as tarefas com (P1) a (P5) podem fazer.
- **Fase 2** depende do aviso da T002.
- **US1** não depende das outras histórias, mas as tarefas da Frente 2 dependem da T003.
- **US2** usa dados de teste até a US1 entregar os dados fortes.
- **US3** depende da T010 e da T026, e sua abertura final (T045) depende de T015 a T020, T033 e T052.
- **US4** depende só dos dados e pode rodar em paralelo à US2.
- **US5** depende da T041 para ter certificado, mas o selo "não calibrado" não depende.
- **US6** depende da US2 e do portão, e não usa a prova.
- **US7** tem a T077 independente. T080 e T081 dependem de P5 e de T079.

### Paralelismo

```text
Frente 1: T018, T019 e T025 podem seguir juntas, pois usam funções separadas.
Frente 2: T015 e T016, no mesmo arquivo, em sequência.
Frente 4: T050 e T065 na mesma pasta, em telas separadas.
```

## Estratégia

**MVP**: US1, US2 e T077, para saber onde o agente está, com selo "não calibrado". Depois, US4, US3 e US5. A US6 entra por último e, se o prazo apertar, para no ciclo por comando, sem aplicar.

**Se apertar até domingo, às 11h**, corte nesta ordem: T075 e T074, T073, T064, T081 e T080, T040. Não corte separação de partições, prova única, portão de eliminatório, reversão e identificação de dados sintéticos.

## Limites entre frentes

| Frente | Tarefas |
| --- | --- |
| **1. Agente** | T002, T004, T010, T011, T018 a T020, T025 a T033, T038 a T044, T047 a T049, T051, T058 a T064, T066 a T074, T077, T078, T080, T081, T084, T085 |
| **2. Fontes e dados (Bia)** | T003, T015 a T017, revisão do gerador na T052 |
| **3. Contato e Nara** | Sem tarefa nesta feature. Mantém o bloqueio real de opt-out. A medição apenas o aproxima pela indicação |
| **4. Produto e qualidade** | T050, T065, T075, T082, T083, guarda do arquivo de prova na T017 |
| **Usuário e pessoa de RH** | T001, T045, T046, T052, T079 |

## Rastreio de requisitos

| Requisitos | Tarefas |
| --- | --- |
| FR-M001 a FR-M004 | T012 a T016, T024 |
| FR-M005 a FR-M007 | T017, T019 |
| FR-M008, FR-M009 | T034 |
| FR-M010 a FR-M013 | T010, T020, T035, T041 |
| FR-M014, FR-M021, FR-M022 | T022, T060 |
| FR-M015 a FR-M017 | T011, T026 a T028 |
| FR-M018 | T016, T029, T030 |
| FR-M019, FR-M020 | T008, T009, T031, T033 |
| FR-M023 a FR-M029 | T036, T038 a T045 |
| FR-M030 a FR-M033 | T056 a T059, T061, T062, T065 |
| FR-M034, FR-M035 | T053, T054, T063, T064 |
| FR-M036 | T058, T080 |
| FR-M037 a FR-M041 | T046 a T052 |
| FR-M042 a FR-M048 | T066 a T075 |
| FR-M049, FR-M050 | T076 a T081 |
| FR-M051 | T033 |
