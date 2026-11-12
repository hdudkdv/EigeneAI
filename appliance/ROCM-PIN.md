# ROCm Pin — Instinct MI50 (gfx906)

| Item | Wert |
|------|------|
| GPU | AMD Instinct **MI50**, **32 GB** HBM2 |
| GFX | **gfx906** |
| Distro | Ubuntu **22.04** LTS |
| ROCm | **6.3.3** (pinned) |
| Ab ROCm 6.4 | MI50 / gfx906 **unsupported** |

## Regeln

1. **Niemals** unattended-upgrades oder `apt upgrade` auf „latest ROCm“ laufen lassen.
2. Apt-Pinning für `rocm*` / `amdgpu*` auf 6.3.3 setzen (siehe `scripts/install-rocm-6.3.3.sh`).
3. Fallback nur nach manuellem Spike: ROCm **5.7.x** — nicht automatisch.
4. `HSA_OVERRIDE_GFX_VERSION=9.0.6` für llama.cpp HIP-Builds setzen, falls nötig.

## Verifikation (auf Hardware)

```bash
rocminfo | grep -E 'gfx906|Marketing Name'
rocm-smi
```

Erwartung: Device mit gfx906 / MI50 sichtbar, Treiber aus dem 6.3.3-Stack.
