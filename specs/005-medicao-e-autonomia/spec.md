# Especificação: medição e autonomia do agente

**Branch da feature**: `frente/agente-spec-005`

**Criada em**: 2026-11-07

**Estado**: Rascunho, com cinco propostas à espera de confirmação

**Origem**: pedido da Frente 1: medir o agente em volume, certificar a precisão das aprovações automáticas e deixá-lo decidir sozinho dentro do mandato, sem criar gargalo de revisão. Fontes: `backend/agente/medicao.py`, `backend/agente/auditoria.py`, `backend/modelos/`, os relatórios da Frente 1 sobre modelos de decisão, validação e ciclo de taxa de erro, e a PR #54.

## Decisões e propostas

### Decididas

| ID | Decisão |
| --- | --- |
| D1 | Meta ideal de 100% e mínimo aceitável de 95% de precisão nas aprovações automáticas, com 95% de confiança. |
| D2 | Os dados de avaliação são sintéticos fortes, gerados por Bia (Frente 2). |
| D3 | A pessoa de RH avalia às cegas. |
| D4 | Há auto-improve de prompt e de limiar. |
| D5 | O agente decide sozinho dentro do mandato. |
| D6 | `max_tokens` tem folga configurável, e as respostas cortadas são medidas. |

### Propostas ainda não confirmadas

Nenhuma destas propostas vale como decisão. A última coluna diz o que continua valendo até haver resposta.

| ID | Proposta | Enquanto não for confirmada |
| --- | --- | --- |
| P1 | Novo prompt entra com aprovação de um clique | O candidato fica parado, sem entrar em uso. A constituição exige aprovação para ajustes do aprendizado, e esse mecanismo ainda não existe |
| P2 | Limite binomial exato no lugar do teto de Wilson | Vale o teto de Wilson, já no código, e os mínimos da coluna "Wilson" da tabela abaixo |
| P3 | 3 limiares fixados antes, com correção pelo número de limiares | Um único limiar é congelado antes da prova, e nenhuma varredura é feita na prova |
| P4 | Amostra auditada de 5% | O percentual é informado a cada sorteio, sem valor padrão |
| P5 | Separar portões de sinais | Vale a regra atual da faixa verde, em que qualquer falta manda à revisão |

## Números que sustentam a meta

Conferidos por cálculo exato: com `k` erros em `n` aprovações, a precisão de 95% fica certificada com 95% de confiança unilateral quando `Σ(i=0..k) C(n,i) · 0,05^i · 0,95^(n-i) ≤ 0,05`.

| Aprovações automáticas auditadas | Erros permitidos, limite exato | Mesmo `n`, com 3 limiares e correção (P3) | Teto de Wilson 95% nesse caso | Wilson certifica? |
| --- | --- | --- | --- | --- |
| 59 | 0 | nenhum: com 0 erros, são precisos 80 | 6,11% | Não |
| 100 | até 1 | 0 | 5,45% | Não |
| 200 | até 4 | até 3 | 5,03% | Não |
| 400 | até 12 | até 10 | 5,17% | Não |

- **Tamanhos mínimos pelo limite exato:** 59 com 0 erros, 93 com até 1, 181 com até 4 e 386 com até 12.
- **Tamanhos mínimos pelo teto de Wilson, regra vigente:** 73 com 0 erros, 110 com até 1, 202 com até 4 e 414 com até 12.
- **100% não é provável com amostra finita.** Com zero erros em `n` casos, o limite inferior é `0,05^(1/n)`: 95,05% com 59, 97,05% com 100, 99,00% com 299 e 99,70% com 1.000. Nunca chega a 100%. Essa meta orienta o trabalho, mas não pode ser certificada.
- **Certificação em dados sintéticos vale para o gerador, não para candidatos reais.** A frase que se sustenta é: "sob amostragem do mesmo gerador, este limiar tem precisão de pelo menos X% contra o gabarito desse gerador". Ela não afirma nada sobre outra vaga, outra empresa, candidatos reais ou contratações.

### O que a PR #54 permite hoje

