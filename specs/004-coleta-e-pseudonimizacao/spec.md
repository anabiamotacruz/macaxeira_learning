# Especificação da feature: coleta e pseudonimização

**Branch da feature**: `frente/agente-spec-004`
**Criada em**: 2026-11-07
**Estado**: Rascunho, para revisão do time
**Base do código lido**: `frente/agente-integracao`, commit `536b94e`. Esse código ainda não está na `main`.
**Entrada**: fontes plugáveis, coleta por provedores contratados, perfil estruturado com provas e pseudonimização antes do modelo e dos rastros.
**Fontes**: `backend/fontes/`, `backend/contratos/`, a arquitetura de coleta (`origin/main`, `docs/superpowers/specs/2026-11-07-arquitetura-coleta-e-agente.md`, "arquitetura" daqui em diante) e a revisão independente `06-revisao-pseudonimizacao-api.md` (notas locais, fora do repositório, feita sobre o commit `f07125c`, "revisão" daqui em diante).

Esta spec não altera a feature 001. O que falta para fontes reais funcionarem de ponta a ponta está em `tasks.md`, e as divergências entre documentos e código estão em `plan.md`.

## Decisões registradas

Estas decisões estão **decididas** e não são reabertas aqui.

| Id | Decisão | Onde está | Estado no código |
| --- | --- | --- | --- |
| D1 | Fontes plugáveis: a lista é configurável e só entra o que for habilitado. | Pedido do time; arquitetura, seção 10 | Existe, sem ligação à montagem |
| D2 | Brave Search API para a busca, Bright Data para ler páginas e People Data Labs para enriquecer. Cada um fica ativo quando a chave está configurada. Não há proxy próprio. | Decisão do responsável pelo produto, que responde a Q2 e substitui "Bright Data como principal"; arquitetura, seções 3 e 4 | Existe, sem ligação à montagem |
| D3 | `MODO_DADOS=sinteticos` na demo. Esse modo manda sobre as chaves. | Pedido do time; arquitetura, seções 13 e 14 | Existe, sem ligação à montagem |
| D4 | Pseudonimização antes do modelo e dos rastros, com cofre separado. | Pedido do time | Existe na análise e na revisão; identificadores comuns ainda escapam |
| D5 | Perfil estruturado em JSON. | Pedido do time; `PerfilColetado` | Existe para GitHub, site e documento; falta para provedores |
| D6 | Provas de origem e data em cada fato. | Pedido do time; `FatoColetado` | Existe no contrato; a prova se perde ao virar `Candidato` |
| D7 | Base legal de legítimo interesse (art. 7º, IX, e art. 10), como consta na arquitetura, seção 5, **pendente de parecer jurídico**. | Arquitetura, seções 1 e 5 | Não refletida: o funil exige autorização (ver Q1) |

## Pseudonimização não é anonimização

- **Anonimização:** o dado perde o vínculo com a pessoa, sem caminho de volta por meios razoáveis (art. 5º, III e XI, da LGPD). Pelo art. 12, dado anonimizado deixa de ser pessoal, salvo se o processo puder ser revertido por meios próprios ou com esforços razoáveis. O §1º lista os fatores do que é razoável.
- **Pseudonimização:** o art. 13 trata de estudos em saúde pública. O §4º dele serve aqui só como definição: o dado só volta a se associar à pessoa com uma informação adicional, mantida separadamente pelo controlador em ambiente controlado e seguro. Aqui, essa informação é o cofre.
- **Consequência para este produto:** o que vem do art. 5º e do art. 12, e não do art. 13, é que dado que pode ser revertido segue sendo pessoal, sujeito às mesmas regras de base legal, remoção, retenção e segurança. O texto enviado ao modelo nunca é descrito como anônimo.
- **Limite da leitura:** esta interpretação ainda precisa de confirmação jurídica, inclusive o uso em recrutamento de uma definição escrita para estudos em saúde pública (T066).

## Dados do LinkedIn: o que é fato hoje

