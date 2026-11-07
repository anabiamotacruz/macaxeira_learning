# Tarefas: agente recrutador conectado à Nara

Contratos e estrutura estão em `plan.md`. **`[P]`** indica tarefa que pode rodar em paralelo. Cada tarefa segue o ciclo: teste falhando, implementação mínima, verificação e commit.

**Verificação padrão:** `pytest <arquivo-do-teste> -v` e `ruff check .`.

## Fase 0: em conjunto (sábado, das 10h às 11h)

### T0: contratos e base do projeto

**Arquivos:** `pyproject.toml`, `backend/contratos/modelos.py`, `backend/contratos/interfaces.py`, `backend/contratos/erros.py`, `tests/contratos/test_modelos.py`, `.env.example`.

**Produz:** os contratos de `plan.md`.

- [ ] Escrever `test_candidato_tem_empresa_e_validade_de_autorizacao`, `test_vaga_nao_aprovada_por_padrao`, `test_pacote_exige_chave_idempotencia` e `test_convite_identifica_simulacao`.
- [ ] Criar `pyproject.toml` com fastapi, uvicorn, pydantic, openai, langfuse, pandas, pytest e ruff, e o marcador `eval`.
- [ ] Implementar modelos, interfaces e erros de `plan.md`.
- [ ] Criar `.env.example` só com nomes de variáveis.
- [ ] Rodar a verificação, abrir PR e levar à `main`. As frentes começam depois disso.

## Frente 1: agente

### T1.1 [P]: regras determinísticas

**Arquivo:** `backend/agente/regras.py`. **Teste:** `tests/agente/test_regras.py`.

**Produz:** `validar_criterios(vaga: Vaga) -> list[str]`, `verificar_requisitos(vaga: Vaga, candidato: Candidato) -> dict[str, bool]`, `pode_contatar(candidato: Candidato, tentativas: int, vaga: Vaga) -> bool`, `decidir(vaga: Vaga, candidato: Candidato, analise: Analise, rastro_id: str) -> Decisao`.

- [ ] Testar `test_recusa_criterio_sensivel` para gênero, idade, raça, religião e estado civil.
- [ ] Testar `test_descarta_sem_requisito_eliminatorio`, com `Decisao.regra` preenchida.
- [ ] Testar `test_nao_contata_opt_out_nem_sem_autorizacao`.
- [ ] Testar `test_pede_humano_com_ressalva_do_revisor` e `test_nao_indica_sem_evidencia`.
- [ ] Implementar e verificar.

### T1.2: máquina de estados

**Arquivo:** `backend/agente/fluxo.py`. **Teste:** `tests/agente/test_fluxo.py`.

**Consome:** interfaces, regras. **Produz:** `class FluxoVaga` com `iniciar()`, `aprovar_vaga()`, `aprovar_lote()`, `registrar_resposta(resposta: RespostaCandidato)`, `retomar()`, `estado` e `eventos: list[EventoFluxo]`.

- [ ] Testar `test_fluxo_completo_com_simulacoes`, de `RASCUNHO` a `CONCLUIDA`.
- [ ] Testar `test_nao_busca_sem_aprovacao` e `test_nao_convida_sem_aprovar_lote`.
- [ ] Testar `test_fonte_indisponivel_segue_e_registra_cobertura_parcial`.
- [ ] Testar `test_estado_salvo_permite_retomar` e `test_meta_em_risco_avisa_recrutador`.
- [ ] Implementar, salvando o estado após cada etapa, e verificar.

### T1.3 [P]: cliente de modelos e rastro

**Arquivo:** `backend/modelos/cliente.py`. **Teste:** `tests/modelos/test_cliente.py`.

**Produz:** implementação de `ClienteModelo`, com `custo_total_usd`, leitura de chave do ambiente e rastro no Langfuse.

- [ ] Testar `test_resposta_invalida_tenta_corrigir_e_falha_com_erro_claro`.
- [ ] Testar `test_modelo_indisponivel_usa_alternativa`.
- [ ] Testar `test_limite_de_gasto_gera_erro_e_fluxo_pausa_com_estado_salvo`, junto com `FluxoVaga`.
- [ ] Testar `test_registra_tokens_custo_e_tempo_por_etapa`.
- [ ] Implementar com a API compatível com a OpenAI e verificar.

