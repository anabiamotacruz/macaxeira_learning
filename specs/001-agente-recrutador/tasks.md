# Tarefas: agente recrutador conectado à Nara

Contratos e estrutura estão em `plan.md`. Ondas: **1** até sábado às 13h, **2** até sábado às 17h, **3** até domingo às 11h. O marcador **(corte)** indica o que pode sair se faltar tempo. **`[P]`** indica tarefa que pode rodar em paralelo. Cada tarefa segue o ciclo: teste falhando, implementação mínima, verificação e commit.

**Verificação padrão:** `pytest <arquivo-do-teste> -v` e `ruff check .`.

## Resumo por frente e onda

| Frente | Onda 1 | Onda 2 | Onda 3 |
| --- | --- | --- | --- |
| **1. Agente** | T1.1, T1.2, T1.3, T1.8, T1.9 | T1.4, T1.7, T1.10, T1.11, T1.12 | T1.5, T1.6, T1.13 |
| **2. Fontes e dados** | T2.1, T2.6, T2.7, T2.8 | T2.2, T2.3, T2.4, T2.9 | T2.5 |
| **3. Contato e Nara** | T3.1, T3.2, T3.3, T3.4 | T3.5, T3.6 | Ajustes da integração |
| **4. Produto e qualidade** | T4.1, T4.2 | T4.3, T4.5, T4.6 | T4.4 |

## Fase 0: em conjunto (sábado, das 10h às 11h)

### T0: contratos e base do projeto

**Arquivos:** `pyproject.toml`, `backend/contratos/modelos.py`, `backend/contratos/interfaces.py`, `backend/contratos/erros.py`, `backend/contratos/simulacoes.py`, `tests/contratos/test_modelos.py`, `tests/contratos/test_simulacoes.py`, `.env.example`, `.github/workflows/ci.yml`.

**Produz:** os contratos de `plan.md`.

- [ ] Escrever `test_candidato_tem_empresa_e_validade_de_autorizacao`, `test_vaga_nao_aprovada_por_padrao`, `test_pacote_exige_chave_idempotencia` e `test_convite_identifica_simulacao`.
- [ ] Criar `pyproject.toml` com fastapi, uvicorn, pydantic, openai, langfuse, pandas, pytest e ruff, e o marcador `eval`.
- [ ] Implementar modelos, interfaces e erros de `plan.md`.
- [ ] Testar `test_busca_exige_empresa_id` e `test_simulacoes_seguem_as_interfaces`.
- [ ] Implementar simulações de todas as interfaces em `simulacoes.py`.
- [ ] Criar `.env.example` só com nomes de variáveis.
- [ ] Criar CI que rode `ruff check .` e `pytest` em todo pull request, sem chaves.
- [ ] Rodar a verificação, abrir PR e levar à `main`. As frentes começam depois disso.

## Frente 1: agente

### T1.1 [P] (onda 1): regras determinísticas

**Arquivo:** `backend/agente/regras.py`. **Teste:** `tests/agente/test_regras.py`.

**Produz:** `validar_criterios(vaga: Vaga) -> list[str]`, `verificar_requisitos(vaga: Vaga, candidato: Candidato) -> dict[str, bool]`, `pode_contatar(candidato: Candidato, tentativas: int, vaga: Vaga) -> bool`, `decidir(vaga: Vaga, candidato: Candidato, analise: Analise, rastro_id: str) -> Decisao`.

- [ ] Testar `test_recusa_criterio_sensivel` para gênero, idade, raça, religião e estado civil.
- [ ] Testar `test_descarta_sem_requisito_eliminatorio`, com `Decisao.regra` preenchida.
- [ ] Testar `test_nao_contata_opt_out_nem_sem_autorizacao`.
- [ ] Testar `test_pede_humano_com_ressalva_do_revisor` e `test_nao_indica_sem_evidencia`.
- [ ] Implementar e verificar.

### T1.2 (onda 1): máquina de estados

**Arquivo:** `backend/agente/fluxo.py`. **Teste:** `tests/agente/test_fluxo.py`.

**Consome:** interfaces, regras. **Produz:** `class FluxoVaga` com `iniciar()`, `aprovar_vaga()`, `aprovar_lote()`, `registrar_resposta(resposta: RespostaCandidato)`, `retomar()`, `estado` e `eventos: list[EventoFluxo]`.

