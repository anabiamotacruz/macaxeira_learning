# Especificação: agente recrutador conectado à Nara

**Criada em**: 2026-11-07
**Estado**: Aprovada. Alteração de 2026-11-07 (coleta real e contato direto) aguardando o acordo das quatro frentes (#8)
**Origem**: `docs/superpowers/specs/2026-11-07-agente-recrutador-design.md`

## Cenários de usuário

### História 0: construir o banco de talentos (P1)

Como recrutador, quero que o agente organize e mantenha o banco de talentos da minha empresa, para ter candidatos autorizados e atualizados quando uma vaga abrir.

**Teste independente:** importar uma base sintética bagunçada e simular autorizações, atualizações e saídas.

1. **Dada** uma base com duplicatas, **quando** ela é importada, **então** cada pessoa aparece uma vez, com a origem registrada.
2. **Dado** um perfil do banco sem autorização, **quando** o agente faz contato, **então** só pede autorização, e o perfil não entra na busca do banco.
3. **Dada** uma autorização vencida, **quando** a validade termina, **então** a pessoa sai da busca e pode ser convidada a renovar, dentro dos limites.
4. **Dadas** duas empresas, **quando** uma busca o próprio banco, **então** ela nunca vê dados da outra.
5. **Dado** que a pessoa pediu remoção, **quando** o pedido é registrado, **então** seus dados são removidos e ela não recebe novo contato.

### História 1: receber candidatos com contexto (P1)

Como recrutador, quero informar uma vaga e receber candidatos com a explicação da escolha, para reduzir o gargalo de encontrar pessoas capacitadas.

**Teste independente:** criar uma vaga na base sintética e conferir indicações, explicações e descartes.

1. **Dada** uma vaga aprovada, **quando** o agente termina a busca, **então** cada indicado tem motivo por critério, evidências, histórico e lacunas.
2. **Dado** um candidato sem requisito eliminatório, **quando** é analisado, **então** ele é descartado, com a regra registrada.
3. **Dado** um currículo com instruções para o agente, **quando** é analisado, **então** as instruções são ignoradas e um alerta é registrado.

### História 2: convidar e entregar à Nara (P1)

Como recrutador, quero que o agente entre em contato com os melhores candidatos, conte o que chamou atenção no perfil e chame para agendar com a Nara, para o candidato interessado seguir o fluxo atual dela.

**Teste independente:** simular candidatos com contato público, respostas, agendamentos e entrevistas, e conferir convites, entregas, dúvidas e follow-ups.

1. **Dada** uma pool aprovada com os melhores candidatos, **quando** o agente convida, **então** o candidato recebe a explicação da vaga, o que interessou no perfil dele, o link de agendamento da Nara, a origem do contato e um botão para não ser mais contatado.
2. **Dado** um candidato encontrado na coleta, **quando** ele não tem um contato publicado por ele mesmo, **então** não recebe mensagem, e nenhum endereço é inferido.
3. **Dado** que o candidato agendou com a Nara, **quando** o agendamento é confirmado, **então** a Nara recebe o pacote completo por MCP, uma única vez.
4. **Dado** que o candidato tem dúvidas, **quando** escreve, **então** o agente responde com o material da vaga ou encaminha a uma pessoa.
5. **Dado** um convite sem resposta, **quando** o intervalo passa e ainda há tentativas, **então** o agente envia um lembrete.
6. **Dado** que uma pessoa ou a Nara entrevistou o candidato, **quando** um humano aprova o resultado, **então** o agente faz o follow-up com os próximos passos.
7. **Dado** que o candidato pediu para sair ou clicou no botão de saída, **quando** houver nova busca, **então** ele não recebe novo contato.

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
- Candidato encontrado na coleta sem contato publicado por ele, ou com contato só em fonte de terceiros.
- Candidato que agenda, desmarca e agenda de novo com a Nara.
- Resultado da entrevista sem aprovação humana.
- Falha no envio depois de o convite ter sido aceito pelo mensageiro.
- Limite de gasto atingido no meio da execução.
- Documento enviado com formato inválido, grande demais ou com texto ilegível.
- Dois jurados usando o link público ao mesmo tempo.
- Reinício do serviço no meio de uma execução.
- Requisição tentando acessar dados de outra empresa.

## Requisitos

### Funcionais

- **FR-001**: O sistema DEVE propor a configuração da vaga para aprovação humana.
- **FR-002**: O sistema DEVE recusar critérios baseados em dados sensíveis.
- **FR-003**: O sistema DEVE buscar candidatos por uma interface comum de fontes e remover duplicatas. Além do banco, as fontes incluem busca semântica na web e provedores de dados contratados (como Bright Data e People Data Labs), com a coleta real desligada por padrão.
- **FR-004**: Requisitos eliminatórios, autorização e limites de contato DEVEM ser aplicados por código determinístico.
- **FR-005**: Cada indicação DEVE ter motivo por critério, evidências, histórico, lacunas e pontos a aprofundar.
- **FR-006**: Um revisor independente DEVE verificar cada indicação antes do contato.
- **FR-007**: O primeiro lote de convites da vaga DEVE exigir aprovação humana.
- **FR-008**: O convite DEVE explicar a vaga, dizer o que interessou no perfil, conter o link de agendamento da Nara, informar a origem do contato e trazer um botão para não ser mais contatado.
- **FR-009**: O sistema DEVE tratar aceite, recusa, dúvida, silêncio e pedido de saída, e continuar a conversa para tirar dúvidas.
- **FR-010**: O pacote DEVE ser entregue à Nara por MCP, sem duplicação, quando o candidato agendar com ela.
- **FR-011**: O sistema NÃO DEVE agendar entrevistas nem decidir contratações.
- **FR-012**: O sistema DEVE tratar falhas de fontes, modelos e mensageiro sem perder o estado.
- **FR-013**: O sistema DEVE registrar rastro, tokens, custo e tempo por execução e por etapa.
- **FR-014**: Cada decisão DEVE guardar entrada, regra, evidências, resultado e responsável.
- **FR-015**: Fontes, Nara, mensagens e dados DEVEM indicar quando são simulados.
- **FR-016**: Ajustes propostos pelo aprendizado DEVEM exigir aprovação e permitir reversão.
- **FR-017**: O sistema DEVE respeitar um limite de gasto por sessão.

- **FR-018**: Cada empresa DEVE ter um banco de talentos isolado.
- **FR-019**: O sistema DEVE importar bases e remover duplicatas, registrando a origem.
- **FR-020**: O sistema DEVE pedir autorização com validade e oferecer saída fácil.
- **FR-021**: Perfis sem autorização válida NÃO DEVEM entrar no banco de talentos nem na busca dele. Quem foi encontrado na coleta pode receber convite para a vaga só pelo contato que publicou (FR-031).
- **FR-022**: O sistema DEVE atualizar perfis por conversa e registrar a data de atualização.
- **FR-023**: O sistema DEVE remover dados a pedido e tratar autorizações vencidas.
- **FR-024**: A busca DEVE consultar o banco da empresa antes de fontes externas.
- **FR-025**: O sistema DEVE receber novos candidatos por um link de cadastro e por indicações, sempre com autorização registrada.
- **FR-026**: O sistema DEVE aceitar currículo enviado pela própria pessoa, validar o arquivo e tratar o conteúdo como dado.
- **FR-027**: O sistema DEVE traduzir a vaga em consultas e reduzir candidatos com filtros determinísticos antes das análises por modelo.
- **FR-028**: O sistema DEVE persistir estado, decisões e eventos, e retomar uma execução depois de reinício.
- **FR-029**: A API DEVE limitar cada requisição à empresa e à sessão atuais, e aplicar limite de requisições.
- **FR-030**: O sistema DEVE mostrar progresso e resultados parciais durante a execução.

- **FR-031**: O contato direto DEVE usar só um contato publicado pela própria pessoa (como o e-mail do currículo, do GitHub ou do site pessoal), com URL de origem e data da coleta, e NÃO DEVE usar contato inferido.
- **FR-032**: Toda mensagem DEVE trazer um botão para a pessoa não ser mais contatada. O bloqueio DEVE valer para todas as vagas da empresa e continuar valendo depois que os dados forem apagados.
- **FR-033**: Sem resposta, o sistema DEVE enviar lembretes até o limite de tentativas da vaga, com intervalo mínimo entre eles, e parar a qualquer resposta.
- **FR-034**: Depois que uma pessoa ou a Nara entrevistar o candidato, o follow-up DEVE ser enviado só com aprovação humana do resultado.
- **FR-035**: O sistema DEVE raciocinar o perfil ideal a partir da vaga e organizar uma pool com os candidatos que mais combinam antes do contato.

### Entidades

- **Banco de talentos:** perfis de uma empresa, com origem, autorização, validade e estado.

- **Vaga**: requisitos, competências com pesos, meta, limites e estado de aprovação.
- **Candidato**: dados sintéticos ou coletados, histórico, fonte, autorização, opt-out e contato público.
- **Contato público**: canal, endereço, URL de origem e data da coleta.
- **Análise**: requisitos atendidos, notas, evidências, lacunas e revisão.
- **Decisão**: resultado, regra, motivo e responsável.
- **Convite**: canal, mensagem, link de agendamento, botão de saída e chave de idempotência.
- **Agendamento**: confirmação da Nara de que o candidato agendou, que libera a entrega do pacote.
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
- **SC-008**: Zero vazamentos entre empresas e zero perfis sem autorização válida na busca.
- **SC-009**: Depois de reinício do serviço, a execução retoma sem duplicar convites nem entregas.
- **SC-010**: Toda indicação pode ser explicada a partir de um registro de decisão com evidências e rastro.
- **SC-011**: Zero mensagens para contato inferido ou sem origem registrada, e 100% das mensagens com botão de saída.
- **SC-012**: Zero pacotes entregues antes do agendamento e zero follow-ups pós-entrevista sem aprovação humana.
