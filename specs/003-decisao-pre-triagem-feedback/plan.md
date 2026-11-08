# Plano de implementação: decisão, pré-triagem e feedback

**Branch**: `frente/agente-spec-003` | **Data**: 2026-11-07 | **Spec**: [spec.md](spec.md)

**Entrada**: `specs/003-decisao-pre-triagem-feedback/spec.md`

## Resumo

Os módulos de decisão, pré-triagem e feedback existem em `frente/agente-integracao` e têm testes, mas nada os chama em produção: `fluxo.py`, `api.py` e `servico.py` não os importam. A etapa de decidir ainda usa `regras.decidir`, com a faixa verde e três tipos de decisão.

O trabalho que falta é:

1. ligar a decisão com cinco saídas ao fluxo e à API;
2. combinar o canal com a Frente 3, que já tem uma pré-triagem própria em `origin/main` (T3.9);
3. completar a reidentificação do pacote;
4. corrigir as divergências da tabela abaixo;
5. medir a precisão por saída, com a meta de D-5.

Esta feature entrega só `spec.md`, `plan.md` e `tasks.md`. O conteúdo de `research.md`, `data-model.md` e `contracts/` fica neste plano, e os contratos já estão em `backend/contratos/modelos.py`.

## Contexto técnico

**Linguagem e versão**: Python 3.12 em `backend/`. TypeScript e Next em `web/`, que está em `origin/main`.

**Dependências principais**: FastAPI, Pydantic, cliente compatível com a OpenAI em `backend/modelos`, com Featherless e `zai-org/GLM-5.2`.

**Armazenamento**: SQLite em `backend/agente/persistencia.py`. A decisão final cabe no registro atual, em `Decisao.entrada["decisao_final"]`. Entrada de garden e roteiro em andamento ainda não têm persistência.

**Testes**: pytest e ruff. `avaliacoes/` ainda não existe nesta branch nem em `origin/main`, então a medição está em `tests/agente/test_medicao.py`.

**Plataforma**: serviço web e MCP, com canais e agente de destino simulados.

**Tipo de projeto**: serviço web com máquina de estados em código.

**Metas de desempenho**: não há meta nova. Decisão, validação e feedback são só código, e a extração usa uma chamada de modelo por mensagem.

**Restrições**: dados sintéticos, nenhuma chave em rastro, isolamento por empresa. Parada de funcionalidades em 8/11, às 11h, e submissão às 13h.

**Escala**: vaga de demonstração, com a amostra necessária para a meta indicada na spec.

## Verificação da constituição

| Princípio | Situação | Observação |
| --- | --- | --- |
| I. Determinismo | Passa | Destino, nota, roteiro e validação ficam em código. O modelo só extrai. |
| II. Humano no controle | **Em conflito** | D-1 retira a aprovação de lote, que o princípio ainda pede para o primeiro lote. Ver "Justificativas". |
| III. Contratos antes | Atenção | Os contratos novos não estão em `origin/main`. Mudanças previstas em `backend/contratos` exigem aviso às quatro frentes. |
| IV. Evidência | Passa, com correção | Motivos têm trecho, mas o feedback lista competência que não causou a recusa (divergência 6). |
| V. Confiabilidade | Pendente | Idempotência de ponta a ponta depende da ligação ao fluxo. |
| VI. Medição e auditoria | Pendente | Módulos têm rastro. A medição não conhece as cinco saídas. |
| VII. Dados e equidade | Passa, com correção | Contrafactuais testados. A reidentificação não cobre os campos novos (divergência 8). |
| VIII. Honestidade | Passa | Selo "não calibrado" e simulações identificadas. |
| IX. Simples e testado | Passa | Sem dependências novas. |

## Divergências entre o código e as decisões

Conferidas por leitura do código e, nos casos marcados com "executado", também por execução.

