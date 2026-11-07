---

description: "Tarefas da decisão, pré-triagem e feedback"
---

# Tarefas: decisão, pré-triagem e feedback

**Entrada**: `specs/003-decisao-pre-triagem-feedback/`, com `spec.md` e `plan.md`

**Testes**: teste antes do código, como manda a constituição. Mudanças em decisão também rodam a medição.

**Base**: `frente/agente-integracao`, commit `536b94e`. As tarefas `[X]` têm código e teste nessa base. Os 246 testes de `test_decisao_final.py`, `test_pre_triagem.py`, `test_feedback.py`, `test_jornada_pre_triagem.py` e `test_destino_e_pre_triagem.py` passaram em 2026-11-07.

**Atenção**: `[X]` significa "o módulo existe e tem teste". Nada disso está ligado ao fluxo nem à API ainda.

## Formato

`- [ ] T000 [P] [US1] F1: descrição com caminho`

- **[P]**: pode rodar em paralelo.
- **[US1] a [US6]**: história da `spec.md`.
- **F1 a F4**: frente responsável. **C**: `backend/contratos`, com aviso às quatro frentes.
- **Bloqueada**: depende de resposta do responsável pelo produto.

## Limites entre as frentes

| Frente | Tarefas abertas |
| --- | --- |
| **F1. Agente** | T004, T007, T008, T015 a T022, T026 a T029, T039, T040, T043 a T045, T049, T050, T051, T054 a T056, T060, T062, T066, T068 a T072, T074 a T076 |
| **F2. Fontes e dados** | T042 |
| **F3. Contato e Nara** | T038, T041, T052, T063, T064 |
| **F4. Produto e qualidade** | T030, T053, T065, T073 |
| **C. Contratos** | T001, T037, T061 |
| **Governança, com as quatro frentes** | T002, T003 |

---

## Fase 1: Acordos

**Objetivo**: registrar o que foi decidido antes de mudar código compartilhado.

- [ ] T001 C: avisar as quatro frentes e levar para a `main`, em PR próprio, os contratos novos de `backend/contratos/modelos.py`
- [ ] T002 Registrar a emenda do princípio II, com o acordo das quatro frentes, em `.specify/memory/constitution.md` e `docs/PADRAO-DO-PROJETO.md`
- [ ] T003 Depois de T002, propor em PR separado o alinhamento de FR-007 em `specs/001-agente-recrutador/spec.md`, do fluxo e de FR-C014 e FR-C015 em `specs/002-contato-e-nara/spec.md` e da seção 8 de `docs/superpowers/specs/2026-11-07-arquitetura-coleta-e-agente.md`
- [ ] T004 F1: registrar em `specs/003-decisao-pre-triagem-feedback/spec.md` as respostas sobre FR-D010, FR-D042, FR-D043, P-1 a P-4, evidência declarada e competência a desenvolver

---

## Fase 2: Base compartilhada

**Objetivo**: contratos e persistência que todas as histórias usam.

- [X] T005 C: destinos, invariantes de `DecisaoFinal` e regra de recusa objetiva em `backend/contratos/modelos.py`, testados em `tests/contratos/test_destino_e_pre_triagem.py`
- [X] T006 C: `Politica` com confirmação e prazo do garden, sem invalidar mandatos antigos, em `backend/contratos/modelos.py` e `backend/agente/mandato.py`, testados em `tests/contratos/test_destino_e_pre_triagem.py`
- [ ] T007 F1: escrever os testes e persistir `EntradaGarden` por empresa em `backend/agente/persistencia.py`, com testes em `tests/agente/test_persistencia.py`
- [ ] T008 F1: escrever os testes e persistir roteiro e resposta em andamento, para retomar depois de um reinício, em `backend/agente/persistencia.py`, com testes em `tests/agente/test_persistencia.py`

**Ponto de controle**: T001 feita antes de qualquer PR que dependa dos contratos novos na `main`.

