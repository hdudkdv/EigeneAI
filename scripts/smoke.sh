#!/usr/bin/env bash
# Lokaler Smoke ohne GPU/MI50
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}/gateway"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -e ".[dev]"
MOCK_INFERENCE=1 EIGENEAI_ADMIN_SECRET=test-admin-secret pytest -q
cd "${ROOT}/web"
if command -v npm >/dev/null 2>&1; then
  npm install
  npm run build
  test -f dist/index.html
fi
echo "Smoke OK (Mock-Inference)."
