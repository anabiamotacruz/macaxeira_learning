# Padrão do projeto

Este documento garante que as quatro frentes gerem com a mesma qualidade, em qualquer máquina. Se algo aqui conflitar com a constituição, vale a constituição.

## 1. O que estamos construindo

Um digital worker recebe uma vaga, encontra e analisa candidatos, explica cada escolha, faz o primeiro contato e envia o link de agendamento da Nara. A Nara agenda e entrevista como já faz hoje. O resultado volta para melhorar a busca, com aprovação humana.

É um produto próprio, que a Tako pode usar. Não é um produto feito para a Tako nem uma extensão interna dela. A Nara é a primeira integração.

**Não fazemos:** agendar ou conduzir entrevistas, avaliar candidatos no lugar da Nara, decidir contratações, integrações reais no hackathon ou scraping do LinkedIn.

## 2. Onde está cada decisão

| Documento | Para que serve |
|---|---|
| `.specify/memory/constitution.md` | Princípios inegociáveis |
| `docs/superpowers/specs/2026-11-07-agente-recrutador-design.md` | Decisões e motivos |
| `specs/001-agente-recrutador/spec.md` | O que o produto precisa fazer |
| `specs/001-agente-recrutador/plan.md` | Arquitetura e contratos |
| `specs/001-agente-recrutador/tasks.md` | Tarefas por frente |

Faltou uma decisão? Não invente: registre a dúvida no PR e avise o grupo. Se for pequena e reversível, escolha a opção mais simples e escreva o motivo no PR.

## 3. Critérios de avaliação

Os quatro têm o mesmo peso. Toda tarefa deve ajudar pelo menos um:

1. **Protótipo e aderência:** faz trabalho real, funciona na demo e se sustenta fora dela.
2. **Viabilidade como startup:** existe mercado, alguém que pagaria e caminho de crescimento.
3. **Criatividade e originalidade.**
4. **Pitch:** clareza sobre problema, solução e potencial de mercado.

## 4. Configuração da máquina

Cada pessoa faz isto uma vez:

```bash
git clone https://github.com/anabiamotacruz/macaxeira_learning.git
```

```bash
cd macaxeira_learning && uv venv --python 3.12 && source .venv/bin/activate
```

```bash
export FEATHERLESS_API_KEY=coloque-a-sua-chave-aqui
```

Coloque o `export` no perfil do seu shell, nunca em um arquivo do repositório. Cada pessoa usa a própria chave. As dependências são instaladas depois que a tarefa de contratos criar o `pyproject.toml`.

**Spec Kit:** o repositório já traz a versão `1.3.2` para Claude Code. Não reinstale nem rode `specify init` de novo, porque isso pode sobrescrever a configuração.

```bash
export SPECIFY_FEATURE_DIRECTORY=specs/001-agente-recrutador
```

**Modelo padrão:** base `https://api.featherless.ai/v1`, modelo `zai-org/GLM-5.2`. Use `max_tokens` de pelo menos 1000, porque o modelo raciocina antes de responder.

## 5. Como gerar código

### Prompt inicial padrão

Cole no início de cada sessão, trocando os campos entre colchetes:

```text
Você vai trabalhar no repositório macaxeira_learning, na frente [1 Agente | 2 Fontes e dados | 3 Contato e Nara | 4 Produto e qualidade].

Antes de agir, leia AGENTS.md, docs/PADRAO-DO-PROJETO.md, .specify/memory/constitution.md, specs/001-agente-recrutador/plan.md e a tarefa [ID] em specs/001-agente-recrutador/tasks.md.

Faça somente essa tarefa, na pasta da sua frente e na branch da frente. Escreva primeiro o teste que falha, depois o código mínimo, e rode os comandos de verificação. Se precisar mudar um contrato ou uma decisão de produto, pare e me pergunte.

No fim, informe o que mudou, o resultado dos testes, o que não foi verificado e o que preciso revisar.
```

### Ciclo de cada tarefa

1. **Pegar:** escolha uma tarefa da sua frente e avise no grupo.
2. **Atualizar:** rode `git pull --rebase origin main` na branch.
3. **Testar primeiro:** escreva o teste indicado e veja-o falhar.
4. **Implementar:** faça o mínimo para passar, seguindo as interfaces do plano.
5. **Verificar:** rode testes e lint.
6. **Revisar:** leia o diff, mesmo que uma IA o tenha escrito.
7. **Entregar:** abra um PR pequeno, com evidência do teste.

### Spec Kit

A spec, o plano e as tarefas já existem. Use assim:

| Comando | Quando usar |
|---|---|
| `/speckit-implement T1.1` | Implementar uma tarefa específica |
| `/speckit-clarify` | Encontrar ambiguidades antes de mudar a spec |
| `/speckit-analyze` | Verificar coerência depois de alterar spec, plano ou tarefas |
| `/speckit-converge` | Comparar o código com a spec e registrar o que falta |

Não use `/speckit-specify` nem `/speckit-plan` para substituir esses arquivos sem acordo do time.

### Como pedir bem

- **Peça uma coisa de cada vez:** "Implemente T2.2", não "faça a parte de dados".
- **Dê o critério de pronto:** diga qual teste precisa passar.
- **Exija evidência:** peça a saída dos comandos, não a palavra "pronto".
- **Não aceite invenção:** biblioteca nova, contrato novo ou mudança de escopo precisam de justificativa.
- **Peça revisão independente** em regras, decisões e análise de perfis.

## 6. Definição de pronto