---

## Fase 3: História 1, decidir dentro do mandato (P1, MVP)

**Objetivo**: toda decisão termina em uma das cinco saídas, explicável e sob mandato.

**Teste independente**: `pytest tests/agente/test_decisao_final.py -v` para o módulo, e `pytest tests/agente/test_fluxo.py -v` para a ligação.

### Pronto

- [X] T009 [US1] F1: `classificar_destino` com Aprovar, Recusar, Revisão humana e limiar em `backend/agente/decisao_final.py`, testado por `test_aprova_quem_passa_nos_portoes_e_tem_nota_alta`, `test_recusa_por_requisito_comprovadamente_nao_atendido`, `test_nota_baixa_nunca_recusa` e `test_sem_limiar_nada_e_aprovado_sozinho` em `tests/agente/test_decisao_final.py`
- [X] T010 [US1] F1: mandato inválido e peças de outra empresa recusadas em `backend/agente/decisao_final.py`, testado por `test_mandato_de_vaga_alterada_para_a_decisao` e `test_pecas_de_empresas_diferentes_sao_recusadas` em `tests/agente/test_decisao_final.py`
- [X] T011 [US1] F1: portões separados de sinais em `backend/agente/decisao_final.py`, testado por `test_instrucao_detectada_e_portao_duro`, `test_trecho_inexistente_em_requisito_e_portao_duro`, `test_ressalva_grave_e_portao_e_leve_so_reduz` e `test_sinais_mudam_o_resultado_que_a_faixa_verde_mandaria_para_a_fila` em `tests/agente/test_decisao_final.py`
- [X] T012 [US1] F1: requisito com evidência e competência só na nota (P-3, não confirmada) em `backend/agente/decisao_final.py`, testado por `test_sem_dado_em_requisito_nunca_aprova_sozinho`, `test_requisito_so_com_evidencia_declarada_nao_passa_sem_a_politica` e `test_competencia_sem_evidencia_vale_nivel_minimo_sem_anular_a_nota` em `tests/agente/test_decisao_final.py`
- [X] T013 [US1] F1: registro com `como_decisao`, rastro e entrada sem nome em `backend/agente/decisao_final.py`, testado por `test_decisao_final_cabe_no_registro_de_decisoes_e_volta_igual`, `test_entrada_nao_guarda_nome_nem_atributos`, `test_responsavel_cita_o_mandato_assinado` e `test_decisao_gera_rastro` em `tests/agente/test_decisao_final.py`
- [X] T014 [US1] F1: decisão igual ao trocar nome ou gênero em `backend/agente/decisao_final.py`, testada por `test_trocar_nome_ou_genero_nao_muda_a_decisao` em `tests/agente/test_decisao_final.py`

### A fazer

