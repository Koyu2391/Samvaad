# Samvaad PROD deploy runbook (single GPU VM, Compose)

## 0. One-time VM prep

- GPU VM: 16 vCPU / 32GB RAM / 200GB SSD / 1× L4 24GB (or A10 24GB).
  This 4GB laptop GPU cannot serve the full E4B model — use `LLAMACPP_N_GPU_LAYERS=15`
  here only for smoke tests.
- Install Docker Engine + NVIDIA Container Toolkit; verify `docker run --rm --gpus all nvidia/cuda:12.3-base nvidia-smi`.
- Open firewall: 80/443 (and 22). Nothing else public.
- DNS: point your domain at the VM.

## 1. Secrets + model + certs (on the VM)

```bash
sudo mkdir -p /etc/samvaad && sudo chmod 700 /etc/samvaad
cp .env.prod.example /etc/samvaad/.env.prod && sudo chmod 600 /etc/samvaad/.env.prod
# Edit: POSTGRES_PASSWORD, DATABASE_URL, JWT_SECRET_KEY (openssl rand -hex 32),
# CORS_ORIGINS, TLS_DOMAIN, LLAMACPP_* (see infra/llm/README.md)

# GGUF model into the named volume (see infra/llm/README.md for URL)
docker volume create samvaad_llm_models
docker run --rm -v samvaad_llm_models:/models curlimages/curl:latest \
  -L -o /models/gemma-4-E4B-it-Q5_K_M.gguf \
  https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q5_K_M.gguf

# TLS (certbot standalone; port 80 must be free)
sudo certbot certonly --standalone -d <TLS_DOMAIN>
# Renewals: certbot renew --deploy-hook "docker restart samvaad_frontend"
```

## 2. Deploy

```bash
docker compose --env-file /etc/samvaad/.env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose --env-file /etc/samvaad/.env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml ps
```

Watch the LLM warm up (minutes on first boot):
`docker logs -f samvaad_llm` until `/health` is healthy.

## 3. Smoke tests

```bash
curl -k https://<TLS_DOMAIN>/api/health        # {"status":"ok",...}
curl -I http://<TLS_DOMAIN>/                    # 301 → https
# Login via UI, upload a PDF (<50MB ok, >50MB must 413),
# chat (answer + sources), delete conversation.
# Burst login (>5/min from one IP) must 429.
```

## 4. Backups

- `samvaad_pgbackup` dumps nightly to the `samvaad_pg_backups` volume
  (keeps 7). Copy off-VM: `docker run --rm -v samvaad_pg_backups:/b
  -v /srv/offsite:/o alpine cp /b/<latest>.dump /o/`.
- Uploads/convs live in named volumes (`backend_uploads`, `backend_convs`);
  snapshot them with the same off-VM job.
- Restore: `pg_restore -h postgres -U rag_user -d rag_financial -c <file>.dump`.

## 5. Rollback

```bash
# Previous images are kept locally; re-run up with the prior git SHA:
git rev-parse --short HEAD   # record before every deploy
git checkout <prior-sha> -- docker-compose.prod.yml nginx/ frontend/Dockerfile
docker compose --env-file /etc/samvaad/.env.prod \
  -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 6. What Phase 4 changed (for reviewers)

- `nginx.prod.conf`: TLS 1.2/1.3 + cipher suite + HSTS, `Strict-Transport-Security`,
  80→443 redirect, login/chat/upload rate limits, 50MB upload cap aligned
  with `MAX_UPLOAD_SIZE_MB`.
- `nginx/prod-05-domain.sh`: renders `TLS_DOMAIN` into the conf at boot,
  fails fast without certs (runs in `/docker-entrypoint.d`).
- `docker-compose.prod.yml`: `TLS_DOMAIN` (replaces dead `VITE_API_URL` —
  frontend uses same-origin `/api`), frontend healthcheck, `pgbackup`
  sidecar + `pg_backups` volume, `json-file` log rotation on all services.
- `frontend/Dockerfile`: `EXPOSE 80 443`.
