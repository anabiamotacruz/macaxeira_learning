# Escopo para entregar

Documento de handoff. Outro agente deve conseguir trabalhar só com este arquivo, o `AGENTS.md` e o código da `main`.

**Quando:** 8/11/2026, madrugada, horário de Fortaleza (UTC−3).
**Corte deste turno:** pouco antes da 1h. Não abra frente nova depois disso.
**Corte do projeto:** funcionalidade nova para às 11h. Submissão até as 13h.

A `main` no momento deste texto é `e399d01` (merge da #104).

## O que o produto é

Digital worker de sourcing para qualquer empresa que recruta. A Nara e a Tako são as primeiras usuárias, não a fronteira do produto. Quem já entrevista continua entrevistando. O agente não agenda, não avalia no lugar de quem entrevista e não decide contratação.

Cada empresa tem o próprio banco. Dado de uma empresa não aparece para outra. Simulação aparece escrita como simulação. Texto de candidato é dado, nunca instrução. Critério sensível fica fora. Contato só por endereço que a pessoa publicou, com a origem na mensagem e com saída (`SAIR`).

## Pipeline fechado

A ordem é esta. Cada etapa entrega contexto para a seguinte.

1. **Contexto.** A busca junta experiência e contato publicado, com a origem de cada dado. Isso alimenta o agente de contexto. Não raspar o LinkedIn. Não inferir e-mail. `work_email` de provedor sem `url_origem` e sem publicação da pessoa continua bloqueado (`contato_nao_publicado`).

2. **Convite.** Outro agente manda o e-mail: explica o contexto, convida a pessoa a participar e pede que ela escreva para o número. O link `wa.me` vai no e-mail, com o código da vaga. A conversa no WhatsApp começa quando ela manda a primeira mensagem. O agente não abre o WhatsApp. Isso é o que mantém o fluxo de acordo com a janela de 24 horas e com o combinado de LGPD.

3. **Conversa.** Ela fala da vaga, tira dúvida, conta experiência e pode pedir para agendar. O agente responde em cima do que ela acabou de dizer, com o material da vaga. Dúvida fora do material vai para uma pessoa. Pergunta sensível não entra. Instrução no texto não vira aprovação. Áudio entra como voz: a transcrição vira o texto da conversa, e a resposta pode sair em voz. Sem chave, os dois lados são simulados e marcados. Deepgram reconhece; ElevenLabs (ou voz da Featherless) fala. `VOZ_REAL=1` sem provedor ligado não chama a rede.

4. **Decisão, em código, durante a conversa.** Três saídas: positivo, negativo, ou não agora. Não agora é o Talent Garden (indisponível agora, ou a lapidar com confirmação do RH). O modelo não decide sozinho requisito eliminatório, opt-out, autorização nem supressão.

5. **Agendamento.** O link sai quando as três coisas fecham juntas: ela aceitou a entrevista, o momento é o certo, e a decisão mostra que ela cobre o que a vaga pede. O link pode ser o da Nara ou o de qualquer outro recrutador no mesmo encaixe. Quem marca é o destino, não o agente.

6. **Documento.** Na entrega, gerar o pacote para ingestão: evidência com trecho e fonte, lacuna, o que a conversa apurou e por que ela segue. Qualquer agente recrutador consome por MCP. Uma pessoa de RH que use a ferramenta consome o mesmo documento. O arquivo é dado, nunca instrução.

7. **Retorno e pergunta dela.** Depois da entrevista, o destino devolve se ela segue para a próxima fase (por exemplo entrevista de código) e por quê. O agente guarda o veredito e não o troca. Se ela perguntar, o agente responde. Vale para quem não passou e para quem passou e quer saber por quê. A resposta usa só o retorno e as evidências já registradas. Sem trecho, com dado sensível ou com contestação, a pergunta vai para uma pessoa. Quem passou não recebe feedback sozinho. Quem não passou também não recebe até perguntar, a menos que o mandato ligue o envio. A opção nasce desligada.

## Campanha

Uma campanha só, mesmo com várias posições. O recrutador assina os números. Não há teto fixo da ferramenta.

| Número | Quem define | Exemplo | O que é |
| --- | --- | --- | --- |
| Examinar | recrutador | 200 | Quantas pessoas a busca olha e grava. O banco da vaga acumula: outra leva soma. A consulta esvaziar não encerra a campanha. |
| Encaminhar | recrutador | 10 ou 50 | Quem segue para a próxima fase (hunting e pré-triagem). Não é lista de contratação. Quem decide se a pessoa é ideal é o recrutador, depois da entrevista. Quem passa desse número fica disponível para o RH e não é descartado. |
| Posições | recrutador | 3 | Quantas vagas a mesma campanha preenche. Não se relança «Software Engineer» várias vezes. |

O código de hoje ainda não tem o número «examinar». Corta a análise em `LIMITE_ANALISES_POR_RODADA = 20` (`backend/agente/montagem.py`) e para em `min(meta_candidatos, max_indicacoes)`. A proposta de vaga recusa meta acima de 100. Esses tetos não são regra de produto. Mexer no mandato para guardar «examinar» altera `backend/contratos` e exige aviso às quatro frentes. Não faça isso neste turno se o aviso não couber.

O teste que trava o que já existe está na #102: uma vaga, meta 3, encaminhamento 10, excesso sem descarte, outra empresa não vê.

## Encaixe do destino

`AgenteRecrutador` em `backend/contratos/interfaces.py` tem três operações: `link_agendamento`, `entregar`, `resultados`. A Nara simulada é o primeiro encaixe, por API e por MCP (`nara_link_agendamento`, `nara_entregar_pacote`, `nara_resultados`). Trocar a Nara por outro recrutador não muda busca, conversa nem feedback.

## O que já está na main

Não refaça.

- Demonstração sintética com mandato, busca, decisão, convite, dúvida, aceite, opt-out e entrega. Sem `X-Empresa-Id` a API responde 401. Outra empresa não vê a vaga.
- Modelo real só com `AGENTE_COM_MODELO=1` e `FEATHERLESS_API_KEY` (#98). Sem a chave, a demonstração segue sem modelo. Cliente: `https://api.featherless.ai/v1`, modelo `zai-org/GLM-5.2`, `max_tokens` 8000 (mínimo 1000), concorrência 1, teto de sessão US$ 5, teto da vaga no mandato.
- Busca externa só com opt-in (#101). Cadeia pronta e desligada do fluxo padrão: Brave (US$ 0,005, 20 resultados por página, páginas 0 a 9, acrescenta `-site:linkedin.com`), Bright Data para ler página (US$ 0,0015; busca Google só com `BRIGHTDATA_ZONA_BUSCA` e `BRIGHTDATA_BUSCA_HABILITADA=1`), People Data Labs para enriquecer (likelihood mínimo 6, US$ 0,28, não pede LinkedIn, telefone, sexo nem nascimento). Orçamento US$ 5 por empresa e US$ 1 por execução. `MODO_DADOS=sinteticos` desliga.
- Dúvida pelo material da vaga ou encaminhada (#88, #89). Convite com origem e aviso de simulação (#87). Critério citado uma vez, pela descrição (#84).
- Mensagem pós-entrevista sem nota nem ranking (#85, #97). Resumo da Nara em uma frase (#90). Pacote no MCP (#91, #100).
- RH indica ou descarta quem está na fila (#94). Diário de cada análise (#104).
- Guia do que a frente do agente chama no contato: `backend/contato/README.md` (#93).
- Snapshot de perfil por 30 dias (#78) e cobertura de canal (#79) existem, e o fluxo da vaga não depende deles para o MVP.
- Voz simulada no WhatsApp, ainda na #103, não na `main`.

Medição já feita, sem chave, empresa `empresa-demo`, vaga Software Engineer, `aceitar_declarada`, no máximo 2 encaminhamentos: 17 analisados, 2 indicados, 10 descartados, 18 na fila humana, gasto zero. O casamento foi por palavra. Um critério de AWS ficou sustentado por uma frase sobre Azure. Isso não é o GLM.

## Pull requests ainda abertas

| PR | O que fazer neste turno |
| --- | --- |
| #103 | Entrar, se o CI estiver verde. É a validação do e-mail, do áudio da pessoa, da voz simulada, do link, do «não agora» e da recusa sem link. |
| #102 | Entrar, se o CI estiver verde. Trava a campanha com os números do recrutador. |
| #92 | Auditoria de injeção no texto do candidato. Entra se não atrasar o fluxo. O buraco que ela fecha é o recontato copiando motivo cru. |
| #96 | Painel da Sofia. Não abrir outro painel. `web/lib` ainda pode estar fora do Git por causa de `lib/` no `.gitignore`. |
| #95, #69, #68, #77 | Documentos, rede simulada, pares de viés, identidade. Não são o caminho crítico desta madrugada. |

## O que ainda falta, nesta ordem

Só entre aqui se #103 e #102 já estiverem encaminhadas e ainda houver tempo antes da 1h.

1. Feedback quando a pessoa pergunta, nos dois resultados (passou e não passou), em cima de `backend/agente/feedback.py` (`responder_pedido_de_feedback`). Sem nota, sem ranking, sem outra pessoa. Teste antes do código.
2. O documento de ingestão saindo do pacote que já existe (`montar_pacote` / entrega MCP), com selo de simulação. Não invente campo novo de contrato se der para montar com o `PacoteContexto` atual.
3. Não ligue voz real, busca real nem modelo real sem chave no ambiente. Não peça para colar chave no chat.

## Como provar

```bash
source .venv/bin/activate
ruff check .
pytest -q
```

A validação nova, quando a #103 estiver na árvore:

```bash
pytest tests/contato/test_validacao_voz.py tests/contato/test_whatsapp.py -q
```

A campanha, quando a #102 estiver na árvore:

```bash
pytest tests/agente/test_escopo_campanha.py -q
```

API da demonstração, sem chave:

```bash
uv run uvicorn backend.agente.api:app --host 127.0.0.1 --port 8000
```

Todo pedido leva `X-Empresa-Id`. Sucesso traz `simulado: true`.

## Não fazer

- Raspar LinkedIn ou cruzar dado para inventar e-mail.
- Mandar WhatsApp antes de a pessoa escrever.
- Tratar 20 análises como tamanho de campanha.
- Chamar de shortlist de contratação o número de encaminhados.
- Mostrar nota ou ranking para a pessoa.
- Mudar `backend/contratos` sem avisar as quatro frentes.
- Gravar ou imprimir chave.
- Usar dado real. Teste e demo são sintéticos.
- Deixar o agente marcar entrevista ou decidir contratação.

## Conversas de origem

- [Recruitment tool improvements](https://cursor.com/agents/bc-904d730e-8c12-590b-ba3f-cfd4de7a62a0)
- [Recruitment process overview](https://cursor.com/agents/bc-fd8edc1b-bb04-5180-b165-69298e9e2e7e)
- Este handoff sai do chat [Macaxeira learning escalabilidade](https://cursor.com/agents/bc-01a1b821-90d3-747d-9d8a-47f2cb1f5a57)
