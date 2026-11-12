# Modell hinzufügen (nicht im Git)

**Default:** `Qwen2.5-14B-Instruct` GGUF **Q5_K_M**

Zielpfad auf der Appliance:

```text
/var/lib/ai/models/Qwen2.5-14B-Instruct-Q5_K_M.gguf
```

## Option A — USB nach Install

1. GGUF auf USB-Stick kopieren (exFAT/ext4).
2. Stick mounten, Datei nach `/var/lib/ai/models/` kopieren.
3. `sudo systemctl restart eigeneai-llama`

## Option B — Download auf einem Rechner mit Internet

Beispiel (Hugging Face — Dateiname kann je nach Quant-Repo variieren):

```bash
# Auf einem Hilfsrechner, dann per scp/USB auf die Appliance
huggingface-cli download \
  Qwen/Qwen2.5-14B-Instruct-GGUF \
  qwen2.5-14b-instruct-q5_k_m.gguf \
  --local-dir ./models
```

Dateiname auf der Appliance auf `Qwen2.5-14B-Instruct-Q5_K_M.gguf` vereinheitlichen
(oder `LLAMA_CPP_MODEL` / `DEFAULT_MODEL` in `/etc/eigeneai/eigeneai.env` anpassen).

## Alternativen (laut Plan)

| Stufe | Datei (Beispiel) |
|-------|------------------|
| Konservativ | Qwen2.5-7B-Instruct Q5_K_M |
| Quant-Fallback | Q4_K_M derselben Familie |
| Stretch | Qwen2.5-32B Q4_K_M |

**Wichtig:** Keine `.gguf`-Dateien committen.