- [ ] Testar `test_fluxo_completo_com_simulacoes`, de `RASCUNHO` a `CONCLUIDA`.
- [ ] Testar `test_nao_busca_sem_aprovacao` e `test_nao_convida_sem_aprovar_lote`.
- [ ] Testar `test_fonte_indisponivel_segue_e_registra_cobertura_parcial`.
- [ ] Testar `test_estado_salvo_permite_retomar` e `test_meta_em_risco_avisa_recrutador`.
- [ ] Implementar, salvando o estado após cada etapa, e verificar.

### T1.3 [P] (onda 1): cliente de modelos e rastro

**Arquivo:** `backend/modelos/cliente.py`. **Teste:** `tests/modelos/test_cliente.py`.

**Produz:** implementação de `ClienteModelo`, com `custo_total_usd`, leitura de chave do ambiente e rastro no Langfuse.

- [ ] Testar `test_resposta_invalida_tenta_corrigir_e_falha_com_erro_claro`.
- [ ] Testar `test_modelo_indisponivel_usa_alternativa`.
- [ ] Testar `test_limite_de_gasto_gera_erro_e_fluxo_pausa_com_estado_salvo`, junto com `FluxoVaga`.
- [ ] Testar `test_registra_tokens_custo_e_tempo_por_etapa`.
- [ ] Implementar com a API compatível com a OpenAI e verificar.

### T1.4 (onda 2): API

**Arquivo:** `backend/agente/api.py`. **Teste:** `tests/agente/test_api.py`.

**Produz:** `POST /vagas`, `POST /vagas/{id}/aprovar`, `POST /vagas/{id}/lote/aprovar`, `POST /convites/{id}/resposta`, `GET /vagas/{id}`, `GET /vagas/{id}/candidatos`, `GET /vagas/{id}/eventos`, `GET /candidatos/{id}/decisao`, `POST /sessoes/reiniciar`.

- [ ] Testar criação, aprovação, consulta de explicações e reinício de sessão.
- [ ] Testar `test_respostas_identificam_simulacao`.
- [ ] Implementar e verificar.

### T1.5 (onda 3, corte): aprendizado

**Arquivo:** `backend/agente/aprendizado.py`. **Teste:** `tests/agente/test_aprendizado.py`.

**Produz:** `propor_ajuste(vaga: Vaga, resultados: list[ResultadoNara]) -> PropostaAjuste | None`, `aplicar(proposta)` e `reverter(proposta)`.

- [ ] Testar `test_detecta_criterio_com_reprovacao_repetida`.
- [ ] Testar `test_nao_aplica_sem_aprovacao`, `test_permite_reverter` e `test_nao_propoe_criterio_sensivel`.
- [ ] Implementar e verificar.

### T1.8 [P] (onda 1): persistência e retomada

**Arquivo:** `backend/agente/persistencia.py`. **Teste:** `tests/agente/test_persistencia.py`.

**Produz:** `Repositorio` com `salvar_estado`, `carregar_estado`, `registrar_evento`, `listar_eventos`, `registrar_chave` e `chave_ja_usada`, em SQLite.

- [ ] Testar `test_estado_sobrevive_a_reinicio`.
- [ ] Testar `test_chave_repetida_nao_duplica_acao`.
- [ ] Testar `test_empresa_so_le_os_proprios_dados`.
- [ ] Implementar e verificar.

### T1.9 [P] (onda 1): proposta de configuração da vaga

**Arquivo:** `backend/agente/configuracao.py`. **Teste:** `tests/agente/test_configuracao.py`.

**Produz:** `propor_configuracao(descricao: str, empresa_id: str, cliente_modelo) -> Vaga | PerguntaVaga`, com `aprovada=False`.

- [ ] Testar `test_propoe_requisitos_competencias_e_meta`.
- [ ] Testar `test_vaga_ambigua_devolve_pergunta`.
- [ ] Testar `test_proposta_passa_por_validar_criterios`.
- [ ] Testar `test_descricao_com_instrucao_nao_altera_regras`.
- [ ] Implementar e verificar.

### T1.10 [P] (onda 2): resiliência

**Arquivo:** `backend/modelos/resiliencia.py`. **Teste:** `tests/modelos/test_resiliencia.py`.

**Produz:** `com_tentativas(funcao, tentativas: int, espera: float, tempo_limite: float)` e `DisjuntorFonte`, para parar temporariamente uma fonte com falhas seguidas.