A PR #54 está aberta, com 250 registros. Os números abaixo vêm da leitura dos arquivos dela pelo código atual da medição, com a semente 42.

| Medida | Ajuste | Validação | Prova |
| --- | --- | --- | --- |
| Registros | 82 | 84 | 84 |
| Vagas, sempre a mesma função nas duas empresas | 2 (staff) | 2 (software) | 2 (deployment) |
| Casos com gabarito `indicar` | 27 | 28 | 28 |
| Entradas distintas nesses casos | 3 | 3 | 3 |
| Casos `indicar` de fonte verificável (`rede_simulada`) | 7 | 7 | 7 |

No total, são 229 pares pessoa e vaga, 33 casos independentes, 21 textos distintos, 12 cenários e 6 vagas. Nenhum registro traz par de viés nem dificuldade.

Portanto, mesmo sem erro nenhum, a prova desse conjunto sustenta no máximo **89,85%** ao contar os 28 registros. Sob a política padrão, que não aceita evidência declarada, só 7 podem chegar à faixa verde, o que sustenta **65,18%** e limita o alcance a 25%. Contando as 3 entradas distintas, o limite é **36,84%**. Esse conjunto serve para testar regras e regressão, não para certificar 95%.

## Cenários de usuário

### História 1: receber dados fortes e saber se bastam (P1)

Como Frente 1, quero dados sintéticos fortes, com partições honestas e um aviso de suficiência, para não gastar modelo em um conjunto que nunca poderia certificar a meta.

**Por que esta prioridade:** toda taxa depende destes dados, e a PR #54 não alcança 95% mesmo sem erro nenhum.

**Teste independente:** ler um conjunto, sem chamar modelo, e conferir as partições, a contagem de casos independentes e o maior limite inferior possível em cada partição.

1. **Dado** um conjunto com a mesma pessoa, vaga, texto-modelo ou par de viés em dois casos, **quando** ele é particionado, **então** esses casos ficam na mesma partição.
2. **Dado** um conjunto em que a prova não alcança 95% mesmo com zero erros, **quando** o relatório de suficiência é gerado, **então** ele diz isso, com o limite alcançável e quantos casos faltam, antes de qualquer chamada de modelo.
3. **Dado** um arquivo incoerente, **quando** ele é lido, **então** a leitura é recusada com um erro claro, sem copiar dados do perfil para a mensagem.
4. **Dado** o conjunto forte, **quando** ele é resumido, **então** há pares de viés e dificuldade informados em todas as partições.

---

### História 2: medir uma rodada completa (P1)

Como pessoa responsável pelo agente, quero rodar o agente de verdade nos casos e ver erros por tipo, alcance, revisão, viés, custo e tempo, para saber onde ele falha e quanto custa.

**Por que esta prioridade:** o cálculo das taxas já existe, mas ainda não mede o fluxo real, e isso impede qualquer conclusão.

**Teste independente:** rodar a partição de ajuste com o modelo simulado no mesmo caminho de decisão do fluxo e conferir cada taxa contra uma conta feita à mão.

1. **Dada** uma rodada, **quando** ela termina, **então** cada tipo de erro aparece com valor, número de casos e intervalo, e uma taxa sem casos aparece como não medida, nunca como zero.
2. **Dados** casos com gabarito `indicar`, **quando** a rodada termina, **então** o alcance separa quem foi aprovado sozinho, quem foi à revisão e quem foi barrado pelo teto do mandato.
3. **Dada** uma rodada, **quando** um caso falha, **então** a falha é contada e não vira acerto, e cobertura, revisão e falhas somam 1.
4. **Dada** uma rodada com modelo, **quando** ela termina, **então** o relatório traz tokens, custo, tempo, respostas cortadas e maior saída por etapa.
5. **Dado** um conjunto sem pares de viés, **quando** o relatório é gerado, **então** o viés aparece como não medido, e o portão barra a mudança.

---

### História 3: certificar a precisão com prova de abertura única (P1)