| Fato | Evidência |
| --- | --- |
| O time decidiu incluir dados do LinkedIn por provedores contratados. A coleta é feita pelo provedor, sob a responsabilidade dele, dentro dos termos e do plano contratado. | Arquitetura, seção 3 e seção 4, camada 6 |
| O código atual dos conectores, escrito pelo agente, bloqueia esses domínios e **não faz essa coleta**. | `url_segura.py`: `DOMINIOS_LINKEDIN` (`linkedin.com`, `linkedin.cn`, `linked.in`, `licdn.com`, `lnkd.in`), `validar_texto_de_busca` e `remover_links_proibidos`. `bright_data.py`: `EXCLUSAO_NA_BUSCA`. `people_data_labs.py`: não pede `linkedin_url` |
| Esse bloqueio tem testes. | `test_recusa_linkedin_em_qualquer_forma`, `test_recusa_pagina_que_se_declara_do_linkedin`, `test_busca_descarta_resultados_proibidos`, `test_linkedin_nunca_e_buscado_nem_por_terceiros_mesmo_indicado` |
| A mesma arquitetura também diz que o sistema nunca abre a URL do LinkedIn e mantém o bloqueio fixo em código. | Arquitetura, seções 4, 6 e 12 |
| A coleta e a entrada desses dados são **responsabilidade e implementação do time**, numa tarefa sem dono automático. | `tasks.md`, tarefa T065 |
| PDF do LinkedIn entra hoje quando a própria pessoa envia o arquivo. | `documentos.py`; arquitetura, camada 5 |

**Sobre a Bright Data:**

- **Web Unlocker contorna bloqueios.** O cabeçalho de `bright_data.py` registra que a API não tem parâmetro para desligar o desbloqueio, que o resolvedor de CAPTCHA só se desliga no painel da zona e que a troca de proxies e o tratamento de impressão digital continuam ligados, porque são o próprio produto. O leitor próprio (`site_publico.py`) faz o oposto: login, CAPTCHA ou bloqueio encerram a leitura.
- **A busca saiu da Bright Data por padrão.** A SERP só entra com `BRIGHTDATA_ZONA_BUSCA` e `BRIGHTDATA_BUSCA_HABILITADA=1`. Essa opção usa alvo Google, que a arquitetura deixa de fora, e o estado das fontes avisa quando ela está ligada. Na consulta real, o alvo Bing devolveu resposta vazia.

**Sobre a Brave:**

- **Para começar, basta a busca.** Na prática: configurar `BRAVE_API_KEY` e deixar `BRIGHTDATA_ZONA_WEB` vazia. O código mantém o trecho do resultado, sem ler a página (`test_falha_ao_ler_uma_pagina_nao_perde_o_trecho`).
- **Armazenar depende de contrato.** Os termos (seção 3(b)(i)) proíbem guardar, fazer cache ou montar base de resultados, salvo armazenamento transitório necessário à operação. A questão Q4 trata disso.

## Cenários de usuário e testes *(obrigatório)*

### História 1: escolher as fontes pela configuração (Prioridade: P1)

Quem opera o produto liga ou desliga fontes pela configuração. A demo roda só com dados sintéticos, mesmo que existam chaves no ambiente. Com chaves e sem o modo sintético, a Brave faz a busca, a Bright Data lê as páginas e a People Data Labs enriquece.

**Por que esta prioridade**: sem isso, a demo pode chamar um provedor real por engano, e o modo real não tem como ser ligado.

**Teste independente**: montar a fonte com um transporte falso e variar o ambiente. Conferir quais provedores entram, em que ordem, qual o estado mostrado e se algum pedido saiu.

**Cenários de aceite**:

1. **Dado** `MODO_DADOS=sinteticos` e todas as chaves configuradas, **quando** a montagem cria as fontes, **então** nenhum provedor nem transporte é criado e o estado diz "somente dados sintéticos".
2. **Dado** todas as chaves e o modo real, **quando** a primeira consulta de texto é feita, **então** a Brave é chamada primeiro, a Bright Data não recebe a busca, e cada troca de provedor é registrada com o motivo.
3. **Dado** nenhuma chave, **quando** a API sobe, **então** o estado diz "sem fontes externas", avisa que falta `BRAVE_API_KEY` e o agente segue só com o banco de talentos, sem troca silenciosa.
4. **Dado** um valor inválido em `MODO_DADOS`, **quando** a montagem roda, **então** a subida é recusada.
5. **Dado** a configuração real, **quando** a API sobe pela montagem real, **então** as fontes configuradas são as que o fluxo usa, e a subida é recusada se faltar uma peça obrigatória.

---

### História 2: pseudonimizar antes do modelo e dos rastros (Prioridade: P1)

