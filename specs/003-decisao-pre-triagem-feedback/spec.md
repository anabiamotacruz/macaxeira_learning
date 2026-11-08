# Especificação: decisão, pré-triagem e feedback

**Branch da feature**: `frente/agente-spec-003`
**Criada em**: 2026-11-07
**Estado**: Rascunho, com decisões do responsável pelo produto registradas e propostas à espera de confirmação
**Frente**: 1. Agente (`backend/agente`), com limites combinados com as Frentes 2, 3 e 4 em `plan.md`
**Entrada**: decisões do responsável pelo produto, código de `backend/agente/decisao_final.py`, `pre_triagem.py` e `feedback.py`, contratos de `backend/contratos/modelos.py`, arquitetura de coleta e agente (#50), spec `002-contato-e-nara` e o relatório "Modelos de decisão em recrutamento"

Esta spec define como o agente decide o destino de cada pessoa, como a pré-triagem completa o que falta e como a pessoa recebe feedback. Ela não altera a feature 001. Os pontos em que a 001, a 002 ou a constituição divergem estão em "Questões para o responsável" e em `plan.md`.

## Como ler os requisitos

| Marca | Significado |
| --- | --- |
| **[Decidido]** | Decisão do responsável pelo produto. Não está em aberto. |
| **[Proposta P-n]** | Ainda não confirmada. Vale como intenção. Não pode ser apresentada como decisão. |
| **[Regra]** | Vem da constituição, de `AGENTS.md`, da arquitetura (#50) ou da spec 002. |
| **[Projeto]** | Detalhe de comportamento que o código já tem e que sustenta um item acima. Pode ser corrigido sem nova decisão de produto. |

## Decisões do responsável pelo produto

| ID | Decisão |
| --- | --- |
| **D-1** | O agente decide dentro de um mandato assinado por uma pessoa responsável, sem aprovação de lote. O grupo aprovou, segundo o responsável. |
| **D-2** | As saídas são: Aprovar para a próxima fase, Recusar, Garden indisponível (pessoa boa, indisponível agora), Garden a lapidar (muito boa, precisa ser desenvolvida, e a empresa quer manter proximidade) e Revisão humana. |
| **D-3** | O score é visível ao recrutador, com pontos a explorar e insights. |
| **D-4** | Quem não passou recebe feedback quando pedir, pelos meios de contato definidos. |
| **D-5** | Meta de precisão: ideal de 100%, aceitando no mínimo 95%. |

## Propostas ainda não confirmadas

| ID | Proposta | Situação no código |
| --- | --- | --- |
| **P-1** | O RH confirma o "a lapidar". | Implementada como padrão: `lapidar_exige_confirmacao=True`. |
| **P-2** | O candidato vê os motivos, não a nota. | Implementada: `FeedbackCandidato` não tem campo de nota. |
| **P-3** | Requisito exige evidência, e competência desejável só reduz a nota. | Implementada em `classificar_destino`. |
| **P-4** | Vaga com ação afirmativa vai para uma pessoa. | Não existe no código. |

## Fora do escopo

O agente não agenda, não entrevista e não decide contratações. A pré-triagem não substitui a entrevista: quem passa recebe o link do agente de destino, que agenda e entrevista.

## Cenários de usuário

### História 1: decidir dentro do mandato (P1)

Como pessoa responsável pela vaga, quero assinar um mandato e deixar o agente decidir dentro dele, para que cada pessoa tenha um destino explicável sem que eu aprove lotes.

**Por que P1:** todas as outras histórias dependem do destino e do registro da decisão.

**Teste independente:** rodar a decisão com vagas, perfis e análises sintéticos, sem canal nem API, e conferir destino, regra, responsável e evidências. Já há testes do módulo. Falta o fluxo usar esse módulo.

1. **Dado** um mandato válido e uma pessoa com todos os requisitos atendidos, evidência aceita, nenhum portão e nota no limiar ou acima, **quando** o agente decide, **então** o destino é Aprovar, sem aprovação de lote.
2. **Dado** um requisito não desenvolvível comprovadamente não atendido, **quando** o agente decide, **então** o destino é Recusar, com a regra `requisito_eliminatorio:<id>`.
3. **Dada** uma pessoa sem autorização válida, **quando** o agente decide, **então** o destino é Recusar, com a regra `sem_autorizacao`.
4. **Dada** uma nota abaixo do piso ou entre o piso e o limiar, **quando** o agente decide, **então** o destino é Revisão humana, e ninguém é recusado por nota.
5. **Dado** um requisito sem dado ou sem evidência aceita, **quando** o agente decide, **então** a pessoa não é aprovada.
6. **Dado** um mandato sem limiar, **quando** o agente decide, **então** ninguém é aprovado sozinho.
7. **Dado** um mandato vencido, de outra empresa ou de uma vaga editada depois da assinatura, **quando** o agente decide, **então** a decisão é recusada com erro, sem destino.
8. **Dada** uma instrução no perfil, um trecho inexistente em requisito ou uma ressalva grave do revisor, **quando** o agente decide, **então** o destino é Revisão humana.
9. **Dado** um par de perfis que difere só em nome ou gênero, **quando** o agente decide, **então** destino, regra e nota são iguais.

### História 2: o recrutador entende a nota (P1)

Como recrutador, quero ver a nota de cada critério, o que falta explorar e onde os candidatos da vaga param, para orientar a conversa e ajustar a vaga.

**Por que P1:** é a decisão D-3 e o que torna a autonomia conferível.

**Teste independente:** consultar pela API uma vaga simulada e conferir score, selo, pontos e insights, sem canal real.

1. **Dada** uma decisão, **quando** o recrutador a consulta, **então** vê nota por critério, peso, nível, qualidade do dado, trechos com fonte, nota geral, faixa, sinais que reduziram a nota e selo de calibração.
2. **Dado** um limiar sem certificação igual ao do mandato, **quando** o score aparece, **então** o selo é "não calibrado".
3. **Dada** uma decisão com lacuna, contradição, afirmação sem exemplo ou experiência parecida, **quando** os pontos a explorar são montados, **então** cada ponto traz trecho, fonte e rótulo de verificado ou não verificado.
4. **Dada** uma experiência parecida, **quando** vira ponto, **então** aparece como inferência e nunca como verificada.
5. **Dado** um critério em que a maioria das pessoas para, com pelo menos 5 pessoas, **quando** os insights são montados, **então** o agregado aparece sem identificar ninguém.
6. **Dadas** menos de 5 pessoas na vaga, **quando** os insights são pedidos, **então** nenhum insight aparece.

### História 3: pré-triagem completa o que falta (P1)

Como recrutador, quero que a pessoa responda só o que falta, para que a próxima fase receba contexto sem repetir perguntas.

**Por que P1:** liga a decisão ao contato e à entrega ao agente de destino.

**Teste independente:** rodar a jornada com transporte simulado: roteiro, resposta, extração, validação e pacote. Essa jornada já existe em teste. Falta ligá-la ao fluxo e ao canal da Frente 3.

1. **Dada** uma pessoa aprovada, **quando** o roteiro é gerado, **então** ele pergunta a disponibilidade e só os critérios em aberto, com o motivo de cada pergunta, sem nome nem nota.
2. **Dada** Revisão humana, **quando** o roteiro é pedido, **então** nada é enviado antes de uma pessoa identificada liberar.
3. **Dados** Recusar ou Garden, **quando** o roteiro é pedido, **então** ele é recusado.
4. **Dado** um critério que viraria pergunta sensível, **quando** o roteiro é gerado, **então** a pergunta não existe e o critério fica bloqueado para uma pessoa olhar.
5. **Dada** uma resposta, **quando** é extraída, **então** o modelo recebe o texto pseudonimizado e delimitado como dado, e devolve dados com trecho que existe na mensagem.
6. **Dada** uma extração inválida ou uma instrução na mensagem, **quando** a validação roda, **então** o destino é Revisão humana, e o perfil não muda.
7. **Dada** uma resposta válida, **quando** a validação roda, **então** só os critérios respondidos são reavaliados, em código.
8. **Dado** que a pessoa passou, **quando** a validação termina, **então** ela recebe o link do agente de destino, e uma falha no link não desfaz a validação.
9. **Dado** um pacote pronto para a entrega, **quando** é reidentificado, **então** nenhum campo sai com marcador de pseudonimização, inclusive pontos a explorar e respostas da pré-triagem, e a revelação fica auditada.

### História 4: manter proximidade pelo garden (P2)

Como RH, quero manter por perto quem é bom mas não pode agora e quem é muito bom mas precisa se desenvolver, para voltar a falar no momento certo e com autorização.

**Teste independente:** decidir com fatos sintéticos e percorrer autorização, revisão, vencimento e opt-out, sem canal real.

1. **Dada** uma pessoa boa que diz não poder agora, com data ou motivo de volta, **quando** o agente decide, **então** o destino é Garden indisponível, com o trecho dito pela pessoa.
2. **Dada** uma pessoa indisponível com nota baixa, **quando** o agente decide, **então** o destino é Revisão humana.
3. **Dada** uma pessoa com nota alta, evidência nas competências e lacunas só em requisitos desenvolvíveis, **quando** o agente decide, **então** o destino é Garden a lapidar, com as lacunas listadas.
4. **[Proposta P-1] Dada** essa proposta, **quando** o RH a confirma, **então** a entrada pode abrir. **Quando** o RH nega, **então** o destino é Revisão humana, e ninguém é recusado.
5. **Dada** uma decisão de garden, **quando** a entrada abre, **então** ela só fica ativa depois da autorização da pessoa, com prazo limitado pela política.
6. **Dado** opt-out, remoção ou autorização vencida, **quando** a situação é consultada, **então** a entrada é encerrada e a pessoa não volta a ser procurada.

### História 5: feedback a quem pedir (P2)

Como pessoa que não passou, quero saber o motivo quando eu pedir, pelo canal em que já conversei, para entender o resultado e o que poderia mudar.

**Teste independente:** enviar pedidos sintéticos e conferir o texto, o encaminhamento e o registro, com canal simulado.

1. **Dado** que a pessoa não pediu, **quando** a decisão é tomada, **então** nenhum feedback é gerado.
2. **Dado** um pedido por e-mail ou WhatsApp, com motivo registrado, **quando** o feedback é gerado, **então** cada motivo liga um critério a um trecho registrado.
3. **[Proposta P-2] Dado** um feedback, **quando** é gerado, **então** não traz nota, faixa, ranking nem menção a outras pessoas.
4. **Dada** uma contestação, um motivo sensível, um motivo sem trecho ou uma decisão sem critério não atendido, **quando** o pedido chega, **então** ele vai para a pessoa responsável, sem revelar o motivo bloqueado.
5. **Dada** uma decisão vinda da entrevista, **quando** o pedido chega, **então** só sai o que o agente de destino informou.
6. **Dado** um pedido de outra pessoa, vaga ou empresa, **quando** chega, **então** é negado sem revelar o que existe.
7. **Dada** uma falha ao registrar a auditoria, **quando** o feedback seria entregue, **então** nada é entregue.

### História 6: saber se a precisão é aceitável (P2)

Como responsável pelo produto, quero medir a precisão contra um gabarito humano, para dizer com honestidade se a meta foi alcançada.

**Teste independente:** rodar a medição em casos sintéticos com gabarito, sem canal nem API, e conferir o relatório por saída, com tamanho da amostra e intervalo.

1. **Dado** um conjunto de casos, **quando** a medição roda, **então** o relatório traz a precisão por saída, o número de casos, os erros e o intervalo.
2. **Dada** uma amostra que não sustenta 95%, **quando** o relatório sai, **então** o selo continua "não calibrado" e a meta aparece como não comprovada.
3. **Dado** um limiar certificado na prova e igual ao do mandato, **quando** o agente decide, **então** o selo passa a "certificado".
4. **Dados** novos modelo, prompt, tipo de vaga ou empresa, **quando** a medição é consultada, **então** o certificado anterior não é apresentado como válido para eles.

### Casos de borda

- Mandato que vence entre a decisão e a resposta da pré-triagem: a reavaliação é recusada e a decisão anterior fica como está.
- Vaga editada depois da assinatura: o mandato deixa de valer para qualquer nova decisão.
- Opt-out entre a pergunta e a resposta: a pessoa não passa, por regra de autorização.
- Autorização que vence durante a conversa ou no garden: sem novo contato.
- Mensagem vazia, longa demais, só com frases sensíveis ou com instrução ao agente.
- Modelo fora do ar ou fora do esquema: extração inválida, que vai para uma pessoa.
- Resposta a pergunta inexistente, resposta duplicada ou trecho que não existe na mensagem.
- Data de volta no passado.
- Pessoa indisponível sem data nem motivo: vai para uma pessoa.
- Pessoa indisponível com requisito não atendido: continua recusada.
- Requisito negado na pré-triagem, com valor esperado igual a `nao`: não conta como atendido.
- Falha do agente de destino ao gerar o link: a validação fica, e o link é tentado de novo.
- Reenvio da mesma resposta ou do mesmo pedido de feedback: não duplica decisão, feedback nem entrega.
- Pedido de feedback de quem saiu ou teve os dados apagados: nada é enviado sem passar pela supressão, e o pedido vai para a pessoa responsável.
- Pedido de feedback fora da janela de 24 horas do WhatsApp: vale a regra de template e opt-in da FR-C011.
- Mais aprovados que `max_indicacoes`: ninguém é recusado, e o registro da decisão com destino precisa continuar coerente.
- Pessoa em mais de uma vaga: a decisão de uma vaga não vale para a outra.
- Menos de 5 pessoas na vaga: insights suprimidos.
- Critério da vaga que cita dado sensível: o mandato é recusado, e o critério nunca vira pergunta nem ponto.

## Requisitos

### Funcionais

#### Mandato e registro

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D001** | [Decidido] D-1 | O agente DEVE decidir só com mandato assinado por uma pessoa responsável, válido para a empresa e a vaga, sem vencimento e com a vaga igual à assinada. |
| **FR-D002** | [Decidido] D-1 | O sistema NÃO DEVE exigir aprovação de lote para quem foi aprovado dentro do mandato. |
| **FR-D003** | [Regra] | Destino, regra e nota DEVEM ser calculados em código. O modelo interpreta texto e não decide. |
| **FR-D004** | [Regra] | Toda decisão DEVE registrar destino, regra, motivo, responsável ligado ao mandato, versão do mandato, rastro, evidências e entrada, sem nome, atributos nem texto da pessoa na entrada. |

#### Saídas

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D005** | [Decidido] D-2 | Toda decisão DEVE terminar em exatamente uma destas saídas: Aprovar para a próxima fase, Recusar, Garden indisponível, Garden a lapidar ou Revisão humana. |
| **FR-D006** | [Decidido] D-2 e [Projeto] | Aprovar DEVE exigir todos os requisitos atendidos, com evidência aceita e confirmados na análise, nenhum portão e nota no limiar do mandato ou acima. Aprovar não é contratar: a próxima fase é a pré-triagem, e depois dela o link do agente de destino. |
| **FR-D007** | [Regra] #50 §5 | Recusar DEVE acontecer só por regra objetiva: falta de autorização válida ou requisito não desenvolvível comprovadamente não atendido. |
| **FR-D008** | [Regra] #50 §5 | Nota baixa, nota intermediária, mandato sem limiar e requisito sem dado ou sem evidência aceita NÃO DEVEM recusar. Esses casos vão para Revisão humana, salvo o previsto em FR-D011. |
| **FR-D009** | [Projeto] | Instrução detectada, trecho inexistente em requisito, ressalva grave, peso inválido, vaga sem requisitos e notas incompletas DEVEM levar à Revisão humana. Recusa objetiva continua tendo prioridade. |
| **FR-D010** | [Decidido] D-2 | Garden indisponível DEVE exigir pessoa boa e o fato dito por ela, com trecho e com data ou motivo de volta. Boa é faixa alta ou média, sem requisito eliminatório não atendido e sem portão. [NEEDS CLARIFICATION: requisito eliminatório ainda sem dado impede "pessoa boa"? O código hoje aceita.] |
| **FR-D011** | [Decidido] D-2 | Garden a lapidar DEVE exigir pessoa muito boa, que precisa ser desenvolvida, e interesse da empresa em manter proximidade. O código entende muito boa como faixa alta, com evidência nas competências e lacunas só em requisitos marcados como desenvolvíveis. |
| **FR-D012** | [Proposta P-1] | O RH DEVE confirmar o Garden a lapidar. Só pessoa identificada confirma. Negar DEVE levar à Revisão humana, nunca à recusa. Enquanto não for confirmada, esta proposta é o único sinal de "a empresa quer manter proximidade". |
| **FR-D013** | [Decidido] D-2 | Revisão humana DEVE registrar o motivo. Nota baixa fica sem prioridade e pode voltar. |
| **FR-D014** | [Proposta P-3] | Requisito DEVE exigir evidência aceita. Competência desejável DEVE só reduzir a nota, e sua falta vale o nível mínimo sem anular a nota. |
| **FR-D015** | [Proposta P-4] | Vaga com ação afirmativa DEVE ter toda decisão encaminhada a uma pessoa, sem nenhuma saída automática. |

#### Score e apoio ao recrutador

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D016** | [Decidido] D-3 | O recrutador DEVE ver, para cada decisão, nota por critério, peso, nível, qualidade do dado, trechos com fonte, nota geral, faixa e sinais que reduziram a nota. |
| **FR-D017** | [Regra] Constituição VIII | O score DEVE trazer o selo "não calibrado" até existir limiar certificado igual ao do mandato, e NÃO DEVE ser apresentado como probabilidade de acerto. |
| **FR-D018** | [Decidido] D-3 | O recrutador DEVE ver pontos a explorar, cada um com tipo, critério, trecho, fonte e rótulo de verificado ou não verificado. Inferência nunca aparece como verificada. |
| **FR-D019** | [Regra] Constituição VII | Pontos a explorar NÃO DEVEM citar dado sensível nem julgar personalidade ou fit cultural. O ponto recusado some sem mudar a decisão. |
| **FR-D020** | [Decidido] D-3 | O recrutador DEVE ver insights da vaga, só com contagens e sem identificar pessoas. Com menos de 5 pessoas, os insights DEVEM ser suprimidos. |

#### Pré-triagem

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D021** | [Projeto] | O roteiro DEVE ser montado em código a partir dos critérios assinados e das lacunas da decisão, com a disponibilidade primeiro, no máximo 6 perguntas e nunca cortando requisito eliminatório. |
| **FR-D022** | [Regra] Constituição II | Só Aprovar recebe roteiro sem intervenção. Revisão humana DEVE esperar a liberação de uma pessoa identificada. Recusar e Garden NÃO DEVEM receber roteiro. |
| **FR-D023** | [Regra] FR-C014 | Pergunta sobre dado sensível NÃO DEVE existir, nem como pergunta bloqueada entregue ao canal. O critério DEVE ficar marcado para uma pessoa olhar. |
| **FR-D024** | [Regra] FR-C010 e FR-C026 | A mensagem DEVE chegar ao modelo pseudonimizada, delimitada como dado e sem frases sensíveis. Extração inválida ou instrução detectada DEVE levar à Revisão humana, nunca à aprovação nem à mudança do perfil. |
| **FR-D025** | [Regra] FR-C015 | A validação DEVE ser feita em código e reavaliar só os critérios respondidos. Portões de integridade continuam valendo. O canal NÃO DEVE decidir o resultado. |
| **FR-D026** | [Regra] FR-C021 | Resposta válida DEVE atualizar o perfil com fonte e data, na empresa da pessoa. Resposta incerta NÃO DEVE mudar o perfil. |
| **FR-D027** | [Regra] FR-C016 e FR-C019 | Só quem passa DEVE receber o link do agente de destino. Falha no link NÃO DEVE desfazer a validação. O agente NÃO DEVE agendar. |
| **FR-D028** | [Regra] FR-C017 | O pacote DEVE levar pontos a explorar e respostas da pré-triagem, além do que já leva. |
| **FR-D029** | [Regra] Constituição VII | A reidentificação DEVE cobrir todos os campos de texto do pacote, acontecer só depois de Aprovar e na entrega, e registrar os marcadores usados antes de revelar. O resultado NÃO DEVE voltar a modelo nem a rastro. |

#### Garden

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D030** | [Regra] FR-C021 | Entrada no garden DEVE começar aguardando autorização e só ficar ativa com a autorização da pessoa, com prazo limitado pela política. |
| **FR-D031** | [Regra] Constituição VII | Opt-out, remoção e autorização vencida DEVEM encerrar a entrada, com ou sem revisão. |
| **FR-D032** | [Projeto] | Revisão e encerramento da entrada DEVEM ser feitos por pessoa identificada, e o motivo de encerramento NÃO DEVE citar dado sensível. |
| **FR-D033** | [Decidido] D-2 | As entradas DEVEM ser persistidas por empresa e aparecer para o RH, com o motivo de retorno e a data de revisão. |

#### Feedback

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D034** | [Decidido] D-4 | O feedback DEVE existir só quando a pessoa pedir. O sistema NÃO DEVE enviá-lo por iniciativa própria. |
| **FR-D035** | [Decidido] D-4 | O pedido e a resposta DEVEM usar os meios de contato definidos, e-mail e WhatsApp (#50 §1), respeitando supressão e janela de atendimento (FR-C003 e FR-C011). Canal fora desses meios DEVE ser recusado. |
| **FR-D036** | [Regra] Constituição IV | Cada motivo DEVE ligar um critério da vaga a um trecho registrado na decisão. O texto do pedido é dado e NÃO DEVE entrar na resposta nem no registro. |
| **FR-D037** | [Regra] Constituição VIII | O feedback DEVE separar o que causou o resultado do que é só orientação. Critério que não causou a recusa NÃO DEVE aparecer como motivo dela. |
| **FR-D038** | [Proposta P-2] | O feedback NÃO DEVE trazer nota, faixa, ranking nem menção a outras pessoas. |
| **FR-D039** | [Projeto] | Contestação, motivo sensível, motivo sem trecho e decisão sem critério não atendido DEVEM ir para a pessoa responsável, com texto padrão à pessoa. |
| **FR-D040** | [Projeto] | Em decisão vinda da entrevista, o feedback DEVE transmitir só o que o agente de destino informou, e critério fora da vaga vai para a pessoa responsável. |
| **FR-D041** | [Regra] FR-014 | Toda geração e todo encaminhamento DEVEM ser registrados antes de sair, só com códigos e critérios. Sem o registro, nada é entregue. |

#### Meta e medição

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D042** | [Decidido] D-5 | A meta de precisão DEVE ser ideal de 100%, com mínimo aceitável de 95%. [NEEDS CLARIFICATION: 95% é o valor observado ou o limite inferior com 95% de confiança? Vale só para Aprovar ou para todas as saídas automáticas?] |
| **FR-D043** | [Decidido] D-5 | [NEEDS CLARIFICATION: até a meta estar comprovada, o agente pode aprovar sozinho com selo "não calibrado", ou toda aprovação vai para uma pessoa?] |
| **FR-D044** | [Regra] Constituição VI | O relatório DEVE trazer precisão por saída, número de casos, erros e intervalo, com versão de modelo, prompt e mandato. NÃO DEVE trazer só o valor observado. |
| **FR-D045** | [Regra] #50 §13 | O gabarito DEVE vir de avaliação humana às cegas, sem a pessoa ver a nota do agente. A afirmação de precisão vale só para o processo medido. |
| **FR-D046** | [Regra] Constituição VIII | Sem amostra suficiente, o sistema DEVE apresentar a meta como não comprovada. Nenhum limiar pode ser baixado para caber na fila. |

#### Integração

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D047** | [Decidido] D-1 e D-2 | O fluxo da vaga DEVE usar a decisão com as cinco saídas na etapa de decidir. |
| **FR-D048** | [Projeto] | O teto `max_indicacoes` NÃO DEVE recusar ninguém, e a decisão registrada DEVE continuar coerente com o que o fluxo fez. |
| **FR-D049** | [Decidido] D-3 | A API DEVE expor score, pontos a explorar, insights e as ações humanas, sempre no escopo da empresa da sessão e com `simulado` identificado. |
| **FR-D050** | [Regra] FR-C016 | O canal da Frente 3 DEVE entregar perguntas e devolver mensagens, sem montar roteiro nem validar por conta própria. |
| **FR-D051** | [Regra] Constituição V | Reenvio de resposta, pedido ou entrega NÃO DEVE duplicar decisão, feedback nem pacote. |

#### Equidade, segurança e limites

| ID | Marca | Requisito |
| --- | --- | --- |
| **FR-D052** | [Regra] Constituição VII | Trocar nome ou gênero NÃO DEVE mudar destino, score, roteiro nem validação. No feedback, muda só a saudação. |
| **FR-D053** | [Regra] Constituição VII | Atributo sensível NÃO DEVE ser critério. Trecho sensível NÃO DEVE aparecer para o recrutador nem mudar a decisão. |
| **FR-D054** | [Regra] FR-018 | Peças de empresas, vagas ou pessoas diferentes DEVEM ser recusadas em toda etapa. Insights usam só decisões da própria vaga. |
| **FR-D055** | [Regra] Constituição VII | Texto de candidato DEVE ser tratado como dado em toda etapa. |
| **FR-D056** | [Regra] Constituição VI | Decisão, roteiro, extração, validação, feedback e reidentificação DEVEM gerar rastro, sem nome, e-mail, telefone nem chaves. |
| **FR-D057** | [Regra] Constituição VIII | Tudo o que vem de simulação DEVE aparecer identificado como simulação. |
| **FR-D058** | [Regra] AGENTS.md | O agente NÃO DEVE agendar, entrevistar nem decidir contratações. |

### Entidades

Todas estão em `backend/contratos/modelos.py`, na branch `frente/agente-integracao`. Ainda não estão em `origin/main`.

- **Mandato e Politica:** o que a pessoa responsável assinou, com limiar, piso, teto, aceite de evidência declarada, confirmação do "a lapidar" e prazo do garden.
- **DecisaoFinal:** destino, regra, motivo, responsável, score, evidências, portões, lacunas, origem e invariantes de cada saída.
- **ScoreRecrutador, NotaCriterio e SinalNota:** o que o recrutador vê.
- **LacunaCriterio:** o que falta em um critério, nascido do registro, não do texto do modelo.
- **FatoIndisponibilidade:** o que a própria pessoa disse sobre não poder agora.
- **EntradaGarden:** a entrada com autorização, prazo e revisão.
- **PontoExplorar, InsightVaga e InsightsDaVaga:** apoio ao recrutador.
- **RoteiroPreTriagem, PerguntaRoteiro, DadoPreTriagem, AtualizacaoPerfil, ResultadoPreTriagem e ContextoOnboarding:** a pré-triagem e o que o canal recebe.
- **PedidoFeedback, RetornoDestino, MotivoFeedback e FeedbackCandidato:** o feedback.

## Critérios de sucesso

### Resultados mensuráveis

- **SC-D001** [Decidido]: A precisão medida das decisões automáticas fica em 95% ou mais, com ideal de 100%, e o relatório sempre informa casos, erros e intervalo. A referência de amostra está abaixo.
- **SC-D002**: Zero aprovações com requisito não atendido, sem dado ou com portão.
- **SC-D003**: Zero recusas fora das regras objetivas, inclusive por nota.
- **SC-D004**: 100% das decisões têm regra, motivo, responsável, mandato, rastro e evidência ou regra registrada.
- **SC-D005**: 100% dos scores mostrados ao recrutador têm selo, e zero selos "certificado" sem limiar certificado igual ao do mandato.
- **SC-D006**: 100% dos pontos a explorar têm trecho, fonte e rótulo, e zero inferências aparecem como verificadas.
- **SC-D007**: Zero insights com menos de 5 pessoas ou com dado de uma pessoa identificável.
- **SC-D008**: Zero perguntas sensíveis em roteiros, e zero respostas sensíveis guardadas.
- **SC-D009**: 100% das extrações inválidas e mensagens com instrução vão para uma pessoa, e nenhuma vira aprovação.
- **SC-D010**: Zero mudanças de destino, score, roteiro ou validação ao trocar nome ou gênero nos pares contrafactuais.
- **SC-D011**: Zero marcadores de pseudonimização em pacotes entregues ao agente de destino, e 100% das revelações auditadas.
- **SC-D012**: Zero entradas ativas no garden sem autorização, e zero pessoas com opt-out procuradas pelo garden.
- **SC-D013**: Zero feedbacks sem pedido, zero com nota ou comparação entre pessoas [Proposta P-2], 100% dos motivos com trecho registrado e 100% das gerações auditadas.
- **SC-D014**: Zero agendamentos, entrevistas ou decisões de contratação feitos pelo agente.
- **SC-D015**: Uma vaga simulada percorre as cinco saídas pela API e pelo canal simulado, sem chamada direta a módulos internos.

### Referência para a meta de 95%

Limite binomial exato unilateral, com 95% de confiança. Isso só se aplica se a resposta a FR-D042 for limite inferior.

| Erros na amostra de aprovações | Casos necessários para sustentar 95% |
| --- | --- |
| 0 | 59 |
| 1 | 93 |
| 2 | 124 |
| 3 | 153 |
| 4 | 181 |

- Com os 33 casos rotulados de hoje, zero erro sustenta no máximo 91%. A meta de 95% não pode ser comprovada agora.
- Nenhuma amostra comprova 100%: zero erro em 299 casos sustenta 99%.
- O relatório propunha 90%. A decisão D-5 substitui essa proposta, e o restante da tabela dele continua útil como referência.

## Questões para o responsável

Além das três marcadas em FR-D010, FR-D042 e FR-D043:

1. **Constituição:** o princípio II ainda pede aprovação do primeiro lote de convites, assim como FR-007 da spec 001, a seção 8 do #50 e o fluxo da spec 002. D-1 contraria esses textos. A governança exige acordo das quatro frentes e atualização de `docs/PADRAO-DO-PROJETO.md`.
2. **P-1 a P-4:** confirmar ou rejeitar. Se P-1 cair, é preciso dizer como a empresa declara que quer manter proximidade.
3. **Evidência declarada:** com `aceitar_declarada=False`, o padrão, uma resposta na pré-triagem nunca aprova um requisito sozinha e a pessoa vai para Revisão humana. Confirmar se esse deve ser o padrão ao assinar o mandato.
4. **Desenvolvimento em competência:** o "a lapidar" só cobre lacuna em requisito desenvolvível. Quem atende aos requisitos, mas tem nota baixa em competência, vai para Revisão humana. Confirmar se isso atende a D-2.

## Premissas

- Testes, avaliações e demonstração usam dados sintéticos, e os canais ficam simulados.
- A pré-triagem acontece depois do contato inicial da spec 002, que continua sendo da Frente 3.
- O score mostrado ao recrutador pode conter marcadores de pseudonimização até a entrega. Só o pacote de entrega é reidentificado.
- O relatório é fonte de método e não substitui decisão de produto. Mandato e revisão humana são analogias e precisam de avaliação jurídica antes de uso real.
- Pesos, reduções e fatores são ponto de partida e não foram calibrados.
- Se faltar tempo, valem os cortes de `AGENTS.md`. A parada de funcionalidades é em 8/11, às 11h, e a submissão, às 13h.
