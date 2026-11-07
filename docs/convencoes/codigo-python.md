# Código Python

- **Versão:** Python 3.12, com `uv` e o `.venv` da raiz. Dependência nova entra no `pyproject.toml` com justificativa no PR.
- **Idioma:** termos do domínio em português (`candidato`, `vaga`), sem acentos em identificadores. Termos técnicos consagrados podem ficar em inglês.
- **Nomes:** `snake_case` para funções e arquivos, `PascalCase` para classes, `MAIUSCULAS` para constantes.
- **Tipos:** toda função pública tem tipos de entrada e saída. Dados que cruzam frentes usam modelos de `backend/contratos`.
- **Dependências:** injete interfaces de `backend/contratos/interfaces.py` no construtor. Uma frente não importa implementação de outra.
- **Funções:** pequenas e com uma responsabilidade. Regra de negócio não fica em rota da API nem em prompt.
- **Erros:** use os erros de `backend/contratos/erros.py`. Não use `except` genérico sem registrar e relançar.
- **Datas:** use `date` ou `datetime` com fuso. Passe `hoje` como parâmetro em regras, para os testes serem reproduzíveis.
- **Determinismo:** cálculos, filtros e ordenação não usam modelo. Empates têm critério explícito, como o `id`.
- **Logs:** use `logging`, nunca `print`. Nunca registre chaves ou dados completos do perfil.
- **Qualidade:** `ruff check .` precisa passar. Não desative regras sem explicar o motivo na linha.