A pessoa que analisa a vaga recebe análises feitas sem que o modelo veja nome, contato, documento ou endereço. Depois da decisão de indicar, e só então, o pacote volta a mostrar os valores citados, com registro na auditoria.

**Por que esta prioridade**: é a principal proteção de dados pessoais do fluxo e a base da equidade por construção.

**Teste independente**: usar um modelo falso que guarda os prompts e uma captura de rastros. Conferir que nenhum valor do conjunto sintético aparece neles e que a reidentificação falha fora do caso permitido.

**Cenários de aceite**:

1. **Dado** um perfil com nome, e-mail, telefone e empregador, **quando** ele vai ao modelo, **então** só marcadores estáveis aparecem no prompt e nos rastros.
2. **Dado** dois perfis iguais, com nome e gênero trocados, **quando** são preparados, **então** o texto enviado é o mesmo.
3. **Dado** um trecho citado pelo modelo, **quando** é conferido, **então** ele é localizado no texto pseudonimizado e mapeado até a fonte original; trecho inventado é recusado.
4. **Dado** uma decisão de indicar da mesma empresa, vaga e pessoa, **quando** o pacote é entregue, **então** só os marcadores citados são revelados e o registro é gravado antes; sem essa decisão, nada é revelado.
5. **Dado** os formatos listados no achado A-1 (domínios fora da lista, e-mail com espaços, nome em caixa alta, caracteres invisíveis e homóglifos), **quando** o perfil é preparado, **então** nenhum deles chega ao modelo.

---

### História 3: perfil estruturado com prova em cada fato (Prioridade: P1)

Quem revisa uma indicação consegue ver, para cada fato, de onde ele veio, quando foi coletado, o trecho literal e se ele é comprovado, declarado ou inferido.

**Por que esta prioridade**: a constituição exige evidência antes de indicação, e hoje a prova termina na conversão para `Candidato`.

**Teste independente**: gerar um perfil por tipo de fonte, com dados sintéticos, e validar cada fato contra o esquema. Depois, seguir um fato até a decisão.

**Cenários de aceite**:

1. **Dado** um perfil de qualquer fonte, **quando** é validado, **então** todo fato traz fonte, exatamente uma origem (URL ou documento), data da coleta, trecho e tipo.
2. **Dado** um resultado de provedor, **quando** ele vira perfil estruturado, **então** nenhum fato sai como comprovado.
3. **Dado** um repositório público com linguagem informada pela API, **quando** o perfil é convertido, **então** o atributo comprovado é preenchido por código, com a origem registrada.
4. **Dado** uma decisão baseada num fato coletado, **quando** a evidência é aberta, **então** ela mostra a mesma origem e a mesma data do fato.
5. **Dado** texto com instrução ao avaliador, **quando** a fonte o retira e gera alerta, **então** o alerta chega à decisão e tira a pessoa da faixa verde.

---

### História 4: reconhecer a mesma pessoa entre fontes (Prioridade: P2)

Quem revisa os candidatos vê cada pessoa uma vez, com todas as fontes dela. Homônimos não são juntados.

**Por que esta prioridade**: sem isso, a mesma pessoa pode gastar duas análises e receber dois contatos. O opt-out também pode valer só para um dos registros.

**Teste independente**: usar um conjunto sintético com pares ligados por link cruzado, pares de homônimos e pares só com nome e cidade parecidos. Conferir as junções sem passar por modelo.

**Cenários de aceite**:

1. **Dado** um perfil de provedor com `github_url` igual ao de uma conta coletada, **quando** a identidade é resolvida, **então** existe uma pessoa com as duas fontes.
2. **Dado** dois registros com o mesmo nome e a mesma cidade, sem link em comum, **quando** a identidade é resolvida, **então** eles ficam separados, com uma sugestão registrada para revisão humana.
3. **Dado** registros juntados em que um pediu opt-out, **quando** o funil roda, **então** vale a regra mais restritiva para a pessoa inteira.
4. **Dado** duas empresas com a mesma pessoa, **quando** a identidade é resolvida, **então** nada de uma empresa aparece ou é usado na outra.

---

### História 5: a pessoa coletada chega à análise (Prioridade: P1)

Quem abre uma vaga em modo real recebe análises de pessoas encontradas em fontes externas, dentro da base legal decidida. Hoje, todas são cortadas antes da análise.

**Por que esta prioridade**: é o que faz a coleta valer alguma coisa. Depende da resposta à questão Q1.

