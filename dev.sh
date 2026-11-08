#!/usr/bin/env bash
# Sobe o ambiente de desenvolvimento: Evolution API (WhatsApp), API do agente e painel web.
#
#   ./dev.sh               sobe tudo e mostra o QR do WhatsApp se o número ainda não estiver pareado
#   ./dev.sh --sem-zap     sobe só a API e o painel, sem Evolution
#
# Ctrl+C derruba a API e o painel. A Evolution continua rodando, pareada:
#   docker compose -f infra/evolution/docker-compose.yml down   para parar.
# Os segredos locais ficam em infra/evolution/.env (ignorado pelo git) e nunca são impressos.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RAIZ"
LOGS="$RAIZ/.dev"
mkdir -p "$LOGS"
INSTANCIA="${EVOLUTION_INSTANCIA:-macaxeira}"
porta_livre() {  # a primeira porta livre a partir da indicada
  local porta=$1
  while ss -ltn "sport = :$porta" 2>/dev/null | grep -q LISTEN; do porta=$((porta + 1)); done
  echo "$porta"
}
PORTA_API="${PORTA_API:-$(porta_livre 8000)}"
PORTA_WEB="${PORTA_WEB:-$(porta_livre 3000)}"
COM_ZAP=1
API_HOST=127.0.0.1  # com o WhatsApp, vira o IP da ponte do Docker: só esta máquina e os containers alcançam
[[ "${1:-}" == "--sem-zap" ]] && COM_ZAP=0

info() { printf '\033[1;32m›\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33m!\033[0m %s\n' "$*"; }

PIDS=()
matar_arvore() {  # o processo e todos os filhos (pnpm → next → node)
  local filho
  for filho in $(pgrep -P "$1" 2>/dev/null); do matar_arvore "$filho"; done
  kill "$1" 2>/dev/null || true
}
encerrar() {
  trap - EXIT INT TERM
  info "Encerrando a API e o painel…"
  for pid in "${PIDS[@]}"; do matar_arvore "$pid"; done
  wait 2>/dev/null || true
}
trap encerrar EXIT INT TERM

esperar_http() {  # url, tentativas
  for _ in $(seq 1 "$2"); do
    curl -s -m 3 -o /dev/null "$1" && return 0
    sleep 2
  done
  return 1
}

# Python
if [[ ! -x .venv/bin/python || pyproject.toml -nt .venv/.dev-sincronizado || uv.lock -nt .venv/.dev-sincronizado ]]; then
  info "Sincronizando o ambiente Python (uv sync)…"
  uv sync && touch .venv/.dev-sincronizado
fi

# WhatsApp (Evolution API)
if [[ $COM_ZAP == 1 ]]; then
  ENV_EVO="infra/evolution/.env"
  if [[ ! -f "$ENV_EVO" ]]; then
    info "Gerando os segredos locais da Evolution em $ENV_EVO"
    (umask 077; printf 'EVOLUTION_API_KEY=%s\nEVOLUTION_DB_SENHA=%s\nEVOLUTION_WEBHOOK_TOKEN=%s\n' \
      "$(openssl rand -hex 24)" "$(openssl rand -hex 16)" "$(openssl rand -hex 24)" > "$ENV_EVO")
  fi
  set -a; . "$ENV_EVO"; set +a

  # Docker sem o helper de credenciais do Docker Desktop: usa uma configuração vazia.
  if grep -q '"credsStore"' "${DOCKER_CONFIG:-$HOME/.docker}/config.json" 2>/dev/null \
     && ! command -v "docker-credential-$(grep -o '"credsStore": *"[^"]*"' "${DOCKER_CONFIG:-$HOME/.docker}/config.json" | sed 's/.*"\([^"]*\)"$/\1/')" >/dev/null; then
    export DOCKER_CONFIG="$LOGS/docker"
    mkdir -p "$DOCKER_CONFIG"; [[ -f "$DOCKER_CONFIG/config.json" ]] || echo '{}' > "$DOCKER_CONFIG/config.json"
  fi

  info "Subindo a Evolution API (docker compose)…"
  docker compose -f infra/evolution/docker-compose.yml --env-file "$ENV_EVO" up -d >/dev/null
  esperar_http "http://127.0.0.1:8080/" 60 || { aviso "A Evolution não respondeu em :8080. Veja: docker compose -f infra/evolution/docker-compose.yml logs"; exit 1; }
  API_HOST="$(docker network inspect evolution_default -f '{{(index .IPAM.Config 0).Gateway}}')"

  evo() {  # método, caminho, [corpo]
    curl -s -m 20 -X "$1" "http://127.0.0.1:8080$2" -H "apikey: $EVOLUTION_API_KEY" \
      -H 'Content-Type: application/json' ${3:+-d "$3"}
  }

  if ! evo GET "/instance/connectionState/$INSTANCIA" | grep -q '"instance"'; then
    info "Criando a instância $INSTANCIA, com o webhook apontando para a API (:$PORTA_API)"
    evo POST /instance/create "$(python3 - "$INSTANCIA" "$PORTA_API" "$API_HOST" <<'EOF'
import json, os, sys
print(json.dumps({
    "instanceName": sys.argv[1], "integration": "WHATSAPP-BAILEYS", "qrcode": True,
    "webhook": {"url": f"http://{sys.argv[3]}:{sys.argv[2]}/whatsapp/webhook",
                "byEvents": False, "base64": True, "events": ["MESSAGES_UPSERT"],
                "headers": {"x-webhook-token": os.environ["EVOLUTION_WEBHOOK_TOKEN"]}},
}))
EOF
)" >/dev/null
  fi

  # O webhook segue a porta da API desta execução.
  evo POST "/webhook/set/$INSTANCIA" "$(python3 - "$PORTA_API" "$API_HOST" <<'EOF'
