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

## 3. Limites conhecidos

- **Sem autenticação.** A empresa vem do cabeçalho `X-Empresa-Id`, e quem conhece a URL da API pode ler os dados de qualquer empresa. Serve para demonstração com dados sintéticos, não para dado real.
- **Estado efêmero.** O SQLite fica numa pasta temporária, e as conversas e o banco simulado ficam em memória. Reiniciar ou fazer redeploy volta tudo ao estado inicial. Mantenha **uma instância só**.
- **Plano gratuito do Render.** A instância dorme após 15 minutos sem uso e perde o estado. Use o `starter` na demonstração, ou abra a API alguns minutos antes.
- **WhatsApp (Evolution API)** não sobe no PaaS: o `infra/evolution` roda em Docker local, e o webhook precisa alcançar a API. Sem ele, o painel mostra as conversas como simuladas. Para ter o WhatsApp real, suba a Evolution numa VPS e defina `EVOLUTION_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCIA` e `EVOLUTION_WEBHOOK_TOKEN` na API. O webhook vai para `https://<api>/whatsapp/webhook`.
- **OCR de PDF escaneado** usa o Tesseract, instalado na imagem.
