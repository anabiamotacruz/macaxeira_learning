# Conjunto sintético — T2.1

> Esta é a base legada de regressão, com cenários repetidos. Para a avaliação
> ampliada, use a [base editorial v3](../avaliacao_v3/README.md): 216 narrativas
> profissionais, 12 funções e 120 famílias indicáveis na prova, com pares de
> viés fora do denominador. Não some as bases como observações independentes.

Todos os candidatos, empregadores do histórico, contatos e resultados são
fictícios. Não há consulta ao LinkedIn, Clay, modelo ou qualquer serviço externo.
Endereços `example.invalid` não são canais reais de envio.

## Arquivos e reprodução

- `candidatos.json`: 250 registros, incluindo duplicatas intencionais.
- `vagas.json`: três funções em cada uma de duas empresas fictícias (seis vagas).
- `respostas_certas.json`: gabarito de avaliação; **não entregar ao agente**.

O conjunto usa `gerar(42, 250)` em `dados/gerador.py` e a data fixa **2026-11-07**.
Para recriar apenas os perfis, na raiz do repositório, com a venv ativada:

```bash
python - <<'PY'
import json
from pathlib import Path
from dados.gerador import gerar

perfis = [p.model_dump(mode="json") for p in gerar(42, 250)]
Path("dados/sinteticos/candidatos.json").write_text(
    json.dumps(perfis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY
```

O gabarito foi definido separadamente por cenários e referencia empresa, pessoa,
fonte, vaga e índice do registro. Não é calculado pela lógica de seleção nem lido
pelo gerador. Mudanças na semente, quantidade, ordem, texto ou regras exigem
revisão do gabarito; seus metadados identificam a versão do conjunto compatível.

## Cenários e limites

Cada bloco de 12 registros contém: cargo incomum, falta explícita de requisito,
exagero sem evidência, instrução maliciosa, opt-out, informação ausente, sinônimo
com erro de digitação, duplicata em outra fonte, autorização vencida, perfil
desatualizado, ausência de autorização e um caso de referência.

A cada 36 registros muda a empresa; 72 cobrem todos os casos das três funções
nas duas empresas. Quantidades menores são permitidas e têm tamanho exato,
mas não garantem cobertura completa. Zero gera lista vazia. Quantidade negativa
é rejeitada; booleanos, strings e números fracionários não são aceitos como
semente ou quantidade. Sementes inteiras negativas são permitidas.

Duplicatas compartilham identificação, nome e contato dentro da mesma empresa,
mas têm fonte e origem diferentes. Há IDs locais iguais entre empresas: use
sempre `(empresa_id, id)` como chave, nunca apenas `id`. Os dados preparados não
implementam o isolamento de acesso; isso será responsabilidade da T2.6.

A semente varia o nome de projeto no texto. Os cenários e sua ordem são fixos
para garantir cobertura. São modelos de perfis deliberadamente simples, não
uma amostra estatística do mercado nem 250 biografias independentes. Não usar
este conjunto como único teste de qualidade de um modelo: ele é previsível e
precisará de casos de avaliação independentes na frente 4.

## Vagas de referência

Os anúncios públicos abaixo foram consultados em 2026-11-07. Usamos resumos e
um **subconjunto profissional de critérios para testes**, não sua transcrição
integral. Todas as vagas estão com `aprovada=False`.

| Função | Referência | Cuidado na interpretação |
|---|---|---|
| Software Engineer | https://jobs.ashbyhq.com/tako/cfedb281-76ee-47a2-8425-30b8eac9b5d1 | Linguagens são exemplos; AWS é preferencial, não exclusividade. Não há mínimo de anos inventado. |
| AI Deployment | https://jobs.ashbyhq.com/tako/cc400aff-2126-4650-bca3-f6eb68a05b23 | O anúncio pede 3+ anos resolvendo problemas de negócio; não exige título anterior de engenheiro. |
| Staff Software Engineer | https://jobs.ashbyhq.com/tako/c3d20b0e-660e-472f-b6ef-22e00ac48ee9 | Exige evidência de liderança e arquitetura, não apenas o título Staff. |

As três referências são presenciais em São Paulo e não publicam faixa salarial.
Disponibilidade deve ser confirmada, não inferida pela cidade de residência.
Meta de cinco candidatos, prazo de sete dias, duas tentativas e pesos iguais são
**escolhas sintéticas da demonstração**, não condições publicadas pela Tako.

O anúncio Staff é afirmativo para mulheres. Preservamos essa informação no
contexto da vaga e deixamos elegibilidade para revisão do RH. O conjunto não
possui filtro, nota ou gabarito por gênero, raça ou deficiência, e não representa
o processo completo de seleção dessa oportunidade real.

## Leitura do gabarito

`atende`, `nao_atende` e `desconhecido` são estados **do arquivo de avaliação**,
não alterações nos contratos compartilhados. Ausência de informação não é uma
negativa. Cada afirmação positiva ou negativa tem um trecho literal verificável.

Autorização para convite é registrada separadamente da aderência profissional:
uma pessoa pode atender aos requisitos e mesmo assim estar bloqueada por
opt-out, ausência de autorização ou vencimento. Perfil desatualizado exige
confirmação de atualidade; autorização válida por si só não garante indicação.

Não há rótulo de resultado esperado nos atributos dos candidatos. O gabarito
não contém decisão final de contratação, nem nota de modelo. Resultados são
sintéticos e ainda não foram validados por recrutador.

## Verificação

```bash
python -m pytest tests/dados/test_gerador.py -v
python -m pytest
ruff check .
```

Os testes validam contrato, referências e evidências, quantidade, datas,
reprodutibilidade, independência entre chamadas, duplicatas, separação de
empresas, cenários adversos e tratamento de argumentos inválidos. Os casos
offline da frente 4 em `evals/dados/` são independentes deste conjunto. Este
gabarito não substitui esses casos nem mede a qualidade do agente por si só.

## Limite desta entrega

Esta T2.1 entrega os modelos `Candidato`, as vagas e o gabarito previstos na
checklist atual. A arquitetura de coleta de 2026-11-07 ainda está marcada como
proposta: respostas HTTP de busca e GitHub, sites e PDFs para os simuladores
serão um desdobramento próprio após o alinhamento das interfaces. Estes arquivos
não são respostas das APIs externas nem comprovam uma integração com elas.

Os registros pendentes, vencidos e com opt-out são entradas adversas de teste,
não pessoas autorizadas para importação automática no banco. Consumidores devem
aplicar as regras de autorização e isolamento antes de usá-los em buscas.

## Cobertura rotulada ampliada

O conjunto tem 250 registros rotulados por candidato e vaga, com 229 pessoas
identificadas por `(empresa_id, id)` e 21 duplicatas intencionais entre fontes.
São 12 tipos de cenário distribuídos nas seis vagas; aumentar o volume não cria
250 comportamentos independentes. Os rótulos são sintéticos, ainda sujeitos à
validação de RH. Cada rótulo é testado individualmente contra os fatos e os
trechos do perfil. Não foi usado nenhum modelo ou classificador para rotular.

Os testes adicionais cobrem sete sementes, tamanhos nas fronteiras dos blocos,
independência das duplicatas, autorização que vence hoje/ontem/amanhã, combinações
de autorização e opt-out e importação/paginação no banco da frente 2.
