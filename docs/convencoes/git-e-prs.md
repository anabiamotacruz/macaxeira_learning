# Git e pull requests

- **Branches:** `frente/agente`, `frente/fontes`, `frente/contato` e `frente/produto`. Para tarefas maiores, use `frente/agente/t1-8-persistencia`.
- **Atualização:** rode `git pull --rebase origin main` antes de abrir PR. Nunca force push na `main`.
- **Commits:** `tipo: descrição`, em português e no imperativo, como `feat: adiciona funil de candidatos`. Tipos: `feat`, `fix`, `test`, `docs`, `refactor` e `chore`.
- **Atribuição:** commits e PRs não mencionam assistentes nem têm `Co-Authored-By`.
- **Tamanho:** um PR por tarefa, de preferência. Se ficar difícil de revisar, divida.
- **Código na `main`:** entra por PR, com testes e lint passando e, se possível, revisão de alguém de outra frente.
- **Pastas:** altere só as da sua frente. Se precisar mexer em outra, combine antes.
- **Contratos:** PR próprio, aviso no grupo e revisão de pelo menos uma pessoa de outra frente.
- **Conflitos:** quem está integrando resolve, sem apagar trabalho de outra pessoa sem combinar.
- **Congelamento:** no domingo, depois das 11h, só correções.