| # | Decisão ou regra | O que o código faz | Onde | Encaminhamento |
| --- | --- | --- | --- | --- |
| 1 | D-1 e D-2: agente decide com cinco saídas | O fluxo ainda usa `regras.decidir`. Nenhum módulo novo é chamado por fluxo, API ou serviço | `fluxo.py:1490`, `api.py:639` | T015 a T022, T039 |
| 2 | D-1: sem aprovação de lote | O código não tem lote, mas constituição II, FR-007 da 001, #50 §8 e fluxo da 002 ainda pedem | `.specify/memory/constitution.md:11` | T002, T003 |
| 3 | D-2: "pessoa boa" | Indisponível vem antes das lacunas: requisito eliminatório sem dado vira Garden indisponível (executado) | `decisao_final.py:501` | FR-D010, T054 |
| 4 | D-2: "a empresa quer manter proximidade" | Não há sinal da empresa. Só a confirmação de P-1, que pode ser desligada, e nesse caso o garden sai sozinho (executado) | `decisao_final.py:454`, `modelos.py:303` | T055 |
| 5 | D-2: agente decide o garden | `DestinoPessoa` e `/candidatos/{id}/destino` dizem que só o RH decide e têm o próprio "talent garden" | `modelos.py:350`, `api.py:689`, `fluxo.py:760` | T051 |
| 6 | D-4 e FR-D037: motivos reais | Recusa por requisito lista também competência sem evidência como "não atendida" (executado) | `feedback.py:128` e `feedback.py:181` | T060 |
| 7 | D-4: meios definidos | `PedidoFeedback.canal` é texto livre: "telegram" é aceito (executado). Nada entrega o feedback, e opt-out não é consultado | `modelos.py:1007`, `feedback.py:241` | T061 a T064 |
| 8 | Reidentificação | `reidentificar_pacote` não revela `pontos_a_explorar` nem `respostas_pre_triagem`, e a auditoria não os lista (executado) | `fontes/anonimizador.py:995` | T042 |
| 9 | D-5: meta de 95% | `escolher_limiar` recebe a meta como parâmetro, usa teto de Wilson com varredura de notas e conhece só `TipoDecisao`. O relatório recomenda limite exato. Nada produz `limiar_certificado` para a decisão | `medicao.py:383`, `medicao.py:390`, `medicao.py:549`, `decisao_final.py:296` | T069 a T072 |
| 10 | Teto do mandato | `classificar_destino` ignora `max_indicacoes`. O fluxo aplica `nao_priorizada`, que muda só a `Decisao` e deixaria `decisao_final` dizendo Aprovar | `fluxo.py:1446`, `regras.py:436` | T017 |
| 11 | Ligação ao fluxo | `_ordem_de_decisao` lê `entrada["nota"]`, mas `como_decisao` grava `nota_geral`. `REGRAS_DA_FAIXA_VERDE` não conhece `aprovacao_por_criterios_v1` | `fluxo.py:164`, `fluxo.py:310` | T016, T018 |
| 12 | Pré-triagem em código da Frente 1 | `origin/main` (T3.9, `ed2cf36`) tem `montar_roteiro` e `validar` próprios, sem mandato nem as cinco saídas. FR-C014 e FR-C015 atribuem a validação à Frente 3 | `backend/contato/whatsapp.py`, em `origin/main` | T038, T041 |
| 13 | FR-C014: roteiro aprovado com a vaga | O roteiro é por pessoa, gerado dos critérios assinados e das lacunas, sem aprovação própria. O mandato cobre os critérios | `pre_triagem.py:210` | Alinhar a 002 em T003 |
| 14 | P-1, P-2 e P-3, não confirmadas | Já estão no código como padrão. P-4 não existe | `modelos.py:303`, `modelos.py` em `FeedbackCandidato`, `decisao_final.py:454` | T004, T056 |
| 15 | D-3 após decisão humana | `_decisao_humana` não leva `decisao_final`: depois de uma reversão, o score some do registro vigente | `fluxo.py:785` | T020 |

## Como as peças se ligam

```text
Mandato assinado (Frente 1)
  -> análise e revisão (Frentes 1 e 2)
  -> classificar_destino -> DecisaoFinal -> como_decisao -> registro
       | Aprovar
       v
  contato inicial e WhatsApp (Frente 3)
       | gerar_roteiro + montar_contexto_onboarding (Frente 1)
       v
  canal entrega perguntas e devolve a mensagem (Frente 3)
       | extrair_respostas + validar_pre_triagem + registrar_no_perfil (Frente 1)
       v
  passou: link do destino + pacote_com_pre_triagem + reidentificar_pacote (Frentes 1 e 2)
       -> AgenteRecrutador.entregar (conector da Frente 1)
  ambíguo: Revisão humana
  não passou: Recusar ou Garden
       -> propor_garden, pedido de autorização (Frente 3), autorizar_garden

Pedido de feedback pelo canal (Frente 3)
  -> responder_pedido_de_feedback (Frente 1) -> canal entrega (Frente 3)
```

## Limites entre as frentes

