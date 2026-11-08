# Plano de implementação: medição e autonomia do agente

**Branch**: `frente/agente-spec-005` | **Data**: 2026-11-07 | **Spec**: `specs/005-medicao-e-autonomia/spec.md`

**Entrada**: especificação da feature, código de `backend/agente/` e `backend/modelos/` na base `frente/agente-integracao` (commit 536b94e), relatórios da Frente 1 e PR #54.

**Nota**: esta feature foi pedida só com `spec.md`, `plan.md` e `tasks.md`. Por isso, o que o fluxo do Spec Kit colocaria em `research.md`, `data-model.md`, `contracts/` e `quickstart.md` está nas seções abaixo.

## Resumo

A base de cálculo já existe em `backend/agente/medicao.py`: taxas, partições, cache, portão, prova de abertura única e relatório. Falta ligá-la ao fluxo e à API, medir o que ainda não é medido, certificar o limiar, aplicar os resultados à decisão, criar a ficha de RH e o `aprendizado.py`, e fazer a primeira rodada real.

Os dados de Bia vêm primeiro. A PR #54 sustenta no máximo 89,85% na prova, mesmo sem erro, então não há certificação de 95% sem o conjunto forte.

## Contexto técnico

**Linguagem/versão**: Python 3.12 no backend; Next e TypeScript no painel.

**Dependências principais**: FastAPI, Pydantic, cliente OpenAI com Featherless, Langfuse. Limite binomial exato sem dependência nova, com `math.comb`, se P2 for confirmada.

**Armazenamento**: SQLite, em `RegistroProvas` e `Repositorio`. Arquivos JSON de dados sintéticos.

**Testes**: pytest e ruff. Modelo simulado nos testes comuns; chamada real só com a marca `eval`.

**Plataforma**: serviço web com painel.

**Tipo de projeto**: aplicação web com núcleo de medição executado por comando e pela API.

**Metas de desempenho**: medir o custo real com 50 casos antes de definir a rodada em volume.

**Restrições**: somente dados sintéticos; `GLM-5.2` pela Featherless; `max_tokens` padrão de 8000 e mínimo de 1000; limite de gasto por sessão; parar funcionalidades novas domingo, às 11h.

**Escala/escopo**: PR #54 com 250 registros. Conjunto forte estimado entre 354 e 600 casos na prova, conforme FR-M007, além de ajuste e validação.

## Verificação da constituição

Avaliada contra a versão 1.0.0, presente na base desta branch.

| Princípio | Situação | Observação |
| --- | --- | --- |
| I. Determinismo | Passa | Limite, portão, partição, gabarito e selo ficam em código. O modelo só propõe texto |
| II. Humano no controle | **Passa com ressalva** | D5 cabe no mandato assinado, mas "primeiro lote de convites" e "ajustes do aprendizado" ainda pedem aprovação. FR-M046 mantém o candidato parado até P1 ser respondida. Entrada automática de prompt exige emenda e acordo das quatro frentes |
| III. Contratos | **Passa com ressalva** | Os modelos novos ficam em `backend/contratos`. Nada muda sem aviso às quatro frentes, e por isso esta spec só os propõe |
| IV. Evidência | Passa | Precisão e afirmação sem evidência entram na medição, e P5 mantém o portão de eliminatório |
| V. Confiabilidade | Passa | Falha é contada, e prova caída fica gasta |
| VI. Medição e auditoria | Passa | É o objetivo da feature. A chamada do agente na rodada já gera rastro |
| VII. Dados e equidade | Passa | Somente dados sintéticos. Pares de viés dependem do conjunto forte |
| VIII. Honestidade | Passa | Selo, escopo do certificado e marca de exemplo fixo são obrigatórios |
| IX. Simples e testado | Passa | Sem treino de modelo nem calibração estatística além do limite |

`AGENTS.md` coloca o aprendizado automático por último na ordem de corte. D4 mantém esse trabalho no escopo, mas ele continua sendo o primeiro a sair se o prazo apertar. FR-016 da feature 001 também exige aprovação e reversão.

## Fase 0: decisões de desenho

### R1. Onde cada partição é usada

- **Decisão**: ajuste escolhe prompt e limiar; validação compara versões pelo portão, quantas vezes for preciso; prova faz a única abertura e gera o certificado.
- **Motivo**: hoje `escolher_limiar` só aceita ajuste, `rodar_prova` só aceita prova, e nada no código dá uso à validação.
- **Alternativa rejeitada**: certificar na validação, porque ela é consultada várias vezes.

### R2. Método do limite

