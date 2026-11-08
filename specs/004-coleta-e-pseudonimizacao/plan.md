# Plano de implementação: coleta e pseudonimização

**Branch**: `frente/agente-spec-004` | **Data**: 2026-11-07 | **Spec**: `specs/004-coleta-e-pseudonimizacao/spec.md`

**Entrada**: a spec desta feature, o código em `frente/agente-integracao` (`536b94e`) e a arquitetura de coleta em `origin/main`.

## Resumo

As peças de coleta e pseudonimização já existem e têm teste: fontes plugáveis, cadeia Brave, Bright Data e People Data Labs, `MODO_DADOS`, `PerfilColetado`, pseudonimizador, cofre e reidentificação. O problema é que elas funcionam isoladas. Só os testes usam essas peças, e a única montagem é `montar_demo`.

Este plano liga as peças, leva a prova de cada fato até a decisão, acrescenta a identidade entre fontes e fecha os achados abertos da revisão. Nenhuma linha de código muda nesta entrega: aqui ficam só a spec, o plano e as tarefas.

**Medição desta base (`536b94e`):**

- `pytest`: 2765 testes passam e 1 fica fora da seleção padrão.
- `pytest tests/fontes tests/contratos`: 1073 testes passam.
- `ruff check .`: limpo.
- Apêndice da revisão, rodado numa cópia isolada: 81 falham e 4 passam, o mesmo resultado do commit revisado (`f07125c`). Conferi o motivo dos casos `O1` a `O3`, `O5`, `L2`, `L3`, `V1` a `V3`, `X1`, `X2`, `M6`, `M7`, `H1`, `H2`, `H6` a `H9`, `Q1` e `Q3`: são falhas de comportamento, não de assinatura.
- Configuração só com `BRIGHTDATA_API_TOKEN` e `BRIGHTDATA_ZONA_BUSCA`, com transporte falso: 1 pedido de busca, nenhuma leitura de página, trecho mantido e pessoa em estado `pendente`.

Nenhum provedor real nem o modelo real foram chamados nesta medição, que é anterior à troca da busca pela Brave. Hoje essa configuração também exige `BRIGHTDATA_BUSCA_HABILITADA=1`.

## Contexto técnico

**Linguagem/versão**: Python 3.12

**Dependências principais**: FastAPI, Pydantic, `httpx` e `httpx2`, `pypdf`, `pypdfium2`, `pytesseract`, `beautifulsoup4`, Langfuse e cliente OpenAI com Featherless

**Armazenamento**: SQLite (`Repositorio`, `BancoTalentos`, `CofrePseudonimos` em arquivo próprio). A arquitetura prevê Postgres em produção.

**Testes**: pytest, com transporte e modelo falsos e dados sintéticos. Sem rede. Avaliações com `pytest -m eval`.

**Plataforma**: servidor Linux; desenvolvimento em macOS. `tesseract` é uma dependência de sistema.

**Tipo de projeto**: serviço web com API, MCP e interface web em outra frente

**Metas de desempenho**: pseudonimização e conferência de trecho em menos de 20 segundos no pior caso de 200 mil caracteres, sem parar outras empresas

**Restrições**:

- Prazos do `AGENTS.md`: parar funcionalidades em 8/11, às 11h; submissão até 8/11, às 13h.
- Demo só com dados sintéticos e simulações identificadas.
- Mudança em `backend/contratos` exige aviso às quatro frentes.
- Nenhuma tarefa pede para burlar login, CAPTCHA ou bloqueio.

**Escala**: amostra de validação da arquitetura, seção 13: 3 vagas e até 50 perfis por vaga. Escala de produção fica fora desta feature.

**Artefatos**: esta entrega reúne spec, plano e tarefas. O conteúdo de `research.md`, `data-model.md` e `contracts/` está nas seções abaixo, a pedido.

## Verificação da constituição

