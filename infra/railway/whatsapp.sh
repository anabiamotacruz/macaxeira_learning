#!/usr/bin/env bash
# Configura o WhatsApp da Evolution na Railway: cria a instância, aponta o webhook para a API
# pela rede privada e mostra o QR para parear. Rode uma vez, da sua máquina, depois do deploy.
#
#   EVOLUTION_PUBLICA=https://evolution-production-xxxx.up.railway.app \
#   EVOLUTION_API_KEY=... EVOLUTION_WEBHOOK_TOKEN=... ./infra/railway/whatsapp.sh
#
# Opcionais: EVOLUTION_INSTANCIA (padrão macaxeira) e WEBHOOK_URL
# (padrão http://api.railway.internal:8000/whatsapp/webhook). Nenhum segredo é impresso.
set -euo pipefail

: "${EVOLUTION_PUBLICA:?defina EVOLUTION_PUBLICA (domínio público da Evolution)}"
: "${EVOLUTION_API_KEY:?defina EVOLUTION_API_KEY}"
: "${EVOLUTION_WEBHOOK_TOKEN:?defina EVOLUTION_WEBHOOK_TOKEN}"
INSTANCIA="${EVOLUTION_INSTANCIA:-macaxeira}"
WEBHOOK_URL="${WEBHOOK_URL:-http://api.railway.internal:8000/whatsapp/webhook}"
BASE="${EVOLUTION_PUBLICA%/}"

evo() {  # método, caminho, [corpo]
  curl -s -m 30 -X "$1" "$BASE$2" -H "apikey: $EVOLUTION_API_KEY" \
    -H 'Content-Type: application/json' ${3:+-d "$3"}
}

webhook="$(python3 - "$WEBHOOK_URL" <<'EOF'
import json, os, sys
print(json.dumps({"enabled": True, "url": sys.argv[1], "byEvents": False, "base64": True,
                  "events": ["MESSAGES_UPSERT"],
                  "headers": {"x-webhook-token": os.environ["EVOLUTION_WEBHOOK_TOKEN"]}}))
EOF
)"

if ! evo GET "/instance/connectionState/$INSTANCIA" | grep -q '"instance"'; then
  echo "› Criando a instância $INSTANCIA"
  evo POST /instance/create "$(python3 - "$INSTANCIA" "$webhook" <<'EOF'
import json, sys
print(json.dumps({"instanceName": sys.argv[1], "integration": "WHATSAPP-BAILEYS",
                  "qrcode": True, "webhook": json.loads(sys.argv[2])}))
EOF
)" >/dev/null
fi
echo "› Webhook → $WEBHOOK_URL"
evo POST "/webhook/set/$INSTANCIA" "{\"webhook\": $webhook}" >/dev/null

pareado() { evo GET "/instance/connectionState/$INSTANCIA" | grep -q '"open"'; }
if pareado; then echo "› WhatsApp já pareado."; exit 0; fi

echo "› Pareie o celular: WhatsApp > Aparelhos conectados > Conectar um aparelho"
echo "  (ou abra $BASE/manager e use o QR de lá)"
for tentativa in $(seq 1 8); do
  codigo="$(evo GET "/instance/connect/$INSTANCIA" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("code",""))' 2>/dev/null || true)"
  if [[ -n "$codigo" ]]; then
    echo "QR $tentativa/8 (renova a cada 30 s):"
    uvx -q --from 'qrcode==8.2' qr --ascii "$codigo"
  fi
  for _ in $(seq 1 15); do pareado && { echo "› WhatsApp pareado."; exit 0; }; sleep 2; done
done
echo "! Não pareou. Rode de novo para outro QR." >&2
exit 1
