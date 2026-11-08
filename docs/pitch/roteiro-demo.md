# Roteiro da demo de 3 minutos

Segue a seção 13 do design (`docs/superpowers/specs/2026-11-07-agente-recrutador-design.md`). Cada passo diz o que mostrar, onde clicar e o que é simulado. Tudo aqui é demonstração: pessoas, contato e Nara são fictícios e aparecem marcados como simulação.

## Antes de apresentar

Para a demo ao vivo, sem custo e instantânea:

```bash
uv run uvicorn backend.agente.api:app --port 8000
```

```bash
cd web && pnpm install && pnpm build && pnpm start -p 3001
```

A API precisa aceitar a origem do app: `ORIGENS_PAINEL=http://localhost:3001`. Com `AGENTE_COM_MODELO=1` e `FEATHERLESS_API_KEY`, a análise usa o GLM-5.2 de verdade. Nesse caso, uma vaga leva de 15 a 20 minutos e cerca de US$ 0,40 a 0,50. Rode antes e apresente a vaga já pronta.

A tela da vaga (`/vagas/[id]`) e a de modelos (`/vagas/modelos`) estão na #107, que depende da #96.

## Os 10 passos

| # | Passo | O que mostrar no app | Situação |
| --- | --- | --- | --- |
| 1 | Problema | Fala: encontrar e qualificar pessoas para vaga de tech consome o recrutador. | Fala |
| 2 | Banco | Na tela da vaga, "Busca e triagem": a base sintética tem duplicatas, opt-out, autorização vencida e perfil desatualizado. Os descartados mostram o motivo de cada um. | Pronto. O jurado entrando como candidato e autorizando ainda não tem tela (fica na API do contato). |
| 3 | Vaga | Criar vaga > "Crie a partir de um modelo de vaga". Os requisitos eliminatórios e as competências aparecem antes do mandato. A pessoa do RH assina o mandato, com o limite de indicações e a nota mínima. | Pronto. A proposta de critérios pelo modelo existe no código (`configuracao.py`), mas não tem tela. |
| 4 | Busca | O andamento ao vivo: o diário registra cada análise. Em "Indicados", cada critério mostra o trecho do perfil. Em "Para o RH decidir", o motivo de quem o agente não decide sozinho (falta de dado, texto suspeito, limite do mandato). | Pronto |
| 5 | Falha ao vivo | Uma fonte fora do ar não para a vaga, e o diário registra a cobertura parcial. | Coberto por teste (`tests/ponta_a_ponta/test_fluxo_demo.py`). Não há botão para derrubar uma fonte ao vivo. |
| 6 | Teste do jurado | O jurado faz o papel da pessoa convidada: escreve uma dúvida no convite (a resposta vem do material da vaga ou vai para uma pessoa) e clica em "Tenho interesse", "Não tenho interesse" ou "Não quero mais contato". Na fila do RH, ele indica ou descarta alguém; indicar sem evidência é recusado, com o motivo. | Pronto |
| 7 | Entrega | Depois do aceite, "Contexto entregue à Nara" mostra o porquê por critério, o que aprofundar e as lacunas. "Baixar documento" gera o Markdown que outro agente ou uma pessoa de RH lê. O convite já trazia o link de agendamento da Nara: o agente não agenda. | Pronto (Nara simulada, por API ou MCP) |
| 8 | Aprendizado | "A Nara terminou as entrevistas" manda o retorno a cada pessoa, sem nota. A proposta de ajuste pelo resultado existe no código (`aprendizado.py`), sempre com aprovação humana. | Retorno pronto. A proposta de ajuste ainda não tem tela. |
| 9 | Prova | O gasto do agente aparece no mandato. Toda decisão tem regra, evidência e rastro (`GET /candidatos/{id}/decisao`). | Gasto e explicação prontos. Métricas e custo por candidato não têm tela. |
| 10 | Negócio | Seção 14 do design: quem paga, modelo de cobrança a validar, Nara como primeira integração e não dona do produto. | Fala, sem número de mercado sem fonte |

## Frases que não podem faltar

- "O agente não agenda, não entrevista e não decide contratação. Quem decide é a pessoa do RH e quem entrevista."
- "Tudo o que vocês estão vendo é simulado e está marcado assim. Nenhuma pessoa real foi contatada."
- "Cada indicação mostra o trecho do perfil que a sustenta. Sem trecho, a pessoa vai para o RH, não para o convite."

## Ferramentas, modelos e APIs

- Backend: Python 3.12, FastAPI, Pydantic, SQLite e Uvicorn.
- App: Next.js e TypeScript.
- Modelo: `zai-org/GLM-5.2` pela API compatível com a OpenAI da Featherless (`https://api.featherless.ai/v1`), só com chave e opt-in.
- Rastro das chamadas: Langfuse, quando configurado.
- Integração com agentes recrutadores: MCP (SDK `mcp`). A Nara simulada também roda como servidor MCP.
- Busca real, desligada por padrão e só com chave: Brave Search API, Bright Data (leitura de página) e People Data Labs (enriquecimento).
- Documentos enviados pela pessoa: `pypdf` e `pypdfium2`.

## Se der errado ao vivo

- A tela não carrega: mostre o fluxo pelo Swagger em `http://localhost:8000/docs`, com `X-Empresa-Id`.
- Vaga com o modelo de verdade demorando: use uma vaga rodada antes, ou suba sem `AGENTE_COM_MODELO`, que é instantâneo.
- Ninguém indicado e todos no RH: confira se o limiar está em 0,7 e se "Aceitar o que a própria pessoa declarou" está marcado.