| Frente | É dona de | Não faz |
| --- | --- | --- |
| **1. Agente** | `backend/agente`: decisão, score, roteiro, extração, validação, garden, feedback, fluxo, API, serviço, medição e persistência | Enviar mensagens, falar com provedores, manter a tela |
| **2. Fontes e dados** | `backend/fontes/anonimizador.py`, cofre e reidentificação, análise e revisão. Evidência com trecho e fonte | Decidir destino |
| **3. Contato e Nara** | `backend/contato` e `backend/nara_simulada`: e-mail, WhatsApp, janela de 24 horas, supressão, autorização, ligação da conversa ao convite, entrega do texto do feedback | Montar roteiro, validar a pré-triagem, decidir destino, escolher o texto do feedback |
| **4. Produto e qualidade** | `web` e `avaliacoes`: telas de score, pontos, insights, confirmação e garden, gabarito e casos | Calcular nota ou decidir no navegador |
| **Compartilhado** | `backend/contratos`. Toda mudança exige aviso às quatro frentes, em PR próprio | |

### O que cada frente precisa entregar à Frente 1

- **Frente 2:** reidentificação com os campos novos (T042).
- **Frente 3:** adaptação da T3.9 para usar `ContextoOnboarding` e devolver a mensagem bruta (T038), reconhecimento do pedido de feedback e entrega do texto (T063 e T064), pedido de autorização do garden (T052).
- **Frente 4:** telas (T030, T053 e T065) e gabarito às cegas das cinco saídas (T073).

## Mudanças previstas em contratos

Todas dependem de aviso às quatro frentes. Nada aqui foi alterado por esta feature.

- `backend/contratos/interfaces.py`: interface do canal da pré-triagem e do feedback.
- `PedidoFeedback.canal`: restringir a e-mail e WhatsApp.
- Campos de `DecisaoFinal` e afins: levar para a `main` com o aviso (T001).
- Vaga com ação afirmativa e sinal de proximidade: só depois de confirmar P-4 e P-1.

## Estrutura do projeto

### Documentação

```text
specs/003-decisao-pre-triagem-feedback/
├── spec.md
├── plan.md
└── tasks.md
```

### Código

```text
backend/
├── agente/
│   ├── decisao_final.py     # existe: destino, score, garden, pontos, insights
│   ├── pre_triagem.py       # existe: roteiro, extração, validação, pacote
│   ├── feedback.py          # existe: resposta a pedido, com auditoria
│   ├── medicao.py           # existe: muda para as cinco saídas e a meta
│   ├── fluxo.py             # muda: decidir, pré-triagem, garden
│   ├── servico.py           # muda: operações novas
│   ├── api.py               # muda: rotas novas
│   ├── exemplos_api.py      # muda: exemplos das rotas
│   └── persistencia.py      # muda: garden e roteiro
├── contratos/
│   ├── modelos.py           # existe: muda com aviso às quatro frentes
│   └── interfaces.py        # muda com aviso às quatro frentes
├── fontes/anonimizador.py   # Frente 2
└── contato/                 # Frente 3, em origin/main
web/                         # Frente 4, em origin/main
tests/
├── agente/                  # test_decisao_final, test_pre_triagem, test_feedback, test_fluxo, test_api
├── contratos/               # test_destino_e_pre_triagem
└── fontes/                  # test_anonimizador
```

**Decisão de estrutura**: mantém a separação por frentes de `AGENTS.md`. `regras.decidir` continua até a troca no fluxo passar nas avaliações, e só então sai do caminho principal.

## Riscos

| Risco | Efeito | Como tratar |
| --- | --- | --- |
| A troca na etapa de decidir quebra testes e telas que esperam a faixa verde | Regressão em `test_fluxo.py` | Trocar em um PR só, atrás de `como_decisao`, e rodar a medição antes e depois |
| Quem tem requisito em aberto vai para Revisão humana e só recebe pré-triagem com liberação | Fila grande, apesar de não haver aprovação de lote | Medir o volume e levar à questão 3 da spec. Não relaxar sem decisão |
| A meta não pode ser comprovada até a submissão | Afirmação indevida no pitch | Apresentar como não comprovada, com selo "não calibrado" |
| Duas pré-triagens em paralelo | Resultados diferentes para a mesma pessoa | Resolver T038 antes de ligar o canal |
| Contratos novos fora da `main` | Outras frentes constroem sobre tipos antigos | T001 primeiro |

## Justificativas

| Violação | Por que é necessária | Alternativa mais simples recusada porque |
| --- | --- | --- |
| Princípio II: sem aprovação do primeiro lote | Decisão D-1, aprovada pelo grupo, segundo o responsável. O mandato assinado passa a ser o ponto de controle humano | Manter o lote contraria D-1. A emenda da constituição precisa do acordo registrado (T002) |