- [ ] Testar `test_repete_erro_temporario_com_espera`.
- [ ] Testar `test_nao_repete_erro_permanente`.
- [ ] Testar `test_tempo_limite_gera_erro_claro`.
- [ ] Testar `test_disjuntor_abre_e_fecha`.
- [ ] Implementar e aplicar nas chamadas de modelo e fontes.

### T1.11 (onda 2): auditoria

**Arquivo:** `backend/agente/auditoria.py`. **Teste:** `tests/agente/test_auditoria.py`.

**Produz:** `registrar_decisao(decisao: Decisao)`, `explicar_candidato(empresa_id: str, candidato_id: str, vaga_id: str) -> dict` e `@rastreado(etapa: str)`, para chamadas de modelo e ferramentas.

- [ ] Testar `test_toda_decisao_tem_entrada_regra_evidencias_e_responsavel`.
- [ ] Testar `test_explicacao_liga_decisao_eventos_e_rastro`.
- [ ] Testar `test_rastro_nao_contem_chave`.
- [ ] Implementar e verificar.

### T1.7 (onda 2): rotina do banco

**Arquivo:** `backend/agente/rotina_banco.py`. **Teste:** `tests/agente/test_rotina_banco.py`.

**Consome:** `BancoTalentos`, regras. **Produz:** `selecionar_para_contato(empresa_id: str, hoje: date) -> list[Candidato]` e `processar_vencidos(empresa_id: str, hoje: date) -> list[Decisao]`.

- [ ] Testar `test_seleciona_perfis_desatualizados_dentro_do_limite`.
- [ ] Testar `test_nao_contata_quem_saiu_ou_foi_removido`.
- [ ] Testar `test_autorizacao_vencida_sai_da_busca`, com decisão registrada.
- [ ] Implementar e verificar.

### T1.6 (onda 3, corte): adaptador MCP

**Arquivo:** `backend/agente/mcp.py`. Expor `buscar_candidatos`, `explicar_escolha` e `entregar_a_nara` sobre as mesmas funções. Só começar com o fluxo principal integrado.

### T1.12 (onda 2): conector MCP para agentes recrutadores

**Arquivo:** `backend/agente/conector_mcp.py`. **Teste:** `tests/agente/test_conector_mcp.py`, com um servidor MCP local e sintético, criado só para o teste.

**Consome:** `AgenteRecrutador`, `PacoteContexto`, `ResultadoEntrevista`. **Produz:** `ConectorMCP`, implementação de `AgenteRecrutador` que chama as ferramentas de um servidor MCP configurado. A Nara é a primeira integração e continua simulada e identificada até haver acesso real.

Esta tarefa é da Frente 1 e substitui a T3.8 proposta na spec da Frente 3. Não se confunde com a T1.6: aqui o agente chama outro agente recrutador; lá, outros clientes chamam as ferramentas do agente.

- [ ] Confirmar a biblioteca MCP na documentação oficial e justificar a dependência no PR.
- [ ] Testar `test_conector_segue_a_interface`.
- [ ] Testar `test_ferramentas_vem_da_configuracao_do_destino`, sem nome de ferramenta fixo no código.
- [ ] Testar `test_entrega_repetida_nao_duplica`, enviando `chave_idempotencia`.
- [ ] Testar `test_servidor_fora_do_ar_deixa_entrega_pendente` e `test_tempo_limite_gera_erro_claro`.
- [ ] Testar `test_resposta_invalida_nao_conta_como_entrega` e `test_resposta_do_servidor_e_tratada_como_dado`.
- [ ] Testar `test_destino_sem_agenda_nem_resultado`.
- [ ] Testar `test_empresa_de_outro_escopo_e_recusada` e `test_simulacao_e_identificada`.
- [ ] Implementar, com rastro em cada chamada, e verificar.

### T1.13 (onda 3): avaliação pela pessoa de RH

**Arquivo:** `backend/agente/avaliacao_rh.py`. **Teste:** `tests/agente/test_avaliacao_rh.py`.

**Consome:** casos sintéticos da Frente 2. **Produz:** `gerar_fichas(casos, semente) -> list[Ficha]`, `importar_avaliacoes(respostas) -> list[AvaliacaoHumana]` e `medir_concordancia(avaliacoes, gabarito) -> dict[str, float]`.

