#!/usr/bin/env bash
# Installiert ROCm 6.3.3 auf Ubuntu 22.04 und pinnt gegen Auto-Upgrades.
set -euo pipefail

ROCM_VERSION="6.3.3"
UBUNTU_CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"

if [[ "${UBUNTU_CODENAME}" != "jammy" ]]; then
  echo "WARNUNG: Dieses Skript ist für Ubuntu 22.04 (jammy) vorgesehen (gefunden: ${UBUNTU_CODENAME})." >&2
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> ROCm ${ROCM_VERSION} Repository einrichten"
mkdir -p /etc/apt/keyrings
curl -fsSL "https://repo.radeon.com/rocm/rocm.gpg.key" \
  | gpg --dearmor -o /etc/apt/keyrings/rocm.gpg

cat >/etc/apt/sources.list.d/rocm.list <<EOF
deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/${ROCM_VERSION} jammy main
EOF

# Hartes Pinning — nie „latest“ nachziehen
cat >/etc/apt/preferences.d/rocm-pin-600 <<'EOF'
Package: *
Pin: release o=repo.radeon.com
Pin-Priority: 600
EOF

# Unattended upgrades: ROCm/AMDGPU ausschließen
mkdir -p /etc/apt/apt.conf.d
cat >/etc/apt/apt.conf.d/99eigeneai-rocm-no-auto-upgrade <<'EOF'
// EigeneAI: ROCm 6.3.3 bleibt gepinnt — kein Auto-Upgrade
Unattended-Upgrade::Package-Blacklist {
  "rocm*";
  "amdgpu*";
  "hip*";
  "hsa*";
  "miopen*";
  "rccl*";
};
EOF

apt-get update
apt-get install -y "rocm-hip-sdk=${ROCM_VERSION}.*" || apt-get install -y rocm-hip-sdk

# PATH für HIP
cat >/etc/profile.d/eigeneai-rocm.sh <<'EOF'
export PATH="/opt/rocm/bin:${PATH}"
export LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH:-}"
# Instinct MI50 = gfx906
export HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-9.0.6}"
EOF

echo "==> ROCm ${ROCM_VERSION} installiert. Bitte NEU STARTEN, dann: rocminfo | grep gfx906"
echo "    Niemals apt upgrade ohne Pin-Prüfung auf ROCm-Pakete ausführen."