- [ ] T015 [US1] F1: escrever em `tests/agente/test_fluxo.py` o teste de que a etapa de decidir registra `DecisaoFinal` nas cinco saídas possíveis nesta etapa, e trocar `regras.decidir` por `classificar_destino` em `_decidir_candidato` de `backend/agente/fluxo.py`
- [ ] T016 [US1] F1: corrigir `_ordem_de_decisao`, que lê `entrada["nota"]`, para a decisão com destino, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T017 [US1] F1: aplicar `max_indicacoes` sem recusar e manter `decisao_final` coerente com a decisão registrada, em `backend/agente/fluxo.py` e `backend/agente/decisao_final.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T018 [US1] F1: atualizar `REGRAS_DA_FAIXA_VERDE` e a taxa anômala para a regra `aprovacao_por_criterios_v1`, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T019 [US1] F1: tratar decisão sem análise e corte de autorização com o contrato novo, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T020 [US1] F1: manter o histórico da decisão final depois de reversão e decisão humana, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T021 [US1] F1: confirmar por teste em `tests/agente/test_fluxo.py` que Aprovar segue sem aprovação de lote, em `backend/agente/fluxo.py`
- [ ] T022 [US1] F1: reexecutar a medição antes e depois da troca com `passa_no_portao` de `backend/agente/medicao.py`, e registrar o resultado no PR

**Ponto de controle**: uma vaga simulada termina com as saídas registradas, e o que já funcionava continua funcionando.

---

## Fase 4: História 2, o recrutador entende a nota (P1)

**Objetivo**: score, pontos e insights visíveis, com selo.

**Teste independente**: `pytest tests/agente/test_api.py -v` com uma vaga simulada.

### Pronto

- [X] T023 [US2] F1: score por critério, qualidade, sinais e selo em `backend/agente/decisao_final.py`, testado por `test_score_traz_nivel_peso_trecho_qualidade_e_selo`, `test_qualidade_separa_declarado_de_comprovado` e `test_selo_so_muda_com_o_limiar_certificado_igual_ao_do_mandato` em `tests/agente/test_decisao_final.py`
- [X] T024 [US2] F1: `pontos_a_explorar` com rótulo e sem dado sensível em `backend/agente/decisao_final.py` e `backend/contratos/modelos.py`, testado por `test_afirmacao_sem_exemplo_e_experiencia_parecida_trazem_trecho`, `test_contradicao_entre_analise_e_atributo_aparece_com_trecho` e `test_criterio_de_vaga_com_termo_proibido_nao_vira_ponto` em `tests/agente/test_decisao_final.py`, e `test_ponto_mostra_nao_verificado_e_inferencia_nunca_e_verificada` em `tests/contratos/test_destino_e_pre_triagem.py`
- [X] T025 [US2] F1: `insights_da_vaga` com supressão em `backend/agente/decisao_final.py`, testado por `test_insight_mostra_o_requisito_em_que_a_maioria_para_sem_expor_pessoas`, `test_insight_some_com_poucas_pessoas` e `test_insight_recusa_decisao_de_outra_vaga_ou_empresa` em `tests/agente/test_decisao_final.py`

### A fazer

- [ ] T026 [US2] F1: incluir a decisão final e o score na resposta de `GET /candidatos/{id}/decisao`, em `backend/agente/api.py` e `backend/agente/servico.py`, com teste em `tests/agente/test_api.py`
- [ ] T027 [P] [US2] F1: adicionar os pontos a explorar da decisão vigente à API, em `backend/agente/api.py` e `backend/agente/servico.py`, com teste em `tests/agente/test_api.py`
- [ ] T028 [P] [US2] F1: adicionar `GET /vagas/{id}/insights`, em `backend/agente/api.py` e `backend/agente/servico.py`, com teste em `tests/agente/test_api.py`
- [ ] T029 [US2] F1: atualizar exemplos e OpenAPI, em `backend/agente/exemplos_api.py` e `backend/agente/gerar_openapi.py`, com teste em `tests/agente/test_gerar_openapi.py`
- [ ] T030 [US2] F4: mostrar score, selo, pontos e insights em `web/app/candidatos/[id]/page.tsx`, consumindo a API

**Ponto de controle**: o recrutador lê a decisão inteira pela API, e o selo "não calibrado" aparece.

---

## Fase 5: História 3, pré-triagem completa o que falta (P1)

**Objetivo**: da aprovação ao link do agente de destino, passando pelo canal real da Frente 3.

**Teste independente**: `pytest tests/agente/test_jornada_pre_triagem.py -v` para a jornada simulada.

### Pronto

- [X] T031 [US3] F1: `gerar_roteiro` com só o que falta, limite e bloqueio sensível em `backend/agente/pre_triagem.py`, testado por `test_pergunta_so_o_que_falta_em_ordem_de_importancia`, `test_limite_de_perguntas_nunca_corta_eliminatorio`, `test_criterio_que_viraria_pergunta_sensivel_e_bloqueado_em_codigo`, `test_nao_ha_roteiro_para_recusa_nem_garden` e `test_ambiguo_so_recebe_roteiro_liberado_por_uma_pessoa` em `tests/agente/test_pre_triagem.py`
- [X] T032 [US3] F1: `extrair_respostas` com texto delimitado, sem nome e com conferência do trecho em `backend/agente/pre_triagem.py`, testado por `test_nome_da_pessoa_nao_chega_ao_modelo`, `test_texto_do_candidato_vai_delimitado_e_sem_poder_fechar_a_marca`, `test_modelo_fora_do_ar_e_extracao_invalida`, `test_trecho_que_nao_existe_na_mensagem_e_extracao_invalida` e `test_instrucao_na_mensagem_nao_chega_ao_modelo` em `tests/agente/test_pre_triagem.py`
- [X] T033 [US3] F1: `validar_pre_triagem` e `reavaliar_criterios` em código em `backend/agente/pre_triagem.py` e `backend/agente/decisao_final.py`, testados por `test_extracao_invalida_vai_para_uma_pessoa_e_nunca_aprova`, `test_quem_nega_requisito_eliminatorio_nao_passa_e_recusa_por_regra`, `test_reavalia_so_o_criterio_da_resposta` e `test_validacao_nao_chama_modelo_nem_agenda` em `tests/agente/test_pre_triagem.py`
- [X] T034 [US3] F1: link do destino e falha sem perder a validação em `backend/agente/pre_triagem.py`, testado por `test_quem_passa_recebe_o_link_do_destino` e `test_falha_no_link_nao_desfaz_a_validacao` em `tests/agente/test_pre_triagem.py`
- [X] T035 [US3] F1: `atualizar_perfil`, `registrar_no_perfil`, `montar_contexto_onboarding` e `pacote_com_pre_triagem` em `backend/agente/pre_triagem.py`, testados por `test_resposta_atualiza_atributo_com_fonte_e_data`, `test_registra_no_banco_de_talentos`, `test_contexto_de_onboarding_nao_traz_nota_nem_faixa` e `test_pacote_leva_pontos_a_explorar_e_respostas` em `tests/agente/test_pre_triagem.py`
- [X] T036 [US3] F1: jornada com transporte simulado em `tests/agente/test_jornada_pre_triagem.py`, testada por `test_quem_passa_recebe_link_e_o_pacote_leva_contexto` e `test_mensagem_com_instrucao_nao_aprova_nem_muda_o_perfil`

### A fazer

- [ ] T037 [US3] C: definir a interface do canal, com entrega de perguntas e devolução da mensagem, em `backend/contratos/interfaces.py`, com simulação em `backend/contratos/simulacoes.py` e teste em `tests/contratos/test_simulacoes.py`
- [ ] T038 [US3] F3: adaptar a T3.9, já em `origin/main`, para receber `ContextoOnboarding` e devolver a mensagem, sem `montar_roteiro` nem `validar` próprios, em `backend/contato/whatsapp.py`, com testes em `tests/contato/test_whatsapp.py`
- [ ] T039 [US3] F1: abrir o roteiro para quem foi aprovado e parar à espera da resposta, com estado salvo, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T040 [US3] F1: receber a mensagem do canal, extrair, validar e registrar de forma idempotente, em `backend/agente/servico.py` e `backend/agente/api.py`, com testes em `tests/agente/test_api.py`
- [ ] T041 [US3] F3: ligar a conversa ao convite e à empresa e chamar a entrada de T040, em `backend/contato/whatsapp.py`, com testes em `tests/contato/test_whatsapp.py`
- [ ] T042 [US3] F2: reidentificar `pontos_a_explorar` e `respostas_pre_triagem` e listar os marcadores na auditoria, em `backend/fontes/anonimizador.py`, com testes em `tests/fontes/test_anonimizador.py`
- [ ] T043 [US3] F1: entregar o pacote de quem passou, com `pacote_com_pre_triagem` antes da reidentificação e chave idempotente, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T044 [US3] F1: tentar de novo o link quando `link_indisponivel` for verdadeiro, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T045 [US3] F1: liberar pré-triagem de caso em Revisão humana por pessoa identificada, em `backend/agente/api.py` e `backend/agente/servico.py`, com teste em `tests/agente/test_api.py`

**Ponto de controle**: a mesma jornada do teste roda pela API e pelo canal simulado da Frente 3, e nenhum pacote sai com marcador.

---

## Fase 6: História 4, manter proximidade pelo garden (P2)

**Objetivo**: garden com autorização, prazo e revisão, visível ao RH.

**Teste independente**: `pytest tests/agente/test_decisao_final.py -k "garden or lapidar or indisponivel or entrada or autorizacao" -v` para o módulo.

### Pronto

- [X] T046 [US4] F1: Garden indisponível em `backend/agente/decisao_final.py`, testado por `test_pessoa_boa_que_nao_pode_agora_vai_ao_garden_sem_confirmacao`, `test_indisponivel_com_nota_baixa_nao_e_recusado_e_vai_para_uma_pessoa` e `test_indisponivel_com_requisito_nao_atendido_continua_recusado` em `tests/agente/test_decisao_final.py`
- [X] T047 [US4] F1: Garden a lapidar e `confirmar_lapidar` (P-1, não confirmada) em `backend/agente/decisao_final.py`, testados por `test_a_lapidar_com_fatos_e_proposto_e_espera_o_rh`, `test_rh_nega_a_lapidar_e_ninguem_e_recusado`, `test_so_uma_pessoa_identificada_confirma` e `test_lacuna_em_requisito_nao_desenvolvivel_nao_vira_a_lapidar` em `tests/agente/test_decisao_final.py`
- [X] T048 [US4] F1: entrada, autorização, prazo, opt-out, revisão e encerramento em `backend/agente/decisao_final.py`, testados por `test_entrada_depende_da_autorizacao_da_pessoa`, `test_autorizacao_tem_prazo_limitado_pela_politica`, `test_opt_out_sai_do_garden_sempre`, `test_garden_vence_no_prazo_e_chega_a_hora_de_rever` e `test_entrada_pode_ser_revista_por_uma_pessoa` em `tests/agente/test_decisao_final.py`

### A fazer

- [ ] T049 [US4] F1: abrir a entrada depois da decisão de garden e expor listagem, confirmação, revisão e encerramento, em `backend/agente/servico.py` e `backend/agente/api.py`, com testes em `tests/agente/test_api.py`
- [ ] T050 [US4] F1: marcar entradas para revisão e encerrar as vencidas em uma rotina, em `backend/agente/servico.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T051 [US4] F1: conciliar `DestinoPessoa` e `/candidatos/{id}/destino` com os destinos de garden decididos pelo agente, em `backend/agente/fluxo.py` e `backend/agente/api.py`, com teste em `tests/agente/test_api.py` e aviso às frentes se tocar `backend/contratos/modelos.py`
- [ ] T052 [US4] F3: enviar o pedido de autorização do garden como `Convite` do tipo `AUTORIZACAO` e devolver a resposta para `autorizar_garden`, em `backend/contato/conversa.py`, com testes em `tests/contato/test_conversa.py`
- [ ] T053 [P] [US4] F4: mostrar a fila de confirmação e o garden em `web/app/banco/page.tsx`, consumindo a API
- [ ] T054 [US4] F1 **Bloqueada por FR-D010**: aplicar a definição de "pessoa boa" à ordem de `_resolver` em `backend/agente/decisao_final.py`, com teste em `tests/agente/test_decisao_final.py`
- [ ] T055 [US4] F1 **Bloqueada por P-1**: garantir sinal de que a empresa quer manter proximidade antes do Garden a lapidar, em `backend/agente/decisao_final.py`, com teste em `tests/agente/test_decisao_final.py`
- [ ] T056 [US4] F1 **Bloqueada por P-4**: levar toda decisão de vaga com ação afirmativa a uma pessoa, em `backend/agente/decisao_final.py`, com teste em `tests/agente/test_decisao_final.py` e aviso às frentes se o contrato de `Vaga` mudar

