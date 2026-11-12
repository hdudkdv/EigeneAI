#!/usr/bin/env bash
# First-Boot Wizard: Hostname, Admin-Secret, erstes Invite, Basis-Netzhinweise.
set -euo pipefail

FLAG=/var/lib/ai/gateway/.firstboot-done
ENV_FILE=/etc/eigeneai/eigeneai.env
mkdir -p /var/lib/ai/gateway /var/lib/ai/models

if [[ -f "${FLAG}" ]]; then
  echo "First-Boot bereits abgeschlossen (${FLAG})."
  exit 0
fi

echo "========================================"
echo "  EigeneAI First-Boot"
echo "========================================"

# Non-interactive defaults when stdin is not a TTY (image bake / CI)
if [[ ! -t 0 ]]; then
  HOSTNAME_NEW="${EIGENEAI_HOSTNAME:-eigeneai}"
  ADMIN_SECRET="${EIGENEAI_ADMIN_SECRET:-$(openssl rand -hex 24)}"
  FIRST_LABEL="${EIGENEAI_FIRST_ACCOUNT:-Familie}"
else
  read -r -p "Hostname [${HOSTNAME:-eigeneai}]: " HOSTNAME_NEW
  HOSTNAME_NEW="${HOSTNAME_NEW:-${HOSTNAME:-eigeneai}}"
  read -r -p "Admin-Secret (leer = zufällig): " ADMIN_SECRET
  ADMIN_SECRET="${ADMIN_SECRET:-$(openssl rand -hex 24)}"
  read -r -p "Label für erstes Invite [Familie]: " FIRST_LABEL
  FIRST_LABEL="${FIRST_LABEL:-Familie}"
fi

hostnamectl set-hostname "${HOSTNAME_NEW}" 2>/dev/null || hostname "${HOSTNAME_NEW}" || true

if [[ -f "${ENV_FILE}" ]]; then
  sed -i "s|^EIGENEAI_ADMIN_SECRET=.*|EIGENEAI_ADMIN_SECRET=${ADMIN_SECRET}|" "${ENV_FILE}"
  sed -i "s|^EIGENEAI_PUBLIC_URL=.*|EIGENEAI_PUBLIC_URL=https://${HOSTNAME_NEW}.local|" "${ENV_FILE}"
else
  mkdir -p /etc/eigeneai
  cat >"${ENV_FILE}" <<EOF
EIGENEAI_HOST=127.0.0.1
EIGENEAI_PORT=8080
EIGENEAI_DATA_DIR=/var/lib/ai/gateway
EIGENEAI_ADMIN_SECRET=${ADMIN_SECRET}
EIGENEAI_PUBLIC_URL=https://${HOSTNAME_NEW}.local
LLAMA_CPP_URL=http://127.0.0.1:8081
MOCK_INFERENCE=0
DEFAULT_MODEL=Qwen2.5-14B-Instruct-Q5_K_M
MODELS_DIR=/var/lib/ai/models
WEB_DIST=/var/lib/ai/web
GPU_COUNT=1
GPU_QUEUE_SIZE=32
LLAMA_CPP_BIN=/opt/eigeneai/llama.cpp/build/bin/llama-server
LLAMA_CPP_MODEL=/var/lib/ai/models/Qwen2.5-14B-Instruct-Q5_K_M.gguf
LLAMA_CPP_HOST=127.0.0.1
LLAMA_CPP_PORT=8081
LLAMA_CPP_CTX=8192
LLAMA_CPP_GPU_LAYERS=999
HSA_OVERRIDE_GFX_VERSION=9.0.6
EOF
  chmod 600 "${ENV_FILE}"
fi

# mDNS friendly name hint
if command -v apt-get >/dev/null 2>&1; then
  apt-get install -y avahi-daemon 2>/dev/null || true
fi

systemctl restart eigeneai-gateway.service 2>/dev/null || true
sleep 2

# Create first invite via admin API (gateway must be up; otherwise write seed file)
INVITE_OUT=/var/lib/ai/gateway/first-invite.txt
if curl -sf -X POST http://127.0.0.1:8080/admin/invites \
  -H "X-Admin-Secret: ${ADMIN_SECRET}" \
  -H "Content-Type: application/json" \
  -d "{\"label\":\"${FIRST_LABEL}\"}" >"${INVITE_OUT}.json" 2>/dev/null; then
  python3 - "${INVITE_OUT}.json" "${INVITE_OUT}" "${ADMIN_SECRET}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write(
    f"Admin-Secret: {sys.argv[3]}\n"
    f"Erstes Invite-Label: {data.get('label')}\n"
    f"Invite-Code: {data.get('code')}\n"
    f"In der Web-UI unter „Einladung“ einlösen.\n"
)
PY
else
  cat >"${INVITE_OUT}" <<EOF
Admin-Secret: ${ADMIN_SECRET}
Gateway war beim First-Boot noch nicht erreichbar.
Später manuell:
  curl -X POST http://127.0.0.1:8080/admin/invites \\
    -H "X-Admin-Secret: ${ADMIN_SECRET}" \\
    -H "Content-Type: application/json" \\
    -d '{"label":"${FIRST_LABEL}"}'
EOF
fi
chmod 600 "${INVITE_OUT}" "${INVITE_OUT}.json" 2>/dev/null || true

# LAN firewall: only SSH + HTTPS
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH || true
  ufw allow 443/tcp || true
  ufw --force enable || true
fi

touch "${FLAG}"
echo "First-Boot fertig. Invite/Admin siehe ${INVITE_OUT}"
echo "Modell-GGUF nach /var/lib/ai/models/ legen, dann: systemctl restart eigeneai-llama"
