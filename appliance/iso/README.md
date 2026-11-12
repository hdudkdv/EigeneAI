# ISO / USB-Scaffolding (Ubuntu 22.04 Appliance)

MVP baut auf **Ubuntu 22.04 Server** auf und automatisiert den Rest per Skripten — kein vollständiges Yocto.

## Empfohlener USB-Pfad

1. Offizielles Ubuntu 22.04.x Server ISO auf USB schreiben (`dd`, balenaEtcher, `virt-install`).
2. Minimal installieren (kein Desktop), SSH optional.
3. Repo auf die Maschine klonen oder Release-Tarball kopieren.
4. Als root:

```bash
cd /opt && git clone <dieses-repo> eigeneai-src
cd eigeneai-src
./appliance/scripts/install-rocm-6.3.3.sh
# Reboot
./appliance/scripts/build-llama-cpp-hip.sh
./appliance/scripts/install-gateway.sh
# First-Boot (interaktiv oder via systemd)
./appliance/first-boot/wizard.sh
```

5. Modell-GGUF nach `/var/lib/ai/models/` (siehe `appliance/scripts/download-model.md`).
6. `systemctl enable --now eigeneai-llama eigeneai-gateway nginx`

## Autoinstall-Hook (optional)

`user-data.example` ist eine Cloud-Init-Skizze für unbeaufsichtigte Ubuntu-Server-Installationen.
Das eigentliche ROCm-/Gateway-Image bleibt bewusst schlank (≤ 4–6 GB **ohne** Modelle).

## Phase 2

- PXE
- Fertiges SquashFS/OEM-Image mit vorinstalliertem ROCm 6.3.3
- WireGuard
