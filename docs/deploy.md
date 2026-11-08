# Deploy

A API (FastAPI) vai num PaaS com Docker, como o Render ou o Railway. O painel (Next) vai na Vercel. Os dados continuam sintéticos e identificados como simulação. As integrações reais (modelo, busca, e-mail) só entram com as chaves e os interruptores do `.env.example`.

## 1. API no Render (ou Railway)

**Render:** New → Blueprint → este repositório. O `render.yaml` cria o serviço `macaxeira-api`. Preencha os segredos que ele pedir.

**Railway:** New Project → Deploy from GitHub. O Railway encontra o `Dockerfile` sozinho. Defina as variáveis abaixo e o health check em `/docs`.

A imagem ouve em `$PORT`, que o provedor define. Para testar localmente:

```bash
docker build -t macaxeira-api .
docker run --rm -p 8000:8000 -e ORIGENS_PAINEL=http://localhost:3000 macaxeira-api
```

### Variáveis da API

| Variável | Obrigatória | Para quê |
| --- | --- | --- |
| `ORIGENS_PAINEL` | sim | URL da Vercel (CORS), separadas por vírgula. Sem ela, só o `localhost:3000` passa. |
| `AGENTE_COM_MODELO=1` e `FEATHERLESS_API_KEY` | recomendado | O agente raciocina com o modelo. Sem elas, roda a demonstração sem modelo. |
| `MODELO_PADRAO` | não | `Qwen/Qwen3-30B-A3B-Instruct-2507` é cerca de 5 vezes mais rápido que o GLM-5.2. |
| `LIMITE_GASTO_SESSAO_USD` | não | Teto de gasto com o modelo por sessão. |
| `LANGFUSE_*` | não | Rastro das chamadas. |
| `AGENTE_BUSCA_REAL=1` e as chaves de fonte | não | Busca real (LinkedIn pela Brave, EnvoAPI, LinkdAPI, PDL). Está desligada por padrão, e cada chamada tem custo. |
| `AGENTE_ENVIO_REAL=1`, `RESEND_API_KEY` e `EMAIL_FROM` | não | E-mail real, só para quem veio da busca real e publicou o e-mail. |

A lista completa, com custos e regras, está no `.env.example`.

## 2. Painel na Vercel

New Project → este repositório, com estes ajustes:

- **Root Directory:** `web`
- **Framework:** Next.js, detectado sozinho.
- **Install Command:** `corepack enable && pnpm install --frozen-lockfile` (o `package.json` fixa o pnpm 12).
- **Variáveis:**
  - `NEXT_PUBLIC_API_URL`: URL pública da API, por exemplo `https://macaxeira-api.onrender.com`, sem barra no fim.
  - `NEXT_PUBLIC_EMPRESA_ID`: opcional. O padrão é `empresa-exemplo`.
  - **Não** defina `NEXT_PUBLIC_MODO_RESERVA`. Ela troca a API pelos dados fixos do painel.

As variáveis `NEXT_PUBLIC_*` entram no build. Se mudar uma, faça o redeploy.

Depois do primeiro deploy, copie a URL da Vercel para a `ORIGENS_PAINEL` da API. As URLs de preview mudam a cada push. Para usar uma delas, acrescente-a também.

## Tudo na Railway (API, painel com login e WhatsApp)

São quatro serviços num projeto só: `api`, `web`, `evolution` e `Postgres`. Só o `web` e a `evolution` têm domínio público. A API fica só na rede privada, e o painel repassa `/api/*` para ela, atrás do login.