- **Decisão**: isolar o método atrás de uma função e registrá-lo no certificado. Vale Wilson até haver resposta sobre P2.
- **Motivo**: 59/0, 100/1, 200/4 e 400/12 ficam fora da meta pelo teto de Wilson atual (6,11%, 5,45%, 5,03% e 5,17%). A meta pede os mínimos 73, 110, 202 e 414 enquanto P2 não for confirmada.
- **Alternativa rejeitada**: trocar agora, porque P2 ainda não foi confirmada.

### R3. Limiar assinado

- **Decisão**: o auto-improve propõe, e uma alteração de limiar segue como novo termo do mandato, reaproveitando o caminho de aditivo, com pessoa nomeada.
- **Motivo**: `limiar_verde` faz parte da `Politica` assinada e imutável. O agente não pode assinar pelo responsável.
- **Alternativa**: o mandato assina meta e confiança, e o limiar vem do certificado. Isso exige campos novos em `Politica`, com aviso às quatro frentes, e fica como decisão de produto.

### R4. Versão avaliada

- **Decisão**: criar uma versão composta a partir de cada prompt, modelo, parâmetros, limiar e gerador, sem alterar `VersaoPrompt`.
- **Motivo**: o hash atual cobre um único prompt e o modelo. Mudar `max_tokens` ou trocar o prompt de revisão não geraria outra versão.

### R5. Agente avaliado

- **Decisão**: um adaptador em `backend/agente/medicao_fluxo.py` usa `analisador`, `revisor` e as mesmas funções de decisão do fluxo, com limiar zero para calibrar, e devolve `RespostaAgente`.
- **Motivo**: sem isso, a medição só avalia agentes de teste. Não usar a máquina de estados inteira evita ampliar buscas, enviar contatos e o teto `max_indicacoes`, que é medido à parte.

### R6. Custo e tempo

- **Decisão**: reaproveitar `ClienteModelo.metricas()`, com a diferença entre antes e depois da rodada, e registrar consumo por caso quando o rastro permitir.
- **Motivo**: `MetricasEtapa` já acumula tokens, custo, tempo, respostas cortadas e maior saída.

### R7. Ficha de RH e aprendizado

- **Decisão**: `backend/agente/avaliacao_rh.py` segue a T1.13, e `backend/agente/aprendizado.py` junta M10 e M11 do ciclo de taxa de erro com a T1.5. O caminho por `ResultadoNara` da T1.5 continua sendo alerta, nunca portão.
- **Motivo**: as duas tarefas apontam para o mesmo arquivo, com assinaturas diferentes.

## Fase 1: desenho

### Modelo de dados proposto

Nada disto foi aplicado. Todo item exige aviso às quatro frentes antes de entrar em `backend/contratos/modelos.py`. Os campos novos são opcionais para não quebrar quem já usa os contratos.

| Contrato | Mudança proposta | Requisito |
| --- | --- | --- |
| `RespostaAgente` | `faltas: list[str] = []` | FR-M017, FR-M049 |
| `ResultadoCaso` | `faltas`, `tokens`, `custo_usd`, `tempo_s`, `cortada` | FR-M017, FR-M019, FR-M020 |
| `MetricasMedicao` | `precisao`, `alcance_automatico`, `alcance_final`, `motivos_revisao`, `consumo` | FR-M015 a FR-M020 |
| `TaxaMedida` | Limite inferior e método, sem remover os campos de Wilson | FR-M025 |
| `CertificadoLimiar` (novo) | `versao`, `conjunto_hash`, `limiar`, `metodo`, `confianca`, `meta`, `aprovacoes`, `erros`, `casos_independentes`, `limite_inferior`, `certificado`, `motivo`, `escopo` | FR-M024 a FR-M029 |
| `VersaoAvaliada` (novo) | Hash composto de prompts, modelo, parâmetros, limiar e gerador | FR-M011 |
| `Ficha`, `AvaliacaoHumana` (novos) | Campos da T1.13 e da seção 2.3 da validação | FR-M037, FR-M038 |
| `CandidatoAjuste` (novo) | `tipo`, `empresa_id`, `etapa`, `valor`, `pai`, `estado`, `relatorio`, `aprovado_por` | FR-M043 a FR-M047 |

### Interfaces

| Interface | Situação | Mudança |
| --- | --- | --- |
| `GET /vagas/{id}/metricas` | Existe. Sem provedor, devolve exemplo fixo | `montar_*` injeta o provedor, com alcance, revisão, viés, custo e selo |
| `GET /vagas/{id}/certificacao` | Não existe | Selo, limite inferior, número de casos, escopo e motivo, sem caso a caso |
| Comando `python -m backend.agente.medicao_cli` | Não existe | `suficiencia`, `rodar`, `prova`, `portao` e `relatorio`. A prova pede confirmação explícita |
| Aprovação de candidato (P1) | Não existe | Só depois da resposta sobre P1 |

