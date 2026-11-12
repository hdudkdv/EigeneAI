#!/usr/bin/env bash
set -euo pipefail
id eigeneai >/dev/null 2>&1 || useradd --system --home /var/lib/ai --shell /usr/sbin/nologin eigeneai
mkdir -p /var/lib/ai /opt/eigeneai
chown -R eigeneai:eigeneai /var/lib/ai
