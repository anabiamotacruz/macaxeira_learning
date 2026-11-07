# Qualidade offline

Esta frente usa somente dados sintéticos, mocks e código local. Os testes não
acessam rede, chaves, `.env` nem um modelo de linguagem real.

## Política de retry

Falhas de `TimeoutError` e `ProvedorIndisponivel` são transitórias. O adaptador
faz no máximo 3 tentativas e relança a última falha; não há retry infinito.
JSON inválido e campos ausentes são falhas de validação e devem seguir para
correção ou revisão humana, não para uma decisão automática.

## Contrato local

Os validadores em `evals/qualidade_offline.py` são um contrato mínimo de
avaliação, separado dos contratos compartilhados do agente.

> CONTRATO A CONFIRMAR COM A FRENTE DO AGENTE

## Formatos JSONL

Cada linha de decisão contém `id`, `candidato_id`, `vaga_id`, `quem_decidiu`,
`quando`, `resultado`, `justificativa`, `evidencias` e `regra_aplicada`.
`quem_decidiu` identifica uma pessoa responsável; a decisão não é válida sem
justificativa e evidências.

Cada linha de custo contém `id`, `candidato_id`, `execucao_id`, `modelo`,
`tokens_entrada`, `tokens_saida`, `custo_estimado`, `moeda` e `etapa`.
`custo_estimado` é calculado com preços fornecidos em `PrecosModelo`; nenhum
preço fica fixado no código. A soma por candidato agrega todas as etapas.