Respostas da API seguem isoladas por empresa e identificam simulação, conforme `docs/convencoes/api-e-dados.md`.

### Guia de validação

```bash
pytest tests/agente/test_medicao.py tests/agente/test_auditoria.py tests/modelos/test_cliente.py
```

Resultado esperado hoje: 338 testes passando. As tarefas marcadas também citam `tests/agente/test_decisao_final.py` e `tests/agente/test_api.py`.

```bash
ruff check .
```

Depois das tarefas:

1. `suficiencia` nos dados da PR #54 avisa que a prova sustenta no máximo 89,85%.
2. `rodar` no ajuste, com modelo simulado, traz todas as métricas.
3. `prova`, com agente simulado, aceita a primeira abertura e recusa a segunda.
4. `pytest -m eval tests/agente/test_rodada_real.py`, com chave no ambiente e limite de gasto, publica custo e respostas cortadas de 50 casos.
5. A sessão de RH usa fichas sem campos ocultos.

## Estado atual do código

Conferido nesta base, com os testes de medição, auditoria, cliente, decisão final e API passando.

| Item | Existe e tem teste | Falta |
| --- | --- | --- |
| Taxas por tipo de erro, cobertura, revisão, falhas | Sim | Precisão com limite, alcance e motivos de revisão |
| Partições, gabarito derivado, resumo | Sim | Suficiência, dificuldade e hash selado |
| Rodada, cache, rastro da chamada | Sim, com agente injetado | Agente real |
| Prova de abertura única | Sim, uma abertura por versão | Bloquear certificação em segunda versão e versão composta |
| Portão | Sim | Validação como conjunto de uso e relatório "não piorou" |
| Escolha de limiar | Sim, com Wilson e sem correção | Certificado, P2 e P3 |
| Relatório | Sim | Novas métricas, escopo do gerador e flag da avaliação de RH |
| Amostra, pausa e liberação | Sim | Ligar ao fluxo real, probabilidade (P4) e intervalo |
| `metricas_autonomia` | Sim, só usada em testes | Provedor da API e intervalo |
| `max_tokens`, cortadas, maior saída | Sim, no cliente | Levar à medição |
| Decisão com portões e sinais | Sim, em `decisao_final.py`, usada só na pré-triagem | Ligar ao fluxo, depende de P5 |
| Selo de calibração | Sim, com `limiar_certificado` | Nenhum chamador fornece o valor |
| Provedor de métricas da API | Sim, injetável | `montar_demo` não injeta |
| `aprendizado.py`, `avaliacao_rh.py` | Não | Tudo |

## Divergências entre os relatórios e o código

| # | Relatório | Código | Encaminhamento |
| --- | --- | --- | --- |
| 1 | Propõe meta de 90%, com δ = 5% | A meta decidida é 95%. O código recebe a meta como parâmetro | Vale D1 |
| 2 | A tabela de casos usa limite exato | `escolher_limiar` usa Wilson: com meta de 5%, recusa 59/0, 100/1, 200/4 e 400/12 | A resposta sobre P2 define os mínimos |
| 3 | Trata portões e sinais como trabalho futuro | `decisao_final.py` já tem isso, mas o fluxo continua em `regras.decidir` | Ligar só com P5 |
| 4 | Diz que `abaixo_do_piso` descarta por nota | Correto no fluxo. `decisao_final.py` já manda nota baixa para uma pessoa | Depende de P5 |
| 5 | Pede amostra de todas as saídas, com probabilidade registrada | `selecionar_amostra` só sorteia decisões automáticas, sem registrar probabilidade | P4 |
| 6 | "Uma olhada por prova" | `RegistroProvas` limita por versão. Outra versão reabre o mesmo conjunto, e o relatório só avisa | FR-M010 |
| 7 | "Alcance" é medida central | Não existe. `cobertura` é (indicados + descartados) ÷ total | FR-M016 |
| 8 | Versão por hash do prompt | O hash cobre uma etapa e o modelo, sem parâmetros nem limiar | R4 |
| 9 | Arquivo de prova selado, fora do repositório | Todos os casos saem dos mesmos arquivos do repositório, e só a API de prova guarda a abertura | FR-M013; local do arquivo a combinar |
| 10 | O relatório de validação usa as mesmas vagas em ajuste e prova, e o do ciclo proíbe isso | O código segue o do ciclo. Na PR #54, cada partição fica com uma única função | FR-M006 pede mais funções |
| 11 | `dificuldade` faz parte do caso | O contrato tem o campo, mas `ler_casos` nunca o preenche, e a PR #54 não o traz | Frente 2 e Frente 1 |
| 12 | Zero sem medida barra | `passa_no_portao` barra, mas `_limiar_viavel` aceita. Com 0 pares na PR #54, o portão barra sempre | Alinhar `_limiar_viavel` |
| 13 | M6 em `prompts.py` e M12 em `medicao.py` | `versionar_prompt` está em `medicao.py`, sem chamador, e `concordancia` não existe. A T1.13 aponta para `avaliacao_rh.py` | R7 |
| 14 | Pede campos novos em `Politica` | Não existem | R3 |
| 15 | Só GitHub ou rede simulada comprovam | Confirmado. Consequência: 21 dos 83 indicáveis da PR #54 podem chegar à faixa verde sob a política padrão | Fonte dos dados fortes e política de evidência |