**Teste independente**: rodar o fluxo pela montagem real, com transporte e modelo falsos e dados sintéticos. Conferir que a pessoa chega ao analisador e que o motivo fica registrado.

**Cenários de aceite**:

1. **Dado** uma conta do GitHub com consentimento registrado para a empresa, **quando** a vaga busca, **então** a pessoa chega à análise, e não termina em `funil:sem_autorizacao`.
2. **Dado** um site indicado pela própria pessoa, **quando** a vaga busca, **então** ocorre o mesmo.
3. **Dado** uma pessoa com requisito eliminatório comprovado por fato de fonte verificável, **quando** a decisão é tomada, **então** ela pode chegar à faixa verde.
4. **Dado** a mesma vaga com `Desenvolvedora Python` ou `Desenvolvedor Python` no perfil, **quando** a consulta usa uma das formas, **então** o resultado é o mesmo.

---

### História 6: remover a pessoa de todos os lugares (Prioridade: P2)

A pessoa que pede exclusão some de banco, cofre, progresso das vagas, análises, decisões e trechos citados, venha de onde vier. Fica só o bloqueio irreversível, para ela não voltar.

**Por que esta prioridade**: a pseudonimização mantém o dado pessoal, então o direito de exclusão precisa alcançar o cofre e as cópias.

**Teste independente**: criar uma pessoa sintética em cada fonte, rodar parte de uma vaga, remover e procurar os valores em todo o armazenamento.

**Cenários de aceite**:

1. **Dado** uma pessoa removida, **quando** os candidatos da vaga são listados, **então** nome, e-mail e perfil não aparecem.
2. **Dado** uma análise em curso, **quando** a pessoa é removida, **então** o cofre não volta a ter linhas dela.
3. **Dado** uma pessoa que veio de fonte externa e nunca entrou no banco, **quando** é removida, **então** a operação termina sem erro, grava o bloqueio e ela não volta na busca seguinte.
4. **Dado** uma decisão de corte por opt-out, **quando** é lida, **então** não traz URL nem nome de arquivo identificável.

---

### História 7: conteúdo hostil não derruba nem contamina a coleta (Prioridade: P3)

Quem escreve a página ou o arquivo é a própria pessoa candidata. O conteúdo não pode parar a busca da empresa nem virar fato por meio de texto invisível.

**Por que esta prioridade**: as proteções básicas existem. Faltam os casos da revisão.

**Teste independente**: usar páginas e PDFs sintéticos hostis, um por caso, e conferir o resultado da leitura e o estado da vaga.

**Cenários de aceite**:

1. **Dado** uma página com `<a href="tel:">`, **quando** a busca roda, **então** as demais pessoas continuam sendo lidas.
2. **Dado** texto escondido por classe em `<style>` ou por modo invisível em PDF, **quando** é lido, **então** não vira fato e gera alerta.
3. **Dado** um perfil de 200 mil caracteres com o nome repetido, **quando** é pseudonimizado, **então** termina dentro do limite de tempo, sem parar outras empresas.
4. **Dado** um erro inesperado de uma fonte, **quando** a vaga busca, **então** ela não fica presa em `buscando`.

### Casos de borda

