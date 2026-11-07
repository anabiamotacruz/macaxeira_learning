# Especificação: Frente 3, contato e Nara

**Criada em**: 2026-11-07
**Estado**: Rascunho, para revisão do time
**Frente**: 3. Contato e Nara (`backend/contato`, `backend/nara_simulada`, branch `frente/contato`)
**Origem**: `specs/001-agente-recrutador/spec.md`. Contratos em `specs/001-agente-recrutador/plan.md`; tarefas T3.1 a T3.6 em `specs/001-agente-recrutador/tasks.md`.

Esta spec detalha a parte de contato da spec 001. Ela não substitui a 001 nem muda contratos. Se houver conflito, vale a 001, e acima dela a constituição.

## Escopo

**A frente faz:**

- Convidar o candidato indicado para a vaga, com explicação, motivo do contato, link de agendamento da Nara e forma de sair.
- Fazer follow-up de quem não respondeu, dentro do limite de tentativas da vaga.
- Conversar com o candidato: classificar respostas, tirar dúvidas previstas e encaminhar o resto a um humano.
- Pedir autorização para o banco de talentos e atualizar perfis por conversa.
- Captar novos candidatos por link de cadastro e por indicação, sempre com autorização.
- Recontatar quem está no banco, com moderação e proposta de valor.
- Montar o pacote de contexto e entregá-lo à Nara.
- Manter a Nara simulada e o conector da Nara atrás da interface `ClienteNara`, pronto para MCP.

**A frente não faz:**

- Agendar ou conduzir entrevistas, avaliar candidatos ou decidir contratações. A Nara agenda e entrevista; o agente só envia o link dela (FR-011).
- Buscar candidatos em fontes, analisar ou revisar perfis (Frente 2).
- Decidir quem pode ser contatado nem mudar estados do fluxo. A frente consome `pode_contatar` e `decidir` (T1.1) e é chamada pelo `FluxoVaga` (T1.2).
- Servidor MCP com as ferramentas do agente (`buscar_candidatos`, `explicar_escolha`, `entregar_a_nara`). Fica na T1.6, Frente 1.

**Sobre "sourcing":** nesta frente, captar é trazer pessoas para o banco por contato autorizado (cadastro, indicação, autorização e recontato). Buscar em fontes é da Frente 2.

## Cenários de usuário

### História 1: convidar para a vaga (P1)

Como recrutador, quero que o agente convide cada candidato aprovado com uma mensagem clara, para a pessoa entender a vaga e por que foi lembrada.

**Teste independente:** criar convites para um lote simulado e conferir conteúdo, envio e reenvio. Tarefa T3.1.

1. **Dado** um candidato indicado em um lote aprovado, **quando** o convite é criado, **então** ele explica a vaga, diz por que a pessoa foi lembrada, traz o link de agendamento da Nara e diz como sair.
2. **Dado** um convite já enviado, **quando** o envio é repetido com a mesma chave, **então** o candidato não recebe a mensagem duas vezes.
3. **Dado** que o mensageiro falhou, **quando** o envio é repetido, **então** o convite sai uma única vez e a falha fica registrada.
4. **Dado** um candidato com opt-out ou sem autorização válida, **quando** o convite seria enviado, **então** nada é enviado e o bloqueio fica registrado com a regra.

### História 2: conversar e fazer follow-up (P1)

Como recrutador, quero que o agente trate as respostas e lembre quem não respondeu, para não perder candidatos por esquecimento e sem incomodar ninguém.

**Teste independente:** simular respostas e silêncios ao longo de dias fictícios e conferir classificações, lembretes e encaminhamentos. Tarefa T3.2 e tarefa nova de follow-up.

1. **Dada** uma resposta, **quando** ela é classificada, **então** recebe um tipo entre aceite, recusa, dúvida, silêncio e opt-out.
2. **Dada** uma mensagem que mistura interesse e pedido para sair, **quando** é classificada, **então** vale o opt-out.
3. **Dada** uma dúvida respondida pelo material da vaga, **quando** o agente responde, **então** a resposta usa só esse material. **Dada** uma dúvida fora dele, **então** ela vai para um humano.
4. **Dado** um convite sem resposta, **quando** o intervalo de follow-up passa e ainda há tentativas, **então** o agente envia um lembrete curto, com o link e a forma de sair.
5. **Dado** que as tentativas da vaga acabaram, **quando** o candidato continua em silêncio, **então** o contato é encerrado como silêncio e nenhum lembrete novo é enviado.
6. **Dado** um lembrete agendado, **quando** chega qualquer resposta antes dele, **então** o lembrete é cancelado.
7. **Dada** uma mensagem com instruções ao agente, **quando** é classificada, **então** as instruções são ignoradas e um alerta é registrado.