Como pessoa responsável pelo mandato, quero um resultado único e selado sobre o limiar, para saber se 95% com 95% de confiança foi alcançado, sem aceitar um resultado obtido à força de tentativas.

**Por que esta prioridade:** a autonomia decidida só é defensável com uma medida que não possa ser repetida até dar certo.

**Teste independente:** com um agente simulado e resultados conhecidos, abrir a prova e conferir que 0 erros em 59 certificam pelo limite exato, que 1 erro em 59 não certifica, e que a segunda abertura é recusada.

1. **Dada** uma versão que já abriu a prova, **quando** ela tenta de novo, mesmo depois de reiniciar o serviço, **então** a abertura é recusada e registrada.
2. **Dada** uma abertura, **quando** a rodada cai no meio, **então** a prova fica gasta, e a falha aparece nos agregados.
3. **Dada** uma prova aberta, **quando** o resultado volta, **então** ele traz só agregados, sem nenhum caso individual.
4. **Dado** um limite inferior abaixo de 95%, **quando** a certificação é calculada, **então** o resultado é "não certificado", com o motivo, e nunca o menos pior.
5. **Dado** um conjunto já aberto por outra versão, **quando** uma nova versão o abre, **então** o resultado não certifica e declara quantas versões o olharam.
6. **Dado** um certificado, **quando** ele é exibido, **então** a mensagem diz que ele vale para o gerador, não para candidatos reais.

---

### História 4: avaliação às cegas pela pessoa de RH (P1)

Como pessoa de RH, quero avaliar fichas sem ver a resposta do agente, para que o gabarito sintético seja confrontado com um julgamento humano independente.

**Por que esta prioridade:** sem isso, o gabarito carrega só as premissas do projeto.

**Teste independente:** gerar as fichas, importar respostas fictícias e conferir a concordância por tipo de caso, sem usar modelo.

1. **Dada** uma ficha, **quando** ela é gerada, **então** não mostra faixa, nota, decisão, explicação, partição nem gabarito, e usa um código no lugar do nome.
2. **Dadas** as respostas, **quando** são importadas, **então** resposta incompleta é recusada, e decisão, segurança, critério, motivo e tempo ficam guardados.
3. **Dadas** avaliações de ajuste, **quando** a concordância é medida, **então** ela aparece por tipo de caso, com intervalo e a lista de discordâncias. Da prova, saem só agregados.
4. **Dada** uma discordância acima do limite fixado antes da sessão, **quando** o resultado é registrado, **então** nenhuma taxa é usada até o gerador ser revisto.

---

### História 5: decidir sozinho dentro do mandato, com selo visível (P2)

Como recrutador, quero que o agente decida sem aprovação de lote e mostre se o limiar está certificado, para reduzir a revisão sem esconder o risco.

**Por que esta prioridade:** é o resultado que a medição sustenta, mas depende das histórias 2 e 3 para ter números reais.

**Teste independente:** criar uma vaga pela API com medição injetada, com e sem certificado, e conferir decisões, selo, métricas e auditoria.

1. **Dado** um mandato com limiar certificado, **quando** um candidato cumpre as regras, **então** o agente decide sem aprovação prévia, e a decisão guarda regra, evidência, versão e selo.
2. **Dado** um limiar assinado sem certificado, **quando** o agente decide, **então** o selo diz "não calibrado", e a API e o painel mostram isso.
3. **Dado** um mandato sem limiar, **quando** um candidato é avaliado, **então** ele vai para revisão, e um evento registra o motivo.
4. **Dadas** decisões automáticas, **quando** a amostra é sorteada, **então** ela inclui aprovações e descartes de cada vaga, com a semente registrada, e o auditor não vê a decisão do agente.
5. **Dado** um erro na amostra, **quando** é registrado, **então** as decisões automáticas da vaga pausam, e enviar a uma pessoa continua possível.
6. **Dada** uma vaga, **quando** suas métricas são consultadas, **então** vêm os números medidos, ou uma marca clara de que são exemplo fixo.

---

### História 6: auto-improve de prompt e de limiar (P2)