**Ponto de controle**: entradas ficam salvas por empresa, e nenhuma fica ativa sem autorização.

---

## Fase 7: História 5, feedback a quem pedir (P2)

**Objetivo**: pedido pelo canal, resposta honesta e auditada.

**Teste independente**: `pytest tests/agente/test_feedback.py -v` para o módulo.

### Pronto

- [X] T057 [US5] F1: resposta a pedido com motivo ligado a trecho, sem nota e auditada em `backend/agente/feedback.py`, testada por `test_feedback_lista_criterio_trecho_e_o_que_poderia_mudar`, `test_todo_motivo_esta_ligado_a_um_trecho_registrado_na_decisao`, `test_nao_traz_nota_faixa_ranking_nem_outros_candidatos`, `test_sem_auditoria_nada_sai` e `test_toda_geracao_fica_auditada_sem_dado_da_pessoa` em `tests/agente/test_feedback.py`
- [X] T058 [US5] F1: encaminhamento à pessoa responsável e negativa de pedidos alheios em `backend/agente/feedback.py`, testados por `test_motivo_sensivel_e_bloqueado_e_vai_para_a_pessoa_responsavel`, `test_contestacao_vai_para_a_pessoa_responsavel`, `test_motivo_sem_trecho_registrado_nao_sai` e `test_pedido_de_outra_pessoa_vaga_ou_empresa_e_negado` em `tests/agente/test_feedback.py`
- [X] T059 [US5] F1: decisão da entrevista e equidade em `backend/agente/feedback.py`, testadas por `test_decisao_da_entrevista_so_transmite_o_que_o_destino_informou`, `test_entrevista_com_criterio_fora_da_vaga_nao_e_transmitida` e `test_trocar_nome_ou_genero_so_muda_a_saudacao` em `tests/agente/test_feedback.py`