A pessoa de RH avalia às cegas cerca de 34 fichas sintéticas, com 12 de ajuste, 18 de prova e 4 duplicatas, em cerca de 1h15 a 1h50. O resultado valida o gabarito e calibra o agente, mas não prova desempenho com pessoas reais.

- [ ] Combinar data e horário com a pessoa de RH.
- [ ] Testar `test_ficha_nao_mostra_gabarito_nem_resposta_do_agente`.
- [ ] Testar `test_selecao_e_reproduzivel_e_respeita_as_particoes`.
- [ ] Testar `test_importacao_guarda_decisao_e_motivo` e `test_resposta_incompleta_e_recusada`.
- [ ] Testar `test_mede_concordancia_por_tipo_de_caso` e `test_duplicatas_medem_consistencia`.
- [ ] Implementar e verificar.
- [ ] Aplicar a avaliação e, se houver muita discordância, corrigir o gerador antes de usar as taxas de erro.
- [ ] Registrar o resultado no relatório, sem dados reais e com os limites da medição.

## Frente 2: fontes e dados

### T2.1 [P] (onda 1): dados sintéticos

**Arquivos:** `dados/gerador.py`, `dados/sinteticos/`. **Teste:** `tests/dados/test_gerador.py`.

**Produz:** `gerar(semente: int, quantidade: int) -> list[Candidato]`, cerca de 200 perfis, pelo menos 3 vagas de tech e `respostas_certas.json` separado.

- [x] Testar `test_geracao_reproduzivel_com_mesma_semente`.
- [x] Testar `test_todos_os_perfis_sao_simulados`.
- [x] Testar `test_contem_armadilhas`: cargo incomum, currículo forte sem requisito, exagero, instrução no currículo e opt-out.
- [x] Testar `test_contem_sujeira`: sinônimos, erros, duplicatas, dados faltantes, autorizações vencidas e perfis desatualizados.
- [x] Testar `test_gera_duas_empresas_separadas`.
- [x] Implementar e verificar.

### T2.6 [P] (onda 1): banco de talentos

**Arquivo:** `backend/fontes/banco_talentos.py`. **Teste:** `tests/fontes/test_banco_talentos.py`.

**Produz:** implementação de `BancoTalentos`.

- [ ] Testar `test_importa_base_e_remove_duplicatas`, com a origem registrada.
- [ ] Testar `test_empresas_nao_veem_dados_uma_da_outra`.
- [ ] Testar `test_busca_ignora_quem_nao_tem_autorizacao_valida`.
- [ ] Testar `test_remover_apaga_dados_e_impede_novo_contato`.
- [ ] Implementar e verificar.

### T2.2 [P] (onda 2): rede de talentos simulada

**Arquivo:** `backend/fontes/rede_simulada.py`. **Teste:** `tests/fontes/test_rede_simulada.py`.

**Produz:** implementação de `FonteCandidatos`, `remover_duplicatas(candidatos) -> list[Candidato]` e controles para injetar falha e limite.

- [ ] Testar paginação, filtros e `test_identifica_fonte_como_simulada`.
- [ ] Testar `test_remove_duplicata_entre_paginas_e_fontes`.
- [ ] Testar `test_injeta_falha_com_fonte_indisponivel`.
- [ ] Implementar e verificar.

### T2.7 [P] (onda 1): geração de consultas

**Arquivo:** `backend/fontes/consultas.py`. **Teste:** `tests/fontes/test_consultas.py`.

**Produz:** `gerar_consultas(vaga: Vaga, cliente_modelo) -> list[str]` e `ampliar_consultas(vaga: Vaga, anteriores: list[str], cliente_modelo) -> list[str]`.

- [x] Testar `test_inclui_sinonimos_de_cargo`.
- [x] Testar `test_nao_usa_criterio_sensivel`.
- [x] Testar `test_ampliacao_nao_remove_requisito_eliminatorio`.
- [x] Testar `test_resposta_invalida_usa_consulta_basica`.
- [x] Implementar e verificar.

### T2.8 [P] (onda 1): funil e cache

**Arquivo:** `backend/fontes/funil.py`. **Teste:** `tests/fontes/test_funil.py`.

**Produz:** `priorizar(vaga: Vaga, candidatos: list[Candidato], limite: int = 20) -> list[Candidato]` e `CacheAnalise`, com chave por vaga, perfil e versão da configuração.

