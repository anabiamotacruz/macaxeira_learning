# Frontend

- **Base:** Next com App Router e TypeScript em modo estrito, em `web/`, usando `pnpm`.
- **Acesso à API:** toda chamada passa por `web/lib/api.ts`. Tipos ficam em `web/lib/tipos.ts` e seguem os contratos.
- **Componentes:** `PascalCase`, um por arquivo, em `web/components`. Lógica de tela fica fora de componentes visuais quando crescer.
- **Estados:** toda tela trata carregando, vazio, erro e sucesso. Execuções longas mostram progresso e resultados parciais.
- **Simulações:** dado com `simulado: true` sempre mostra o selo "Simulado". O mesmo vale para gravações.
- **Explicabilidade:** indicação e descarte sempre mostram motivo, evidências e regra aplicada.
- **Textos:** português do Brasil, claros e sem jargão técnico para o recrutador. Erros dizem o que fazer a seguir.
- **Acessibilidade:** use HTML semântico, rótulos em campos e foco visível, e não dependa só de cor.
- **Segurança:** o navegador nunca recebe chaves. Variáveis `NEXT_PUBLIC_` não podem conter segredos.
- **Demo:** o fluxo principal precisa funcionar sem explicação do time e em uma aba anônima.
