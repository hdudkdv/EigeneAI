# EigeneAI

Lokaler Familien-/Freundes-Chat auf einer **Ubuntu-22.04-Appliance** mit **AMD Instinct MI50 (32 GB, gfx906)**.  
Inference bleibt im LAN — **kein** öffentliches Expose, **kein** Cloud-LLM.

| Baustein | Wahl |
|----------|------|
| Client | Deutsche **Web-Chat-PWA** (Safari/Android), gehostet auf der Appliance |
| Auth | **Bearer-Token pro Account**, Invite, isolierte Historie, Revoke |
| Inference | **llama.cpp (HIP/ROCm)** + schlankes OpenAI-Gateway |
| ROCm | **6.3.3** gepinnt — niemals auto-upgraden |
| Default-Modell | **Qwen2.5-14B-Instruct GGUF Q5_K_M** (Gewichte **nicht** im Git) |

```
Browser/PWA  --HTTPS+Token (LAN)-->  nginx  -->  Gateway  -->  llama.cpp (HIP)
                                      |              |
                                   Web-UI      Accounts/Queue/Historie
```

## Hardware

- CPU: x86_64 (Intel/AMD)
- GPU: **1× Instinct MI50**, **32 GB** HBM2 (`gfx906`) — MVP
- Soft-Reserve: `GPU_COUNT` in der Config für später 2+ GPUs (Phase 2)
- Netz: LAN; selbstsigniertes HTTPS; VPN später

## Repository-Struktur

```
appliance/   Install-/First-Boot-Skripte, systemd, ROCm-Pin, ISO-Hinweise
gateway/     FastAPI-Gateway (OpenAI-kompatibel + Admin + Chat-API)
web/         Deutsche PWA (Token-Login, Streaming, Modellstatus)
```

## Installationspfad (USB → Appliance)

1. Ubuntu **22.04** Server von USB installieren (siehe `appliance/iso/README.md`).
2. Dieses Repo nach `/opt/eigeneai-src` klonen oder kopieren.
3. ROCm **6.3.3** installieren und **neustarten**:

   ```bash
   sudo ./appliance/scripts/create-eigeneai-user.sh
   sudo ./appliance/scripts/install-rocm-6.3.3.sh
   sudo reboot
   ```

4. llama.cpp HIP bauen und Gateway/Web installieren:

   ```bash
   sudo ./appliance/scripts/build-llama-cpp-hip.sh
   sudo ./appliance/scripts/install-gateway.sh
   sudo ./appliance/first-boot/wizard.sh
   ```

5. Dienste starten:

   ```bash
   sudo systemctl enable --now eigeneai-llama eigeneai-gateway nginx
   ```

6. Im LAN öffnen: `https://<ip-oder-eigeneai.local>/`  
   Selbstsigniertes Zertifikat einmal im Browser akzeptieren.  
   Invite-Code steht nach First-Boot in `/var/lib/ai/gateway/first-invite.txt`.

**Firewall:** nur SSH + HTTPS (443). Inference-Port `8081` bleibt auf localhost.

## Modell hinzufügen

Gewichte gehören **nicht** ins Git. Default-Datei:

```text
/var/lib/ai/models/Qwen2.5-14B-Instruct-Q5_K_M.gguf
```

Anleitung: [`appliance/scripts/download-model.md`](appliance/scripts/download-model.md)  
Danach: `sudo systemctl restart eigeneai-llama`

## Accounts einladen / widerrufen

Admin-Secret: `/etc/eigeneai/eigeneai.env` → `EIGENEAI_ADMIN_SECRET`  
(oder Ausgabe vom First-Boot).

```bash
# Invite erzeugen
curl -s -X POST https://eigeneai.local/admin/invites \
  -H "X-Admin-Secret: $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"label":"Alex"}'

# Accounts listen
curl -s https://eigeneai.local/admin/accounts \
  -H "X-Admin-Secret: $ADMIN"

# Token widerrufen
curl -s -X POST https://eigeneai.local/admin/accounts/<account_id>/revoke \
  -H "X-Admin-Secret: $ADMIN"
```

Nutzer öffnen die PWA → Reiter **Einladung** → Code + Name → erhalten ihr **eigenes Token** (isolierte Chats).

## Entwicklung ohne MI50 (Smoke)

```bash
# Gateway-Tests (Mock-Inference)
cd gateway
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
MOCK_INFERENCE=1 pytest -q

# Web bauen
cd ../web && npm ci && npm run build

# Gateway lokal mit Mock + UI
export MOCK_INFERENCE=1
export EIGENEAI_ADMIN_SECRET=dev-admin
export WEB_DIST=$PWD/../web/dist
export EIGENEAI_DATA_DIR=/tmp/eigeneai-data
cd ../gateway && python -m app
```

## Was braucht echte Hardware?

| Thema | Ohne MI50 (CI/Smoke) | Mit MI50 |
|-------|----------------------|----------|
| Invite / Token / Revoke | ✅ | ✅ |
| Isolierte Chat-Historie | ✅ | ✅ |
| Queue-Hinweis / API | ✅ (Mock) | ✅ |
| PWA Login + Streaming-UI | ✅ gegen Mock | ✅ |
| ROCm 6.3.3 / gfx906 | Skripte nur | **Validieren** |
| llama.cpp HIP + 14B Q5 | Build-Skript nur | **VRAM/Tokens messen** |
| Selbstsigniertes LAN-HTTPS | nginx-Config | Endgeräte-Test |

## Hinweise

- ROCm-Pin-Doku: [`appliance/ROCM-PIN.md`](appliance/ROCM-PIN.md)
- Concurrent Chats teilen sich **eine** GPU-Warteschlange (`GPU_COUNT=1`).
- Phase 2: WireGuard/VPN, 2+ GPUs, optionale Android-APK.
