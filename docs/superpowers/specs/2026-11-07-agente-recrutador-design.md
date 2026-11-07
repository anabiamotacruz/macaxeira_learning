# Agente recrutador conectado à Nara: design

**Data:** 2026-11-07. **Estado:** aprovado pelo time em 2026-11-07.
**Contexto:** Converge Challenge powered by Tako, Desafio Tako (digital workers para RH).

Neste documento, "decidido" vem do time. "Decisão de design" é uma proposta do autor, que pode ser corrigida.

## 1. Intenção

Hoje existe um gargalo em encontrar pessoas capacitadas para cada vaga, e construir um banco de talentos útil é a parte mais difícil (decidido). O produto é um digital worker que constrói e mantém o banco de cada empresa (decidido). Quando recebe uma vaga, encontra e analisa candidatos, explica cada escolha, faz o primeiro contato e entrega a pessoa à Nara com o contexto. A Nara agenda e conduz a entrevista como já faz hoje (decidido).

Este é um produto próprio, que a Tako pode usar, e não um produto feito para ela (decidido). Para uma empresa como a Tako, a Nara entrevista quem chega, e este agente traz para ela pessoas mais adequadas, com contexto para uma entrevista melhor.

Essa dor ainda precisa ser confirmada com recrutadores e com a Tako.

## 2. Objetivos, não objetivos e antiobjetivos

**Objetivos**

- Construir e manter um banco de talentos próprio para cada empresa, com autorização e dados atualizados (decidido).
- Encontrar candidatos adequados a uma vaga configurada pelo administrador, para qualquer tipo de vaga (decidido).
- Explicar cada indicação com evidências, histórico de trabalho e lacunas do currículo ou do perfil (decidido).
- Convidar o candidato e enviar o link de agendamento da Nara (decidido).
- Melhorar a busca com os resultados da Nara, com aprovação humana (decisão de design, inspirada na Sherpa).
- Atender aos quatro critérios do evento, com pesos iguais: protótipo e aderência, viabilidade como startup, criatividade e originalidade, e pitch.

**Não objetivos**

- Agendar ou conduzir entrevistas, ou avaliar candidatos no lugar da Nara.
- Decidir contratações.
- Integrar de verdade com a Nara, ATS ou WhatsApp no hackathon. O LinkedIn é coletado pelo conector, via Bright Data.
- Criar uma rede compartilhada de candidatos entre empresas. Isso fica como visão futura.
- Otimizar sites em geral. Do conceito original, fica apenas a melhoria contínua da busca e dos convites.

**Antiobjetivos**

- Um wrapper fino que só envia currículos a um modelo.
- Indicações sem evidência ou sem explicação.
- Filtrar por gênero, idade, raça, religião, estado civil ou outro dado sensível.
- Apresentar uma simulação como se fosse integração real.

## 3. Restrições

- **Prazo:** o código do projeto começa em 7/11, às 10h. A submissão termina em 8/11, às 13h.
- **Dados:** somente sintéticos, exceto os perfis do LinkedIn coletados pelo conector via Bright Data.
- **Time:** 4 pessoas trabalhando em paralelo (decidido).
- **Submissão:** descrição, vídeo de demonstração, link navegável e testável, material do Demo Day e lista de ferramentas, modelos e APIs. Sinalizar que responde ao Desafio Tako.
- **Demo Day:** 3 minutos. Os jurados testam a solução.
- **Ambiente disponível:** Python 3.12, FastAPI, Pydantic, Next, Langfuse e Featherless, com o `GLM-5.2` testado. Consulte `AGENTS.md`.

## 4. Abordagens

| Abordagem | Ganha | Perde | Decisão |
|---|---|---|---|
| **1. Fluxo com regras e IA nas decisões abertas** | Confiabilidade, auditoria, custo e depuração | Menos impacto pela arquitetura | **Núcleo do produto** |
| **2. Vários agentes especializados** | Impacto visual e divisão natural | Mais falhas, custo e dificuldade para explicar decisões | Descartada como arquitetura |
| **3. Tudo por MCP** | Conversa com a Tako e facilita trocar conectores | Tempo em infraestrutura | Vira um **adaptador** sobre a abordagem 1 |

