# IA e prompts

- **Quando usar modelo:** interpretar texto, gerar consultas, explicar e redigir. Regras, contas, autorização e estados ficam em código.
- **Acesso:** toda chamada usa `ClienteModelo`, com `etapa` definida. Não crie cliente novo por módulo.
- **Modelos:** `GLM-5.2` em análise e revisão; modelo mais barato em extração e triagem, depois de testado. Use `max_tokens` de pelo menos 1000 no `GLM-5.2`.
- **Prompts:** ficam em `prompts.py`, no módulo que os usa, com constantes nomeadas. Não espalhe texto de prompt pelo fluxo.
- **Saída:** sempre validada com esquema Pydantic. Resposta inválida segue o caminho de nova tentativa e, depois, revisão humana.
- **Dados externos:** currículos, mensagens e documentos ficam entre delimitadores e são declarados como dados. Instruções neles nunca são seguidas e geram alerta.
- **Evidências:** o modelo cita o trecho de origem. O código confere se o trecho existe e descarta afirmação sem fonte.
- **Critérios proibidos:** não envie atributos sensíveis para decisões e não os use em consultas.
- **Mudança de prompt ou modelo:** rode as avaliações e registre o antes e o depois no PR.
- **Custo:** toda chamada registra tokens, custo e tempo. Ative o cache quando a mesma análise se repetir.
- **Testes:** testes comuns usam `ClienteModelo` simulado. Chamadas reais ficam em execuções marcadas, para não gastar créditos.