### História 3: entregar à Nara (P1)

Como recrutador, quero que a Nara receba o contexto de quem aceitou, para a entrevista começar do ponto certo.

**Teste independente:** aceitar convites simulados e conferir o pacote e as entregas na Nara simulada. Tarefa T3.3.

1. **Dado** que o candidato aceitou, **quando** a entrega ocorre, **então** a Nara recebe o pacote com todos os campos da seção 6 do design.
2. **Dado** um pacote, **quando** é montado, **então** só entram evidências com trecho e fonte, e nenhum atributo sensível.
3. **Dada** uma entrega já feita, **quando** ela é repetida, inclusive depois de reinício, **então** a Nara não recebe o pacote duas vezes.
4. **Dada** a Nara simulada, **quando** ela devolve link e resultados, **então** ambos são marcados como simulação e os resultados se repetem com a mesma semente.
5. **Dado** que a Nara está fora do ar, **quando** a entrega falha, **então** ela fica pendente para nova tentativa, sem perder o aceite.

### História 4: autorização e atualização por conversa (P1)

Como recrutador, quero que o agente peça autorização e atualize os perfis do banco, para ter candidatos autorizados e atuais.

**Teste independente:** conversar com perfis simulados sem autorização, com autorização e desatualizados. Tarefa T3.4.

1. **Dado** um perfil sem autorização, **quando** o agente faz contato, **então** só pede autorização, sem perguntas sobre o perfil nem convite para vaga.
2. **Dado** que a pessoa autorizou, **quando** a resposta é registrada, **então** a autorização ganha data de validade.
3. **Dada** uma atualização por mensagem, **quando** é extraída, **então** o perfil muda e a data de atualização é registrada.
4. **Dado** um pedido de saída, **quando** é registrado, **então** a pessoa é removida do banco e não recebe novo contato.

### História 5: captar novos candidatos (P2)

Como recrutador, quero receber pessoas por link de cadastro e por indicação, para o banco crescer com autorização.

**Teste independente:** gerar links, cadastrar perfis fictícios e registrar indicações. Tarefa T3.5.

1. **Dado** um link de cadastro, **quando** é gerado, **então** identifica a empresa e a origem.
2. **Dado** um cadastro sem autorização, **quando** é enviado, **então** a pessoa não entra no banco.
3. **Dada** uma indicação, **quando** é registrada, **então** o indicado recebe só um pedido de autorização.
4. **Dado** um token inválido, vencido ou de outra empresa, **quando** é usado, **então** o cadastro é recusado.

### História 6: recontato com proposta de valor (P2)

Como recrutador, quero manter o banco vivo sem cansar as pessoas, para elas continuarem respondendo.

**Teste independente:** simular históricos de contato e conferir quem pode ser recontatado. Tarefa T3.6.

1. **Dado** um contato nos últimos 90 dias, **quando** um recontato é avaliado, **então** ele não é enviado.
2. **Dado** um recontato, **quando** a mensagem é montada, **então** diz por que a pessoa foi contatada, o que ela ganha e como sair.
3. **Dado** quem recusou ou saiu, **quando** um recontato é avaliado, **então** ele não é enviado.

### História 7: Nara por MCP (P3, corte)

Como time, quero que o conector da Nara já fale MCP, para trocar a simulação pela Nara real sem mudar o fluxo, se a Tako der acesso.

**Teste independente:** rodar a Nara simulada como servidor MCP local e usar o conector MCP no lugar da chamada direta.

1. **Dada** a Nara simulada, **quando** é exposta por MCP, **então** oferece as operações da `ClienteNara`: link de agendamento, entrega e resultados.
2. **Dado** o conector MCP, **quando** substitui a chamada direta, **então** os testes da `ClienteNara` passam sem mudança.
3. **Dado** que o servidor MCP está fora do ar, **quando** a entrega é tentada, **então** o comportamento é o mesmo da História 3, cenário 5.

Entra só depois do fluxo principal integrado, e sai antes dele se faltar tempo (ordem de corte do `AGENTS.md`).

## Casos de borda