### T1.4: API

**Arquivo:** `backend/agente/api.py`. **Teste:** `tests/agente/test_api.py`.

**Produz:** `POST /vagas`, `POST /vagas/{id}/aprovar`, `POST /vagas/{id}/lote/aprovar`, `POST /convites/{id}/resposta`, `GET /vagas/{id}`, `GET /vagas/{id}/candidatos`, `GET /vagas/{id}/eventos`, `GET /candidatos/{id}/decisao`, `POST /sessoes/reiniciar`.

- [ ] Testar criação, aprovação, consulta de explicações e reinício de sessão.
- [ ] Testar `test_respostas_identificam_simulacao`.
- [ ] Implementar e verificar.

### T1.5: aprendizado

**Arquivo:** `backend/agente/aprendizado.py`. **Teste:** `tests/agente/test_aprendizado.py`.

**Produz:** `propor_ajuste(vaga: Vaga, resultados: list[ResultadoNara]) -> PropostaAjuste | None`, `aplicar(proposta)` e `reverter(proposta)`.

- [ ] Testar `test_detecta_criterio_com_reprovacao_repetida`.
- [ ] Testar `test_nao_aplica_sem_aprovacao`, `test_permite_reverter` e `test_nao_propoe_criterio_sensivel`.
- [ ] Implementar e verificar.

### T1.7: rotina do banco

**Arquivo:** `backend/agente/rotina_banco.py`. **Teste:** `tests/agente/test_rotina_banco.py`.

**Consome:** `BancoTalentos`, regras. **Produz:** `selecionar_para_contato(empresa_id: str, hoje: date) -> list[Candidato]` e `processar_vencidos(empresa_id: str, hoje: date) -> list[Decisao]`.

- [ ] Testar `test_seleciona_perfis_desatualizados_dentro_do_limite`.
- [ ] Testar `test_nao_contata_quem_saiu_ou_foi_removido`.
- [ ] Testar `test_autorizacao_vencida_sai_da_busca`, com decisão registrada.
- [ ] Implementar e verificar.

### T1.6 (opcional): adaptador MCP

**Arquivo:** `backend/agente/mcp.py`. Expor `buscar_candidatos`, `explicar_escolha` e `entregar_a_nara` sobre as mesmas funções. Só começar com o fluxo principal integrado.

## Frente 2: fontes e dados

### T2.1 [P]: dados sintéticos

**Arquivos:** `dados/gerador.py`, `dados/sinteticos/`. **Teste:** `tests/dados/test_gerador.py`.

**Produz:** `gerar(semente: int, quantidade: int) -> list[Candidato]`, cerca de 200 perfis, pelo menos 3 vagas de tech e `respostas_certas.json` separado.

- [ ] Testar `test_geracao_reproduzivel_com_mesma_semente`.
- [ ] Testar `test_todos_os_perfis_sao_simulados`.
- [ ] Testar `test_contem_armadilhas`: cargo incomum, currículo forte sem requisito, exagero, instrução no currículo e opt-out.
- [ ] Testar `test_contem_sujeira`: sinônimos, erros, duplicatas, dados faltantes, autorizações vencidas e perfis desatualizados.
- [ ] Testar `test_gera_duas_empresas_separadas`.
- [ ] Implementar e verificar.

### T2.6 [P]: banco de talentos

**Arquivo:** `backend/fontes/banco_talentos.py`. **Teste:** `tests/fontes/test_banco_talentos.py`.

**Produz:** implementação de `BancoTalentos`.

- [ ] Testar `test_importa_base_e_remove_duplicatas`, com a origem registrada.
- [ ] Testar `test_empresas_nao_veem_dados_uma_da_outra`.
- [ ] Testar `test_busca_ignora_quem_nao_tem_autorizacao_valida`.
- [ ] Testar `test_remover_apaga_dados_e_impede_novo_contato`.
- [ ] Implementar e verificar.

### T2.2 [P]: rede de talentos simulada

**Arquivo:** `backend/fontes/rede_simulada.py`. **Teste:** `tests/fontes/test_rede_simulada.py`.

**Produz:** implementação de `FonteCandidatos`, `remover_duplicatas(candidatos) -> list[Candidato]` e controles para injetar falha e limite.