Uma tarefa só está pronta quando:

- [ ] O teste indicado na tarefa passa, e os demais continuam passando.
- [ ] O lint passa.
- [ ] Os contratos não mudaram, ou as quatro frentes foram avisadas.
- [ ] Falhas previsíveis foram tratadas: fonte fora do ar, limite, resposta inválida e dado faltante.
- [ ] Chamadas de modelo e ferramentas geram rastro.
- [ ] Decisões guardam regra, evidências e motivo.
- [ ] Nenhum dado real ou chave entrou no repositório.
- [ ] Simulações estão identificadas na interface e na API.
- [ ] As avaliações foram rodadas, se a mudança afeta busca, análise, revisão ou decisão.

## 7. Qualidade do agente

### Confiabilidade

| Situação | Comportamento exigido |
|---|---|
| Fonte fora do ar ou com limite | Repetir com espera, seguir com outras fontes e registrar cobertura parcial |
| Modelo indisponível | Repetir, usar alternativa ou pausar e retomar |
| Resposta inválida do modelo | Validar, tentar corrigir e, se persistir, enviar a um humano |
| Vaga ambígua | Perguntar; nunca inventar requisito |
| Poucos candidatos | Ampliar dentro dos limites ou avisar risco à meta |
| Falha no envio | Repetir sem duplicar |
| Instrução dentro de um currículo | Tratar como dado e registrar o alerta |

### Avaliações

Rode `pytest avaliacoes -m eval` antes de mudar a lógica de busca, análise, revisão ou decisão, e registre o resultado no PR.

**Precisam ser zero:**
- Violações de requisito eliminatório.
- Contatos a quem pediu para sair.
- Mudanças de resultado ao trocar nome ou gênero.

**Precisam ser acompanhadas:**
- Precisão entre os 5 primeiros.
- Armadilhas tratadas corretamente.
- Afirmações sem evidência.
- Conclusão diante de falhas injetadas.

### Custo e latência

Cada execução registra tokens, custo e tempo por etapa. O painel mostra custo por candidato analisado e por candidato entregue. Use modelo barato em extração e triagem, e `GLM-5.2` em análise e revisão. Não invente comparação com o processo manual sem dados reais de um recrutador.

### Auditoria

Toda chamada usa o Langfuse. Toda decisão guarda entrada, regra, evidências, resultado e responsável. A partir de um candidato, é preciso conseguir explicar por que ele foi indicado ou descartado.

## 8. Dados e limites

- **Somente dados sintéticos.** Nada de dados pessoais reais de candidatos.
- **LinkedIn:** sem scraping, robôs ou serviços de coleta. Fontes reais são uma lacuna a pesquisar.
- **GitHub:** só a API oficial, com contas e repositórios de teste do time, e sem contato frio.
- **Equidade:** gênero, idade, raça, religião, estado civil e outros dados sensíveis não são critérios.
- **Nara e Tako:** integrações simuladas devem aparecer assim. Nunca afirme acesso que não temos.

## 9. Git e colaboração

- **Branches:** `frente/agente`, `frente/fontes`, `frente/contato`, `frente/produto`.
- **Pull requests:** pequenos e frequentes, com pelo menos uma pessoa de outra frente revisando, se possível.
- **Commits:** no formato `tipo: descrição`, como `feat: adiciona rede simulada`, sem atribuição a assistentes.
- **Pastas:** cada frente altera só as suas. `backend/contratos` é compartilhada.
- **Comunicação:** avise no grupo ao pegar uma tarefa, ao concluir, ao mudar um contrato e ao ficar bloqueado.
- **Segredos:** `.env` nunca vai para o repositório. Se uma chave vazar, revogue-a imediatamente.

## 10. As quatro frentes

Todas têm a mesma prioridade. Os responsáveis serão definidos pelo time.

| Frente | Pasta | Responsabilidade |
|---|---|---|
| **1. Agente** | `backend/agente`, `backend/modelos` | Máquina de estados, regras, decisões, aprendizado e API |
| **2. Fontes e dados** | `backend/fontes`, `dados` | Dados sintéticos, rede simulada, análise de perfis e revisor |
| **3. Contato e Nara** | `backend/contato`, `backend/nara_simulada` | Convite, conversa, pacote de contexto e Nara simulada |
| **4. Produto e qualidade** | `web`, `avaliacoes`, `docs/pitch` | Painel, avaliações, métricas, deploy, demo e submissão |

## 11. Prazos

| Quando | Marco |
|---|---|
| Sábado, 10h | Início do código; contratos combinados em conjunto |
| Sábado, 11h | Contratos na `main`; frentes em paralelo |
| Sábado, 13h | Primeiro fluxo com simulações; Nara simulada congelada se a Tako não der acesso de teste |
| Sábado, 17h | Fluxo completo integrado |
| Domingo, 11h | Parar funcionalidades novas |
| Domingo, 12h30 | Submissão pronta, com margem |
| Domingo, 13h | Prazo final |
| Domingo, 16h | Demo Day |

**Se faltar tempo, corte nesta ordem:** vaga fora de tech, GitHub real, MCP, retomada automática e aprendizado automático. O fluxo principal, a avaliação e o rastro não saem.

## 12. Lacunas

- Confirmar a dor com recrutadores e com a Tako.
- Pesquisar fontes reais autorizadas e o tratamento da LGPD.
- Perguntar à Tako se há ambiente de teste da Nara ou do MCP.
- Definir o cliente inicial do pitch.
