# Deploy do link testável (T4.3)

O link público tem duas partes:

| Parte | Onde | Arquivos |
| --- | --- | --- |
| API (FastAPI, `backend/`) | Render, com contêiner sempre ligado. Railway e Fly servem com o mesmo `Dockerfile`. | `Dockerfile`, `.dockerignore`, `render.yaml` |
| Painel (Next, `web/`) | Vercel | nenhum arquivo extra; a Vercel detecta o Next |

## Por que a API não vai para a Vercel

A API monta uma única demonstração em memória no primeiro pedido e grava num SQLite temporário (`backend/agente/montagem.py`). As funções Python da Vercel não mantêm processo nem disco entre chamadas, então vaga, convites e eventos se perderiam entre um clique e outro. A API precisa de um processo contínuo.

Toda reinicialização do serviço volta a demonstração ao estado inicial. Para o júri, isso é desejável. `POST /sessoes/reiniciar` faz o mesmo sem reiniciar o serviço.

A Featherless só fornece o modelo. Ela não hospeda código.

## Ordem

1. Levar o painel ligado à API (#96, da Sofia) à `main`. Sem isso, o link mostra só telas de exemplo. Confira se `web/lib` entrou no Git: o `lib/` do `.gitignore` já o escondeu uma vez.
2. Publicar a API e anotar a URL.
3. Publicar o painel com essa URL.
4. Voltar à API e colocar o domínio do painel em `ORIGENS_PAINEL`.
5. Verificar em aba anônima.

## 1. API no Render

1. No Render, **New > Blueprint** e escolher este repositório. O `render.yaml` cria o serviço `macaxeira-api`.
2. Quando pedir `ORIGENS_PAINEL`, deixar em branco por enquanto. `FEATHERLESS_API_KEY` também pode ficar em branco enquanto o modelo estiver desligado.
3. Esperar o build e abrir `https://<servico>.onrender.com/docs`. A página do Swagger confirma que a API subiu.

O plano gratuito dorme após 15 minutos sem uso e leva cerca de 1 minuto para acordar. O `render.yaml` usa `starter` por isso. Se ficar no gratuito, abra o link uns minutos antes do Demo Day.

### Alternativa: Railway

**New Project > Deploy from GitHub repo**. O Railway usa o `Dockerfile` da raiz e define `PORT` sozinho. Configure as mesmas variáveis da tabela abaixo e gere um domínio público em **Settings > Networking**.

### Variáveis da API

| Variável | Valor no link público | Observação |
| --- | --- | --- |
| `ORIGENS_PAINEL` | `https://<projeto>.vercel.app` | Sem barra no fim. Vários domínios separados por vírgula. Sem isso, o navegador bloqueia o painel por CORS. |
| `AGENTE_COM_MODELO` | vazio | Com `1`, cada visitante gasta crédito da Featherless. Ainda não há limite de gasto por sessão (T4.5). |
| `AGENTE_BUSCA_REAL` | vazio | A busca externa usa chaves pagas e dados que não são sintéticos. |
| `MODO_DADOS` | `sinteticos` | Garante que nenhum provedor externo seja criado. |
| `NARA_MCP_URL` | vazio | Vazio, a Nara simulada roda dentro da própria API. |

## 2. Painel na Vercel

1. **Add New > Project**, escolher o repositório e definir **Root Directory** como `web`.
2. A Vercel detecta Next e pnpm pelo `pnpm-lock.yaml`. Não mude os comandos de build.
3. Variáveis de ambiente:

| Variável | Valor |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | URL da API, sem barra no fim |
| `NEXT_PUBLIC_EMPRESA_ID` | a empresa da demonstração, a mesma do painel local |
| `NEXT_PUBLIC_MODO_RESERVA` | `false` |

As variáveis `NEXT_PUBLIC_*` entram no build. Depois de mudar qualquer uma, faça **Redeploy**.

4. Com o domínio da Vercel em mãos, coloque-o em `ORIGENS_PAINEL` na API e reinicie o serviço.

## 3. Verificação

Em aba anônima:

- [ ] `https://<api>/docs` abre.
- [ ] O painel carrega sem erro de CORS no console.
- [ ] Criar e aprovar uma vaga, aprovar o lote, responder como candidato e ver a entrega à Nara simulada.
- [ ] O selo "Simulado" aparece.
- [ ] `POST /sessoes/reiniciar` volta ao estado inicial.

## Limites conhecidos

- Todos os visitantes compartilham a mesma demonstração. A separação é por empresa, pelo cabeçalho `X-Empresa-Id`, então dois jurados na mesma empresa veem as ações um do outro.
- Não há limite de requisições nem de gasto por sessão (T4.5). Por isso o modelo fica desligado no link público.
- O OCR de PDF sem texto precisa do binário do Tesseract, que a imagem não instala. A demonstração não usa OCR.