O time propôs usar a abordagem 1 como principal e a 3 por MCP. A abordagem 1 foi confirmada na aprovação deste documento.

Da abordagem 2 ficam duas ideias: analisar perfis em paralelo e usar um revisor independente antes de cada indicação.

## 5. Fluxo do digital worker

### Construção do banco (decidido; detalhes como decisão de design)

Cada empresa tem o próprio banco. O agente:

1. **Organiza a base:** importa currículos, planilhas, ATS e avaliações e remove duplicatas.
2. **Pede autorização:** convida a pessoa a continuar no banco, com prazo e opção de sair.
3. **Atualiza por conversa:** pergunta o que mudou, disponibilidade e interesses, em poucas mensagens.
4. **Recebe documentos:** currículo, PDF do LinkedIn ou GitHub autorizado, enviados pela própria pessoa.
5. **Traz gente nova:** página de carreira, QR em eventos, indicações, comunidades e processos anteriores.
6. **Mantém a base viva:** recontata com moderação, renova autorizações e remove dados vencidos ou a pedido.

O principal risco é a pessoa não ver motivo para responder. A proposta precisa oferecer vagas mais certeiras, retorno sobre o perfil e controle dos próprios dados.

### Da vaga à entrega

A meta do agente é configurável. Exemplo: "Entregar à Nara 5 candidatos interessados para esta vaga em 7 dias."

1. **Configurar:** o agente lê a descrição da vaga e propõe requisitos eliminatórios, competências, pesos, limites e meta. O administrador aprova.
2. **Buscar:** traduz a vaga em consultas para cada fonte, amplia ou restringe filtros e remove duplicatas.
3. **Analisar:** extrai histórico de trabalho, verifica requisitos e reúne evidências para cada competência.
4. **Revisar:** um revisor independente tenta derrubar a indicação e aponta exageros e afirmações sem evidência.
5. **Decidir:** descarta, indica ou pede a decisão humana, conforme as regras.
6. **Convidar:** faz o primeiro contato, explica a vaga e envia o link de agendamento da Nara (decidido).
7. **Conversar:** trata interesse, dúvidas, recusa, silêncio e pedido para não receber contato.
8. **Entregar:** envia à Nara o pacote de contexto.
9. **Aprender:** recebe o resultado da Nara e propõe ajustes na busca.
10. **Encerrar ou replanejar:** conclui ao atingir a meta. Se ela estiver em risco, amplia a busca ou avisa o recrutador.

O fluxo é uma máquina de estados em código. O modelo interpreta textos, propõe consultas, redige mensagens e explica escolhas. Ele não decide requisitos eliminatórios, autorização, limites de contato nem permissões.

### Autonomia (decisão de design)

| Faz sozinho | Precisa de aprovação | Sempre humano |
|---|---|---|
| Buscar e analisar perfis | Critérios e meta da vaga | Decidir contratação |
| Descartar quem falha em requisito objetivo, com registro | Primeiro lote de convites da vaga | Avaliar a entrevista |
| Responder dúvidas previstas no material da vaga | Mudanças propostas pelo aprendizado | Resolver dúvidas jurídicas |
| Aplicar limites de contato e opt-out | Casos ambíguos | Autorizar usos fora da política |

## 6. Pacote de contexto para a Nara

Cada entrega contém (conteúdo decidido; estrutura como decisão de design):

- Identificação da vaga e do candidato.
- Motivo da escolha, por critério.
- Histórico de trabalho.
- Evidências, com a fonte de cada uma.
- Lacunas do currículo ou do perfil.
- Pontos que a Nara deve aprofundar.
- Observações do revisor.
- Autorização, fonte de origem e estado do contato.
- Identificador do rastro, para auditar a decisão.

Uma lacuna é uma pergunta a investigar, não um defeito. Períodos sem trabalho, por exemplo, nunca reduzem a nota por si só.

## 7. Fontes de candidatos

Fontes reais são uma **lacuna de pesquisa durante o hackathon** (decidido). Para isso não travar o time:

