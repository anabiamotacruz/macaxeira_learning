# Especificação: Frente 3, contato e Nara

**Criada em**: 2026-11-07
**Atualizada em**: 2026-11-07, para seguir a arquitetura de coleta e contato (`docs/superpowers/specs/2026-11-07-arquitetura-coleta-e-agente.md`, #50) e o fluxo de contato direto (#49)
**Estado**: Rascunho, para revisão do time. Contato com pessoas reais depende do acordo das quatro frentes (#8) e de parecer jurídico.
**Frente**: 3. Contato e Nara (`backend/contato`, `backend/nara_simulada`, branches `frente/contato` e `frente/contato-*`)
**Origem**: `specs/001-agente-recrutador/spec.md` e a arquitetura do #50. Contratos em `backend/contratos`. Tarefas em `specs/001-agente-recrutador/tasks.md` e nas issues #34 a #42.

Esta spec detalha a parte de contato. Ela não muda contratos. Se houver conflito, vale a constituição. Nos pontos de contato, segue a arquitetura do #50 (seções 8, 9 e 14), e as divergências com a spec 001 estão em "Questões para o time".

## Fluxo do produto

Etapas da arquitetura do #50, seção 8. Em negrito, o que é desta frente.

1. A empresa informa a vaga, e o agente propõe os critérios para aprovação (Frente 1).
2. Hunting: jobs coletam perfis em fontes públicas e provedores contratados, como Bright Data e People Data Labs, e gravam versões com a fonte de cada informação (Frente 1).
3. Triar, ranquear, analisar com visão cega, revisar e decidir (Frente 1).
4. O recrutador aprova o lote de contato (Frente 1 e painel).
5. **E-mail inicial: o agente redige, o código monta, confere a supressão e os limites e envia. O e-mail diz o que interessou no perfil e de onde veio o contato, e traz o link de exclusão e o link do WhatsApp.**
6. **No máximo um lembrete por vaga para quem não respondeu.**
7. **O candidato chama no WhatsApp. O agente tira dúvidas e faz a pré-triagem, com um roteiro aprovado junto com a vaga.**
8. **Validar e entregar: se o candidato passa na pré-triagem, o agente envia o link de agendamento da Nara, e o pacote de contexto vai para a Nara por MCP. Caso ambíguo vai para uma pessoa.**
9. A Nara agenda e entrevista. Contratação e avaliação são humanas.
10. Aprender com os resultados, com aprovação humana (Frente 1).

## Escopo

**A frente faz:**

- E-mail inicial para o candidato aprovado no lote, pelo e-mail que ele mesmo publicou para contato.
- Um lembrete por vaga, no máximo.
- Respostas por e-mail: classificar e aplicar a exclusão em código, na hora.
- Conversa no WhatsApp, iniciada pelo candidato: dúvidas com o material da vaga e pré-triagem pelo roteiro.
- Validação da pré-triagem, envio do link da Nara e montagem do pacote de contexto.
- Lista de supressão no contato: link de exclusão, "sair" no WhatsApp e consulta antes de cada envio.
- Pedido de autorização para o banco de talentos e atualização de perfis por conversa.
- Recontato de quem está no banco, com moderação.
- Simuladores dos canais (e-mail e WhatsApp) e da Nara, que imitam o formato das APIs reais (#50, seção 13). A Nara simulada também é exposta como servidor MCP.

**A frente não faz:**

- Agendar ou conduzir entrevistas, avaliar candidatos ou decidir contratações. A Nara agenda e entrevista; a pré-triagem é uma conversa curta antes dela e não a substitui.
- Coletar, triar, ranquear, analisar ou decidir quem é indicado (Frente 1). A coleta entrega o contato público com a origem; esta frente só o usa.
- Coletar telefone. O número chega quando o candidato chama no WhatsApp.
- Decidir quem pode ser contatado nem mudar estados do fluxo. A frente consome `pode_contatar` e `decidir` (T1.1) e é chamada pelo fluxo (T1.2).
- O conector MCP que chama a Nara (T1.12) e o servidor MCP com as ferramentas do agente (T1.6), ambos da Frente 1.

## Cenários de usuário

### História 1: e-mail inicial (P1)

Como recrutador, quero que o agente envie um e-mail individual e personalizado a cada candidato aprovado, para a pessoa entender a vaga, saber de onde veio o contato e escolher se quer conversar.

**Teste independente:** criar e-mails para um lote simulado, com contatos públicos fictícios, e conferir conteúdo, envio e reenvio no simulador de e-mail. Tarefa T3.1 (#35).

1. **Dado** um candidato do lote aprovado, com e-mail publicado para contato, **quando** o e-mail é criado, **então** ele traz a empresa e a vaga, o motivo da escolha, a origem do contato, o link de exclusão, o cabeçalho `List-Unsubscribe` e o link `wa.me` com o código do convite.
2. **Dado** um candidato sem e-mail publicado para contato, **quando** o e-mail seria criado, **então** nada é enviado, nenhum endereço é inferido, e o candidato fica como "sem canal".
3. **Dada** uma empresa que desligou a personalização, **quando** o e-mail é criado, **então** a mensagem é montada por código, sem modelo.
4. **Dado** um e-mail já enviado, **quando** o envio é repetido com a mesma chave, **então** o candidato não recebe duas vezes.
5. **Dado** que o provedor de e-mail falhou, **quando** o envio é repetido, **então** o e-mail sai uma única vez e a falha fica registrada.
6. **Dado** um candidato na lista de supressão, **quando** o e-mail seria enviado, **então** nada é enviado e o bloqueio fica registrado com a regra.

### História 2: lembrete (P1)

Como recrutador, quero um único lembrete para quem não respondeu, para não perder candidatos sem incomodar ninguém.

**Teste independente:** simular silêncios ao longo de dias fictícios e conferir o lembrete. Tarefa T3.7 (#41).

1. **Dado** um e-mail sem resposta, **quando** o intervalo mínimo passa, **então** o agente envia um lembrete curto, com a origem do contato, o link de exclusão e o link do WhatsApp.
2. **Dado** que o lembrete já foi enviado, **quando** o candidato continua em silêncio, **então** o contato é encerrado como silêncio e nada mais é enviado nessa vaga.
3. **Dado** um lembrete agendado, **quando** chega qualquer resposta, mensagem no WhatsApp ou pedido de exclusão, **então** o lembrete é cancelado.

### História 3: respostas por e-mail (P1)

Como recrutador, quero que as respostas por e-mail sejam entendidas, para tratar interesse, dúvida, recusa e exclusão sem demora.

**Teste independente:** simular respostas no webhook do e-mail e conferir as classificações. Tarefa T3.2 (#36).

1. **Dada** uma resposta por e-mail, **quando** ela é classificada, **então** recebe um tipo entre aceite, recusa, dúvida, silêncio e opt-out.
2. **Dada** uma mensagem que mistura interesse e pedido de exclusão, **quando** é classificada, **então** vale a exclusão, aplicada em código na hora.
3. **Dada** uma resposta de interesse por e-mail, **quando** é registrada, **então** o agente responde com o link do WhatsApp para a pré-triagem.
4. **Dada** uma mensagem com instruções ao agente, **quando** é classificada, **então** as instruções são ignoradas, um alerta é registrado e a mensagem não vira aceite.

### História 4: conversa e pré-triagem no WhatsApp (P1)

Como recrutador, quero que o candidato tire dúvidas e responda uma pré-triagem curta no WhatsApp, para só os interessados e compatíveis seguirem para a Nara.

**Teste independente:** o jurado faz o papel do candidato no simulador do WhatsApp, com dúvidas, respostas da pré-triagem e pedido de saída. Tarefas T3.2 (#36) e T3.9, proposta.

1. **Dado** que o candidato mandou a primeira mensagem com o código do convite, **quando** a conversa começa, **então** ela fica ligada ao convite certo, sem expor dados pessoais.
2. **Dada** uma dúvida respondida pelo material da vaga, **quando** o agente responde, **então** a resposta usa só esse material. **Dada** uma dúvida fora dele, **então** ela vai para uma pessoa.
3. **Dado** o roteiro de pré-triagem aprovado com a vaga, **quando** o agente pergunta, **então** segue o roteiro, e perguntas sobre idade, gênero, estado civil, religião, saúde ou outros dados sensíveis são bloqueadas em código.
4. **Dada** uma resposta da pré-triagem, **quando** é extraída, **então** vira dado estruturado validado, e o texto do candidato nunca vira instrução.
5. **Dada** uma mensagem fora da janela de 24 horas, **quando** o agente precisa escrever, **então** só usa template aprovado e com o opt-in que o candidato deu na conversa.
6. **Dado** que o candidato escreveu "sair" ou equivalente, **quando** a mensagem chega, **então** ele entra na lista de supressão na hora.

### História 5: validar e entregar à Nara (P1)

Como recrutador, quero que quem passou na pré-triagem receba o link da Nara e que a Nara receba o contexto, para a entrevista começar do ponto certo.

**Teste independente:** concluir pré-triagens simuladas e conferir o link enviado e as entregas por MCP na Nara simulada. Tarefa T3.3 (#37), com o conector da T1.12.

1. **Dado** que o candidato passou na pré-triagem, **quando** o código valida, **então** o agente envia o link de agendamento da Nara e o pacote vai para a Nara por MCP.
2. **Dado** um resultado ambíguo, **quando** o código valida, **então** a decisão vai para uma pessoa, e nada é enviado antes dela.
3. **Dado** que o candidato não passou, **quando** o código valida, **então** recebe uma resposta respeitosa, com a opção de entrar no banco de talentos, e nenhum pacote é enviado.
4. **Dado** um pacote, **quando** é montado, **então** só entram evidências com trecho e fonte, a confiança de cada uma e as respostas da pré-triagem, sem atributo sensível.
5. **Dada** uma entrega já feita, **quando** ela é repetida, inclusive depois de reinício, **então** a Nara não recebe o pacote duas vezes.
6. **Dado** que a Nara está fora do ar, **quando** a entrega falha, **então** ela fica pendente para nova tentativa, sem perder a validação.

### História 6: autorização e atualização por conversa (P1)

Como recrutador, quero que o agente peça autorização para o banco de talentos e atualize os perfis, para ter candidatos autorizados e atuais nas próximas vagas.

**Teste independente:** conversar com perfis simulados sem autorização, com autorização e desatualizados. Tarefa T3.4 (#38).

1. **Dado** um perfil do banco sem autorização e sem contato publicado, **quando** o agente faz contato, **então** só pede autorização, sem perguntas sobre o perfil.
2. **Dado** um candidato vindo do hunting, **quando** o contato da vaga termina, **então** ele só entra no banco se autorizar. Sem isso, o perfil expira no prazo de retenção.
3. **Dado** que a pessoa autorizou, **quando** a resposta é registrada, **então** a autorização ganha data de validade.
4. **Dada** uma atualização por mensagem, **quando** é extraída, **então** o perfil muda e a data de atualização é registrada.
5. **Dado** um pedido de exclusão, **quando** é registrado, **então** os dados são apagados e só o hash fica na lista de supressão.

### História 7: recontato com proposta de valor (P2)

Como recrutador, quero manter o banco vivo sem cansar as pessoas, para elas continuarem respondendo.

**Teste independente:** simular históricos de contato e conferir quem pode ser recontatado. Tarefa T3.6 (#40).

1. **Dado** um contato nos últimos 90 dias, **quando** um recontato é avaliado, **então** ele não é enviado.
2. **Dado** um recontato, **quando** a mensagem é montada, **então** diz por que a pessoa foi contatada, o que ela ganha e traz o link de exclusão.
3. **Dado** quem recusou ou está na lista de supressão, **quando** um recontato é avaliado, **então** ele não é enviado.

### História 8: Nara simulada por MCP (P2)

Como time, quero a Nara simulada exposta como servidor MCP, para o conector da T1.12 ser testado de ponta a ponta e trocado pela Nara real só por configuração.

**Teste independente:** rodar a Nara simulada como servidor MCP local e usar o conector da T1.12 no lugar da chamada direta. Issue #42.

1. **Dada** a Nara simulada, **quando** é exposta por MCP, **então** oferece link de agendamento, entrega e resultados, sempre marcados como simulação.
2. **Dado** o conector da T1.12, **quando** substitui a chamada direta, **então** os testes de `AgenteRecrutador` passam sem mudança.
3. **Dado** que o servidor MCP está fora do ar, **quando** a entrega é tentada, **então** o comportamento é o da História 5, cenário 6.

## Casos de borda

- Pedido de exclusão com lembrete agendado ou no meio da pré-triagem.
- Resposta que chega depois do lembrete ou depois do encerramento por silêncio.
- Mensagem ambígua, como "talvez" ou "depende do salário".
- Interesse e exclusão na mesma mensagem.
- Candidato sem e-mail publicado, com e-mail só em fonte de terceiros ou com e-mail que parece inferido.
- O mesmo e-mail para duas pessoas, ou duas pessoas da mesma vaga com o mesmo e-mail.
- Link de exclusão clicado duas vezes, por outra pessoa ou depois de os dados serem apagados.
- Mensagem no WhatsApp sem código de convite, com código de outra empresa ou com código já usado.
- Candidato que volta a escrever depois da janela de 24 horas.
- Candidato que tenta responder perguntas sensíveis ou que pede para pular a pré-triagem.
- Taxa de rejeição de e-mail alta: os envios pausam com alerta (#50, seção 10).
- Falha do provedor depois de ele ter aceitado o envio.
- Nara simulada fora do ar ou lenta.
- Entrega repetida depois de reinício do serviço.
- Autorização que vence durante a conversa.
- Mensagem com instruções ao agente, vazia ou grande demais.
- Classificação ou extração inválida devolvida pelo modelo.

## Requisitos

### Funcionais

| ID | Requisito | Detalha |
|---|---|---|
| **FR-C001** | O e-mail inicial DEVE conter empresa e vaga, o motivo da escolha em uma frase, a origem do contato, o link de exclusão, o cabeçalho `List-Unsubscribe` e o link `wa.me` com o código do convite. O código DEVE conferir esses itens antes do envio. | FR-008, #50 §9 |
| **FR-C002** | Todo envio DEVE ter `chave_idempotencia` determinística, no formato `empresa:vaga:candidato:tipo:tentativa`, e repetir com a mesma chave NÃO DEVE gerar novo envio. | FR-012, FR-028 |
| **FR-C003** | Antes de qualquer envio, o sistema DEVE consultar `pode_contatar` (T1.1) e a lista de supressão. A frente NÃO DEVE reimplementar regras de autorização, opt-out ou limite. | FR-004, FR-021 |
| **FR-C004** | O contato DEVE usar só um e-mail que a própria pessoa publicou para contato, recebido do hunting com a fonte. NÃO DEVE usar e-mail inferido, tirado de commits ou de listas compradas, nem coletar telefone. | FR-031, #50 §3 |
| **FR-C005** | O e-mail DEVE ser individual e personalizado, sem pixel de rastreamento, com limite diário por domínio de envio e por empresa. | #50 §9 |
| **FR-C006** | Sem resposta, o sistema DEVE enviar no máximo um lembrete por vaga, depois de um intervalo mínimo configurável (padrão de 3 dias, por decisão de design). | #50 §9 |
| **FR-C007** | A decisão de enviar o lembrete DEVE ser determinística, receber `hoje` como parâmetro e não usar modelo. Qualquer resposta, mensagem no WhatsApp ou exclusão cancela o lembrete. | FR-004 |
| **FR-C008** | Sem resposta depois do lembrete, o contato DEVE ser encerrado como silêncio, com decisão registrada. | FR-014 |
| **FR-C009** | O sistema DEVE classificar cada resposta em aceite, recusa, dúvida, silêncio ou opt-out, e o opt-out DEVE ter prioridade e ser aplicado em código. | FR-009 |
| **FR-C010** | Classificação ou extração inválida do modelo DEVE ir para uma pessoa, nunca virar aceite ou aprovação na pré-triagem. | FR-012 |
| **FR-C011** | A conversa no WhatsApp DEVE começar só por iniciativa do candidato. Fora da janela de 24 horas, só com template aprovado e com o opt-in dado na conversa. | #50 §9 |
| **FR-C012** | A conversa DEVE ser ligada ao convite pelo código curto do link `wa.me`, sem expor dados pessoais, e código de outra empresa DEVE ser recusado. | FR-018, #50 §9 |
| **FR-C013** | O agente DEVE responder dúvidas só com o material da vaga e encaminhar a uma pessoa as que estiverem fora dele. | FR-009 |
| **FR-C014** | A pré-triagem DEVE seguir o roteiro aprovado com a vaga. Perguntas sobre dados sensíveis DEVEM ser bloqueadas em código, e as respostas DEVEM virar dados estruturados validados por Pydantic. | FR-002, #50 §9 |
| **FR-C015** | A validação da pré-triagem DEVE ser feita em código. Caso ambíguo DEVE ir para uma pessoa. Quem não passa recebe uma resposta respeitosa e a opção de entrar no banco de talentos. | FR-004, Constituição II |
| **FR-C016** | Quem passa na pré-triagem DEVE receber o link de agendamento da Nara, e o pacote DEVE ser entregue à Nara por MCP nesse momento, uma única vez por chave. Falhas DEVEM deixar a entrega pendente para nova tentativa. | FR-010, #50 §8 |
| **FR-C017** | O pacote para a Nara DEVE ter vaga, candidato, motivo por critério, histórico, evidências com fonte e confiança, lacunas, pontos a aprofundar, ressalvas do revisor, respostas da pré-triagem, origem do contato, fonte e rastro. | FR-005, FR-010 |
| **FR-C018** | O pacote NÃO DEVE conter evidência sem trecho nem atributo sensível. | Constituição IV e VII |
| **FR-C019** | O agente NÃO DEVE agendar entrevistas. Ele envia o link da Nara, e ela agenda. A pré-triagem NÃO DEVE substituir a entrevista. | FR-011 |
| **FR-C020** | Link de exclusão, cabeçalho `List-Unsubscribe` e "sair" no WhatsApp DEVEM pôr a pessoa na lista de supressão na hora, por um clique e sem login, de forma idempotente. A lista guarda só o hash do e-mail e das identidades, e o resto dos dados é apagado. | FR-020, FR-023, FR-032, #50 §5 |
| **FR-C021** | Perfil do banco sem autorização e sem contato publicado DEVE receber só o pedido de autorização. A autorização DEVE ter validade, e a atualização por conversa DEVE alterar o perfil e a data de atualização. Candidato do hunting só entra no banco se autorizar. | FR-020, FR-021, FR-022 |
| **FR-C022** | Retirado: o produto busca os candidatos e não recebe cadastros (T3.5 cancelada, #39). | — |
| **FR-C023** | Retirado: o produto não recebe indicações (T3.5 cancelada, #39). | — |
| **FR-C024** | Recontato DEVE respeitar no máximo um contato a cada 90 dias, explicar o motivo, trazer o link de exclusão e não alcançar quem recusou ou está na lista de supressão. | FR-020, FR-023 |
| **FR-C025** | O modelo DEVE ser usado só para redigir mensagens, classificar respostas, conversar, responder dúvidas e extrair respostas e atualizações, sempre via `ClienteModelo` com `etapa` e saída validada por Pydantic. Regras, limites, supressão e validação ficam em código. | Constituição I |
| **FR-C026** | Texto do candidato DEVE ir ao modelo entre delimitadores, declarado como dado. Instruções nele DEVEM ser ignoradas e gerar alerta visível. | Constituição VII |
| **FR-C027** | Mensagens NÃO DEVEM mudar, além do nome, ao trocar nome ou gênero do candidato. O modelo recebe o nome só como marcador. | Constituição VII, SC-003 |
| **FR-C028** | A empresa DEVE poder desligar a personalização do e-mail. Nesse caso, a mensagem é montada por código, sem modelo, e continua cumprindo FR-C001. | FR-008 |
| **FR-C029** | Os simuladores de e-mail, WhatsApp e Nara DEVEM imitar o formato das APIs reais (envio, rejeição, webhook e janela de 24 horas), e tudo o que eles produzem DEVE ser marcado como simulação. | FR-015, #50 §13 |
| **FR-C030** | A Nara simulada DEVE oferecer link fictício, receber pacotes e devolver resultados reproduzíveis por semente, e DEVE poder ser exposta como servidor MCP local para o conector da T1.12. | FR-010, FR-015, FR-016 |
| **FR-C031** | Todo envio, classificação, pré-triagem e entrega DEVE gerar rastro com `@rastreado(etapa)` e evento do fluxo, com nome, e-mail e telefone mascarados no rastro. | FR-013, FR-014, #50 §12 |
| **FR-C032** | Toda leitura e escrita DEVE usar `empresa_id`. Webhooks de e-mail e WhatsApp DEVEM ter a assinatura verificada. | FR-018, FR-029, #50 §12 |

### Entidades

Usa as entidades de `backend/contratos` com os nomes do #4: `Convite` (com `link_agendamento` opcional), `RespostaCandidato`, `PacoteContexto`, `ResultadoEntrevista`, `Candidato`, `Vaga` e `Decisao`. O modelo de dados da seção 7 do #50 (`Contato`, `PreTriagem`, `contatos[]` no perfil e o hash de supressão) ainda não está nos contratos e depende do acordo das frentes.

- **E-mail inicial:** um `Convite` de tipo `VAGA`, tentativa 1.
- **Lembrete:** um `Convite` de tipo `VAGA`, tentativa 2. Não há tentativa 3.
- **Pedido de autorização:** um `Convite` de tipo `AUTORIZACAO`, sem link de agendamento.
- **Conversa no WhatsApp:** mensagens ligadas ao convite pelo código curto.
- **Pré-triagem:** perguntas do roteiro, respostas estruturadas, resultado e quem revisou.
- **Preferências de contato:** configuração da empresa, local da frente (`PreferenciasContato`), com personalização e canal.

## Critérios de sucesso

- **SC-C001**: Zero mensagens, inclusive lembretes e recontatos, a pessoas na lista de supressão ou sem base para contato.
- **SC-C002**: Zero e-mails, mensagens ou entregas duplicados em reenvio, falha injetada e reinício.
- **SC-C003**: 100% dos e-mails com empresa e vaga, motivo, origem do contato, link de exclusão, `List-Unsubscribe` e link do WhatsApp.
- **SC-C004**: Zero e-mails para contato inferido ou sem fonte, e zero mensagens no WhatsApp iniciadas pela empresa fora das regras.
- **SC-C005**: Zero segundos lembretes na mesma vaga.
- **SC-C006**: Zero perguntas sensíveis feitas na pré-triagem.
- **SC-C007**: Zero pacotes entregues sem pré-triagem validada, e 100% dos pacotes com todos os campos de FR-C017 e sem evidência sem trecho.
- **SC-C008**: 100% das mensagens com instruções embutidas geram alerta, e nenhuma vira aceite ou aprovação.
- **SC-C009**: Trocar nome ou gênero não muda o conteúdo das mensagens, além do nome.
- **SC-C010**: 100% das dúvidas fora do material da vaga vão para uma pessoa.

## Rastreabilidade

| Origem | Requisitos desta spec | Tarefa |
|---|---|---|
| FR-008, #50 §9 | FR-C001, FR-C002, FR-C005, FR-C028 | T3.1 (#35) |
| FR-031, #50 §3 | FR-C004 | T3.1, com o hunting da Frente 1 |
| #50 §9 (lembrete) | FR-C006 a FR-C008 | T3.7 (#41) |
| FR-009 | FR-C009, FR-C010, FR-C013 | T3.2 (#36) |
| #50 §9 (WhatsApp e pré-triagem) | FR-C011, FR-C012, FR-C014, FR-C015 | T3.2 e T3.9, proposta |
| FR-010, #50 §8 | FR-C016 a FR-C018, FR-C030 | T3.3 (#37), #42 e T1.12 |
| FR-011 | FR-C019 | Todas |
| FR-032, #50 §5 | FR-C020 | T3.10, proposta, com a Frente 1 |
| FR-020, FR-021, FR-022 | FR-C021 | T3.4 (#38) |
| FR-023 | FR-C020, FR-C024 | T3.4, T3.6 (#40) |
| FR-015, #50 §13 | FR-C029, FR-C030 | T3.1, T3.3 |
| FR-004 | FR-C003, FR-C007 | Consome T1.1 |
| FR-013, FR-014 | FR-C008, FR-C031 | Todas, com T1.11 |
| FR-018, FR-029 | FR-C012, FR-C032 | Todas |

## Questões para o time

Nada aqui muda contrato. Cada item precisa de acordo das quatro frentes antes de virar mudança (#9).

1. **Spec 001 diverge do #50:**
   - FR-010 diz que o pacote vai "quando o candidato agendar", e esta spec segue o #50 (depois da pré-triagem validada);
   - FR-033 diz "lembretes até o limite de tentativas da vaga", e esta spec segue o #50 (um lembrete por vaga);
   - FR-034 pede follow-up depois da entrevista, que o #50 não prevê e que saiu do escopo desta frente.
   Propor o alinhamento da 001 com o #50.
2. **Contratos do #50, seção 7:** `Contato` (canal, estado, mensagens), `PreTriagem`, `contatos[]` com `publicado_para_contato` no perfil e hash de supressão. A frente precisa deles para o e-mail, o WhatsApp e a pré-triagem.
3. **Tarefas novas:** T3.9 (WhatsApp e pré-triagem) e T3.10 (lista de supressão e link de exclusão). T3.8 não é usado, porque a T1.12 o substituiu. A T3.7 (#41) passa a ser o lembrete único.
4. **Roteiro da pré-triagem:** quem gera e quem aprova. O #50 diz que ele é gerado a partir dos critérios e aprovado junto com a vaga (Frente 1).
5. **Estado do contato no pacote:** a seção 6 do design pede, mas `PacoteContexto` não tem esse campo. O `Contato` do #50 resolveria.
6. **Intervalo do lembrete:** 3 dias é decisão de design. Confirmar com o time ou com recrutadores.

## Premissas

- Canais simulados no hackathon. O e-mail e o WhatsApp reais ficam fora (#50, seção 14), salvo testes com contas do próprio time.
- Testes, avaliações e demo usam dados sintéticos, inclusive contatos públicos fictícios. No simulador do WhatsApp, o jurado faz o papel do candidato.
- Contato com pessoas reais só depois do acordo das quatro frentes (#8) e de parecer jurídico.
- A Nara simulada fica congelada no sábado, às 13h, se a Tako não der acesso de teste.
- Até as outras frentes entregarem, usar `backend/contratos/simulacoes.py`.