Outra diferença é de pastas: `AGENTS.md` cita `avaliacoes/`, mas a `main` remota tem `evals/`. Esta base e a `main` local não têm `dados/`, `web/` nem `evals/`, que estão na `main` remota.

## Limites entre frentes

| Frente | Entrega | Não faz |
| --- | --- | --- |
| **1. Agente** | `medicao.py`, `medicao_fluxo.py`, `medicao_cli.py`, `aprendizado.py`, `avaliacao_rh.py`, `auditoria.py`, ligação em `fluxo.py`, `servico.py`, `montagem.py`, `api.py`, e medidas em `backend/modelos/` | Gerador, painel, regras de contato |
| **2. Fontes e dados (Bia)** | Conjunto forte em `dados/`, pares de viés, dificuldade, gabarito, arquivo de prova selado com a Frente 4 | Limite, certificado, avaliação do agente |
| **3. Contato e Nara** | Bloqueio real de contato com opt-out e dados de resultado da Nara | A medição só usa a indicação como aproximação de opt-out; não define limiar |
| **4. Produto e qualidade** | Tela de métricas, selo e fila, formulário da ficha, testes `eval`, guarda do arquivo de prova, frase da demo | Cálculos, que continuam em `medicao.py` |
| **Compartilhado** | Propostas em `backend/contratos`, com aviso às quatro frentes | Mudar contrato sem aviso |

Mudanças fora de `backend/agente` e `backend/modelos` são tarefas das frentes indicadas. Enquanto elas não chegam, a Frente 1 usa dados de teste criados nos próprios testes.

## Estrutura do projeto

### Documentação (esta feature)

```text
specs/005-medicao-e-autonomia/
├── spec.md
├── plan.md
└── tasks.md
```

### Código (raiz do repositório)

```text
backend/
├── contratos/modelos.py        # compartilhado: mudanças propostas, com aviso
├── agente/
│   ├── medicao.py              # existe
│   ├── medicao_fluxo.py        # novo: agente avaliado sobre as decisões reais
│   ├── medicao_cli.py          # novo: comando da rodada, da prova e do relatório
│   ├── avaliacao_rh.py         # novo
│   ├── aprendizado.py          # novo
│   ├── auditoria.py            # existe
│   ├── decisao_final.py        # existe
│   ├── fluxo.py, servico.py, montagem.py, api.py, prompts.py, persistencia.py
└── modelos/cliente.py          # existe
dados/                          # Frente 2
evals/ ou avaliacoes/           # Frente 4: pasta a confirmar
web/                            # Frente 4
tests/agente/, tests/modelos/, tests/dados/
```

**Decisão de estrutura**: manter os cálculos puros em `medicao.py` e separar o que depende do fluxo em `medicao_fluxo.py`, para que testar um cálculo não exija montar o fluxo.

## Ordem sugerida e prazo

1. Hoje: passo 0 do relatório, diagnóstico de motivos de revisão e PR #54 nesta base.
2. Hoje: agente avaliado, novas métricas, rodada real de 50 casos e resposta sobre P2.
3. Com dados de Bia: suficiência, escolha de limiar e versão congelada.
4. Domingo de manhã: sessão de RH, revisão do gerador, se preciso, e a única abertura da prova.
5. Até domingo, às 11h: selo na API e no painel. Se apertar, o auto-improve fica no ciclo por comando, sem aplicação.

Se não houver casos suficientes até o congelamento, a submissão apresenta a faixa verde como **não certificada**.

## Rastreio de complexidade

| Item fora do mais simples | Por que é necessário | Alternativa simples rejeitada porque |
| --- | --- | --- |
| Versão composta | Trocar parâmetro ou segundo prompt reabriria a prova sem registro | Hash de um prompt não identifica o que foi avaliado |
| Dois arquivos de medição novos | Cálculo puro continua testável, sem o fluxo | Colocar tudo em `medicao.py`, com 840 linhas, acoplaria cálculo e fluxo |