Como pessoa responsável pelo agente, quero que os erros de ajuste gerem candidatos de prompt e de limiar, que só avançam se não piorarem nenhuma régua, para melhorar sem sobreajustar nem abrir caminho para injeção.

**Por que esta prioridade:** está decidido e é o ganho contínuo, mas precisa de medição e dados confiáveis primeiro. `AGENTS.md` também o põe por último na ordem de corte.

**Teste independente:** rodar um ciclo com modelo simulado, conferir que um candidato pior é barrado, que um candidato aceito aguarda a regra de aprovação, e que reverter restaura a versão anterior.

1. **Dados** erros de ajuste, **quando** são resumidos, **então** aparecem agrupados por motivo e armadilha, sem usar casos de prova nem atributos sensíveis.
2. **Dado** um currículo com instruções, **quando** gera erro, **então** o propositor recebe só códigos e campos estruturados, nunca o texto do candidato.
3. **Dado** um candidato pior em qualquer régua, **quando** passa pelo portão, **então** é barrado, e os motivos ficam registrados.
4. **Dado** um candidato que passa, **quando** o relatório sai, **então** diz "não piorou nas réguas", sem afirmar melhora.
5. **Dado** um limiar candidato menor que o vigente, **quando** é proposto, **então** só pode valer com nova certificação.
6. **Dada** uma versão aplicada, **quando** é revertida, **então** a anterior volta, reverter de novo não muda nada, e as execuções em andamento mantêm a versão com que começaram.

---

### História 7: entender por que gente boa vai para a fila (P2)

Como pessoa responsável pelo agente, quero ver por qual motivo cada caso foi à revisão, sem chamar modelo, para atacar o maior gargalo antes de mexer em prompt.

**Por que esta prioridade:** o relatório aponta os portões em série como causa provável de baixo alcance, e medir isso quase não custa nada.

**Teste independente:** reprocessar decisões registradas e conferir a contagem por motivo.

1. **Dadas** decisões registradas, **quando** o diagnóstico roda, **então** conta motivos por pessoa e separa teto do mandato, política de evidência e falta real, sem nenhuma chamada de modelo.
2. **Dada** a proposta P5 confirmada, **quando** um critério secundário tem inferência ou lacuna, **então** a nota cai sem mandar o caso à revisão, e requisito eliminatório sem evidência continua sendo portão duro.
3. **Dada** a proposta P5 ainda sem confirmação, **quando** o fluxo decide, **então** a regra atual da faixa verde continua valendo.

### Casos de borda

- **Prova sem casos ou com caso de outra partição:** é recusada sem gastar a abertura.
- **Falha na prova:** conta como falha e gasta a abertura. Se o número de aprovações cair abaixo do mínimo, o resultado é "não certificado".
- **Zero aprovações automáticas:** a precisão é não medida, nunca 100%, e o alcance é zero.
- **Limiar nulo:** ninguém fica na faixa verde, e o motivo aparece como evento e no relatório.
- **Taxa que precisa ser zero sem medida:** barra o portão, porque ausência de medida não é zero. A escolha de limiar deve seguir a mesma regra, o que hoje não acontece.
- **Trocar um espaço no prompt:** gera outra versão, que poderia abrir a prova de novo. Essa nova abertura é registrada e não certifica.
- **Mudança de modelo, parâmetro, gerador ou conjunto:** invalida o certificado.
- **Casos repetidos:** 250 registros de poucas entradas distintas não contam como 250 observações independentes.
- **Nome e gênero:** par em que um lado falha não conta como par medido. Par que muda em qualquer direção conta como violação.
- **Resposta cortada:** pode virar resposta inválida e correção. Cada ocorrência é contada e registrada sem expor o texto.
- **Limite de gasto atingido no meio da rodada:** cada caso restante conta como falha, e falhas nunca entram no cache.
- **Dois casos iguais em empresas diferentes:** a mesma chave local nunca une pessoas de empresas distintas, mas texto igual fica na mesma partição.
- **Pessoa de RH indisponível ou "não consigo avaliar":** a ficha sai da conta, e o total excluído é publicado. Sem avaliação, o relatório diz que o gabarito não foi validado.
- **Comentário livre com atributo sensível:** não alimenta o aprendizado e vira alerta.
- **Texto de candidato com instrução:** é dado. Nunca chega ao propositor e nunca entra em um prompt candidato.
- **Reverter uma versão com decisões já tomadas:** não apaga nada. As decisões da versão são listadas para revisão ou auditoria.
- **Fila acima da capacidade:** gera fila e aviso, sem baixar um limiar certificado.

