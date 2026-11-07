# Fontes e consultas

## T2.7 — geração de consultas

`gerar_consultas(vaga, cliente_modelo)` devolve consultas de palavras-chave em
texto simples. Por exemplo, requisitos “Python” e “experiência em produção”
geram consultas independentes `Python` e `produção`. Palavras de ligação e introduções
genéricas são removidas; termos técnicos e acentos são preservados. Valores
categóricos explícitos, como “Python” em “Linguagem”, substituem a descrição
genérica na descoberta. Competências opcionais não viram filtros obrigatórios.

Cada palavra-chave é uma alternativa de descoberta. Com uma resposta válida do
modelo, seguem consultas adicionais com o título original e até seis sinônimos,
sem concatenar todos os requisitos. Sem requisitos úteis, usa-se o cargo, nunca
consulta vazia. O chamador executa as consultas separadamente, percorre todas as
páginas e reúne os resultados por empresa e id (OU entre consultas).

A descoberta pode trazer quem só menciona um termo, inclusive em contexto negativo.
Ela não comprova requisitos: o funil verifica todos os campos estruturados e a
análise confere as evidências. Negação, intervalos e elegibilidade ficam nas regras
determinísticas. A extração é lexical, sem equivalência semântica ou stemming.
O teste integrado percorre as consultas nas seis vagas e nos 250 registros
sintéticos e exige recuperar ao menos um perfil com todos os requisitos por vaga.

`ampliar_consultas(vaga, anteriores, cliente_modelo)` pede outros sinônimos e
devolve somente consultas novas. Se não houver novidade, retorna lista vazia;
o chamador deve sinalizar que essa estratégia de expansão se esgotou. Não há
aleatoriedade, coleta, paginação ou execução de consultas neste módulo.

### Decisões de implementação

- O modelo sugere somente cargos. O código monta a consulta com os requisitos,
  em vez de aceitar uma consulta inteira escrita pelo modelo.
- Dados de critérios sensíveis na vaga são recusados antes da chamada. Termos
  proibidos ou operadores na resposta fazem a saída voltar à consulta básica.
- Resposta fora do esquema, lista vazia, limite excedido de sugestões ou modelo
  indisponível usam a consulta básica de palavras-chave (ou o título quando não há termos). Limite de gasto continua
  sendo um erro para o fluxo pausar, nunca uma falha silenciosamente ignorada.
- Apenas o título delimitado vai ao modelo; descrição livre e consultas
  anteriores não são necessárias para sugerir cargos e não são enviadas.
- A validação textual é uma barreira limitada por padrões conhecidos. Aderência
  semântica dos sinônimos e eficiência de recuperação precisam ser avaliadas
  com os conectores; o texto da consulta não comprova nenhum requisito.
- Fonte que use DSL própria precisa de adaptador: não deve executar este texto
  como SQL ou Elasticsearch. Requisitos negativos, intervalos e outros valores
  estruturados permanecem responsabilidade dos filtros determinísticos.

### Observabilidade e limites

Cada operação registra empresa, vaga, etapa, regra e quantidade em `logging`,
sem conteúdo da vaga ou texto da exceção. A chamada usa exclusivamente
`ClienteModelo.completar`, com etapa `gerar_consultas` ou `ampliar_consultas`,
para que o cliente central registre tokens, custo e rastro.

T1.3 (cliente real) e T1.11 (auditoria) ainda não existem nesta base. A integração
real com Langfuse e a qualidade dos sinônimos do modelo real não foram
verificadas. Os testes usam o cliente simulado e não gastam créditos. A lista de
critérios proibidos é local até existir uma implementação compartilhável da
frente 1; os contratos não foram alterados.

### Verificação

```bash
python -m pytest tests/fontes/test_consultas.py -v
python -m pytest tests/test_qualidade_offline.py tests/test_registros.py -q -rxX
python -m pytest -q -rxX
ruff check .
```

A suíte offline existente verifica adaptadores falsos, não mede ainda a precisão
destas consultas. `avaliacoes/` e a medição integrada de recuperação não existem
neste checkout. O teste de qualidade marcado como pendente de fluxo pode aparecer
como `XPASS`; isso não comprova a integração com o agente real.