import json, os, sys
print(json.dumps({"webhook": {
    "enabled": True, "url": f"http://{sys.argv[2]}:{sys.argv[1]}/whatsapp/webhook",
    "byEvents": False, "base64": True, "events": ["MESSAGES_UPSERT"],
    "headers": {"x-webhook-token": os.environ["EVOLUTION_WEBHOOK_TOKEN"]}}}))
EOF
)" >/dev/null

  pareado() { evo GET "/instance/connectionState/$INSTANCIA" | grep -q '"open"'; }
  if pareado; then
    info "WhatsApp já pareado."
  else
    info "Pareie o celular: WhatsApp > Aparelhos conectados > Conectar um aparelho"
    for tentativa in $(seq 1 8); do
      codigo="$(evo GET "/instance/connect/$INSTANCIA" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("code",""))' 2>/dev/null || true)"
      if [[ -n "$codigo" ]]; then
        clear
        echo "QR $tentativa/8 (renova a cada 30 s). Escaneie no celular:"
        uvx -q --from 'qrcode==8.2' qr --ascii "$codigo"
      fi
      for _ in $(seq 1 15); do pareado && break 2; sleep 2; done
    done
    if pareado; then info "WhatsApp pareado."; else aviso "Não pareou. Rode ./dev.sh de novo para outro QR. Seguindo sem o WhatsApp."; fi
  fi
  export EVOLUTION_URL="http://127.0.0.1:8080" EVOLUTION_INSTANCIA="$INSTANCIA"
  WHATSAPP_NUMERO="$(evo GET "/instance/fetchInstances?instanceName=$INSTANCIA" | python3 -c '
import sys, json
d = json.load(sys.stdin); d = d[0] if isinstance(d, list) and d else d
print("".join(c for c in str((d or {}).get("ownerJid") or "").split("@")[0] if c.isdigit()))' 2>/dev/null || true)"
  export WHATSAPP_NUMERO
  [[ -n "$WHATSAPP_NUMERO" ]] && info "Convites vão com o link wa.me do número pareado (${WHATSAPP_NUMERO:0:5}****${WHATSAPP_NUMERO: -4})."
fi

# Modelo e voz: com a chave da Featherless, o agente pensa com o modelo e fala em voz real.
if [[ -n "${FEATHERLESS_API_KEY:-}" ]]; then
  # Qwen3-30B-A3B: ~5 s por chamada contra ~26 s do GLM-5.2; a vaga chega aos convites em ~1 min.
  export MODELO_PADRAO="${MODELO_PADRAO:-Qwen/Qwen3-30B-A3B-Instruct-2507}"
  export AGENTE_COM_MODELO="${AGENTE_COM_MODELO:-1}" VOZ_REAL="${VOZ_REAL:-1}"
  info "Modelo $MODELO_PADRAO ligado e voz real (VOZ_REAL=$VOZ_REAL)."
else
  aviso "Sem FEATHERLESS_API_KEY: o agente roda sem modelo e sem voz real."
fi

# API do agente (libera o CORS para a porta do painel desta execução)
export ORIGENS_PAINEL="${ORIGENS_PAINEL:-http://localhost:$PORTA_WEB,http://127.0.0.1:$PORTA_WEB}"
info "Subindo a API em http://$API_HOST:$PORTA_API (log em .dev/api.log)"
RECARREGAR=(); [[ "${DEV_RELOAD:-0}" == 1 ]] && RECARREGAR=(--reload)  # recarregar apaga as conversas em memória
.venv/bin/uvicorn backend.agente.api:app --host "$API_HOST" --port "$PORTA_API" "${RECARREGAR[@]}" \
  > "$LOGS/api.log" 2>&1 &
PIDS+=($!)
esperar_http "http://$API_HOST:$PORTA_API/docs" 30 || { aviso "A API não subiu. Veja .dev/api.log"; tail -20 "$LOGS/api.log"; exit 1; }

# Painel web
# Instala também quando a main trouxe dependência nova (package.json ou lockfile mais novos).
if [[ ! -f web/node_modules/.modules.yaml || web/package.json -nt web/node_modules/.modules.yaml \
      || web/pnpm-lock.yaml -nt web/node_modules/.modules.yaml ]]; then
  info "Instalando as dependências do painel (pnpm install)…"
  (cd web && pnpm install --frozen-lockfile && touch node_modules/.modules.yaml)
fi
info "Subindo o painel em http://localhost:$PORTA_WEB (log em .dev/web.log)"
(cd web && NEXT_PUBLIC_API_URL="http://$API_HOST:$PORTA_API" pnpm dev --port "$PORTA_WEB") \
  > "$LOGS/web.log" 2>&1 &
PIDS+=($!)
esperar_http "http://127.0.0.1:$PORTA_WEB" 60 || { aviso "O painel não subiu. Veja .dev/web.log"; tail -20 "$LOGS/web.log"; exit 1; }

echo
info "Pronto:"
echo "   Painel     http://localhost:$PORTA_WEB"
echo "   API        http://$API_HOST:$PORTA_API/docs"
[[ $COM_ZAP == 1 ]] && echo "   Evolution  http://localhost:8080/manager   (instância $INSTANCIA)"
echo "   Ctrl+C para parar. Logs em .dev/"
wait