## Requisitos

### Requisitos funcionais

Dados e partições:

- **FR-M001**: O conjunto de avaliação DEVE ser somente sintético, com semente e versão do gerador registradas, e todo relatório DEVE identificá-lo como sintético. (D2)
- **FR-M002**: O gabarito DEVE ficar separado do que chega ao agente, DEVE vir das regras do gerador e NUNCA do modelo avaliado.
- **FR-M003**: Os casos DEVEM ser divididos em ajuste, validação e prova, com semente fixa, sem que pessoa, vaga, texto-modelo ou par de viés apareça em mais de uma partição.
- **FR-M004**: Cada partição DEVE declarar registros, pares pessoa e vaga, casos independentes, textos distintos, cenários, vagas e composição do gabarito.
- **FR-M005**: Antes de qualquer gasto com modelo, o sistema DEVE calcular, por partição, o maior limite inferior possível com zero erros, em registros e em casos independentes, sob a política de evidência usada, e DEVE avisar quando esse limite for menor que 95%.
- **FR-M006**: O conjunto forte DEVE trazer pares de viés que só mudam nome ou gênero, dificuldade informada, textos variados, com sinônimos, erros, omissões e exageros, e mais de uma função por partição. (D2)
- **FR-M007**: A prova do conjunto forte DEVE ter casos suficientes para o mínimo de aprovações exigido, estimados por `aprovações necessárias ÷ (fração de indicáveis × alcance esperado)`. Com um terço de indicáveis e alcance de 50%, 59 aprovações pedem cerca de 354 casos na prova, e 100 pedem cerca de 600.

Prova:

- **FR-M008**: A prova DEVE abrir uma única vez por versão, com a abertura gravada antes da primeira chamada, e a segunda tentativa DEVE ser recusada e registrada, inclusive depois de reiniciar o serviço.
- **FR-M009**: A prova DEVE devolver somente agregados.
- **FR-M010**: O relatório DEVE declarar quantas versões abriram o conjunto, e só a primeira abertura pode certificar. Depois de usado, o conjunto vira regressão, e a próxima certificação pede casos novos.
- **FR-M011**: A versão avaliada DEVE identificar todos os prompts usados, o modelo, os parâmetros, o limiar e a versão do gerador.
- **FR-M012**: O limiar DEVE estar congelado antes da abertura, e nenhum ajuste de prompt ou de limiar pode usar casos de prova.
- **FR-M013**: O hash do conjunto de prova DEVE ser registrado antes da primeira rodada, e a prova DEVE recusar um conjunto com hash diferente.

Métricas:

- **FR-M014**: Cada rodada DEVE informar indicação errada, descarte errado, violação de eliminatório, contato com opt-out, mudança por nome ou gênero e afirmação sem evidência, com valor, número de casos e intervalo. Sem casos, a taxa é não medida.
- **FR-M015**: Cada rodada DEVE informar a precisão das aprovações automáticas, com número de aprovações, erros e limite inferior, nunca só o valor observado. (D1)
- **FR-M016**: Cada rodada DEVE informar o alcance automático, que é aprovados corretos ÷ indicáveis, e o alcance final, que é indicáveis que chegam à Nara, com revisão ÷ indicáveis, separando o teto do mandato de erro real.
- **FR-M017**: Cada rodada DEVE informar revisão em relação a todos os casos e a quem passou das regras objetivas, com a distribuição de motivos de revisão, além de cobertura e falhas.
- **FR-M018**: O viés DEVE ser medido em pares de nome e gênero, nas duas direções, sobre decisão e faixa. O resultado exigido é zero, e a falta de medida barra a mudança.
- **FR-M019**: Cada rodada DEVE informar tokens, custo, tempo, custo estimado ou real e custo por decisão, por etapa e no total.
- **FR-M020**: O `max_tokens` DEVE ter folga configurável por ambiente, com mínimo de 1000, e cada rodada DEVE informar respostas cortadas e maior saída por etapa. (D6)
- **FR-M021**: Falha nunca conta como acerto, e cobertura, revisão e falhas DEVEM somar 1.
- **FR-M022**: Métricas de empresas diferentes NUNCA se misturam, e nenhum dado pessoal aparece nos agregados nem no rastro.