### A fazer

- [ ] T060 [US5] F1: separar a causa do resultado da orientação, para que competência não apareça como motivo de recusa por requisito, em `backend/agente/feedback.py`, com teste em `tests/agente/test_feedback.py`
- [ ] T061 [US5] C: restringir `PedidoFeedback.canal` a e-mail e WhatsApp, em `backend/contratos/modelos.py`, com teste em `tests/contratos/test_destino_e_pre_triagem.py`
- [ ] T062 [US5] F1: receber o pedido, buscar a decisão no registro e responder de forma idempotente, em `backend/agente/servico.py` e `backend/agente/api.py`, com testes em `tests/agente/test_api.py`
- [ ] T063 [US5] F3: reconhecer o pedido de feedback na conversa, verificar a pessoa pelo convite e chamar T062, em `backend/contato/conversa.py`, com testes em `tests/contato/test_conversa.py`
- [ ] T064 [US5] F3: entregar o texto só depois de consultar supressão e janela de 24 horas, em `backend/contato/mensageiro.py`, com testes em `tests/contato/test_mensageiro.py`
- [ ] T065 [P] [US5] F4: mostrar os pedidos encaminhados à pessoa responsável em `web/app/candidatos/[id]/page.tsx`, consumindo a API
- [ ] T066 [US5] F1: colocar o encaminhamento na fila da pessoa responsável e tratar quem saiu ou teve os dados apagados, em `backend/agente/servico.py`, com teste em `tests/agente/test_api.py`