- **Chave em branco:** conta como ausente, e o provedor não entra.
- **Token da Bright Data sem zona de leitura:** o provedor entra na cadeia e a leitura falha com motivo próprio, sem cobrança.
- **Bright Data sem as duas variáveis da SERP:** ela não aceita consulta de texto, e o estado avisa quando só uma delas foi definida.
- **SERP ligada de propósito:** entra depois da Brave, e o estado avisa que o alvo é o Google.
- **Sem `BRAVE_API_KEY`:** a Brave fica de fora, e o estado avisa que a busca na web está indisponível.
- **Todos os provedores fora do ar:** o fluxo segue com cobertura parcial, com o motivo registrado.
- **Busca de texto com a Brave fora do ar:** a People Data Labs não aceita consulta de texto e a SERP fica desligada por padrão, então não há reserva para a busca. O resultado é cobertura parcial, não troca.
- **Página além da décima na Brave:** o `offset` da API vai só até 9, então a consulta termina sem chamar nem cobrar.
- **Cota mensal da Brave esgotada:** o 429 não é repetido e sai com o motivo `sem_creditos`. Limite por segundo é repetido.
- **Orçamento esgotado no meio da execução:** nada é chamado além do limite, e a reserva é devolvida em caso de falha.
- **Resultado de busca sem página lida:** o trecho é mantido como declarado, sem virar comprovado.
- **Página que se declara de domínio bloqueado:** é recusada, mesmo que a URL pedida seja outra.
- **E-mail de terceiro numa página:** não vira contato da pessoa (achado M-5).
- **Contato vindo de provedor:** não vira canal de contato, nem depois de autorização, sem confirmação da própria pessoa.
- **Telefone encontrado em site ou documento:** não é guardado como canal (arquitetura, seção 3).
- **Marcador escrito pela própria pessoa:** vira `(marca removida)`, inclusive na forma de largura total (achado B-3).
- **Mesmo valor em empresas diferentes:** numeração e valores ficam isolados por empresa e pessoa.
- **Cofre indisponível:** nada é enviado ao modelo sem pseudonimização.
- **Conta do GitHub consentida para a empresa A:** não é coletada na busca da empresa B (achado M-6).
- **Pessoa suprimida durante uma consulta em cache:** continua fora do resultado.
- **Dado real em ambiente de validação:** segue o protocolo da arquitetura, seção 13.

## Requisitos *(obrigatório)*

### Requisitos funcionais

**Estado:** *Existe* = há código e teste na base lida; *Parcial* = cobre só parte; *Falta* = não há. O detalhe por tarefa está em `tasks.md`.