| Princípio | Situação | Observação |
| --- | --- | --- |
| I. Determinismo | Passa | Identidade, base legal, atributos comprovados e supressão ficam em código. O modelo só extrai texto, validado por esquema. |
| II. Humano no controle | Passa | Sugestão de junção vai a uma pessoa. A decisão sobre LinkedIn e base legal é do time. |
| III. Contratos | **Atenção** | T002 avisa as frentes antes de qualquer mudança. As mudanças previstas estão listadas abaixo. |
| IV. Evidência | **Lacuna aberta** | A prova termina em `candidato_de_perfil`. T035 fecha. |
| V. Confiabilidade | **Lacuna aberta** | Página hostil ainda derruba a busca (A-10). T060 fecha. |
| VI. Medição e auditoria | **Lacuna aberta** | Sem medição de vazamento. T030 fecha. |
| VII. Dados e equidade | **Conflito** | O texto confirmado diz "somente dados sintéticos", "sem scraping do LinkedIn" e "sem contato frio a partir de dados de terceiros". As decisões D2 e D7 e a camada 6 da arquitetura vão além disso. A demo continua sintética. O modo real não entra em produção sem T063, T065, T066 e T067. |
| VIII. Honestidade | Passa | `simulado` vem de cada fonte. O achado B-2, sobre a saída fixa da API, fica fora desta feature. |
| IX. Simples e testado | Passa | Cada tarefa aberta nasce de um teste que falha. |

## Estado por módulo

| Módulo | O que já faz | O que falta |
| --- | --- | --- |
| `fontes/registro.py` | Lista configurável de fontes | Catálogo real na montagem |
| `fontes/provedores/` | Cadeia, política de URL, orçamento, cache, disjuntor, supressão e `MODO_DADOS` | Ligação à montagem; `PerfilColetado`; direito de armazenar os resultados da Brave (Q4) |
| `fontes/github_teste.py` | API oficial, só para contas consentidas | Consentimento por empresa, token e autorização |
| `fontes/site_publico.py` | SSRF, `robots.txt`, login e CAPTCHA encerram a leitura | Casos hostis, contato de terceiro e prazo total |
| `fontes/documentos.py` | PDF, OCR e limites | Texto invisível e limite geral de PDF |
| `fontes/perfis.py` | Converte perfil em `Candidato`, sem inferidos | Manter prova, atributos comprovados e alertas |
| `fontes/anonimizador.py` | Marcadores, política, cofre, mapa de trecho e reidentificação | Formatos do A-1, custo do A-9 e criptografia em repouso |
| `fontes/banco_talentos.py` | Isolamento, remoção com bloqueio e apagamento no cofre | Remoção de quem veio de outra fonte |
| `agente/montagem.py` | `montar_demo` | `montar_real` |
| `fontes/funil.py` | Junta registros de mesmo `id` | Vínculo de identidade |

## Desenho

Decisões abaixo são de desenho e podem ser corrigidas pelo time. As marcadas "decidido" estão na spec.

### Caminho do dado

```text
Fontes plugáveis (decidido)
  banco de talentos | GitHub | site indicado | documento enviado | cadeia de provedores
        |  supressão conferida antes da coleta
        v
PerfilColetado (JSON, com prova em cada fato; decidido)
        |  identidade entre fontes (código)
        v
Pessoa com vínculos e atributos comprovados (código)
        |  base legal (Q1) e funil
        v
Candidato + referência aos fatos
        |  pseudonimização com cofre único (decidido)
        v
Modelo e rastros  --> decisão em código --> reidentificação só depois de indicar
```

### Identidade entre fontes

- **Módulo novo:** `backend/fontes/identidade.py`, com funções puras e sem modelo.
- **Prova que junta:** mesma URL normalizada de GitHub ou site, mesmo e-mail publicado pela pessoa, mesmo usuário de uma rede citada nos dois registros.
- **Sugestão que não junta:** nome e cidade parecidos ou nome e empresa parecidos. A sugestão é registrada para uma pessoa revisar.
- **Identificador:** a pessoa fica com o menor `id` do grupo, e os demais viram apelidos. Bloqueio e opt-out consideram todos.
- **Por empresa:** chaves e vínculos nunca cruzam empresas.
- **Registro:** cada junção guarda a regra aplicada e as fontes, sem o valor.
- **LinkedIn como chave:** a arquitetura, camada 2, usa a URL como chave. Hoje `remover_links_proibidos` retira esses links do texto, então essa chave não existe no código. Ela depende de T065.

### Prova até a decisão