- [ ] Testar `test_ordem_reproduzivel`.
- [ ] Testar `test_exclui_sem_autorizacao_ou_requisito`.
- [ ] Testar `test_ordem_nao_muda_com_nome_ou_genero`.
- [ ] Testar `test_cache_evita_nova_analise_e_expira_ao_mudar_vaga`.
- [ ] Implementar e verificar.

### T2.3 (onda 2): analisador

**Arquivo:** `backend/fontes/analisador.py`. **Teste:** `tests/fontes/test_analisador.py`.

**Consome:** `ClienteModelo`, regras. **Produz:** implementação de `Analisador`.

- [ ] Com o modelo simulado, testar `test_evidencias_citam_trecho_do_perfil`.
- [ ] Testar `test_remove_afirmacao_sem_trecho`.
- [ ] Testar `test_instrucao_no_curriculo_vira_alerta`, sem alterar a nota.
- [ ] Testar `test_lacuna_nao_reduz_nota_sozinha`.
- [ ] Implementar e verificar.

### T2.4 (onda 2): revisor independente

**Arquivo:** `backend/fontes/revisor.py`. **Teste:** `tests/fontes/test_revisor.py`.

**Produz:** implementação de `Revisor`, em uma chamada separada, sem receber a justificativa do analisador como verdade.

- [ ] Testar `test_aponta_exagero_sem_evidencia`, `test_nao_inventa_problema_em_caso_solido` e `test_resposta_invalida_pede_humano`.
- [ ] Implementar e verificar.

### T2.9 (onda 2): documentos enviados pela pessoa

**Arquivo:** `backend/fontes/documentos.py`. **Teste:** `tests/fontes/test_documentos.py`.

**Produz:** `ler_documento(nome: str, conteudo: bytes) -> str`, para texto e PDF, e `extrair_perfil(texto: str, cliente_modelo) -> dict[str, str]`.

- [ ] Testar `test_recusa_tipo_nao_permitido_e_arquivo_grande`, com limite de 5 MB.
- [ ] Testar `test_pdf_sem_texto_gera_pedido_de_novo_envio`.
- [ ] Testar `test_instrucao_no_documento_vira_alerta`.
- [ ] Testar `test_extracao_nao_inventa_experiencia`.
- [ ] Implementar e verificar.

### T2.5 (onda 3, corte): GitHub com contas de teste

**Arquivo:** `backend/fontes/github_teste.py`. Usar a API oficial, limitada a uma lista explícita de contas de teste do time. Testar `test_recusa_conta_fora_da_lista`.

## Frente 3: contato e Nara

### T3.1 [P] (onda 1): convite e mensageiro simulado

**Arquivo:** `backend/contato/mensageiro.py`. **Teste:** `tests/contato/test_mensageiro.py`.

**Produz:** implementação de `Mensageiro` e `criar_convite(vaga, candidato, analise, link_nara, cliente_modelo) -> Convite`.

- [ ] Testar `test_convite_contem_vaga_e_link_da_nara`.
- [ ] Testar `test_reenvio_com_mesma_chave_nao_duplica`.
- [ ] Testar `test_falha_de_envio_permite_repetir`.
- [ ] Implementar e verificar.

### T3.2 [P] (onda 1): conversa com o candidato

**Arquivo:** `backend/contato/conversa.py`. **Teste:** `tests/contato/test_conversa.py`.

**Produz:** `classificar_resposta(texto: str, cliente_modelo) -> RespostaCandidato` e `responder_duvida(vaga, texto, cliente_modelo) -> str | None`.

- [ ] Testar aceite, recusa, dúvida e silêncio.
- [ ] Testar `test_opt_out_tem_prioridade_e_bloqueia_novo_contato`.
- [ ] Testar `test_duvida_fora_do_material_vai_para_humano`.
- [ ] Testar `test_instrucao_na_mensagem_nao_altera_regras`.
- [ ] Implementar e verificar.

### T3.4 [P] (onda 1): autorização e atualização por conversa

**Arquivo:** `backend/contato/cadastro.py`. **Teste:** `tests/contato/test_cadastro.py`.

**Consome:** `BancoTalentos`, `Mensageiro`, `ClienteModelo`. **Produz:** `pedir_autorizacao(candidato) -> Convite`, `tratar_resposta_cadastro(candidato, texto: str) -> Candidato` e `extrair_atualizacao(texto: str, cliente_modelo) -> dict[str, str]`.

