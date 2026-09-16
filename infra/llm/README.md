# llm service (Phase 3) — containerized llama.cpp

Image: `ghcr.io/ggml-org/llama.cpp:server-cuda` (no local Dockerfile needed).
Model files live in the `samvaad_llm_models` volume (`/models`, read-only).

## First-time model setup (prod VM + this dev machine)

```bash
# 1. Create the volume (compose does this automatically on first up)
docker volume create samvaad_llm_models

# 2. Download the GGUF into the volume (example: Gemma-4-E4B Q5_K_M)
docker run --rm -v samvaad_llm_models:/models \
  curlimages/curl:latest \
  -L -o /models/gemma-4-E4B-it-Q5_K_M.gguf \
  https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q5_K_M.gguf

# 3. Set in /etc/samvaad/.env.prod
LLAMACPP_MODEL_FILE=gemma-4-E4B-it-Q5_K_M.gguf
```

## VRAM tuning

`LLAMACPP_N_GPU_LAYERS` controls GPU offload:

| Machine | VRAM | Suggested value |
|---|---|---|
| Prod VM (L4 24GB) | 24GB | `99` (full offload, default) |
| This dev laptop (RTX 3050 4GB) | 4GB | `15-20` (partial; rest stays on CPU, slower) |
| CPU-only fallback | — | `0` |

`start.sh` used `--n-gpu-layers 20 --ctx-size 8192 --threads 8`; the compose
service defaults match that except `N_GPU_LAYERS` defaults to 99 for prod.
Set `LLAMACPP_CTX_SIZE` / `LLAMACPP_THREADS` in `.env.prod` to override.

## Healthcheck

`GET http://llm:8000/health` (same endpoint `start.sh` polls). Backend waits
for `llm healthy` before starting (`depends_on`). Model load can take minutes
on first boot — `start_period: 120s` covers it.