| Id | Requisito | Estado |
| --- | --- | --- |
| **FR-E001** | As fontes DEVEM vir de uma lista configurável, em que só entra o que foi habilitado. Fonte fora do catálogo DEVE impedir a subida. | Existe |
| **FR-E002** | Toda fonte DEVE implementar a mesma interface, de modo que trocar ou acrescentar uma fonte não mude o núcleo. | Existe |
| **FR-E003** | A Brave DEVE responder primeiro às consultas de texto. A Bright Data só DEVE fazer busca com `BRIGHTDATA_ZONA_BUSCA` e `BRIGHTDATA_BUSCA_HABILITADA=1`, com aviso de que o alvo é o Google. A leitura de páginas continua na Bright Data, e o enriquecimento, só na People Data Labs. Cada provedor DEVE ficar ativo apenas quando sua chave estiver configurada. | Existe |
| **FR-E004** | O sistema NÃO DEVE operar nem ler do ambiente um proxy próprio. O roteamento fica a cargo do provedor contratado. | Parcial: código sem teste dedicado |
| **FR-E005** | `MODO_DADOS=sinteticos` DEVE mandar sobre as chaves: nenhum provedor ou transporte é criado, e item sem a marca de simulado é descartado. Valor inválido DEVE impedir a subida. | Existe |
| **FR-E006** | O estado das fontes (ativas, sem fontes externas, somente sintéticos) DEVE ficar visível na API e na interface, sem troca silenciosa. | Parcial: existe em `FonteProvedores.estado`, sem exposição |
| **FR-E007** | Falha de provedor DEVE resultar em troca registrada ou cobertura parcial. Orçamento, cache e disjuntor DEVEM ser aplicados antes da chamada. | Existe |
| **FR-E008** | DEVE existir uma montagem real, escolhida por configuração, que ligue fontes, modelo, pseudonimizador, cofre persistente e reidentificação, e recuse subir se faltar uma peça. | Falta (C-1) |
| **FR-E009** | A demo DEVE subir sempre em modo sintético, mesmo com chaves no ambiente e com `MODO_DADOS` em branco, cujo padrão é real. | Parcial: `montar_demo` não lê as fontes externas, e não há teste que fixe isso |
| **FR-E010** | A leitura de páginas DEVE recusar esquema, porta, destino interno, encurtador e domínio bloqueado, conferindo de novo a cada redirecionamento. | Parcial: os blocos IPv6 e o prazo total da leitura estão abertos em `site_publico.py` (M-9) |
| **FR-E011** | No leitor próprio, login, CAPTCHA ou bloqueio DEVEM encerrar a leitura, e `robots.txt` DEVE ser respeitado. | Existe |
| **FR-E012** | Nenhum requisito ou tarefa desta feature DEVE pedir a um agente que burle login, CAPTCHA ou bloqueio. A leitura pela zona de Web Unlocker só DEVE ocorrer com a zona configurada de propósito pelo time. | Existe: sem zona, não há leitura |
| **FR-E013** | Só contato publicado pela própria pessoa DEVE virar canal. Contato de provedor NÃO DEVE virar canal. | Parcial: `candidato_de_item` grava o e-mail do provedor em `atributos`, e uma página pode dar o e-mail de terceiro (M-5) |
| **FR-E014** | Telefone NÃO DEVE ser guardado como canal a partir de fontes coletadas. | Falta: site e documento coletam telefone |
| **FR-E015** | Consentimento e indicação de fonte DEVEM valer por pessoa e empresa, com validade. | Falta (C-2, M-6, B-6) |
| **FR-E016** | Na ingestão, DEVEM ser descartados CPF, RG, endereço, data de nascimento e foto. Só os campos necessários DEVEM ser pedidos aos provedores. | Parcial: a lista de campos pedidos existe; o descarte na ingestão não |
| **FR-E017** | Todo perfil coletado DEVE ser um JSON validado por esquema versionado e gerado do contrato. | Existe |
| **FR-E018** | Todo fato DEVE trazer fonte, exatamente uma origem (URL ou documento), data da coleta, trecho e tipo. | Existe |
| **FR-E019** | Resultados de provedor DEVEM virar `PerfilColetado` sem perder procedência, e nunca como fato comprovado. | Falta |
| **FR-E020** | A prova de cada fato DEVE continuar disponível até a decisão e o pacote de contexto. | Falta |
| **FR-E021** | Atributos comprovados DEVEM ser extraídos por código da própria fonte, com origem registrada. Fato declarado só DEVE cumprir requisito quando a regra aceitar esse tipo. | Falta (C-3) |
| **FR-E022** | Alertas de instrução DEVEM chegar à decisão e tirar a pessoa da faixa verde. Instrução apontada pelo modelo DEVE gerar alerta, mesmo sem cópia literal. | Falta (A-2, A-3) |
| **FR-E023** | Identificadores diretos DEVEM ser trocados antes do modelo e dos rastros, sem opção de desligar. Identificadores indiretos DEVEM seguir a política, com o custo declarado. | Parcial: núcleo existe; formatos comuns escapam (A-1) |
| **FR-E024** | Valores conhecidos da pessoa, inclusive links e perfis, DEVEM ser sempre retirados. | Falta (A-1, L2) |
| **FR-E025** | A correspondência DEVE ficar num cofre separado do banco, isolada por empresa e pessoa, sem listagem, com permissão restrita. | Existe |
| **FR-E026** | Em uso com dados reais, o cofre DEVE ser persistente e criptografado em repouso. | Falta |
| **FR-E027** | Análise, revisão e reidentificação DEVEM usar o mesmo pseudonimizador, recebido obrigatoriamente na construção. | Falta (M-2) |
| **FR-E028** | Trecho citado DEVE ser conferido no texto pseudonimizado e mapeado até a fonte. | Existe |
| **FR-E029** | A reidentificação DEVE ocorrer só depois da decisão de indicar da mesma empresa, vaga e pessoa, com registro antes de revelar. | Existe |
| **FR-E030** | Nenhuma interface, documento ou código DEVE descrever o resultado da pseudonimização como anônimo. | Existe |
| **FR-E031** | Trocar nome ou gênero NÃO DEVE mudar o texto enviado ao modelo nem o resultado da busca nas fontes. | Parcial: texto enviado coberto; busca nas fontes aberta (M-4) |
| **FR-E032** | Origem identificável NÃO DEVE ficar na decisão, e saídas a outros agentes NÃO DEVEM entregar nome ou contato. | Falta (A-6, A-7) |
| **FR-E033** | Registros só DEVEM ser juntados por prova: link cruzado, e-mail publicado igual ou mesmo usuário. | Falta |
| **FR-E034** | Nome e cidade parecidos só DEVEM sugerir a junção. Na dúvida, os registros DEVEM ficar separados, com a sugestão registrada. | Falta |
| **FR-E035** | Depois da junção, a pessoa DEVE aparecer uma vez, com todas as fontes, e valer a regra mais restritiva entre os registros. | Falta: o funil só junta pelo mesmo `id` |
| **FR-E036** | A resolução de identidade DEVE ser determinística, por empresa, com a regra registrada. | Falta |
| **FR-E037** | A base legal DEVE ser registrada por pessoa e empresa. [NEEDS CLARIFICATION: Q1, como a base legal decidida convive com o corte `sem_autorizacao` do funil?] | Falta |
| **FR-E038** | Pessoa coletada com base válida DEVE chegar à análise. Sem base válida, DEVE ficar fora da busca, com o motivo registrado. | Falta (C-2) |
| **FR-E039** | Remover a pessoa DEVE ser uma operação única sobre banco, cofre, progressos, análises e trechos citados, gravando o bloqueio, venha ela de onde vier. | Falta (A-5) |
| **FR-E040** | O cofre DEVE recusar novo marcador de pessoa removida. Apagar a empresa DEVE incluir o cofre. | Falta (A-5) |
| **FR-E041** | A supressão DEVE ser conferida antes de cada coleta, em todas as fontes. | Parcial: a cadeia de provedores faz isso; as demais fontes não conferem antes da leitura |
| **FR-E042** | Texto escondido em HTML ou PDF NÃO DEVE virar fato e DEVE gerar alerta. | Falta (A-4) |
| **FR-E043** | Erro de uma página, arquivo ou fonte NÃO DEVE interromper as demais pessoas nem prender a vaga. | Falta (A-10) |
| **FR-E044** | Pseudonimização e conferência de trecho DEVEM ter custo limitado, em todas as fontes. | Parcial: há teste de texto grande; os casos H4 e H5 ainda falham (A-9) |
| **FR-E045** | A leitura de PDF DEVE ter limite de tempo e de memória. | Parcial: só o OCR tem tempo limite (M-1) |
| **FR-E046** | Os rastros de coleta DEVEM guardar etapa, função, tipo de erro e duração, sem chave nem dado pessoal. | Existe |
| **FR-E047** | Dados do LinkedIn só DEVEM entrar como entrega de provedor contratado, dentro dos termos e do plano. A coleta e a integração são responsabilidade e implementação do time. [NEEDS CLARIFICATION: Q3, qual a forma da entrega, quem é o dono e como ela convive com o bloqueio atual?] | Falta, fora do alcance de tarefa automática |
| **FR-E048** | Enquanto essa entrega do time não existir, os bloqueios atuais DEVEM permanecer. Mudá-los exige alteração humana revisada. | Existe |
| **FR-E049** | Validação com pessoas reais DEVE seguir o protocolo da arquitetura, seção 13: só leitura, sem contato, amostra definida, métricas agregadas e dados fora do repositório, das mensagens e dos rastros compartilhados. | Falta: não há ferramenta nem registro |
| **FR-E050** | Perfil não contatado ou sem resposta DEVE expirar no prazo de retenção, salvo aceite para entrar no banco de talentos. | Falta |