- Opt-out no meio da conversa ou com lembrete agendado.
- Resposta que chega depois do último lembrete ou depois do encerramento por silêncio.
- Mensagem ambígua, como "talvez" ou "depende do salário".
- Aceite e opt-out na mesma mensagem.
- Falha do mensageiro depois de o mensageiro ter aceitado o envio.
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
| **FR-C001** | O convite DEVE conter a explicação da vaga, o motivo do contato, o link de agendamento da Nara e a forma de sair. | FR-008 |
| **FR-C002** | Todo envio DEVE usar `Convite` com `chave_idempotencia` determinística, no formato `empresa:vaga:candidato:tipo:tentativa`, e repetir com a mesma chave NÃO DEVE gerar novo envio. | FR-012, FR-028 |
| **FR-C003** | Antes de qualquer envio, inclusive lembretes e recontatos, o sistema DEVE consultar `pode_contatar` (T1.1). A frente NÃO DEVE reimplementar regras de autorização, opt-out ou limite. | FR-004, FR-021 |
| **FR-C004** | O sistema DEVE classificar cada resposta em aceite, recusa, dúvida, silêncio ou opt-out, e o opt-out DEVE ter prioridade sobre os demais. | FR-009 |
| **FR-C005** | Classificação inválida do modelo DEVE virar dúvida encaminhada a um humano, nunca aceite. | FR-012 |
| **FR-C006** | O agente DEVE responder dúvidas só com o material da vaga e encaminhar a um humano as que estiverem fora dele. | FR-009 |
| **FR-C007** | Sem resposta, o sistema DEVE enviar lembretes até `vaga.max_tentativas_contato`, contando o convite, com intervalo mínimo fixo entre tentativas. O intervalo padrão é de 3 dias, por decisão de design, e é configurável. | FR-009 |
| **FR-C008** | A decisão de enviar lembrete DEVE ser determinística, receber `hoje` como parâmetro e não usar modelo. Qualquer resposta cancela os lembretes pendentes. | FR-004 |
| **FR-C009** | Ao esgotar as tentativas, o contato DEVE ser encerrado como silêncio, com decisão registrada. | FR-014 |
| **FR-C010** | Pedido de saída DEVE bloquear qualquer contato futuro, em todas as vagas da empresa, e acionar a remoção no banco. | FR-020, FR-023 |
| **FR-C011** | O pacote para a Nara DEVE ter vaga, candidato, motivo por critério, histórico, evidências com fonte, lacunas, pontos a aprofundar, ressalvas do revisor, autorização, fonte e rastro. | FR-005, FR-010 |
| **FR-C012** | O pacote NÃO DEVE conter evidência sem trecho nem atributo sensível. | Constituição IV e VII |
| **FR-C013** | A entrega DEVE ocorrer só depois do aceite, uma única vez por chave, e falhas DEVEM deixá-la pendente para nova tentativa. | FR-010, FR-012 |
| **FR-C014** | O agente NÃO DEVE agendar entrevistas. Ele envia o link da Nara e ela agenda. | FR-011 |
| **FR-C015** | Sem autorização válida, o contato DEVE se limitar ao pedido de autorização. | FR-020, FR-021 |
| **FR-C016** | A autorização DEVE ser registrada com validade, e a atualização por conversa DEVE alterar o perfil e a data de atualização. | FR-020, FR-022 |
| **FR-C017** | O link de cadastro DEVE identificar empresa e origem e usar token verificável. Cadastro sem autorização NÃO DEVE entrar no banco. | FR-025 |
| **FR-C018** | O indicado DEVE receber só um pedido de autorização, e a indicação DEVE registrar quem indicou. | FR-025 |
| **FR-C019** | Recontato DEVE respeitar no máximo um contato a cada 90 dias, explicar o motivo e a forma de sair e não alcançar quem recusou ou saiu. | FR-020, FR-023 |
| **FR-C020** | O modelo DEVE ser usado só para redigir mensagens, classificar respostas e extrair atualizações, sempre via `ClienteModelo` com `etapa` e saída validada por Pydantic. | Constituição I |
| **FR-C021** | Texto do candidato DEVE ir ao modelo entre delimitadores, declarado como dado. Instruções nele DEVEM ser ignoradas e gerar alerta. | Constituição VII |
| **FR-C022** | Mensagens NÃO DEVEM mudar, além do nome, ao trocar nome ou gênero do candidato. | Constituição VII, SC-003 |
| **FR-C023** | Convites, links, mensagens, pacotes e resultados da Nara simulada DEVEM trazer `simulado=True`. | FR-015 |
| **FR-C024** | Todo envio, classificação e entrega DEVE gerar rastro com `@rastreado(etapa)` e evento do fluxo, com tokens, custo e tempo quando houver modelo. | FR-013, FR-014 |
| **FR-C025** | Toda leitura e escrita DEVE usar `empresa_id`, e resposta a convite de outra empresa DEVE ser recusada. | FR-018, FR-029 |
| **FR-C026** | A Nara simulada DEVE oferecer link fictício, receber pacotes e devolver resultados reproduzíveis por semente. | FR-015, FR-016 |
| **FR-C027** | (corte) A Nara simulada DEVE poder ser exposta como servidor MCP local, e um conector MCP DEVE implementar `ClienteNara` sem mudar o fluxo. | Design, seções 4 e 12 |