- `PerfilColetado` passa a ser gravado por empresa e pessoa, numa tabela do banco, junto da remoção.
- `Candidato.perfil_texto` continua sendo o texto para a busca e para o modelo. A prova é consultada pelo `id`.
- A evidência da análise aponta para o fato de onde veio o trecho, o que permite mostrar origem e data na decisão.

### Base legal

Bloqueada por Q1. A implementação técnica só começa depois da decisão do time, e o corte do funil continua como está até lá.

### Mudanças de contrato previstas

Todas pedem aviso às quatro frentes (T002), antes de começar:

1. Campo próprio para alertas em `Candidato` (A-2).
2. Vínculos de identidade.
3. Referência entre evidência e fato coletado.
4. Base legal por pessoa e empresa (Q1).
5. Rota de remoção da pessoa na API (A-5). Rotas são contrato com a Frente 4.

## Divergências entre documentos e código

| # | Tema | Documento | Código |
| --- | --- | --- | --- |
| 1 | **LinkedIn por provedor** | Arquitetura, seção 3 e camada 6: inclui dados do LinkedIn por provedores contratados | Conectores bloqueiam esses domínios e não fazem essa coleta |
| 2 | **LinkedIn, dentro da própria arquitetura** | Camada 6 inclui; seções 4, 6 e 12 mantêm "bloqueio fixo em código, sem exceção"; seção 13 diz "nada de `linkedin.com`" | Segue o bloqueio |
| 3 | **Constituição** | `constitution.md` 1.0.0 e `AGENTS.md`, como estão confirmados: "sem scraping do LinkedIn" e "somente dados sintéticos". Há um rascunho local não commitado (2.0.0) que diz "o conector coleta o LinkedIn pela Bright Data" | O conector não faz isso, e a arquitetura atribui a coleta ao provedor |
| 4 | **Camadas 1 e 2** | Consultas `site:linkedin.com/in` e URL do LinkedIn como chave de identidade | `-site:linkedin.com`, `validar_texto_de_busca` e `remover_links_proibidos` fazem o oposto |
| 5 | **Busca** | Arquitetura, seção 4: raspar resultados do Google, mesmo por terceiros, fica de fora; seção 3 cita Brave Search | **Resolvida (Q2):** a busca é da Brave, em `brave.py`. A SERP com alvo `google.com/search` só entra com `BRIGHTDATA_BUSCA_HABILITADA=1`, com aviso. Falta registrar na arquitetura |
| 6 | **Bright Data** | "Dataset ou API do provedor", com perfis profissionais | Web Unlocker e SERP API, sem dataset |
| 7 | **People Data Labs** | "Busca de pessoas por cargo e cidade", com `linkedin_url` | Só Person Enrichment, sem busca nem `linkedin_url`. Por isso, a reserva não cobre consulta de texto |
| 8 | **Regras de coleta** | Arquitetura, seção 6: `robots.txt`, limites por domínio e sem contorno | Valem em `site_publico.py`. O caminho pela Bright Data não consulta `robots.txt`, e o Web Unlocker contorna bloqueios por natureza |
| 9 | **Base legal** | Legítimo interesse, com primeiro contato sem autorização prévia | O funil corta quem não tem autorização, e `test_pessoa_vinda_de_provedor_nao_vai_ao_modelo_nem_recebe_convite` fixa isso |
| 10 | **Contato** | Só e-mail publicado pela pessoa; não compramos listas | People Data Labs é consultada com `work_email`, e `candidato_de_item` o grava em `atributos`, marcado como não publicado |
| 11 | **Telefone** | "Não coletamos" | `site_publico.py` e `documentos.py` coletam, e `_atributos_de_contato` o aceita |
| 12 | **Modelo de dados** | `FonteBruta`, `PerfilSnapshot`, `VisaoCega`, confiança autodeclarada, verificável e verificada, hash e versão | `PerfilColetado`, tipo comprovado, declarado e inferido, sem snapshot nem hash |
| 13 | **Momento da coleta** | "O agente não busca dados na web enquanto decide": jobs separados gravam snapshots | `FluxoVaga._buscar` chama as fontes dentro da execução da vaga |
| 14 | **Variáveis** | `.env.example` lista `FONTES_HABILITADAS`, `MODO_DADOS` e as chaves | Nenhuma delas muda o que a API faz, porque não há ligação à montagem (C-1) |
| 15 | **Modo padrão** | Constituição confirmada: somente sintéticos | `MODO_DADOS` em branco significa real em `configuracao.py` |
| 16 | **Dono de `backend/fontes`** | `AGENTS.md`: Frente 2 | O código atual foi escrito nas branches `frente/agente-*` |
| 17 | **Pastas** | `AGENTS.md`: `avaliacoes/`. Plano 001: `dados/` e `rede_simulada.py` | `origin/main` tem `evals/` e `dados/`; a base lida não tem nenhuma delas |
| 18 | **Nome do arquivo** | Spec e LGPD: pseudonimização | O módulo se chama `anonimizador.py`; o cabeçalho dele já avisa |
| 19 | **Situação da arquitetura** | O cabeçalho diz "proposta, aguardando aprovação", e várias linhas dizem "decidido" | Não se aplica |
| 20 | **Onde está a arquitetura** | Citada como referência desta feature | O arquivo está só em `origin/main`, não na base lida |

