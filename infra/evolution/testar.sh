#!/usr/bin/env bash
# Testes rápidos do WhatsApp pela Evolution, sem a API do agente.
#
#   infra/evolution/testar.sh estado              pareado ou não
#   infra/evolution/testar.sh enviar 5585999990000  manda um texto e um áudio (voz Kokoro) para o número
#   infra/evolution/testar.sh ouvir               mostra as mensagens que chegam (Ctrl+C para sair)
#
# Depois de `ouvir`, rode ./dev.sh de novo: ele devolve o webhook para a API.
set -euo pipefail
PASTA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a; . "$PASTA/.env"; set +a
INSTANCIA="${EVOLUTION_INSTANCIA:-macaxeira}"
EVO="http://127.0.0.1:8080"

evo() { curl -s -m 30 -X "$1" "$EVO$2" -H "apikey: $EVOLUTION_API_KEY" -H 'Content-Type: application/json' ${3:+-d "$3"}; }

case "${1:-}" in
  estado)
    evo GET "/instance/connectionState/$INSTANCIA" | python3 -c '
import sys, json
estado = json.load(sys.stdin).get("instance", {}).get("state", "?")
print({"open": "Pareado e conectado.", "connecting": "Esperando o QR. Rode ./dev.sh.",
       "close": "Desconectado. Rode ./dev.sh para outro QR."}.get(estado, estado))'
    ;;

  enviar)
    numero="${2:?informe o número com DDI e DDD, ex.: 5585999990000}"
    texto="Olá! Teste do agente recrutador pelo WhatsApp. Já já chega um áudio."
    evo POST "/message/sendText/$INSTANCIA" "{\"number\":\"$numero\",\"text\":\"$texto\"}" \
      | python3 -c 'import sys,json; d=json.load(sys.stdin); print("texto:", "enviado" if d.get("key") else d)'
    : "${FEATHERLESS_API_KEY:?defina FEATHERLESS_API_KEY para testar a voz}"
    audio="$(curl -s -m 60 https://api.featherless.ai/v1/audio/speech \
      -H "Authorization: Bearer $FEATHERLESS_API_KEY" -H 'Content-Type: application/json' \
      -d '{"model":"hexgrad/Kokoro-82M","voice":"pf_dora","response_format":"mp3","input":"Olá! Aqui é a voz do agente recrutador. Se você está ouvindo isto, o WhatsApp e a voz estão funcionando."}' \
      | base64 -w0)"
    evo POST "/message/sendWhatsAppAudio/$INSTANCIA" "{\"number\":\"$numero\",\"audio\":\"$audio\"}" \
      | python3 -c 'import sys,json; d=json.load(sys.stdin); print("áudio:", "enviado" if d.get("key") else d)'
    ;;

  ouvir)
    host="$(docker network inspect evolution_default -f '{{(index .IPAM.Config 0).Gateway}}')"
    porta=8090
    while ss -ltn "sport = :$porta" | grep -q LISTEN; do porta=$((porta + 1)); done
    evo POST "/webhook/set/$INSTANCIA" "{\"webhook\":{\"enabled\":true,\"url\":\"http://$host:$porta/\",\"byEvents\":false,\"base64\":false,\"events\":[\"MESSAGES_UPSERT\"]}}" >/dev/null
    echo "Ouvindo na porta $porta. Mande uma mensagem para o número pareado. Ctrl+C para sair."
    python3 - "$host" "$porta" <<'EOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class Ouvinte(BaseHTTPRequestHandler):
    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.send_response(200); self.end_headers()
        dados = corpo.get("data") or {}
        chave = dados.get("key") or {}
        if chave.get("fromMe"):
            return
        numero = (chave.get("remoteJid") or "").split("@")[0]
        mascarado = numero[:5] + "****" + numero[-4:] if len(numero) > 9 else numero
        msg = dados.get("message") or {}
        texto = msg.get("conversation") or (msg.get("extendedTextMessage") or {}).get("text")
        tipo = "texto" if texto else ("áudio" if "audioMessage" in msg else ", ".join(msg) or "?")
        print(f"recebido de {mascarado}: {texto or '[' + tipo + ']'}", flush=True)

    def log_message(self, *args):
        pass

HTTPServer((sys.argv[1], int(sys.argv[2])), Ouvinte).serve_forever()
EOF
    ;;

  *)
    sed -n '2,8p' "$0"
    ;;
esac