- **Banco de talentos:** primeira fonte da busca, separado por empresa.
- **Conector único:** toda fonte implementa a mesma interface.
- **Rede de talentos simulada:** fonte externa secundária, em um serviço separado, com busca, paginação, limite de requisições, duplicatas e dados incompletos.
- **GitHub real (opcional):** API oficial, restrita a contas e repositórios de teste do time, para mostrar evidência técnica. Sem varredura de pessoas reais e sem contato frio.
- **LinkedIn:** o conector coleta pela Bright Data.

A identificação de cada fonte como simulada ou real aparece na interface.

## 8. Dados sintéticos

Foco da demo: vagas de tech (decidido). A configurabilidade é demonstrada quando um jurado altera a vaga. Uma vaga fora de tech entra se houver tempo (decisão de design).

- **Volume:** cerca de 200 perfis, pelo menos 3 vagas e 2 empresas, para testar o isolamento.
- **Base bagunçada:** currículos e planilhas com duplicatas, autorizações vencidas e perfis desatualizados.
- **Realismo:** usar estatísticas públicas e a CBO quando valer o tempo. Se atrapalhar o prazo, usar distribuições definidas à mão e declarar isso.
- **Sujeira planejada:** sinônimos de cargo, erros de digitação, duplicatas, exageros, lacunas e informações faltantes.
- **Armadilhas:** bom candidato com cargo incomum, currículo forte sem requisito eliminatório e pessoa que pediu para não receber contato.
- **Comportamentos simulados:** aceitar, recusar, perguntar, ficar em silêncio e sair da lista.
- **Nara simulada:** recebe o pacote, oferece um link de agendamento fictício e devolve avaliações sintéticas. Sempre identificada como simulação.

Essas simulações provam o funcionamento do agente. Não provam taxas reais de resposta nem contratações.

## 9. Fora da demo: orientações do guia

Estes pontos vêm do guia do evento e sustentam o critério de protótipo. Entram no núcleo desde o início, no subconjunto da seção 12.

### Confiabilidade

| Situação | Comportamento |
|---|---|
| Fonte fora do ar ou com limite | Repete com espera, continua com outras fontes e registra a cobertura parcial |
| Modelo indisponível | Repete e usa um modelo alternativo; sem nenhum, pausa e retoma do último estado |
| Resposta inválida do modelo | Valida com esquema, tenta corrigir e, se persistir, envia para revisão humana |
| Vaga ambígua | Pergunta ao administrador; não inventa requisitos |
| Poucos candidatos | Amplia dentro dos limites aprovados ou avisa que a meta está em risco |
| Falha ao enviar convite ou pacote | Repete sem duplicar, usando uma chave única |
| Texto de candidato com instruções | Trata como dado; nunca altera regras |

O estado fica salvo após cada etapa, para o processo ser retomado.

### Medição

Um comando único roda o conjunto de avaliação e gera um relatório. O painel mostra o último resultado.

| Métrica | O que mostra |
|---|---|
| Precisão entre os 5 primeiros | Se os melhores indicados são mesmo bons |
| Armadilhas tratadas corretamente | Se o agente resiste a exageros e casos difíceis |
| Violações de requisito eliminatório | Deve ser zero |
| Contatos a quem pediu para sair | Deve ser zero |
| Afirmações sem evidência | Qualidade das explicações |
| Mudança ao trocar nome ou gênero | Teste de viés; o resultado deve permanecer igual |
| Taxa de conclusão diante de falhas injetadas | Confiabilidade |

As respostas certas são definidas à parte dos dados entregues ao agente. Se possível, um recrutador avalia uma amostra às cegas. Sem isso, as respostas vêm das regras usadas na geração e o relatório declara esse limite. Os resultados de produção e os de avaliação ficam separados.

### Custo e latência

Cada execução registra tokens, custo e tempo por etapa e por candidato. O painel mostra o custo por candidato analisado e por candidato entregue à Nara.

Decisão de design: modelo mais barato em extração e triagem; `GLM-5.2` em análise e revisão. Modelos e limites serão definidos com testes. A comparação com o processo manual só pode usar números reais de um recrutador. Sem isso, o pitch mostra só o custo do agente.

