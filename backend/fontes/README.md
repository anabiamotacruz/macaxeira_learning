# Fontes e consultas

## T2.7 — geração de consultas

`gerar_consultas(vaga, cliente_modelo)` devolve texto simples, independente do
provedor: o título original seguido das descrições dos requisitos e até seis
variações de cargo propostas pelo modelo. Valores esperados diferentes de
`sim`, `true` e `yes` também são mantidos no texto. Competências opcionais não
viram filtros obrigatórios.

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
  indisponível usam o título e requisitos originais. Limite de gasto continua
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

## T2.8 — funil e cache

`priorizar(vaga, candidatos, limite=20, hoje=...)` aplica igualdade normalizada
nos valores estruturados de cada requisito, sem inferir fatos do currículo.
Filtra empresa, opt-out, estado e validade de autorização antes de ordenar.
Perfil sem dado eliminatório fica fora da pré-seleção com motivo
`requisito_desconhecido`, não recebe uma decisão final de descarte.

O ranking é lexical e ponderado pelas competências da vaga. Lê somente campos
profissionais estruturados: cargo, competências, habilidades, skills,
tecnologias, linguagens, cloud e atributos com o nome exato de uma competência.
Valores explicitamente negativos, vazios ou desconhecidos não pontuam. Não
interpreta negação em prosa: a estruturação deve separar competências afirmadas.
Nome, contato, gênero, texto livre e histórico não entram na pontuação. Isso
evita pontuar nomes e instruções de currículo, mas pode deixar de recuperar
informação ainda não estruturada. Lacunas de carreira não recebem penalidade.
É uma prioridade de análise, não uma nota de adequação final.

Empates usam o id. Duplicatas da mesma empresa e id aparecem uma vez; qualquer
opt-out, autorização inválida ou conflito eliminatório bloqueia o grupo nessa
etapa. Entre cópias elegíveis, usa data de atualização e desempate estável com
conteúdo profissional/fonte/origem. A função devolve cópias independentes.

`CacheAnalise.salvar(vaga, candidato, analise, versao_configuracao=...)` valida o
escopo. `obter` retorna uma cópia ou `None`. A chave inclui todo o conteúdo do
perfil e da vaga, empresa e versão da configuração. O chamador deve versionar
prompt/modelo nesse parâmetro. O cache usa LRU, com limite padrão de 1.000 itens,
e revalida a elegibilidade ao consultar. Sem `hoje` explícito, a data UTC é lida
a cada operação; os testes usam datas fixas. O cache é local e não persiste
após reinício, nem coordena vários processos.

A T1.1 ainda não está nesta base. A checagem conservadora de igualdade atende
aos campos do contrato atual; comparadores numéricos e tempo de experiência não
são interpretados neste módulo. A validação de critérios reutiliza a T2.7 e
deve ser alinhada à regra central da frente 1 quando ela chegar. Auditoria final
de decisões e rastro Langfuse permanecem com as tarefas T1.1/T1.11. O funil
registra regra e escopo em logging, sem dados pessoais, e não chama modelos.

Avaliações locais do funil, separadas dos testes comuns:

```bash
python -m pytest tests/fontes/test_funil.py -v
python -m pytest tests/fontes/test_funil_avaliacao.py -m eval -v
```

Elas conferem elegibilidade contra os 250 rótulos nas seis vagas e invariância da
ordem ao alterar nome e gênero. Não medem precisão top 5, qualidade de análise ou
taxa de contratação e não substituem a avaliação independente da frente 4.
