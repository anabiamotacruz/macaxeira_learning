# API do agente recrutador

**Proposta**, válida enquanto o acordo das frentes não sair: rotas, campos e erros podem mudar. Código em `backend/agente/api.py`; contrato em `openapi.json`, com a lista de rotas e os exemplos de pedido e resposta.

As respostas são exemplos fixos e sintéticos de `backend/agente/exemplos_api.py`. Nada é gravado e nenhuma lógica roda. Os números de `/metricas` são ilustrativos e não medem o agente. A rota `/destino` repete o `destino` e o `responsavel` recebidos; o resto não depende do corpo enviado.

O agente não agenda, não entrevista e não decide contratações.

## Gerar o contrato

```bash
uv run python -m backend.agente.gerar_openapi
```

`tests/agente/test_gerar_openapi.py` falha se `openapi.json` divergir do código.

## Rodar

```bash
uv run uvicorn backend.agente.api:app --reload
```

```bash
curl -H "X-Empresa-Id: empresa-exemplo" http://127.0.0.1:8000/vagas/vaga-exemplo-1
```

A documentação interativa fica em `/docs`.

## Regras do contrato

- **Sessão:** `empresa_id` vem do cabeçalho simulado `X-Empresa-Id`, nunca do corpo. Sem ele, a resposta é 401.
- **Isolamento:** os recursos de exemplo pertencem a `empresa-exemplo`. Para outra empresa, a resposta é 404. Como nada é gravado, `POST /vagas` devolve a vaga com a empresa da sessão, mas outra empresa não consegue consultá-la depois.
- **Identificação:** toda resposta traz `simulado: true`. As de sucesso trazem também `exemplo_fixo: true`, que sai quando a lógica entrar.
- **Erros:** `{"erro": {"codigo": "...", "mensagem": "..."}, "simulado": true}`.
- **Listas:** `pagina` e `limite`, com limite máximo de 100.
- **Ações repetíveis:** `/parar`, `/retomar`, `/reverter` e `/destino` exigem `chave_idempotencia` e `responsavel`.

## Ainda não coberto

- `POST /convites/{id}/resposta`, da T1.4d.
- Limite de requisições (FR-029).
- CORS: um navegador em outra origem não chama a API diretamente. Use um proxy do Next ou combine a origem com a Frente 1.
