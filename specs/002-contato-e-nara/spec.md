# Especificação: Frente 3, contato e Nara

**Criada em**: 2026-11-07
**Atualizada em**: 2026-11-07, com o fluxo de contato direto da proposta #49
**Estado**: Rascunho, para revisão do time. O contato direto com pessoas reais depende do acordo das quatro frentes (#8) e de parecer jurídico.
**Frente**: 3. Contato e Nara (`backend/contato`, `backend/nara_simulada`, branches `frente/contato` e `frente/contato-*`)
**Origem**: `specs/001-agente-recrutador/spec.md`. Contratos em `backend/contratos`. Tarefas T3.1 a T3.6 em `specs/001-agente-recrutador/tasks.md` e issues #34 a #42.

Esta spec detalha a parte de contato da spec 001. Ela não substitui a 001 nem muda contratos. Se houver conflito, vale a 001, e acima dela a constituição.

## Fluxo do produto

1. A empresa informa a vaga e o perfil desejado, e o agente raciocina o perfil ideal (Frente 1).
2. O agente faz a busca semântica de candidatos alinhados: busca semântica na web e coleta por provedores, como Bright Data e People Data Labs (Frente 1, coleta real desligada por padrão).
3. O agente organiza uma pool com os candidatos que mais combinam (Frente 1).
4. **O agente entra em contato com a pessoa, conta o que interessou no perfil dela e chama para agendar a entrevista com a Nara (esta frente).**
5. **Quando a pessoa agenda, o contexto do candidato vai direto para a Nara, por MCP (esta frente e a T1.12).**
6. **O agente continua a conversa para tirar dúvidas (esta frente).**
7. **Depois que uma pessoa ou a Nara entrevista o candidato, e um humano aprova o resultado, o agente faz o follow-up (esta frente).**

## Escopo

**A frente faz:**

- Convidar o candidato da pool pelo contato que ele mesmo publicou, ou pelo canal autorizado no banco. O convite conta o que interessou no perfil, traz o link de agendamento da Nara, diz de onde veio o contato e oferece um botão para não ser mais contatado.
- Enviar lembretes a quem não respondeu, dentro do limite de tentativas da vaga.
- Conversar com o candidato: classificar respostas, tirar dúvidas com o material da vaga e encaminhar o resto a uma pessoa.
- Entregar o pacote de contexto à Nara quando a pessoa agendar.
- Fazer o follow-up depois da entrevista, só com aprovação humana do resultado.
- Pedir autorização para o banco de talentos e atualizar perfis por conversa.
- Captar novos candidatos por link de cadastro e por indicação, sempre com autorização.
- Recontatar quem está no banco, com moderação e proposta de valor.
- Manter a Nara simulada, também exposta como servidor MCP, para o conector da T1.12 usar.

**A frente não faz:**

- Agendar ou conduzir entrevistas, avaliar candidatos ou decidir contratações. A Nara agenda e entrevista; o agente só envia o link dela (FR-011).
- Raciocinar o perfil ideal, buscar, coletar, analisar ou montar a pool. Isso é da Frente 1 (#20).
- Encontrar o contato da pessoa. A coleta entrega o contato público com a origem, e esta frente só o usa.
- Decidir quem pode ser contatado nem mudar estados do fluxo. A frente consome `pode_contatar` e `decidir` (T1.1) e é chamada pelo fluxo (T1.2).
- O conector MCP que chama a Nara (T1.12, #24) e o servidor MCP com as ferramentas do agente (T1.6, #25), ambos da Frente 1.

## Cenários de usuário

### História 1: convidar para a vaga (P1)

Como recrutador, quero que o agente convide cada candidato da pool com uma mensagem personalizada, para a pessoa entender a vaga, por que foi lembrada e como agendar.

**Teste independente:** criar convites para uma pool simulada, com contatos públicos fictícios, e conferir conteúdo, envio e reenvio. Tarefa T3.1 (#35).

1. **Dado** um candidato da pool com contato público, **quando** o convite é criado, **então** ele explica a vaga, conta o que interessou no perfil, traz o link de agendamento da Nara, diz de onde veio o contato e oferece um botão para não ser mais contatado.
2. **Dado** um candidato sem contato publicado por ele mesmo, **quando** o convite seria criado, **então** nada é enviado, e nenhum endereço é inferido.
3. **Dada** uma empresa que desligou a personalização, **quando** o convite é criado, **então** a mensagem é montada por código, sem modelo.
4. **Dado** um convite já enviado, **quando** o envio é repetido com a mesma chave, **então** o candidato não recebe a mensagem duas vezes.
5. **Dado** que o mensageiro falhou, **quando** o envio é repetido, **então** o convite sai uma única vez e a falha fica registrada.
6. **Dado** um candidato que pediu para sair ou está na lista de bloqueio, **quando** o convite seria enviado, **então** nada é enviado e o bloqueio fica registrado com a regra.

### História 2: conversar e tirar dúvidas (P1)

Como recrutador, quero que o agente trate as respostas e continue a conversa, para o candidato tirar dúvidas sem depender de uma pessoa a cada mensagem.

**Teste independente:** simular respostas e conferir classificações, respostas e encaminhamentos. Tarefa T3.2 (#36).

1. **Dada** uma resposta, **quando** ela é classificada, **então** recebe um tipo entre aceite, recusa, dúvida, silêncio e opt-out.
2. **Dada** uma mensagem que mistura interesse e pedido para sair, **quando** é classificada, **então** vale o opt-out.
3. **Dada** uma dúvida respondida pelo material da vaga, **quando** o agente responde, **então** a resposta usa só esse material. **Dada** uma dúvida fora dele, **então** ela vai para uma pessoa.
4. **Dada** uma mensagem com instruções ao agente, **quando** é classificada, **então** as instruções são ignoradas, um alerta é registrado e a mensagem não vira aceite.

### História 3: lembrar quem não respondeu (P1)

Como recrutador, quero que o agente lembre quem não respondeu, para não perder candidatos por esquecimento e sem incomodar ninguém.

**Teste independente:** simular silêncios ao longo de dias fictícios e conferir os lembretes. Tarefa T3.7, proposta (#41).

1. **Dado** um convite sem resposta, **quando** o intervalo mínimo passa e ainda há tentativas, **então** o agente envia um lembrete curto, com o link e o botão de saída.
2. **Dado** que as tentativas da vaga acabaram, **quando** o candidato continua em silêncio, **então** o contato é encerrado como silêncio e nenhum lembrete novo é enviado.
3. **Dado** um lembrete agendado, **quando** chega qualquer resposta ou agendamento antes dele, **então** o lembrete é cancelado.

### História 4: entregar à Nara no agendamento (P1)

Como recrutador, quero que a Nara receba o contexto de quem agendou, para a entrevista começar do ponto certo.

**Teste independente:** simular agendamentos na Nara simulada e conferir o pacote e as entregas por MCP. Tarefa T3.3 (#37), com o conector da T1.12.

1. **Dado** que o candidato agendou com a Nara, **quando** o agendamento é confirmado, **então** a Nara recebe por MCP o pacote com todos os campos da seção 6 do design.
2. **Dado** um candidato que aceitou mas ainda não agendou, **quando** o fluxo avança, **então** nenhum pacote é enviado.
3. **Dado** um pacote, **quando** é montado, **então** só entram evidências com trecho e fonte, e nenhum atributo sensível.
4. **Dada** uma entrega já feita, **quando** ela é repetida, inclusive depois de reinício ou de um novo agendamento, **então** a Nara não recebe o pacote duas vezes.
5. **Dada** a Nara simulada, **quando** ela devolve link, agendamentos e resultados, **então** tudo é marcado como simulação e se repete com a mesma semente.
6. **Dado** que a Nara está fora do ar, **quando** a entrega falha, **então** ela fica pendente para nova tentativa, sem perder o agendamento.

### História 5: follow-up depois da entrevista (P2)

Como recrutador, quero que o agente dê retorno ao candidato depois da entrevista, para ninguém ficar sem resposta e sem que o agente decida no lugar de uma pessoa.

**Teste independente:** simular resultados de entrevista, com e sem aprovação humana, e conferir os follow-ups. Tarefa nova, proposta.

1. **Dado** o resultado de uma entrevista feita por uma pessoa ou pela Nara, **quando** ainda não há aprovação humana, **então** nenhum follow-up é enviado.
2. **Dado** que um humano aprovou o resultado, **quando** o follow-up é montado, **então** ele comunica os próximos passos aprovados e não traz notas nem avaliação da entrevista.
3. **Dado** um follow-up já enviado, **quando** o envio é repetido, **então** a pessoa não recebe duas vezes.
4. **Dado** que a pessoa pediu para sair depois da entrevista, **quando** o follow-up seria enviado, **então** nada é enviado.

### História 6: autorização e atualização por conversa (P1)

Como recrutador, quero que o agente peça autorização para o banco de talentos e atualize os perfis, para ter candidatos autorizados e atuais nas próximas vagas.

**Teste independente:** conversar com perfis simulados sem autorização, com autorização e desatualizados. Tarefa T3.4 (#38).

1. **Dado** um perfil do banco sem autorização e sem contato público, **quando** o agente faz contato, **então** só pede autorização, sem perguntas sobre o perfil.
2. **Dado** um candidato vindo da coleta, **quando** ele termina o contato da vaga, **então** só entra no banco se autorizar.
3. **Dado** que a pessoa autorizou, **quando** a resposta é registrada, **então** a autorização ganha data de validade.
4. **Dada** uma atualização por mensagem, **quando** é extraída, **então** o perfil muda e a data de atualização é registrada.
5. **Dado** um pedido de saída, **quando** é registrado, **então** a pessoa é removida do banco, entra na lista de bloqueio e não recebe novo contato.

### História 7: captar novos candidatos (P2)

Como recrutador, quero receber pessoas por link de cadastro e por indicação, para o banco crescer com autorização.

**Teste independente:** gerar links, cadastrar perfis fictícios e registrar indicações. Tarefa T3.5 (#39).

1. **Dado** um link de cadastro, **quando** é gerado, **então** identifica a empresa e a origem.
2. **Dado** um cadastro sem autorização, **quando** é enviado, **então** a pessoa não entra no banco.
3. **Dada** uma indicação, **quando** é registrada, **então** o indicado recebe só um pedido de autorização.
4. **Dado** um token inválido, vencido ou de outra empresa, **quando** é usado, **então** o cadastro é recusado.

### História 8: recontato com proposta de valor (P2)

Como recrutador, quero manter o banco vivo sem cansar as pessoas, para elas continuarem respondendo.

**Teste independente:** simular históricos de contato e conferir quem pode ser recontatado. Tarefa T3.6 (#40).

1. **Dado** um contato nos últimos 90 dias, **quando** um recontato é avaliado, **então** ele não é enviado.
2. **Dado** um recontato, **quando** a mensagem é montada, **então** diz por que a pessoa foi contatada, o que ela ganha e traz o botão de saída.
3. **Dado** quem recusou ou saiu, **quando** um recontato é avaliado, **então** ele não é enviado.

### História 9: Nara simulada por MCP (P2)

Como time, quero a Nara simulada exposta como servidor MCP, para o conector da T1.12 ser testado de ponta a ponta e trocado pela Nara real só por configuração.

**Teste independente:** rodar a Nara simulada como servidor MCP local e usar o conector da T1.12 no lugar da chamada direta. Issue #42.

1. **Dada** a Nara simulada, **quando** é exposta por MCP, **então** oferece link de agendamento, agendamentos, entrega e resultados.
2. **Dado** o conector da T1.12, **quando** substitui a chamada direta, **então** os testes de `AgenteRecrutador` passam sem mudança.
3. **Dado** que o servidor MCP está fora do ar, **quando** a entrega é tentada, **então** o comportamento é o da História 4, cenário 6.

## Casos de borda

- Opt-out, clique no botão de saída ou agendamento com lembrete agendado.
- Resposta que chega depois do último lembrete ou depois do encerramento por silêncio.
- Mensagem ambígua, como "talvez" ou "depende do salário".
- Aceite e opt-out na mesma mensagem.
- Candidato da coleta sem contato público, com contato só em fonte de terceiros ou com contato que parece inferido.
- Mesmo contato público para duas pessoas, ou duas pessoas na mesma vaga com o mesmo e-mail.
- Botão de saída clicado duas vezes, por outra pessoa ou depois de os dados serem apagados.
- Candidato que aceita mas não agenda, ou que agenda, desmarca e agenda de novo.
- Resultado de entrevista sem aprovação humana, ou aprovação revertida.
- Falha do mensageiro depois de ele ter aceitado o envio.
- Nara simulada fora do ar ou lenta.
- Entrega repetida depois de reinício do serviço.
- Autorização que vence durante a conversa.
- Indicação de alguém que já está no banco, que saiu ou que foi removido.
- Token de cadastro reusado, vencido ou de outra empresa.
- Mensagem com instruções ao agente, vazia ou grande demais.
- Classificação inválida devolvida pelo modelo.
- Candidato que responde a um convite de outra vaga ou de outra empresa.

## Requisitos

### Funcionais

| ID | Requisito | Detalha |
|---|---|---|
| **FR-C001** | O convite DEVE conter a explicação da vaga, o que interessou no perfil, o link de agendamento da Nara, a origem do contato e o botão para não ser mais contatado. | FR-008 |
| **FR-C002** | Todo envio DEVE usar `Convite` com `chave_idempotencia` determinística, no formato `empresa:vaga:candidato:tipo:tentativa`, e repetir com a mesma chave NÃO DEVE gerar novo envio. | FR-012, FR-028 |
| **FR-C003** | Antes de qualquer envio, inclusive lembretes, follow-ups e recontatos, o sistema DEVE consultar `pode_contatar` (T1.1) e a lista de bloqueio. A frente NÃO DEVE reimplementar regras de autorização, opt-out ou limite. | FR-004, FR-021 |
| **FR-C004** | O sistema DEVE classificar cada resposta em aceite, recusa, dúvida, silêncio ou opt-out, e o opt-out DEVE ter prioridade sobre os demais. | FR-009 |
| **FR-C005** | Classificação inválida do modelo DEVE virar dúvida encaminhada a uma pessoa, nunca aceite. | FR-012 |
| **FR-C006** | O agente DEVE responder dúvidas só com o material da vaga e encaminhar a uma pessoa as que estiverem fora dele. | FR-009 |
| **FR-C007** | Sem resposta, o sistema DEVE enviar lembretes até `vaga.max_tentativas_contato`, contando o convite, com intervalo mínimo fixo entre tentativas. O intervalo padrão é de 3 dias, por decisão de design, e é configurável. | FR-033 |
| **FR-C008** | A decisão de enviar lembrete DEVE ser determinística, receber `hoje` como parâmetro e não usar modelo. Qualquer resposta ou agendamento cancela os lembretes pendentes. | FR-004, FR-033 |
| **FR-C009** | Ao esgotar as tentativas, o contato DEVE ser encerrado como silêncio, com decisão registrada. | FR-014 |
| **FR-C010** | Pedido de saída ou clique no botão de saída DEVE bloquear qualquer contato futuro, em todas as vagas da empresa, acionar a remoção no banco e manter a pessoa na lista de bloqueio depois que os dados forem apagados. | FR-020, FR-023, FR-032 |
| **FR-C011** | O pacote para a Nara DEVE ter vaga, candidato, motivo por critério, histórico, evidências com fonte, lacunas, pontos a aprofundar, ressalvas do revisor, autorização ou origem do contato, fonte e rastro. | FR-005, FR-010 |
| **FR-C012** | O pacote NÃO DEVE conter evidência sem trecho nem atributo sensível. | Constituição IV e VII |
| **FR-C013** | A entrega DEVE ocorrer por MCP só depois de a pessoa agendar com a Nara, uma única vez por chave, e falhas DEVEM deixá-la pendente para nova tentativa. | FR-010, FR-012 |
| **FR-C014** | O agente NÃO DEVE agendar entrevistas. Ele envia o link da Nara, e ela agenda. | FR-011 |
| **FR-C015** | O contato direto DEVE usar só um contato publicado pela própria pessoa, recebido da coleta com URL de origem e data, e NÃO DEVE usar contato inferido. Perfil do banco sem autorização e sem contato público DEVE receber só o pedido de autorização. | FR-021, FR-031 |
| **FR-C016** | A autorização DEVE ser registrada com validade, e a atualização por conversa DEVE alterar o perfil e a data de atualização. Candidato vindo da coleta só entra no banco se autorizar. | FR-020, FR-022 |
| **FR-C017** | O link de cadastro DEVE identificar empresa e origem e usar token verificável. Cadastro sem autorização NÃO DEVE entrar no banco. | FR-025 |
| **FR-C018** | O indicado DEVE receber só um pedido de autorização, e a indicação DEVE registrar quem indicou. | FR-025 |
| **FR-C019** | Recontato DEVE respeitar no máximo um contato a cada 90 dias, explicar o motivo, trazer o botão de saída e não alcançar quem recusou ou saiu. | FR-020, FR-023 |
| **FR-C020** | O modelo DEVE ser usado só para redigir mensagens, classificar respostas, responder dúvidas e extrair atualizações, sempre via `ClienteModelo` com `etapa` e saída validada por Pydantic. | Constituição I |
| **FR-C021** | Texto do candidato DEVE ir ao modelo entre delimitadores, declarado como dado. Instruções nele DEVEM ser ignoradas e gerar alerta. | Constituição VII |
| **FR-C022** | Mensagens NÃO DEVEM mudar, além do nome, ao trocar nome ou gênero do candidato. | Constituição VII, SC-003 |
| **FR-C023** | Convites, links, mensagens, pacotes, agendamentos e resultados da Nara simulada DEVEM trazer `simulado=True`. | FR-015 |
| **FR-C024** | Todo envio, classificação, entrega e follow-up DEVE gerar rastro com `@rastreado(etapa)` e evento do fluxo, com tokens, custo e tempo quando houver modelo. | FR-013, FR-014 |
| **FR-C025** | Toda leitura e escrita DEVE usar `empresa_id`, e resposta a convite de outra empresa DEVE ser recusada. | FR-018, FR-029 |
| **FR-C026** | A Nara simulada DEVE oferecer link fictício, agendamentos simulados, receber pacotes e devolver resultados reproduzíveis por semente. | FR-015, FR-016 |
| **FR-C027** | A Nara simulada DEVE poder ser exposta como servidor MCP local, para o conector da T1.12 implementar `AgenteRecrutador` sem mudar o fluxo. | FR-010 |
| **FR-C028** | O follow-up depois da entrevista DEVE ser enviado só com aprovação humana do resultado, comunicar os próximos passos aprovados e NÃO DEVE trazer notas nem avaliação da entrevista. | FR-034, Constituição II |
| **FR-C029** | O botão de saída DEVE funcionar com um clique, por um link com token próprio da empresa e do candidato, sem exigir login, e ser idempotente. | FR-032 |
| **FR-C030** | A empresa DEVE poder desligar a personalização do convite. Nesse caso, a mensagem é montada por código, sem modelo, e continua cumprindo FR-C001. | FR-008 |

### Entidades

Usa as entidades de `backend/contratos` com os nomes do #4: `Convite` (com `link_agendamento` opcional), `RespostaCandidato`, `PacoteContexto`, `ResultadoEntrevista`, `Candidato`, `Vaga` e `Decisao`. Os campos novos que o fluxo exige estão em "Questões para o time".

- **Lembrete:** um `Convite` de tipo `VAGA`, com tentativa maior que 1 na chave de idempotência.
- **Pedido de autorização:** um `Convite` de tipo `AUTORIZACAO`, sem link de agendamento.
- **Follow-up pós-entrevista:** uma mensagem com chave própria, criada só depois da aprovação humana.
- **Preferências de contato:** configuração da empresa, local da frente (`PreferenciasContato`), com personalização e canal.

## Critérios de sucesso

- **SC-C001**: Zero mensagens, inclusive lembretes, follow-ups e recontatos, a pessoas com opt-out, na lista de bloqueio ou sem base para contato (sem autorização e sem contato público).
- **SC-C002**: Zero convites, entregas ou follow-ups duplicados em reenvio, falha injetada e reinício.
- **SC-C003**: 100% dos convites com vaga, o que interessou no perfil, link de agendamento, origem do contato e botão de saída.
- **SC-C004**: 100% dos pacotes com todos os campos de FR-C011 e zero evidência sem trecho.
- **SC-C005**: Zero lembretes além de `max_tentativas_contato` ou antes do intervalo mínimo.
- **SC-C006**: 100% das mensagens com instruções embutidas geram alerta e nenhuma vira aceite.
- **SC-C007**: Trocar nome ou gênero não muda o conteúdo das mensagens, além do nome.
- **SC-C008**: 100% das dúvidas fora do material da vaga vão para uma pessoa.
- **SC-C009**: Zero pacotes entregues antes do agendamento e zero follow-ups sem aprovação humana.
- **SC-C010**: Zero mensagens para contato inferido ou sem URL de origem.

## Rastreabilidade

| FR da 001 | Requisitos desta spec | Tarefa |
|---|---|---|
| FR-008 | FR-C001, FR-C002, FR-C030 | T3.1 (#35) |
| FR-009 | FR-C004 a FR-C006 | T3.2 (#36) |
| FR-033 | FR-C007 a FR-C009 | T3.7, proposta (#41) |
| FR-010 | FR-C011 a FR-C013, FR-C027 | T3.3 (#37), #42 e T1.12 (#24) |
| FR-011 | FR-C014 | Todas |
| FR-034 | FR-C028 | Tarefa nova, proposta |
| FR-031, FR-032 | FR-C010, FR-C015, FR-C029 | T3.1, T3.4 e tarefa nova |
| FR-015 | FR-C023, FR-C026 | T3.1, T3.3 |
| FR-020, FR-022 | FR-C016 | T3.4 (#38) |
| FR-023 | FR-C010, FR-C019 | T3.4, T3.6 (#40) |
| FR-025 | FR-C017, FR-C018 | T3.5 (#39) |
| FR-004, FR-021 | FR-C003, FR-C008 | Consome T1.1 |
| FR-012, FR-028 | FR-C002, FR-C005, FR-C013 | T3.1, T3.3 |
| FR-013, FR-014 | FR-C009, FR-C024 | Todas, com T1.11 |
| FR-018, FR-029 | FR-C025 | Todas |

## Questões para o time

Nada aqui muda contrato. Cada item precisa de acordo das quatro frentes antes de virar mudança (#9).

1. **Contato público:** `Candidato` não tem contato. Proposta: `contato: ContatoPublico | None`, com `canal`, `endereco`, `url_origem` e `coletado_em`, preenchido pela coleta.
2. **Agendamento:** `AgenteRecrutador` não informa quem agendou, e a entrega depende disso. Proposta: `agendamentos(empresa_id, vaga_id) -> list[str]`, com os ids dos candidatos que agendaram. Outra opção é a Nara pedir o contexto por MCP no momento do agendamento.
3. **Botão de saída:** proposta de `Convite.link_saida: str | None`, gerado pela frente, e uma lista de bloqueio persistente por empresa, que guarda só o mínimo para impedir novo contato.
4. **Aprovação do follow-up:** onde fica a aprovação humana do resultado da entrevista? Proposta: uma `Decisao` com `responsavel` humano, ligada ao `ResultadoEntrevista`.
5. **Estado do contato no pacote:** a seção 6 do design pede, mas `PacoteContexto` não tem esse campo.
6. **Tarefas novas:** T3.7 (lembretes, #41), T3.8 (follow-up pós-entrevista) e T3.9 (botão de saída e lista de bloqueio). A Nara por MCP fica na #42, junto com a T1.12.
7. **Lembretes para quem veio da coleta:** usam o mesmo limite da vaga, ou só uma mensagem até a pessoa responder?
8. **Intervalo dos lembretes:** 3 dias é decisão de design. Confirmar com o time ou com recrutadores.

## Premissas

- Canais simulados. Sem WhatsApp, e-mail ou SMS reais no hackathon.
- Testes, avaliações e demo usam dados sintéticos, inclusive contatos públicos fictícios.
- Contato direto com pessoas reais só com a coleta real ligada, depois do acordo das quatro frentes (#8) e de parecer jurídico.
- A Nara simulada fica congelada no sábado, às 13h, se a Tako não der acesso de teste.
- Até as outras frentes entregarem, usar `backend/contratos/simulacoes.py`.
