# Especificação: agente recrutador conectado à Nara

**Criada em**: 2026-11-07
**Estado**: Aprovada
**Origem**: `docs/superpowers/specs/2026-11-07-agente-recrutador-design.md`

## Cenários de usuário

### História 1: receber candidatos com contexto (P1)

Como recrutador, quero informar uma vaga e receber candidatos com a explicação da escolha, para reduzir o gargalo de encontrar pessoas capacitadas.

**Teste independente:** criar uma vaga na base sintética e conferir indicações, explicações e descartes.

1. **Dada** uma vaga aprovada, **quando** o agente termina a busca, **então** cada indicado tem motivo por critério, evidências, histórico e lacunas.
2. **Dado** um candidato sem requisito eliminatório, **quando** é analisado, **então** ele é descartado, com a regra registrada.
3. **Dado** um currículo com instruções para o agente, **quando** é analisado, **então** as instruções são ignoradas e um alerta é registrado.

### História 2: convidar e entregar à Nara (P1)

Como recrutador, quero que o agente faça o primeiro contato e envie o link da Nara, para o candidato interessado seguir o fluxo atual dela.

**Teste independente:** simular respostas de candidatos e conferir convites, entregas e pedidos de saída.

1. **Dado** um lote aprovado, **quando** o agente convida, **então** o candidato recebe explicação da vaga e link de agendamento da Nara.
2. **Dado** que o candidato aceitou, **quando** a entrega ocorre, **então** a Nara simulada recebe o pacote completo.
3. **Dado** que o candidato pediu para sair, **quando** houver nova busca, **então** ele não recebe novo contato.

### História 3: configurar qualquer vaga (P2)

Como administrador, quero configurar vagas de qualquer tipo, para usar o mesmo agente em diferentes áreas.

1. **Dada** uma descrição de vaga, **quando** o agente a lê, **então** propõe critérios e meta para aprovação.
2. **Dado** um critério sensível, **quando** ele é informado, **então** o sistema o recusa.
3. **Dada** uma vaga ambígua, **quando** é analisada, **então** o agente pergunta em vez de inventar requisitos.

### História 4: confiar no agente (P2)

Como responsável pelo RH, quero acompanhar custo, qualidade e rastro, para saber por que cada decisão foi tomada.

1. **Dado** um candidato, **quando** abro seu histórico, **então** vejo regras, evidências e chamadas relacionadas.
2. **Dada** uma execução, **quando** termina, **então** vejo tempo, tokens e custo por candidato.

### História 5: melhorar a busca (P3)

Como recrutador, quero que os resultados da Nara melhorem a busca, para receber indicações melhores nas próximas rodadas.

1. **Dado** um padrão de reprovação, **quando** o agente o detecta, **então** propõe um ajuste com o antes e o depois.
2. **Dada** uma proposta, **quando** não é aprovada, **então** a configuração continua igual.

### Casos de borda

- Fonte fora do ar durante a busca.
- Modelo indisponível ou com resposta inválida.
- Vaga sem candidatos suficientes.
- Mesmo candidato vindo duas vezes da mesma fonte ou de fontes diferentes.
- Candidato que pede para sair durante a conversa.
- Falha no envio depois de o convite ter sido aceito pelo mensageiro.
- Limite de gasto atingido no meio da execução.

## Requisitos

### Funcionais

- **FR-001**: O sistema DEVE propor a configuração da vaga para aprovação humana.
- **FR-002**: O sistema DEVE recusar critérios baseados em dados sensíveis.
- **FR-003**: O sistema DEVE buscar candidatos por uma interface comum de fontes e remover duplicatas.
- **FR-004**: Requisitos eliminatórios, autorização e limites de contato DEVEM ser aplicados por código determinístico.
- **FR-005**: Cada indicação DEVE ter motivo por critério, evidências, histórico, lacunas e pontos a aprofundar.
- **FR-006**: Um revisor independente DEVE verificar cada indicação antes do contato.
- **FR-007**: O primeiro lote de convites da vaga DEVE exigir aprovação humana.
- **FR-008**: O convite DEVE explicar a vaga e conter o link de agendamento da Nara.
- **FR-009**: O sistema DEVE tratar aceite, recusa, dúvida, silêncio e pedido de saída.
- **FR-010**: O pacote DEVE ser entregue à Nara sem duplicação depois do aceite.
- **FR-011**: O sistema NÃO DEVE agendar entrevistas nem decidir contratações.
- **FR-012**: O sistema DEVE tratar falhas de fontes, modelos e mensageiro sem perder o estado.
- **FR-013**: O sistema DEVE registrar rastro, tokens, custo e tempo por execução e por etapa.
- **FR-014**: Cada decisão DEVE guardar entrada, regra, evidências, resultado e responsável.
- **FR-015**: Fontes, Nara, mensagens e dados DEVEM indicar quando são simulados.
- **FR-016**: Ajustes propostos pelo aprendizado DEVEM exigir aprovação e permitir reversão.
- **FR-017**: O sistema DEVE respeitar um limite de gasto por sessão.

### Entidades

- **Vaga**: requisitos, competências com pesos, meta, limites e estado de aprovação.
- **Candidato**: dados sintéticos, histórico, fonte, autorização e opt-out.
- **Análise**: requisitos atendidos, notas, evidências, lacunas e revisão.
- **Decisão**: resultado, regra, motivo e responsável.
- **Convite**: canal, mensagem, link da Nara e chave de idempotência.
- **Pacote para a Nara**: contexto completo do candidato.
- **Resultado da Nara**: avaliação simulada usada no aprendizado.

## Critérios de sucesso

- **SC-001**: Zero violações de requisito eliminatório no conjunto de avaliação.
- **SC-002**: Zero contatos a candidatos com opt-out.
- **SC-003**: Trocar nome ou gênero não muda indicações nem ordem no teste de viés.
- **SC-004**: Toda indicação tem evidência para cada critério aprovado como atendido.
- **SC-005**: O fluxo termina ou pausa de forma recuperável em 100% das falhas injetadas.
- **SC-006**: Um jurado altera uma vaga e vê o primeiro resultado sem ajuda do time.
- **SC-007**: A precisão entre os 5 primeiros é medida e aparece no painel. A meta será definida depois da primeira execução.