- [ ] Testar `test_sem_autorizacao_nao_faz_perguntas_do_perfil`.
- [ ] Testar `test_autorizacao_registra_validade`.
- [ ] Testar `test_atualizacao_altera_perfil_e_data`.
- [ ] Testar `test_pedido_de_saida_remove_do_banco`.
- [ ] Testar `test_texto_com_instrucao_nao_altera_regras`.
- [ ] Implementar e verificar.

### T3.3 [P] (onda 1): pacote e Nara simulada

**Arquivos:** `backend/contato/pacote.py`, `backend/nara_simulada/servico.py`. **Teste:** `tests/contato/test_pacote.py`, `tests/nara_simulada/test_servico.py`.

**Produz:** `montar_pacote(vaga, candidato, analise, decisao) -> PacoteNara` e implementação de `ClienteNara`.

- [ ] Testar `test_pacote_tem_todos_os_campos_decididos`.
- [ ] Testar `test_link_e_resultado_identificam_simulacao`.
- [ ] Testar `test_entrega_repetida_nao_duplica`.
- [ ] Testar `test_resultados_reproduziveis_alimentam_aprendizado`.
- [ ] Implementar e verificar.

### T3.5 [P] (onda 2): entrada de novos candidatos

**Arquivo:** `backend/contato/entrada.py`. **Teste:** `tests/contato/test_entrada.py`.

**Produz:** `gerar_link_cadastro(empresa_id: str, origem: str) -> str`, `registrar_cadastro(token: str, dados: dict[str, str], autorizacao: bool) -> Candidato` e `registrar_indicacao(empresa_id: str, indicador: str, contato: str) -> Convite`.

- [ ] Testar `test_link_identifica_empresa_e_origem`.
- [ ] Testar `test_cadastro_sem_autorizacao_nao_entra_no_banco`.
- [ ] Testar `test_indicado_so_recebe_pedido_de_autorizacao`.
- [ ] Testar `test_token_invalido_e_recusado`.
- [ ] Implementar e verificar.

### T3.6 [P] (onda 2): recontato e proposta de valor

**Arquivo:** `backend/contato/recontato.py`. **Teste:** `tests/contato/test_recontato.py`.

**Produz:** `montar_recontato(candidato: Candidato, motivo: str, cliente_modelo) -> Convite` e `pode_recontatar(candidato: Candidato, historico, hoje: date) -> bool`, com no máximo 1 contato a cada 90 dias, por decisão de design.

- [ ] Testar `test_respeita_intervalo_entre_contatos`.
- [ ] Testar `test_mensagem_diz_por_que_contatou_e_como_sair`.
- [ ] Testar `test_nao_recontata_quem_recusou_ou_saiu`.
- [ ] Implementar e verificar.

## Frente 4: produto e qualidade

### T4.1 [P] (onda 1): painel

**Arquivos:** `web/app/`. **Teste:** `web` com testes da interface principal.

**Consome:** API de T1.4; começa com dados simulados locais.

- [ ] Criar a tela do banco, com importação, estados, autorizações e cadastro do candidato fictício.
- [ ] Criar a tela de vaga, com criação, aprovação e meta.
- [ ] Criar a tela de candidatos, com explicação, evidências, lacunas e decisão.
- [ ] Mostrar progresso e resultados parciais durante a execução.
- [ ] Mostrar eventos em tempo real, aprovação de lote e resposta do jurado como candidato.
- [ ] Mostrar custo, métricas, rastro e o selo "Simulado".
- [ ] Verificar no navegador o fluxo principal e o estado de erro.

### T4.2 [P] (onda 1): avaliações

**Arquivos:** `avaliacoes/casos/`, `avaliacoes/test_avaliacoes.py`, `avaliacoes/relatorio.py`.

**Produz:** `pytest avaliacoes -m eval` e um relatório JSON para o painel.

- [ ] Criar `test_zero_violacoes_de_requisito` e `test_zero_contato_com_opt_out`.
- [ ] Criar `test_zero_vazamento_entre_empresas` e `test_zero_busca_sem_autorizacao`.
- [ ] Criar `test_troca_de_nome_e_genero_nao_muda_resultado`.
- [ ] Criar `test_armadilhas_tratadas` e `test_precisao_top_5`.
- [ ] Criar `test_conclui_ou_pausa_com_falhas_injetadas`.
- [ ] Rodar um subconjunto rápido e sem custo de modelo no CI.
- [ ] Gerar o relatório e verificar.