**Ponto de controle**: um pedido pelo canal simulado volta com motivos reais ou vai para uma pessoa, sem envio espontâneo.

---

## Fase 8: História 6, saber se a precisão é aceitável (P2)

**Objetivo**: medir a meta com honestidade, sem prometer o que a amostra não sustenta.

**Teste independente**: `pytest tests/agente/test_medicao.py -v`.

### Pronto

- [X] T067 [US6] F1: taxas com intervalo, limiar no ajuste, portão e prova de abertura única em `backend/agente/medicao.py`, para `TipoDecisao`, testados por `test_escolhe_limiar_com_maior_cobertura_dentro_da_meta`, `test_sem_limiar_viavel_devolve_nulo_nunca_o_menos_pior`, `test_portao_barra_piora_em_qualquer_regua` e `test_prova_so_abre_uma_vez_por_versao` em `tests/agente/test_medicao.py`

### A fazer

- [ ] T068 [US6] F1 **Bloqueada por FR-D042**: fixar a definição da meta de 95% em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T069 [US6] F1: medir precisão pelas cinco saídas, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T070 [US6] F1: se FR-D042 pedir limite inferior, usar limite binomial exato e corrigir a varredura de limiares, em `backend/agente/medicao.py`, com teste em `tests/agente/test_medicao.py`
- [ ] T071 [US6] F1: levar o limiar certificado da prova até `classificar_destino`, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T072 [US6] F1 **Bloqueada por FR-D043**: aplicar o que vale até a meta estar comprovada, em `backend/agente/fluxo.py`, com teste em `tests/agente/test_fluxo.py`
- [ ] T073 [US6] F4: montar em `avaliacoes/` o gabarito humano às cegas das cinco saídas, com casos sintéticos e a amostra da spec

