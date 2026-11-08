# API do agente recrutador

**Proposta**, válida enquanto o acordo das frentes não sair: rotas, campos e erros podem mudar. Código em `backend/agente/api.py`; contrato em `openapi.json`, com a lista de rotas e os exemplos de pedido e resposta.

As rotas rodam o fluxo real da vaga e gravam em SQLite. Sem configuração, `backend.agente.api:app` monta a demonstração de `backend/agente/montagem.py`: dados sintéticos, simulações no lugar de modelo, fontes e destino, nenhuma chave e banco numa pasta temporária. Para outras peças, use `criar_app(ServicoVagas(...))`.

Assinar o mandato e retomar respondem na hora e seguem em segundo plano; acompanhe por `GET /vagas/{id}` e `/eventos`.

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
curl -X POST -H "X-Empresa-Id: empresa-exemplo" -H "Content-Type: application/json" \
  -d @pedido-vaga.json http://127.0.0.1:8000/vagas
```

A documentação interativa fica em `/docs`.

Por padrão, a API sobe a demonstração sem modelo: tudo sintético e sem chave. Para o agente raciocinar com o modelo de verdade na análise, na revisão, nas consultas e nas dúvidas, defina `AGENTE_COM_MODELO=1` e `FEATHERLESS_API_KEY`. As pessoas, o contato e a Nara continuam simulados. O gasto do modelo conta para o limite do mandato: passou do limite, a vaga pausa. Sem a chave, a API avisa no log e segue sem modelo.

## Regras do contrato

- **Sessão:** `empresa_id` vem do cabeçalho simulado `X-Empresa-Id`, nunca do corpo. Sem ele, a resposta é 401.
- **Isolamento:** o que é de outra empresa não existe para a sessão: a resposta é 404.
- **Identificação:** a sessão é simulada, então toda resposta traz `simulado: true`. `exemplo_fixo: true` marca o que ainda não vem da lógica: `/metricas` sem provedor de medição e `/sessoes/reiniciar` sem dados para recarregar. Os números dessas respostas são ilustrativos e não medem o agente.
- **Erros:** `{"erro": {"codigo": "...", "mensagem": "..."}, "simulado": true}`. Além de 401, 404 e 422, as ações usam 409: `transicao_invalida`, `auditoria_pendente`, `aditivo_necessario`, `acao_recusada` e `chave_reutilizada`.
- **Listas:** `pagina` e `limite`, com limite máximo de 100.
- **Ações repetíveis:** `/parar`, `/retomar`, `/reverter` e `/destino` exigem `chave_idempotencia` e `responsavel`, que precisa ser uma pessoa. Repetir com a mesma chave devolve a primeira resposta; a mesma chave com outro pedido é recusada.

## Ainda não coberto

- `POST /convites/{id}/resposta`, da T1.4d. Sem ela, a vaga com entrega depois do aceite fica em `convidando`; `ServicoVagas.registrar_resposta` já aplica a resposta.
- Medição real em `/metricas`: injete `metricas=` em `ServicoVagas`.
- Limite de requisições (FR-029).
- CORS: um navegador em outra origem não chama a API diretamente. Use um proxy do Next ou combine a origem com a Frente 1.