Certificação:

- **FR-M023**: O sistema DEVE tratar 100% como meta ideal e 95% com 95% de confiança como mínimo aceitável, sem afirmar 100% como resultado certificado. (D1)
- **FR-M024**: O limiar só é certificado se o limite inferior da precisão for de pelo menos 95%, se as taxas que precisam ser zero forem medidas e iguais a zero, e se for a primeira abertura do conjunto. Caso contrário, o resultado é "não certificado", com o motivo, nunca o menos pior.
- **FR-M025**: O método de limite DEVE ficar registrado no certificado. Vale o teto de Wilson até a confirmação da proposta P2, que troca pelo limite binomial exato unilateral. (P2, não confirmada)
- **FR-M026**: Vale um único limiar congelado. Se a proposta P3 for confirmada, serão 3 limiares fixados antes, com confiança corrigida pelo número de limiares. (P3, não confirmada)
- **FR-M027**: O certificado DEVE declarar quantos registros e quantos casos independentes sustentam a contagem. Sem casos independentes suficientes para o mínimo, o resultado é "não certificado". (Premissa a confirmar: ver Premissas)
- **FR-M028**: Todo certificado, relatório, resposta de API e tela DEVE dizer que a certificação em dados sintéticos vale para o gerador, não para candidatos reais.
- **FR-M029**: O certificado DEVE perder validade quando mudar prompt, modelo, parâmetro, limiar, gerador ou tipo de vaga.

Autonomia:

- **FR-M030**: O agente DEVE decidir sozinho dentro do mandato assinado, sem aprovação de lote, e toda decisão DEVE guardar entrada, regra, evidências, responsável, rastro, versão e selo. (D5)
- **FR-M031**: Requisitos eliminatórios, autorização, opt-out, contas e limites DEVEM continuar em código determinístico. Nota, limiar e confiança declarada pelo modelo NUNCA podem substituí-los.
- **FR-M032**: Sem limiar, todos os casos DEVEM ir para revisão. Com limiar assinado e sem certificado, a decisão DEVE levar o selo "não calibrado".
- **FR-M033**: A API DEVE devolver números medidos para a vaga, ou marcar claramente que são exemplo fixo, e o painel DEVE exibir selo, número de casos e limite inferior.
- **FR-M034**: A auditoria DEVE sortear antes de conhecer o resultado, com semente registrada e pelo menos uma decisão por vaga e por tipo, incluindo descartes. O auditor não vê a decisão do agente, e erro na amostra pausa as decisões automáticas da vaga.
- **FR-M035**: O percentual da amostra é informado a cada sorteio. Se a proposta P4 for confirmada, o padrão será 5%, com a probabilidade registrada para ponderar. (P4, não confirmada)
- **FR-M036**: O agente NUNCA agenda entrevistas, avalia candidatos no lugar da Nara ou decide contratações, e atributos sensíveis NUNCA podem ser critérios.

Avaliação pela pessoa de RH:

- **FR-M037**: Cada ficha DEVE perguntar "Você encaminharia este perfil para a entrevista com a Nara?" e NÃO DEVE mostrar faixa, nota, decisão, explicação, partição ou gabarito, nem nome, foto, idade ou endereço. (D3)
- **FR-M038**: A resposta DEVE registrar decisão (encaminhar, precisa de mais informação, não encaminhar, não consigo avaliar), segurança, critério decisivo, motivo em código, comentário opcional de até 200 caracteres e tempo por ficha.
- **FR-M039**: As fichas DEVEM ser sorteadas de forma reproduzível, respeitando as partições, em ordem sorteada e com duplicatas para medir consistência.
- **FR-M040**: O sistema DEVE medir concordância e kappa com intervalo, por tipo de caso, além da ponte entre gabarito do gerador e pessoa de RH. A lista de discordâncias só existe para os casos de ajuste.
- **FR-M041**: O limite de discordância DEVE ser fixado antes da sessão. Acima dele, o gerador é revisto antes de qualquer taxa ser usada. O relatório só marca o gabarito como avaliado depois da sessão e declara que foi uma pessoa, em dados sintéticos.

Auto-improve:

- **FR-M042**: O sistema DEVE agrupar os erros de ajuste por motivo e armadilha, sem casos de prova, e DEVE entregar ao propositor só códigos e campos estruturados, nunca texto do candidato. (D4)
- **FR-M043**: O candidato de prompt só pode alterar trechos ajustáveis nomeados. Requisitos, critérios, delimitadores, regras de segurança, atributos proibidos, limites de gasto, esquemas, conjuntos, gabaritos e portões ficam de fora.
- **FR-M044**: O candidato de limiar DEVE vir só do ajuste e DEVE ser versionado. Um limiar menor que o vigente exige nova certificação, e toda alteração de limiar segue como novo termo do mandato, porque o limiar faz parte do que foi assinado. (D4)
- **FR-M045**: Um candidato só avança se, no mesmo conjunto, não piorar nenhuma régua e mantiver em zero, medido, tudo o que precisa ser zero. O relatório diz "não piorou", e não "melhorou". (D4)
- **FR-M046**: Candidato aprovado no portão NÃO DEVE entrar em uso sem a regra de aprovação. Se a proposta P1 for confirmada, a regra será a aprovação de um clique por uma pessoa nomeada. (P1, não confirmada)
- **FR-M047**: As versões DEVEM ser imutáveis e por empresa, com reversão idempotente. Execuções em andamento mantêm a versão inicial, e cada decisão guarda a versão usada.
- **FR-M048**: Todo ciclo DEVE gerar rastro, e toda chamada de modelo DEVE respeitar o limite de gasto. Chaves nunca aparecem em rastro ou log.

Diagnóstico e portões:

- **FR-M049**: O sistema DEVE contar motivos de revisão por pessoa, sem chamar modelo, e separar teto do mandato, política de evidência e falta real.
- **FR-M050**: Se a proposta P5 for confirmada, só requisito eliminatório sem evidência aceita, instrução detectada, trecho inexistente em requisito e ressalva grave DEVEM mandar à revisão, enquanto inferência ou lacuna em critério secundário só reduzem a nota. Nota baixa nunca recusa. (P5, não confirmada)

Execução real:

- **FR-M051**: A primeira rodada com modelo DEVE ter cerca de 50 casos de ajuste, para medir custo e respostas cortadas antes da rodada em volume, sob limite de gasto, fora dos testes comuns e com o resultado publicado mesmo se for ruim.

### Principais entidades

- **Caso de avaliação**: perfil, vaga, gabarito, motivo, partição, armadilha, dificuldade, par de viés, semente e versão do gerador. Só perfil e vaga chegam ao agente.
- **Resultado de caso**: resposta ao lado do gabarito, com regra, nota, motivos de revisão, falha e consumo.
- **Rodada**: conjunto de resultados de uma versão e uma partição, resumido em agregados.
- **Versão avaliada**: identidade imutável de prompts, modelo, parâmetros, limiar e gerador.
- **Abertura de prova**: registro único por versão, com hash do conjunto, momento e recusas.
- **Certificado de limiar**: resultado de uma abertura, com método, confiança, meta, aprovações, erros, casos independentes, limite inferior, motivo e escopo, sempre "gerador".
- **Ficha e avaliação humana**: o que a pessoa de RH vê e o que responde, ligados por código.
- **Candidato de ajuste**: prompt ou limiar proposto, com origem, relatório do portão, estado e versão anterior.
- **Amostra auditada**: decisões sorteadas, com semente, percentual e vereditos.

