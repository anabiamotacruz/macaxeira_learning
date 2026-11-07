# API e dados

- **Contratos:** `backend/contratos` é a fonte única de formatos. Mudanças exigem aviso às quatro frentes.
- **Rotas:** substantivos no plural, em português, como `/vagas/{id}/candidatos`. Ações usam verbos curtos no fim, como `/aprovar`.
- **Escopo:** toda leitura e escrita usa `empresa_id`. Ele vem da sessão, nunca de um campo livre confiado ao cliente.
- **Respostas de erro:** `{"erro": {"codigo": "...", "mensagem": "..."}}`, com código HTTP adequado e sem stack trace.
- **Validação:** entradas e saídas passam por Pydantic. Campo desconhecido em dado crítico é rejeitado.
- **Datas:** ISO 8601. Valores monetários de custo em `usd`, com o nome da unidade no campo.
- **Idempotência:** convites, entregas à Nara e ações repetíveis usam `chave_idempotencia`.
- **Simulação:** toda resposta com dado simulado traz `simulado: true`.
- **Paginação:** listas usam `pagina` e `limite`, com limite máximo definido no servidor.
- **Persistência:** SQLite, acessado somente pelo `Repositorio`. Mudanças de tabela ficam em um único arquivo de esquema.
