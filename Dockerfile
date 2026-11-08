# API do agente (FastAPI) para deploy em PaaS (Render, Railway) ou VPS.
# O painel web (Next) vai separado, na Vercel: veja docs/deploy.md.
FROM python:3.12-slim

# Tesseract: OCR de currículo em PDF escaneado (backend/fontes/documentos.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependências primeiro, para o cache da camada sobreviver a mudanças de código.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend ./backend
COPY dados/sinteticos ./dados/sinteticos
COPY dados/__init__.py ./dados/__init__.py

RUN useradd --create-home --uid 1000 agente && chown -R agente /app
USER agente

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8000
EXPOSE 8000

# Um único processo: as conversas e o banco de talentos simulado ficam em memória.
# Socket dual-stack (IPv4 e IPv6) em $PORT: a rede privada da Railway usa IPv6, o domínio público, IPv4.
CMD ["python", "-c", "import os, socket, uvicorn\ns = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)\ns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\ns.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)\ns.bind(('::', int(os.environ.get('PORT', '8000'))))\nconfig = uvicorn.Config('backend.agente.api:app', proxy_headers=True, forwarded_allow_ips='*')\nuvicorn.Server(config).run(sockets=[s])"]