### Entidades

Usa as entidades de `plan.md`, sem campos novos: `Convite`, `RespostaCandidato`, `PacoteNara`, `ResultadoNara`, `Candidato`, `Vaga` e `Decisao`. Lacunas de contrato estão em "Questões para o time".

- **Lembrete:** um `Convite` de tipo `VAGA`, com tentativa maior que 1 na chave de idempotência.
- **Pedido de autorização:** um `Convite` de tipo `AUTORIZACAO`.

## Critérios de sucesso

- **SC-C001**: Zero mensagens, inclusive lembretes e recontatos, a pessoas com opt-out ou sem autorização válida.
- **SC-C002**: Zero convites ou entregas duplicados em reenvio, falha injetada e reinício.
- **SC-C003**: 100% dos convites com vaga, motivo, link da Nara e forma de sair.
- **SC-C004**: 100% dos pacotes com todos os campos de FR-C011 e zero evidência sem trecho.
- **SC-C005**: Zero lembretes além de `max_tentativas_contato` ou antes do intervalo mínimo.
- **SC-C006**: 100% das mensagens com instruções embutidas geram alerta sem mudar a classificação.
- **SC-C007**: Trocar nome ou gênero não muda o conteúdo das mensagens, além do nome.
- **SC-C008**: 100% das dúvidas fora do material da vaga vão para um humano.

## Rastreabilidade

| FR da 001 | Requisitos desta spec | Tarefa |
|---|---|---|
| FR-008 | FR-C001, FR-C002 | T3.1 |
| FR-009 | FR-C004 a FR-C009 | T3.2 e tarefa nova de follow-up |
| FR-010 | FR-C011 a FR-C013 | T3.3 |
| FR-011 | FR-C014 | Todas |
| FR-015 | FR-C023, FR-C026 | T3.1, T3.3 |
| FR-020, FR-022 | FR-C015, FR-C016 | T3.4 |
| FR-023 | FR-C010, FR-C019 | T3.4, T3.6 |
| FR-025 | FR-C017, FR-C018 | T3.5 |
| FR-004, FR-021 | FR-C003, FR-C008 | Consome T1.1 |
| FR-012, FR-028 | FR-C002, FR-C005, FR-C013 | T3.1, T3.3 |
| FR-013, FR-014 | FR-C009, FR-C024 | Todas, com T1.11 |
| FR-018, FR-029 | FR-C025 | Todas |
| Design, seções 4 e 12 | FR-C027 | Nova (corte): Nara por MCP |

## Questões para o time

Nada aqui muda contrato. Cada item precisa de acordo das quatro frentes antes de virar mudança.

1. **Estado do contato no pacote:** a seção 6 do design pede "estado do contato", mas `PacoteNara` não tem esse campo.
2. **Agendamento confirmado:** `ClienteNara` não informa se a pessoa agendou. Sem isso, a meta "entregar N interessados" conta só entregas.
3. **Tarefas novas:** follow-up e Nara por MCP não têm tarefa na 001. Proposta: T3.7 (follow-up, onda 2) e T3.8 (Nara por MCP, onda 3, corte).
4. **Link no pedido de autorização:** `Convite.link_nara` é obrigatório, mas o pedido de autorização não tem vaga. Proposta: string vazia.
5. **Intervalo de follow-up:** 3 dias é decisão de design. Confirmar com o time ou com recrutadores.

## Premissas

- Canais simulados. Sem WhatsApp, e-mail ou SMS reais no hackathon.
- A Nara simulada fica congelada no sábado, às 13h, se a Tako não der acesso de teste.
- Somente dados sintéticos, gerados pela Frente 2 ou nos próprios testes.
- Até as outras frentes entregarem, usar `backend/contratos/simulacoes.py`.