## Limites entre frentes

| Frente | Pastas | Nesta feature |
| --- | --- | --- |
| 1. Agente | `backend/agente`, `backend/modelos` | `montar_real`, ligação ao fluxo, retirada de `origem` da decisão, saída do MCP, rota de remoção e coordenação da integração |
| 2. Fontes e dados | `backend/fontes`, `dados` | Conectores, `PerfilColetado` em cada fonte, identidade, atributos comprovados, pseudonimizador, cofre e casos hostis |
| 3. Contato e Nara | `backend/contato`, `backend/nara_simulada` | Usa só o contato publicado; mostra a origem no primeiro e-mail; aplica o opt-out recebido. Campos de identificação no pacote seguem com o achado M-3 |
| 4. Produto e qualidade | `web`, avaliações, `docs/pitch` | Mostra o estado das fontes e a etiqueta de simulação; conjunto sintético e medição de vazamento |
| Compartilhada | `backend/contratos` | Só com aviso às quatro frentes |
| Time (pessoas) | Fora do código | Parecer jurídico, Q1, Q3, Q4, emenda à constituição, contas e chaves, e dados do LinkedIn |

**Enquanto as outras frentes não chegam**, a Frente 1 usa as simulações de `backend/contratos/simulacoes.py` e avisa o que cada frente precisa entregar.

## Estrutura do projeto

### Documentação (desta feature)

```text
specs/004-coleta-e-pseudonimizacao/
├── spec.md
├── plan.md
└── tasks.md
```

### Código-fonte

```text
backend/
├── contratos/modelos.py            # Candidato, PerfilColetado, FatoColetado, ContatoColetado
├── agente/
│   ├── montagem.py                 # acrescenta montar_real
│   ├── fluxo.py                    # identidade antes do funil, retirada de origem da decisão
│   ├── regras.py                   # alerta na faixa e atributo comprovado
│   ├── api.py                      # estado das fontes e remoção
│   └── mcp.py                      # saída sem identificadores
└── fontes/
    ├── registro.py
    ├── perfis.py                   # prova, atributos comprovados e alertas
    ├── identidade.py               # novo
    ├── anonimizador.py
    ├── documentos.py
    ├── github_teste.py
    ├── site_publico.py
    ├── banco_talentos.py
    └── provedores/
        ├── brave.py
        ├── bright_data.py
        ├── people_data_labs.py
        ├── cadeia.py
        ├── configuracao.py
        ├── controles.py
        ├── fonte.py                # item de provedor vira PerfilColetado
        ├── modelos.py
        ├── transporte.py
        └── url_segura.py

tests/
├── contratos/test_perfil_coletado.py
├── agente/test_montagem_real.py    # novo
├── agente/test_coleta_ponta_a_ponta.py  # novo
└── fontes/
    ├── test_identidade.py          # novo
    ├── test_revisao_coleta.py      # novo: casos do apêndice da revisão
    └── provedores/
```

**Decisão de estrutura**: mantém as pastas por frente. O único módulo de código novo é `identidade.py`, em `backend/fontes`. `montar_real` fica ao lado de `montar_demo`, que é o único lugar onde o agente conhece as implementações.

## Registro de complexidade

Nenhuma exceção técnica a justificar. O conflito com o princípio VII não é de complexidade: ele fica registrado acima e é resolvido pelo time, em T067.
