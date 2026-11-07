# Testes e avaliações

- **Ciclo:** escreva o teste, veja falhar, implemente o mínimo e rode de novo.
- **Local:** `tests/<pasta do backend>/test_<modulo>.py`. Nomes dizem o comportamento, como `test_nao_contata_opt_out_nem_sem_autorizacao`.
- **Independência:** testes comuns não usam internet, chaves ou modelo real. Use `backend/contratos/simulacoes.py`.
- **Reprodutibilidade:** fixe sementes e datas. Teste não depende do relógio nem da ordem de execução.
- **Dados:** somente sintéticos, gerados por `dados/gerador.py` ou criados no próprio teste.
- **Casos obrigatórios:** caminho feliz, dado faltante, falha externa, resposta inválida e entrada maliciosa, quando se aplicarem.
- **Avaliações:** `pytest avaliacoes -m eval` mede o comportamento do agente. Violação de requisito, contato com opt-out, vazamento entre empresas e mudança por nome ou gênero precisam ser zero.
- **Respostas certas:** ficam separadas dos dados entregues ao agente. Não ajuste o agente olhando o conjunto final.
- **Ponta a ponta:** `tests/ponta_a_ponta` cobre o fluxo da demo, com modelo simulado, e roda com modelo real antes de cada congelamento.
- **Evidência no PR:** cole a saída resumida dos testes. "Funcionou aqui" não conta.