### Entidades principais

- **PerfilColetado:** perfil em JSON, antes de virar `Candidato`. Empresa, pessoa, marca de simulado, data, nome, fatos, contatos e alertas. Continua sendo dado pessoal.
- **FatoColetado:** afirmação com fonte, origem, data da coleta, trecho e tipo (comprovado, declarado ou inferido).
- **ContatoColetado:** contato com origem e a indicação de publicação pela própria pessoa.
- **ItemColetado:** achado de provedor, com provedor, fonte, data e hora, URL e confiança. Modelo local, que ainda precisa virar `PerfilColetado`.
- **PerfilPseudonimizado:** texto com marcadores, mapa até a fonte e relatório sem valores.
- **Cofre de pseudônimos:** correspondência entre marcador e valor, por empresa e pessoa.
- **Vínculo de identidade (novo):** ligação entre registros da mesma pessoa, com a prova e a regra aplicada.
- **Base legal por pessoa (nova):** base aplicada, empresa, origem e validade. Depende de Q1.

## Critérios de sucesso *(obrigatório)*

### Resultados mensuráveis

- **SC-E001**: Em modo sintético, com todas as chaves configuradas, 0 pedido sai para qualquer provedor em toda a suíte.
- **SC-E002**: Os 18 casos `L1` e os casos `L2` e `L5` da revisão passam, com 0 identificador escapando.
- **SC-E003**: Num conjunto sintético de pelo menos 50 currículos, com identificadores conhecidos e meta declarada, 0 identificador direto chega ao modelo ou aos rastros. O resultado para identificadores indiretos é publicado por categoria.
- **SC-E004**: 100% dos fatos dos perfis de exemplo de GitHub, site, documento e provedor têm fonte, origem, data, trecho e tipo, e 0 fato de provedor sai como comprovado.
- **SC-E005**: 100% das evidências de uma decisão de ponta a ponta levam à origem e à data do fato coletado.
- **SC-E006**: No conjunto sintético de identidade, 100% dos pares com prova são juntados, e 0 par de homônimos sem prova é juntado.
- **SC-E007**: Com a montagem real e peças falsas nas pontas, uma pessoa sintética de cada fonte habilitada chega à análise (casos `O1`, `O2`, `O3` e `O5`), respeitada a resposta a Q1.
- **SC-E008**: Depois de remover uma pessoa, 0 ocorrência do nome ou do e-mail dela é encontrada em banco, cofre, progresso, análises e decisões (casos `V1` a `V4` e `L3`).
- **SC-E009**: Cada caso hostil `H1`, `H2` e `H6` a `H9` passa, e os casos `H4` e `H5` terminam em menos de 20 segundos.
- **SC-E010**: Todos os casos da revisão ligados a esta feature (ver `tasks.md`) passam. Na base lida, os 85 casos dão 81 falhas e 4 aprovações, resultado igual ao do commit revisado.
- **SC-E011**: A suíte continua sem regressão: 2765 testes passam na base lida, com `ruff check .` limpo.
- **SC-E012**: Nenhum dado real ou chave aparece no repositório, nos rastros ou nas mensagens, conferido por busca antes de cada entrega.

