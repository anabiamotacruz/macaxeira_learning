# API do agente recrutador (FastAPI), para Render, Railway, Fly ou qualquer host de contêiner.
# O painel (web/) é publicado à parte, na Vercel. Guia: docs/deploy.md.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9/uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependências primeiro, para aproveitar o cache entre builds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Só o que a API lê em tempo de execução: o código e os dados sintéticos da demonstração.
COPY backend ./backend
COPY dados ./dados

RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

# O provedor define PORT; localmente, 8000.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.agente.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