- [ ] Testar paginação, filtros e `test_identifica_fonte_como_simulada`.
- [ ] Testar `test_remove_duplicata_entre_paginas_e_fontes`.
- [ ] Testar `test_injeta_falha_com_fonte_indisponivel`.
- [ ] Implementar e verificar.

### T2.3: analisador

**Arquivo:** `backend/fontes/analisador.py`. **Teste:** `tests/fontes/test_analisador.py`.

**Consome:** `ClienteModelo`, regras. **Produz:** implementação de `Analisador`.

- [ ] Com o modelo simulado, testar `test_evidencias_citam_trecho_do_perfil`.
- [ ] Testar `test_remove_afirmacao_sem_trecho`.
- [ ] Testar `test_instrucao_no_curriculo_vira_alerta`, sem alterar a nota.
- [ ] Testar `test_lacuna_nao_reduz_nota_sozinha`.
- [ ] Implementar e verificar.

### T2.4: revisor independente

**Arquivo:** `backend/fontes/revisor.py`. **Teste:** `tests/fontes/test_revisor.py`.

**Produz:** implementação de `Revisor`, em uma chamada separada, sem receber a justificativa do analisador como verdade.

- [ ] Testar `test_aponta_exagero_sem_evidencia`, `test_nao_inventa_problema_em_caso_solido` e `test_resposta_invalida_pede_humano`.
- [ ] Implementar e verificar.

### T2.5 (opcional): GitHub com contas de teste

**Arquivo:** `backend/fontes/github_teste.py`. Usar a API oficial, limitada a uma lista explícita de contas de teste do time. Testar `test_recusa_conta_fora_da_lista`.

## Frente 3: contato e Nara

### T3.1 [P]: convite e mensageiro simulado

**Arquivo:** `backend/contato/mensageiro.py`. **Teste:** `tests/contato/test_mensageiro.py`.

**Produz:** implementação de `Mensageiro` e `criar_convite(vaga, candidato, analise, link_nara, cliente_modelo) -> Convite`.

- [ ] Testar `test_convite_contem_vaga_e_link_da_nara`.
- [ ] Testar `test_reenvio_com_mesma_chave_nao_duplica`.
- [ ] Testar `test_falha_de_envio_permite_repetir`.
- [ ] Implementar e verificar.

### T3.2 [P]: conversa com o candidato

**Arquivo:** `backend/contato/conversa.py`. **Teste:** `tests/contato/test_conversa.py`.

**Produz:** `classificar_resposta(texto: str, cliente_modelo) -> RespostaCandidato` e `responder_duvida(vaga, texto, cliente_modelo) -> str | None`.

- [ ] Testar aceite, recusa, dúvida e silêncio.
- [ ] Testar `test_opt_out_tem_prioridade_e_bloqueia_novo_contato`.
- [ ] Testar `test_duvida_fora_do_material_vai_para_humano`.
- [ ] Testar `test_instrucao_na_mensagem_nao_altera_regras`.
- [ ] Implementar e verificar.

### T3.4 [P]: autorização e atualização por conversa

**Arquivo:** `backend/contato/cadastro.py`. **Teste:** `tests/contato/test_cadastro.py`.

**Consome:** `BancoTalentos`, `Mensageiro`, `ClienteModelo`. **Produz:** `pedir_autorizacao(candidato) -> Convite`, `tratar_resposta_cadastro(candidato, texto: str) -> Candidato` e `extrair_atualizacao(texto: str, cliente_modelo) -> dict[str, str]`.

- [ ] Testar `test_sem_autorizacao_nao_faz_perguntas_do_perfil`.
- [ ] Testar `test_autorizacao_registra_validade`.
- [ ] Testar `test_atualizacao_altera_perfil_e_data`.
- [ ] Testar `test_pedido_de_saida_remove_do_banco`.
- [ ] Testar `test_texto_com_instrucao_nao_altera_regras`.
- [ ] Implementar e verificar.

### T3.3 [P]: pacote e Nara simulada

**Arquivos:** `backend/contato/pacote.py`, `backend/nara_simulada/servico.py`. **Teste:** `tests/contato/test_pacote.py`, `tests/nara_simulada/test_servico.py`.

**Produz:** `montar_pacote(vaga, candidato, analise, decisao) -> PacoteNara` e implementação de `ClienteNara`.