## Premissas

- A demo do hackathon usa só dados sintéticos e identifica as simulações (arquitetura, seção 14; constituição, princípios VII e VIII).
- O modelo real não entra nos testes desta feature. Eles provam o que o código aceita, não com que frequência o modelo responde de um jeito.
- O prazo de retenção da arquitetura ("ex.: 90 dias") é o valor inicial, até o parecer jurídico.
- A transparência no primeiro contato, a mensagem e o opt-out pelo candidato são da feature 002 (Frente 3). Aqui, entregamos só a origem e o contato publicado.
- Decidir se o trecho citado sustenta o critério (achado C-5), autenticação, rotas da fila, custo do modelo e medição ficam fora desta feature. A lista está em `tasks.md`.
- Conversas, reuniões e formulários não são fonte nesta feature.

## Questões em aberto

| Id | Questão | Por que importa | Opções |
| --- | --- | --- | --- |
| **Q1** | Como a base de legítimo interesse convive com o corte `sem_autorizacao` e com "sem contato frio a partir de dados de terceiros" da constituição? | Hoje todo candidato de fonte externa é cortado antes da análise, e há teste que fixa isso. A correção técnica depende da resposta. | **A:** manter a exigência de autorização; a coleta só alimenta quem autorizou. **B:** registrar a base por pessoa, permitir a análise sem autorização e condicionar o contato ao e-mail publicado e à transparência; exige emenda à constituição e parecer. |
| **Q2** | **Respondida: opção B, Brave Search API.** A busca inicial pode usar a SERP API da Bright Data, cujo alvo no código é `google.com/search`? | O responsável pelo produto decidiu pela API oficial da Brave: a SERP com alvo Google conflita com a arquitetura, seção 4, e o alvo Bing devolveu resposta vazia na consulta real. | Implementada em `provedores/brave.py`. A SERP fica desligada por padrão. Falta registrar a decisão na arquitetura, que está em `origin/main` (T064). |
| **Q3** | Como os dados do LinkedIn por provedor contratado entram, e quem é o dono? | A decisão existe, o código bloqueia, e a constituição confirmada ainda proíbe. | Decisão do time: dataset ou API, termos do plano, dono humano, emenda à constituição e relação com os bloqueios atuais. |
| **Q4** | Como guardar o que vem da Brave, se os termos proíbem sem um plano com esse direito? | O plano público (Search, US$ 5 por mil) não diz incluir o direito, e a Brave não publica qual plano inclui. Hoje o resultado inteiro fica até 24 horas no `CacheConsultas`, em memória, e a URL do resultado é gravada em `decisoes` e `progressos` depois do corte do funil. `FonteProvedores.guardar` não tem chamador em produção. | **A:** contratar o direito com a Brave, por escrito, antes de usar dados reais. **B:** reduzir o cache ao transitório e tirar a URL do que é gravado, o que depende de A-6 e de parecer sobre o que é "transitório". |