**Ponto de controle**: o relatório diz se a meta foi comprovada, com casos, erros e intervalo.

---

## Fase 9: Fechamento

- [ ] T074 F1: ensaiar uma vaga simulada pelas cinco saídas e pela API, com teste em `tests/agente/test_jornada_pre_triagem.py`
- [ ] T075 F1: rodar `pytest`, `ruff check .` e a medição, e registrar o resultado em `specs/003-decisao-pre-triagem-feedback/tasks.md`
- [ ] T076 F1: rever os itens "Decidido" e "Proposta" de `specs/003-decisao-pre-triagem-feedback/spec.md` e marcar as tarefas concluídas

---

## Dependências e ordem

### Entre fases

- **Fase 1:** T001 vem antes dos PRs que precisam dos contratos na `main`. T002 e T003 não bloqueiam a demonstração, mas D-1 fica em conflito com a constituição até serem feitas.
- **Fase 2:** T007 e T008 bloqueiam as partes persistentes de US3 e US4.
- **História 1:** bloqueia a ligação das demais.
- **Histórias 2 e 6:** dependem só da História 1 e podem seguir em paralelo.
- **Histórias 3, 4 e 5:** dependem da História 1 e do canal da Frente 3. T037 e T038 vêm antes de T040 e T041.

### Dentro das histórias

- Teste falhando antes do código.
- T042 antes de T043. T015 antes de T016 a T021.

### Paralelo

```bash
# História 2, depois de T026:
Tarefa: "T027 pontos a explorar na API"
Tarefa: "T028 insights na API"

# Entre frentes, depois de T037:
Tarefa: "T038 F3: adaptar a T3.9"
Tarefa: "T042 F2: reidentificar os campos novos"
```

## Estratégia

### MVP

1. T001.
2. História 1 ligada ao fluxo: T015 a T022.
3. História 2 na API: T026 a T029.
4. Validar e demonstrar com selo "não calibrado".

### Depois

1. História 3, com T037, T038 e T042 primeiro.
2. Histórias 4 e 5.
3. História 6, em paralelo desde o início, se houver quem rotule.

### Se faltar tempo

Valem os cortes de `AGENTS.md`. Dentro desta feature, sugere-se manter a História 1, a História 2 e a jornada simulada da História 3 com o canal simulado. A meta deve ser apresentada como não comprovada.
