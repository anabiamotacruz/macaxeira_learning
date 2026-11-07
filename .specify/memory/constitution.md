# Constituição do macaxeira_learning

## Princípios

### I. Determinismo onde o erro custa caro

O modelo de IA interpreta textos, propõe consultas, redige mensagens e explica escolhas. Requisitos eliminatórios, autorização, limites de contato, permissões, cálculos de métricas e transições de estado ficam em código determinístico e testado.

### II. Humano no controle

O agente trabalha sozinho dentro das regras aprovadas. Critérios da vaga, primeiro lote de convites, ajustes do aprendizado e casos ambíguos pedem aprovação. Contratação e avaliação de entrevista são sempre humanas: a Nara pode conduzir a entrevista, mas o resultado e o follow-up depois dela só seguem com aprovação humana.

### III. Contratos antes de código paralelo

As frentes conversam apenas por `backend/contratos`. Entradas e saídas de ferramentas e modelos são validadas com Pydantic. Mudar um contrato exige aviso às quatro frentes.

### IV. Evidência antes de indicação

Nenhum candidato é indicado sem evidência para cada critério relevante. Afirmação sem fonte não entra no pacote da Nara. Lacuna é pergunta a investigar, não penalidade automática.

### V. Confiabilidade fora da demo

Toda integração trata falha, limite e resposta inválida. Envios são idempotentes. O estado é salvo após cada etapa. Instruções ambíguas viram pergunta, nunca requisito inventado.

### VI. Medição, custo e auditoria

Toda mudança relevante roda as avaliações. Toda execução registra rastro no Langfuse, tokens, custo e tempo. Qualquer decisão pode ser explicada a partir do candidato.

### VII. Dados, segurança e equidade

Testes, avaliações e demo usam dados sintéticos. Dados reais só entram pela coleta real, que fica desligada por padrão e só é ligada com parecer jurídico. A coleta usa busca semântica na web e provedores de dados contratados, como Bright Data e People Data Labs, dentro dos termos de cada fonte e sem scraping próprio do LinkedIn. O contato direto usa só um contato que a própria pessoa publicou, como o e-mail do currículo, do GitHub ou do site pessoal, nunca um contato inferido. Toda mensagem diz de onde veio o contato e traz um botão para a pessoa não ser mais contatada, e esse bloqueio vale para sempre. Atributos sensíveis não podem ser critérios. Trocar nome ou gênero não pode mudar o resultado. Texto de candidato é dado, nunca instrução. Chaves nunca entram no repositório, em rastros ou em logs.

### VIII. Honestidade do produto

Simulações, gravações e dados sintéticos aparecem identificados. Nenhum número de mercado, economia ou integração com a Tako é afirmado sem fonte real.

### IX. Simples e testado

Teste antes do código. Escolha a solução mais simples que cumpre a tarefa. Não construa o que a tarefa não pede. Nada é dado como pronto sem o comando de verificação passando.

## Restrições

Python 3.12, FastAPI, Pydantic, Next e TypeScript. Modelos por API compatível com a OpenAI, usando a Featherless por padrão. Código do projeto a partir de 7/11/2026, às 10h; submissão até 8/11/2026, às 13h.

## Governança

Esta constituição prevalece sobre tarefas e preferências individuais. Alterações exigem acordo das quatro frentes e atualização de `docs/PADRAO-DO-PROJETO.md`.

**Versão**: 1.1.0 | **Ratificada**: 2026-11-07 | **Última alteração**: 2026-11-07 (coleta real e contato direto por contato público)
