#!/usr/bin/env bash
# Baut llama.cpp mit HIP/ROCm für gfx906 (MI50).
set -euo pipefail

PREFIX="${PREFIX:-/opt/eigeneai/llama.cpp}"
SRC_DIR="${SRC_DIR:-/opt/eigeneai/src/llama.cpp}"
REPO_URL="${REPO_URL:-https://github.com/ggerganov/llama.cpp.git}"
# gfx906 = MI50; bei Bedarf erweitern für Phase-2 Multi-GPU gleicher Familie
OFFLOAD_ARCH="${OFFLOAD_ARCH:-gfx906}"

export HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-9.0.6}"
export PATH="/opt/rocm/bin:${PATH}"

apt-get update
apt-get install -y build-essential cmake git libcurl4-openssl-dev

mkdir -p "$(dirname "${SRC_DIR}")"
if [[ ! -d "${SRC_DIR}/.git" ]]; then
  git clone --depth 1 "${REPO_URL}" "${SRC_DIR}"
else
  git -C "${SRC_DIR}" pull --ff-only || true
fi

cmake -S "${SRC_DIR}" -B "${SRC_DIR}/build" \
  -DGGML_HIP=ON \
  -DAMDGPU_TARGETS="${OFFLOAD_ARCH}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}"

cmake --build "${SRC_DIR}/build" -j"$(nproc)"
cmake --install "${SRC_DIR}/build"

mkdir -p /opt/eigeneai/llama.cpp/build/bin
# Einheitlicher Pfad für systemd
if [[ -x "${SRC_DIR}/build/bin/llama-server" ]]; then
  ln -sfn "${SRC_DIR}/build/bin/llama-server" /opt/eigeneai/llama.cpp/build/bin/llama-server
fi

echo "==> llama-server HIP-Build bereit (AMDGPU_TARGETS=${OFFLOAD_ARCH})"
"${SRC_DIR}/build/bin/llama-server" --version || true