### Autonomia com auditoria

- **Tracing desde o primeiro dia:** Langfuse em cada chamada de modelo e ferramenta.
- **Registro de decisões:** cada decisão guarda entrada, regra aplicada, evidências, resultado e responsável.
- **Visão humana:** a partir de um candidato, é possível ver por que ele foi indicado ou descartado.
- **Segredos:** chaves ficam fora do repositório e dos rastros.

## 10. Melhoria contínua

Inspirada na Sherpa, a melhoria só muda a configuração após aprovação:

1. Reunir resultados da Nara e respostas dos candidatos.
2. Identificar um padrão. Exemplo: as indicações falham sempre no mesmo critério.
3. Propor o ajuste, sem incluir critérios proibidos.
4. Testar no conjunto de avaliação e mostrar o antes e o depois.
5. Pedir aprovação do recrutador.
6. Aplicar, acompanhar e permitir reverter.

Isso também é o principal ponto de originalidade, com a entrega à Nara com contexto e evidência.

## 11. Arquitetura

Decisão de design, com API, MCP e painel usando o mesmo núcleo:

- **Núcleo:** máquina de estados, regras e decisões.
- **Modelos:** cliente único compatível com a API da OpenAI, usando a Featherless por padrão.
- **Conectores:** fontes, mensagens e Nara, cada um com sua interface.
- **Serviços simulados:** rede de talentos, mensageiro e Nara.
- **API:** FastAPI.
- **Painel:** Next, com meta, candidatos, explicações, aprovações, métricas e rastro.
- **MCP:** adaptador fino, feito depois do fluxo principal, com poucas ferramentas como `buscar_candidatos`, `explicar_escolha` e `entregar_a_nara`.

## 12. Trabalho em paralelo

Antes do paralelismo, o time define em conjunto os contratos: modelos de vaga, candidato, evidência, decisão, convite, pacote e eventos. Depois, cada frente trabalha com simulações das demais.

| Frente | Responsabilidade |
|---|---|
| **1. Agente** | Máquina de estados, regras, decisões e aprendizado |
| **2. Fontes e dados** | Dados sintéticos, rede simulada, análise de perfis e GitHub opcional |
| **3. Contato e Nara** | Convite, conversa, Nara simulada e pacote de contexto |
| **4. Produto e qualidade** | Painel, avaliações, métricas, demo e material de submissão |

Cada pessoa trabalha na própria máquina, e as quatro frentes têm a mesma prioridade (decidido). Os responsáveis serão definidos depois.

### Limites das frentes (decisão de design)

Repositório: `anabiamotacruz/macaxeira_learning`.

| Frente | Pasta e branch | Entrega para as demais | Usa das demais |
|---|---|---|---|
| **1. Agente** | `backend/agente`, `frente/agente` | Execução da vaga, decisões e eventos | Fontes, contato e Nara, por interfaces |
| **2. Fontes e dados** | `backend/fontes`, `dados`, `frente/fontes` | Busca de candidatos, perfis e análise | Contratos |
| **3. Contato e Nara** | `backend/contato`, `backend/nara_simulada`, `frente/contato` | Convite, respostas, pacote e resultado | Contratos |
| **4. Produto e qualidade** | `web`, `avaliacoes`, `docs/pitch`, `frente/produto` | Painel, relatório de avaliação, demo e submissão | API e eventos |

- **Contratos:** ficam em `backend/contratos`. Mudanças depois do acordo inicial exigem aviso às quatro frentes.
- **Integração:** cada frente começa com simulações das outras. As entregas entram na `main` por pull request, em ciclos curtos.
- **Comunicação:** como as máquinas são diferentes, a pasta local não sincroniza. O time usa o repositório e o grupo.
- **Ambiente:** cada pessoa prepara a própria máquina e usa a própria chave da Featherless. Chaves nunca entram no repositório.
- **Langfuse:** projeto compartilhado, com uma configuração comum feita no início.

### Ordem de corte (decisão de design)

**Precisa existir na submissão:**

