# CORA: telas de referência (landing, app e vídeo)

Exportado do canvas de design em 08/11/2026. O canvas original fica em `https://claude.ai/artifact/6Bx8TAvgF4JdWFvEvbjqNu`, mas pede login no claude.ai; use os arquivos desta pasta.

## Como ver

- `html/`: cada tela em HTML que abre direto no navegador. Precisa de internet só para as fontes do Google. Abas, filtros e a demo animada funcionam.
- `fonte/`: o markup original de cada tela (`.dc.html`), com todos os estilos inline. É o melhor lugar para copiar medidas, cores e textos. Os `{{...}}` vêm do `renderVals()` no fim de cada arquivo.

Para ver no navegador com o JavaScript funcionando, sirva a pasta:

```bash
python3 -m http.server 8000 --directory docs/design/cora/html
```

## Telas

| Arquivo | O que é |
| --- | --- |
| `Main` | Landing page. Demo animada de e-mail e WhatsApp com 5 cargos. |
| `App-Catalogo` | Lista de vagas com filtros Todas, Buscando, Concluídas e Rascunhos. |
| `App-CriarVaga` | Descrição em linguagem natural, critérios propostos (E-01 a E-03, D-01 a D-04) com aprovação um a um, meta e blacklist da vaga. |
| `App-PainelVaga` | Quadro Analisando, Aguardando autorização, Em conversa e Entregue à Nara, com abas Quadro, Lista, Rastro e Critérios. |
| `App-Candidato` | Nota por critério, evidências, lacunas, contato por e-mail e WhatsApp, e dossiê para a Nara. |
| `App-Banco` | Banco de talentos com as 3 situações, origem, validade da autorização e pedidos de remoção. |
| `App-Empresa` | Perfil da empresa com blacklist de empresas e regras de contato. |
| `Roteiro`, `Cena1` a `Cena8` | Roteiro e quadros do vídeo de demonstração de 2:30. |

## Padrão visual

- **Navegação:** barra de topo branca de 60px, sem menu lateral. Ela tem:
  - logo do coral (`html/coral.png`) e "CORA";
  - abas em pílula: Vagas, Banco de talentos e Empresa;
  - busca com ⌘K;
  - botão "Criar vaga";
  - avatar.
- **Abas dentro da vaga:** sublinhadas, com a ativa marcada por borda inferior de 2px em `#FB3C0D`.
- **Caixa do agente:** "Peça algo à CORA…", fixa embaixo (sticky) no Painel, no Candidato e no Banco.
- **Fontes:**
  - Geist, nos pesos 400, 500, 600 e 700;
  - Geist Mono só para dados e rastro;
  - Source Serif 4 só no dossiê.
- **Cores:**
  - fundo `#F7F8F5`, cartões `#FFFFFF` e bordas `#DFE6E1` ou `#E4E9E5`;
  - texto `#0B3038`, secundário `#526C68` e texto pequeno `#5E7672`;
  - coral da marca `#FB3C0D` (logo e destaques);
  - botão primário `#DC3209` com texto branco, hover `#C42C08`. É mais escuro que o coral da marca para passar no contraste.
- **Situações (badges):**
  - Autorizada: `#E3F3E8` com texto `#2F6E52`;
  - Aguardando autorização: `#FFF1CC` com texto `#855A0E`;
  - Descartada: `#FFF1EE` com texto `#A43826`.
- **Raios:** botões de 8px e cartões de 10 a 12px.

## O que as telas têm e o app em `web/` ainda não

1. Blacklist de empresas, por empresa e por vaga. Não existe no contrato nem na spec, então precisa de mudança em `backend/contratos`, com aviso às quatro frentes.
2. Regras de contato no perfil da empresa: canais, tentativas, intervalo, horário e validade da autorização.
3. As 3 situações (Autorizada, Aguardando autorização e Descartada com a regra) no lugar dos 5 estados de `EstadoBanco`.
4. Painel em quadro, com aba de rastro e custo.
5. Critérios com código e aprovação um a um.
6. Detalhe do candidato no tema claro, com dossiê.

## Dados

Todos os nomes, e-mails, telefones e links são de exemplo: Maré Tech, `@exemplo.com`, `agenda.nara.exemplo`. A Nara aparece como "Nara simulada" nas telas do app, porque a regra do projeto pede para identificar simulação.