- [ ] Testar `test_pacote_tem_todos_os_campos_decididos`.
- [ ] Testar `test_link_e_resultado_identificam_simulacao`.
- [ ] Testar `test_entrega_repetida_nao_duplica`.
- [ ] Testar `test_resultados_reproduziveis_alimentam_aprendizado`.
- [ ] Implementar e verificar.

## Frente 4: produto e qualidade

### T4.1 [P]: painel

**Arquivos:** `web/app/`. **Teste:** `web` com testes da interface principal.

**Consome:** API de T1.4; começa com dados simulados locais.

- [ ] Criar a tela do banco, com importação, estados, autorizações e cadastro do candidato fictício.
- [ ] Criar a tela de vaga, com criação, aprovação e meta.
- [ ] Criar a tela de candidatos, com explicação, evidências, lacunas e decisão.
- [ ] Mostrar eventos em tempo real, aprovação de lote e resposta do jurado como candidato.
- [ ] Mostrar custo, métricas, rastro e o selo "Simulado".
- [ ] Verificar no navegador o fluxo principal e o estado de erro.

### T4.2 [P]: avaliações

**Arquivos:** `avaliacoes/casos/`, `avaliacoes/test_avaliacoes.py`, `avaliacoes/relatorio.py`.

**Produz:** `pytest avaliacoes -m eval` e um relatório JSON para o painel.

- [ ] Criar `test_zero_violacoes_de_requisito` e `test_zero_contato_com_opt_out`.
- [ ] Criar `test_zero_vazamento_entre_empresas` e `test_zero_busca_sem_autorizacao`.
- [ ] Criar `test_troca_de_nome_e_genero_nao_muda_resultado`.
- [ ] Criar `test_armadilhas_tratadas` e `test_precisao_top_5`.
- [ ] Criar `test_conclui_ou_pausa_com_falhas_injetadas`.
- [ ] Gerar o relatório e verificar.

### T4.3: deploy e link testável

- [ ] Publicar API e painel em um link público, até sábado às 17h.
- [ ] Configurar segredos no provedor e limite de gasto por sessão.
- [ ] Verificar o link em uma aba anônima, com dados reiniciados.

### T4.4: demo e submissão

**Arquivos:** `docs/pitch/`.

- [ ] Roteiro de 3 minutos, conforme a seção 13 do design.
- [ ] Gravar uma execução de reserva, identificada como gravação.
- [ ] Preparar descrição, vídeo, material de apresentação e lista de ferramentas, modelos e APIs.
- [ ] Sinalizar que o projeto responde ao Desafio Tako.
- [ ] Revisar se todo número tem fonte e toda simulação está identificada.
- [ ] Enviar até domingo às 12h30, com margem para o prazo das 13h.

## Dependências

- T0 antes de tudo.
- T1.1, T1.3, T2.1, T2.2, T2.6, T3.1, T3.2, T3.3, T3.4, T4.1 e T4.2 podem rodar em paralelo depois de T0.
- T1.2 depende só dos contratos e usa simulações até as demais chegarem.
- T2.3 e T2.4 usam um `ClienteModelo` simulado até T1.3 chegar.
- T1.5 depende de `ClienteNara.resultados`, com simulação disponível desde T0.
- T1.7 usa um `BancoTalentos` simulado até T2.6 chegar.
- T4.3 e a parte final de T4.4 dependem da integração.

## Cobertura da spec

| Requisitos | Tarefas |
|---|---|
| FR-001, FR-002 | T1.1, T1.2, T4.1 |
| FR-003, FR-012 | T2.2, T1.2 |
| FR-004 | T1.1 |
| FR-005 | T2.3, T3.3 |
| FR-006 | T2.4 |
| FR-007, FR-011 | T1.2 |
| FR-008, FR-009 | T3.1, T3.2 |
| FR-010 | T3.3 |
| FR-013, FR-017 | T1.3, T4.1 |
| FR-014 | T1.1, T1.2, T1.4 |
| FR-015 | T2.2, T3.1, T3.3, T1.4, T4.1 |
| FR-016 | T1.5 |
| FR-018, FR-019, FR-021, FR-023, FR-024 | T2.6, T1.2, T1.7 |
| FR-020, FR-022 | T3.4 |