1. **api:** New → GitHub Repo → este repositório. A Railway usa o `Dockerfile`. Não gere domínio. Em Settings, ponha Healthcheck Path `/docs` e Replicas 1. Variáveis:
   ```
   PORT=8000
   AGENTE_COM_MODELO=1
   FEATHERLESS_API_KEY=<chave>
   MODELO_PADRAO=Qwen/Qwen3-30B-A3B-Instruct-2507
   LIMITE_GASTO_SESSAO_USD=5
   EVOLUTION_URL=http://evolution.railway.internal:8080
   EVOLUTION_API_KEY=${{evolution.AUTHENTICATION_API_KEY}}
   EVOLUTION_INSTANCIA=macaxeira
   EVOLUTION_WEBHOOK_TOKEN=<segredo, ex.: openssl rand -hex 24>
   VOZ_REAL=1
   ```
2. **web:** New → GitHub Repo → o mesmo repositório. Configure assim:
   - **Root Directory:** `/web`
   - **Custom Install Command:** `corepack enable && pnpm install --frozen-lockfile`
   - **Domínio:** gere um em Generate Domain.
   - **Variáveis:**
     ```
     API_INTERNA_URL=http://api.railway.internal:8000
     NEXT_PUBLIC_API_URL=/api
     PAINEL_USUARIO=<usuário>
     PAINEL_SENHA=<senha forte>
     ```
3. **Postgres:** New → Database → PostgreSQL.
4. **evolution:** New → Docker Image → `evoapicloud/evolution-api:v2.3.7`. Gere um domínio na porta 8080 e adicione um Volume em `/evolution/instances`. Variáveis:
   ```
   PORT=8080
   SERVER_PORT=8080
   SERVER_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}
   AUTHENTICATION_API_KEY=<segredo, ex.: openssl rand -hex 24>
   AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES=false
   DATABASE_PROVIDER=postgresql
   DATABASE_CONNECTION_URI=${{Postgres.DATABASE_URL}}
   DATABASE_SAVE_DATA_INSTANCE=true
   DATABASE_SAVE_DATA_NEW_MESSAGE=false
   DATABASE_SAVE_DATA_CONTACTS=false
   DATABASE_SAVE_DATA_CHATS=false
   DATABASE_SAVE_DATA_HISTORIC=false
   CACHE_REDIS_ENABLED=false
   CACHE_LOCAL_ENABLED=true
   LANGUAGE=pt-BR
   ```
5. **Parear o WhatsApp**, uma vez, da sua máquina:
   ```bash
   EVOLUTION_PUBLICA=https://<domínio da evolution> EVOLUTION_API_KEY=<o mesmo> \
   EVOLUTION_WEBHOOK_TOKEN=<o mesmo da api> ./infra/railway/whatsapp.sh
   ```
   O script cria a instância e aponta o webhook para `http://api.railway.internal:8000/whatsapp/webhook`. Depois mostra o QR. Outra opção é parear pelo `https://<evolution>/manager`.
6. Abra o domínio do `web`. O navegador pede o usuário e a senha.

Os nomes dos serviços (`api`, `evolution`, `Postgres`) entram nos endereços `*.railway.internal` e nas referências `${{…}}`. Se você mudar um nome, ajuste as variáveis.

## 3. Limites conhecidos

- **Login único.** Com `PAINEL_USUARIO` e `PAINEL_SENHA`, o painel e o `/api` pedem senha (HTTP Basic). A empresa ainda vem do cabeçalho `X-Empresa-Id`, então quem tem a senha vê qualquer empresa. Na Railway, deixe a API sem domínio público. No Render, a API fica pública e sem senha.
- **Estado efêmero.** O SQLite fica numa pasta temporária, e as conversas e o banco simulado ficam em memória. Reiniciar ou fazer redeploy volta tudo ao estado inicial. Mantenha **uma instância só**.
- **Plano gratuito do Render.** A instância dorme após 15 minutos sem uso e perde o estado. Use o `starter` na demonstração, ou abra a API alguns minutos antes.
- **WhatsApp (Evolution API)** só sobe no deploy completo da Railway, descrito acima. No Render com a Vercel, ele fica de fora, e o painel mostra as conversas como simuladas.
- **OCR de PDF escaneado** usa o Tesseract, instalado na imagem.