### T4.5 [P] (onda 2): segurança do link público

**Arquivos:** `backend/agente/api.py`, em conjunto com a Frente 1, `tests/agente/test_seguranca_api.py`.

- [ ] Testar `test_sessao_nao_acessa_dados_de_outra_empresa`.
- [ ] Testar `test_limite_de_requisicoes_por_sessao`.
- [ ] Testar `test_erros_nao_expoem_chave_nem_stack_trace`.
- [ ] Testar `test_limite_de_gasto_por_sessao_bloqueia_novas_execucoes`.
- [ ] Implementar e verificar.

### T4.6 (onda 2): teste de ponta a ponta

**Arquivo:** `tests/ponta_a_ponta/test_fluxo_demo.py`.

- [ ] Testar `test_da_base_baguncada_a_entrega_na_nara`, com modelo simulado.
- [ ] Testar `test_jurado_altera_vaga_e_plano_muda`.
- [ ] Testar `test_fonte_cai_e_execucao_continua`.
- [ ] Testar `test_reinicio_nao_duplica_convite_nem_entrega`.
- [ ] Testar `test_dois_jurados_nao_se_afetam`.
- [ ] Rodar com o modelo real uma vez antes de cada congelamento.

### T4.3 (onda 2): deploy e link testável

- [ ] Publicar API e painel em um link público, até sábado às 17h.
- [ ] Configurar segredos no provedor e limite de gasto por sessão.
- [ ] Verificar o link em uma aba anônima, com dados reiniciados.

### T4.4 (onda 3): demo e submissão

**Arquivos:** `docs/pitch/`.

- [ ] Roteiro de 3 minutos, conforme a seção 13 do design.
- [ ] Gravar uma execução de reserva, identificada como gravação.
- [ ] Preparar descrição, vídeo, material de apresentação e lista de ferramentas, modelos e APIs.
- [ ] Sinalizar que o projeto responde ao Desafio Tako.
- [ ] Revisar se todo número tem fonte e toda simulação está identificada.
- [ ] Enviar até domingo às 12h30, com margem para o prazo das 13h.

## Dependências

- T0 antes de tudo.
- As tarefas marcadas com [P] podem rodar em paralelo depois de T0.
- T1.2 depende só dos contratos e usa simulações até as demais chegarem.
- T2.3 e T2.4 usam um `ClienteModelo` simulado até T1.3 chegar.
- T1.5 depende de `ClienteNara.resultados`, com simulação disponível desde T0.
- T1.7 usa um `BancoTalentos` simulado até T2.6 chegar.
- T1.11 usa `Repositorio` de T1.8. T2.3 usa o funil de T2.8.
- T1.13 depende dos casos sintéticos de T2.1 e da disponibilidade da pessoa de RH.
- T4.5 depende de T1.4; T4.6 depende da integração da onda 1.
- T4.3 e a parte final de T4.4 dependem da integração.

## Cobertura da spec

| Requisitos | Tarefas |
|---|---|
| FR-001, FR-002 | T1.9, T1.1, T1.2, T4.1 |
| FR-003, FR-012 | T2.2, T1.2, T1.10 |
| FR-004 | T1.1 |
| FR-005 | T2.3, T3.3 |
| FR-006 | T2.4 |
| FR-007, FR-011 | T1.2 |
| FR-008, FR-009 | T3.1, T3.2 |
| FR-010 | T3.3 |
| FR-013, FR-017 | T1.3, T4.1 |
| FR-014 | T1.1, T1.11, T1.4 |
| FR-015 | T2.2, T3.1, T3.3, T1.4, T4.1 |
| FR-016 | T1.5 |
| FR-025 | T3.5 |
| FR-026 | T2.9 |
| FR-027 | T2.7, T2.8 |
| FR-028 | T1.8, T1.2 |
| FR-029 | T4.5, T1.4 |
| FR-030 | T4.1, T1.2 |
| SC-001 a SC-004, SC-008 | T4.2 |
| SC-005, SC-006, SC-009 | T4.6 |
| SC-007 | T4.2, T4.1 |
| SC-010 | T1.11 |
| FR-018, FR-019, FR-021, FR-023, FR-024 | T2.6, T1.2, T1.7 |
| FR-020, FR-022 | T3.4 |
| FR-010, FR-012, FR-015 (entrega por MCP) | T1.12 |
| SC-007 (validação humana) | T1.13 |
