#!/usr/bin/env bash
# Installiert Gateway + Web-UI auf die Appliance.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${VENV:-/opt/eigeneai/venv}"
DATA="${DATA:-/var/lib/ai}"

apt-get update
apt-get install -y python3 python3-venv python3-pip nginx openssl

"${ROOT}/appliance/scripts/create-eigeneai-user.sh"

python3 -m venv "${VENV}"
"${VENV}/bin/pip" install -U pip
"${VENV}/bin/pip" install -e "${ROOT}/gateway[dev]"

# Gateway-Code an fester Stelle für systemd WorkingDirectory
mkdir -p /opt/eigeneai/app
rsync -a --delete "${ROOT}/gateway/" /opt/eigeneai/app/gateway/
# First-boot + appliance scripts
mkdir -p /opt/eigeneai/appliance
rsync -a "${ROOT}/appliance/" /opt/eigeneai/appliance/
chmod +x /opt/eigeneai/appliance/scripts/*.sh /opt/eigeneai/appliance/first-boot/wizard.sh

# Web build (Node optional; fertiges dist kann vorab liegen)
if [[ -f "${ROOT}/web/package.json" ]]; then
  if command -v npm >/dev/null 2>&1; then
    (cd "${ROOT}/web" && npm install && npm run build)
  elif [[ ! -f "${ROOT}/web/dist/index.html" ]]; then
    echo "WARNUNG: npm fehlt und web/dist ist leer — UI später bauen." >&2
  fi
fi

mkdir -p "${DATA}/models" "${DATA}/gateway" "${DATA}/web" /etc/eigeneai /etc/eigeneai/ssl
chown -R eigeneai:eigeneai "${DATA}"
if [[ -d "${ROOT}/web/dist" ]]; then
  rsync -a --delete "${ROOT}/web/dist/" "${DATA}/web/"
fi

if [[ ! -f /etc/eigeneai/eigeneai.env ]]; then
  cp "${ROOT}/appliance/config/eigeneai.env.example" /etc/eigeneai/eigeneai.env
  chmod 600 /etc/eigeneai/eigeneai.env
fi

# Systemd units
install -m 644 "${ROOT}/appliance/systemd/eigeneai-llama.service" /etc/systemd/system/
install -m 644 "${ROOT}/appliance/systemd/eigeneai-gateway.service" /etc/systemd/system/
install -m 644 "${ROOT}/appliance/systemd/eigeneai-firstboot.service" /etc/systemd/system/
systemctl daemon-reload

# Nginx TLS reverse proxy (self-signed for LAN MVP)
if [[ ! -f /etc/eigeneai/ssl/cert.pem ]]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout /etc/eigeneai/ssl/key.pem \
    -out /etc/eigeneai/ssl/cert.pem \
    -subj "/CN=eigeneai.local/O=EigeneAI/OU=LAN"
fi

install -m 644 "${ROOT}/appliance/config/nginx-eigeneai.conf" /etc/nginx/sites-available/eigeneai
ln -sfn /etc/nginx/sites-available/eigeneai /etc/nginx/sites-enabled/eigeneai
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx

systemctl enable eigeneai-llama.service eigeneai-gateway.service eigeneai-firstboot.service

echo "==> Gateway installiert. First-Boot: systemctl start eigeneai-firstboot (oder Reboot)."
echo "    Modell nach ${DATA}/models/ legen — siehe README."