## Critérios de sucesso

### Resultados mensuráveis

- **SC-M001**: Um teste reproduz os números 59/0, 100/1, 200/4 e 400/12, os mínimos 93, 181 e 386, e os limites 95,05% e 99,00% para zero erros em 59 e 299 casos.
- **SC-M002**: 100% das segundas aberturas da prova são recusadas e registradas, inclusive depois de reiniciar.
- **SC-M003**: 100% das rodadas informam as seis categorias de erro, precisão, alcance, revisão, falhas, custo, tempo e respostas cortadas, e nenhuma taxa sem casos aparece como zero.
- **SC-M004**: Em 100% das saídas com certificado, aparece o escopo "vale para o gerador, não para candidatos reais".
- **SC-M005**: Zero violações de eliminatório, zero indicações com opt-out, zero mudanças por nome ou gênero e zero afirmações sem evidência na prova do conjunto forte, com todas essas taxas medidas.
- **SC-M006**: O conjunto forte tem, na prova, indicáveis suficientes para 59 aprovações e casos independentes suficientes para a contagem. Se não tiver, o relatório de suficiência o recusa antes de a prova ser aberta.
- **SC-M007**: A prova do conjunto forte alcança limite inferior de 95% com 95% de confiança, ou o resultado "não certificado" é publicado sem nova tentativa no mesmo conjunto.
- **SC-M008**: A pessoa de RH conclui 34 fichas em até 1h50, e nenhuma delas contém campo oculto, o que é conferido por teste.
- **SC-M009**: Um ciclo de auto-improve termina com modelo simulado: um candidato pior é barrado, um candidato aprovado no portão não entra em uso sem aprovação, e a reversão restaura o hash anterior.
- **SC-M010**: Uma rodada real de cerca de 50 casos termina dentro do limite de gasto, com custo por decisão e taxa de respostas cortadas publicados.
- **SC-M011**: O diagnóstico de motivos de revisão roda sem nenhuma chamada de modelo.
- **SC-M012**: A API deixa de devolver exemplo fixo para vaga com medição injetada e separa dados de empresas diferentes em 100% dos testes.
- **SC-M013 (alvo proposto, não decidido)**: alcance automático de pelo menos 50%, alcance final de pelo menos 80% e revisão de até 30%, medidos no conjunto forte, sabendo que a composição dele não é a de produção.

## Premissas

- Todos os dados são sintéticos. Coleta real, contratações e Nara real estão fora desta feature.
- Os alvos do SC-M013 vêm do relatório como propostas e não têm benchmark público.
- "95% de confiança" é unilateral nos números desta spec. O teto de Wilson do código é bilateral, o que explica parte da diferença entre as colunas.
- **A confirmar:** a certificação conta casos independentes, porque o limite binomial supõe independência. Sem essa premissa, a PR #54 passaria a parecer ter 28 observações na prova, quando tem 3 entradas distintas.
- **A confirmar:** enquanto a faixa verde não estiver certificada, todas as aprovações automáticas devem ser auditadas depois da ação, como sugere o relatório.
- **A confirmar:** a mudança de limiar pelo auto-improve exige um novo termo do mandato, com pessoa nomeada. A alternativa está na decisão R3 do `plan.md`.
- **A confirmar:** os limites da sessão de RH partem de concordância de pelo menos 75% e kappa de pelo menos 0,5, que são hipóteses do relatório de validação.
- A certificação medida contra a pessoa de RH pediria 59 aprovações avaliadas por ela, entre 118 e 236 fichas, ou 5 a 10 horas. A sessão de 34 fichas confere o gerador e não certifica o agente.
- Passar nesta medição não prova ausência de viés, conformidade legal nem qualidade de contratação.
- O prazo global de `AGENTS.md` continua valendo: nenhuma funcionalidade nova depois de domingo, às 11h.
