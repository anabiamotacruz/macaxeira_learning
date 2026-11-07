# Base editorial de avaliação v3

Este conjunto atende à revisão da T2.1: histórias profissionais autoradas
individualmente, mais funções, incerteza explícita e pares de viés identificáveis.
Todos os relatos, pessoas, contatos e vagas são sintéticos. Não houve coleta,
scraping, chamada de modelo externo ou uso de currículos reais.

## Volume que pode entrar na medição

| Conteúdo | Ajuste | Prova | Total de registros |
| --- | ---: | ---: | ---: |
| Experiência profissional positiva, com autorização válida | 24 | 120 | 144 |
| Experiência ou responsabilidade ambígua | 12 | 12 | 24 |
| Falta explícita de requisito | 12 | 12 | 24 |
| Profissionalmente positivo, contato bloqueado | 12 | 12 | 24 |
| Variantes de viés, excluídas do denominador independente | 0 | 24 | 24 |
| **Total** | **60** | **180** | **240** |

Há **216 narrativas profissionais distintas** e **120 famílias indicáveis na
prova**, dez por função, antes de contar variantes. As 24 variantes reutilizam
12 dessas famílias em 12 pares e **não aumentam a amostra para 144 pessoas**.
A chave de caso é `id_caso`; a unidade agrupada é `grupo_independencia`.

As funções são backend, frontend, mobile, engenharia de dados, QA, SRE, segurança,
ML, produto, UX, plataforma e integrações. São 24 vagas sintéticas: uma por função
em cada uma de duas empresas. O requisito eliminatório é atuação profissional
comprovada na função; não é um corte por título literal, empresa, tempo ou gênero.
Competências orientam análise, mas não são todas obrigatórias. O rótulo positivo
**não significa nota máxima em todas as competências**.

## Como os textos foram construídos

`dados/corpus_v3/bloco_a.json`, `bloco_b.json` e `bloco_c.json` contêm relatos
editoriais de 35 a 65 palavras, sem nomes, códigos ou projetos aleatórios para
fabricar unicidade. Mudam o problema, a ação individual e o mecanismo técnico.
Há resumos curriculares, respostas de entrevista, tópicos e narrativas impessoais,
além dos relatos em primeira pessoa. A revisão cruzada verificou positivos,
negativas explícitas e incerteza;
relatos de plataforma e integrações considerados próximos foram reescritos.

Os positivos descrevem atuação e entregas. Os negativos negam experiência na
função apesar de trabalho em área adjacente. Os ambíguos deixam incerto escopo,
autoria ou execução profissional: o esperado é pedir esclarecimento humano,
sem converter falta de evidência em uma negativa. Os bloqueados distinguem
aderência profissional de autorização: há opt-out, vencimento e falta de aceite.

O empacotador define os campos estruturados conforme esses cenários editoriais,
sem chamar classificador, regras de seleção ou ler um gabarito previamente
calculado pelo agente. Não preenche cargo derivado da categoria nem uma lista de competências
presumidas pela função. A intenção editorial de cada cenário é a origem dos rótulos: isso **não
é rotulagem independente por recrutador**. Revisão de RH continua pendente.

## Pares de viés

Cada par tem `par_vies` e `variacao_vies` no gabarito. Ambos os membros possuem a
mesma identidade e fatos profissionais; variam apenas nome e gênero. Em seis
pares o gênero também aparece em uma frase de apresentação no texto. Os
`campos_variados` documentam a intervenção. Não há pares raciais/etários nesta
versão; não extrapolar o resultado a todos os eixos de equidade.

Execute os membros separadamente, com estado de avaliação isolado, e compare
indicação, bloqueios e notas por critério. Não importe os dois membros como
pessoas distintas nem os misture em uma disputa por posição no mesmo ranking.
Eles testam invariância, não ampliam o denominador de precisão. Os testes desta
entrega comparam elegibilidade no funil; a invariância de análise com modelo real
ainda precisa ser medida.

## Arquivos e protocolo de uso

- `candidatos.json` e `vagas.json`: entradas, validadas pelos contratos existentes.
  IDs são opacos; nomes e e-mails não revelam categoria, ordinal, partição ou par.
  A ordem dos casos é embaralhada de forma fixa, sem alterar o RNG global.
- `respostas_certas.json`: reservado ao avaliador. Guarda partição, grupo,
  `par_vies`, estados dos requisitos, trechos literais e expectativa.
- `manifesto.json`: contagens, hashes e diagnóstico lexical, sem executar o modelo.
- `PLANO.md`: escopo e verificações desta revisão.

Expectativas `indicar`, `descartar`, `pedir_humano` e `bloquear_contato` são rótulos
locais de avaliação, **não novos valores de contratos de decisão**.
`bloquear_contato` não significa inadequação profissional nem decisão de contratação.

1. Congele os hashes do manifesto e registre versão de prompt/modelo antes da rodada.
2. Use apenas ajuste para desenvolver e calibrar; nunca reutilize prova como ajuste.
3. Famílias e todas as variantes permanecem na mesma partição. Se houver mudança no
   corpus após examinar erros de prova, crie outra versão de prova ainda não usada.
4. Os campos `experiencia_*` são fatos estruturados autorados para o teste do
   funil determinístico; sua presença facilita essa etapa. Para medir extração
   de fatos do texto, o avaliador deve ocultá-los na entrada do extrator e
   compará-los depois com o gabarito. O teste do funil desta entrega não faz
   essa avaliação de interpretação, nem estima precisão do modelo.
5. Entregue somente candidatos e vagas ao agente, por caso, sem gabarito, arquivos
   editoriais ou metadados de avaliação. Não distribua o diretório inteiro ao modelo.
6. Registre resultado, evidências, falhas e versões antes de consultar o gabarito.
7. Compute métricas separadas: acerto dos 120 indicáveis, negativos, ambiguidade,
   autorização e diferenças entre pares. Reporte tamanho, erros e incerteza.

Os registros adversos são entradas de teste, não autorização para importação.
Partições estão no gabarito, fora do modelo `Candidato`. Não foi necessário mudar
`backend/contratos` ou os fixtures antigos usados pelas regressões da aplicação.

## Reprodução e verificação

```bash
.venv/bin/python -m dados.avaliacao_v3
.venv/bin/pytest tests/dados/test_avaliacao_v3.py -q
.venv/bin/pytest tests/dados/test_avaliacao_v3_eval.py -m eval -q
.venv/bin/pytest -q
.venv/bin/ruff check .
```

A auditoria compara trigramas após normalizar caixa, acentos e números; sinaliza
Jaccard >= 0,65 entre narrativas não variantes. Isso detecta algumas repetições,
mas **não demonstra diversidade semântica ou independência estatística**. A revisão
editorial complementa o diagnóstico; ambos precisam de validação humana externa.
Hashes detectam alterações, não comprovam qualidade dos rótulos.

O conjunto antigo de 250 registros em `dados/sinteticos/` continua disponível para
regressão e demonstração. Use esta v3 para desenvolver o protocolo de avaliação;
não some os dois conjuntos como se fossem observações independentes.

Ter mais de cem casos distintos de prova permite uma rodada mais informativa,
mas **não comprova a meta de 95%**. Nenhuma taxa de acerto de modelo foi medida
nesta entrega. As histórias são curtas e editoriais, com um requisito por vaga;
não representam toda a diversidade de currículos reais, vagas com vários
eliminatórios ou a distribuição de pessoas do mercado.
