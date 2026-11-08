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

## T2.3 — análise com evidências

`Analisador(cliente_modelo, hoje=..., cache=..., versao_configuracao=...)` implementa
`analisar(vaga, candidato) -> Analise`. O funil valida empresa, autorização e
requisitos estruturados antes de qualquer chamada. O cache reutiliza análises
válidas, com invalidação por mudanças na vaga, perfil ou versão de configuração.

O modelo recebe somente critérios profissionais, fonte e texto delimitado em JSON.
Nome, atributos arbitrários, contatos estruturados e datas do histórico não são
enviados. Segmentos reconhecidos como instrução ou critério sensível são retirados,
preservando as frases profissionais adjacentes; instruções geram alerta.

O código valida o esquema, limita notas a 0–1 e aceita apenas competências da vaga
com evidência de fonte conhecida e trecho literal presente tanto no perfil original
quanto no texto enviado. Afirmações sem evidência são removidas. Requisitos são
verificados em código; lacunas são perguntas e não geram descontos no código.

Há no máximo duas solicitações locais em caso de resposta inválida ou modelo
indisponível; o cliente central pode ter sua própria política de tentativas. Se
ambas falham, retorna análise sem notas com alerta de revisão humana, sem cachear
a falha. Limite de gasto propaga para o fluxo pausar. Cada solicitação, cache e
resultado registra etapa e ids, sem imprimir o perfil.

Limites: a sanitização reconhece padrões conhecidos, não prova proteção contra
toda injeção ou atributo pessoal em texto livre. A existência literal de uma citação
não prova sua interpretação semântica: a revisão independente T2.4 continua
necessária antes da indicação. As notas propostas pelo modelo e a invariância
foram verificadas com respostas sintéticas, não com o modelo real. T1.1/T1.3/T1.11
continuam pendentes para regras centrais, cliente e auditoria completos. Não há
mudança nos contratos compartilhados.

## T2.4 — revisor independente

`Revisor(cliente_modelo, hoje=...).revisar(vaga, candidato, analise)` confere o
escopo e a elegibilidade atual antes de qualquer chamada. Faz uma solicitação
separada, na etapa `revisar_perfil`, recebendo apenas os critérios profissionais,
o perfil sanitizado e a fonte. Não recebe notas, lacunas, conclusões ou evidências
do analisador. O cliente é injetado: uma chamada separada não significa outro
provedor ou outro modelo.

O revisor produz suas próprias evidências e possíveis ressalvas. O código valida
critério, fonte e trecho literal no perfil original e sanitizado; uma ressalva do
modelo só entra se citar trecho verificável. Uma proposta inválida gera pedido de
revisão humana, sem apresentar o motivo inventado como fato. O código também
confere as evidências e notas da análise original, além do resultado dos requisitos
estruturados. Ausência de evidência independente é inconclusiva, não reprovação.

A saída é uma cópia de `Analise`: preserva as notas e ressalvas anteriores e
acrescenta as novas ressalvas em `ressalvas_revisor`. O consumidor deve encaminhar
análises com ressalvas para revisão humana, conforme as regras da frente 1.
Nenhum envio, decisão de contratação ou alteração de contrato ocorre aqui.

Resposta fora do esquema ou indisponibilidade admitem até duas solicitações locais;
a falha final exige revisão humana. Limite de gasto propaga. Não há cache da
revisão: cada execução revalida autorização e gera nova chamada com registros de
etapa e ids, sem imprimir currículo ou resposta do modelo.

Validação sintética: 19 testes específicos e 12 avaliações mecânicas com citações
literais/adulteradas nas seis vagas. Essas avaliações verificam o tratamento de
citações, não a pertinência semântica ou a calibração das notas. Avaliação com o
modelo real e validação humana continuam pendentes; uma citação literal pode ser
interpretada incorretamente pelo modelo. A sanitização compartilha os limites
conhecidos documentados na T2.3. A integração do fluxo com T1.1/T1.3/T1.11 ainda
precisa ser validada quando essas tarefas estiverem disponíveis.