- Vaga, busca, análise, revisor, decisão, convite e entrega à Nara simulada.
- Link testável, tracing, registro de decisões e custo por candidato.
- Avaliação com armadilhas, requisitos eliminatórios, opt-out e teste de viés.
- Falhas de fonte e de modelo, e resposta inválida do modelo.

**Cortar nesta ordem, se faltar tempo:**

1. Vaga fora de tech.
2. GitHub real.
3. MCP, que o guia não exige.
4. Retomada automática depois de queda, mantendo o estado salvo.
5. Aprendizado automático. Nesse caso, ele vira uma proposta simples baseada em regras, sem experimento.

### Teste do jurado (decisão de design)

O teste roda de verdade, não com resultados prontos:

- **Funil:** filtros determinísticos reduzem os 200 perfis, e só os melhores passam por análise e revisão.
- **Tempo:** a tela mostra o progresso e os primeiros resultados enquanto o restante termina. Cache evita refazer análises iguais.
- **Sessões:** uma vaga por sessão, com botão de reinício e limite de gasto por sessão.
- **Vaga sem base:** o agente responde que há poucos candidatos e que a meta está em risco, sem inventar pessoas.
- **Reserva:** uma execução gravada fica pronta, identificada como gravação, para o caso de a internet ou a API falharem.

### Prazos internos (decisão de design)

- **Sábado, às 13h:** se a Tako não oferecer acesso de teste até aí, a Nara simulada fica congelada.
- **MCP:** expõe as nossas ferramentas. Se a Tako oferecer acesso ao dela, o conector da Nara passa a seguir o formato real.

## 13. Demo de 3 minutos

1. **Problema:** o gargalo de encontrar pessoas para uma vaga de tech.
2. **Banco:** o agente organiza uma base bagunçada. Um jurado entra como candidato, com dados fictícios, autoriza e atualiza o perfil.
3. **Vaga:** o agente propõe os critérios, e um humano aprova.
4. **Busca:** procura primeiro no banco, analisa os perfis, descarta armadilhas e mostra por que escolheu cada pessoa.
5. **Falha ao vivo:** uma fonte cai, e o agente continua e registra a cobertura parcial.
6. **Teste do jurado:** ele altera a vaga ou responde como candidato.
7. **Entrega:** o candidato aceita, recebe o link da Nara, e o pacote é entregue à Nara simulada.
8. **Aprendizado:** o resultado volta, e o agente propõe um ajuste para aprovação.
9. **Prova:** a tela mostra métricas, custo por candidato e rastro.
10. **Negócio:** quem paga, mercado e relação com a Tako.

## 14. Negócio para o pitch

Tudo aqui é hipótese até haver validação:

- **Quem paga:** empresas com alto volume de vagas ou dificuldade de preenchê-las, por meio do RH ou recrutamento.
- **Modelo:** cobrança por candidato qualificado entregue à entrevista, a validar.
- **Caminho de crescimento:** começar com o banco de cada empresa, depois adicionar canais e parcerias. Uma rede compartilhada fica como visão de longo prazo.
- **Relação com a Tako:** ela é uma possível usuária, não a dona do produto. A Nara é a primeira integração, e a camada de conectores permite atender outros sistemas.
- **Diferencial:** construir e manter o banco vivo, com evidência, contexto para a entrevista e aprendizado com o resultado. Gem, Beamery, Phenom, Gupy, hireEZ, GoPerfect, Juicebox e Paradox atuam perto disso, e falta comparar melhor.

Nenhum número de mercado ou economia entra no pitch sem fonte.

## 15. Fica para quem constrói

- Formato exato dos contratos, respeitando as seções 6 e 12.
- Estrutura do repositório, banco de dados e estratégia de deploy para o link testável.
- Modelo específico por etapa e limites de orçamento.
- Forma de hospedar o Langfuse.
- Detalhes da interface do painel.

## 16. Em aberto

- Confirmar a dor com recrutadores e com a Tako.
- Validar por que candidatos responderiam e permaneceriam no banco.
- Pesquisar fontes reais autorizadas e o tratamento da LGPD.
- Perguntar à Tako se é possível acessar um ambiente de teste da Nara ou do MCP.
- Decidir o cliente inicial para o pitch.
