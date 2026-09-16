#!/usr/bin/env bash
# Samvaad Financial RAG — start all services in the right order.
set -e

ROOT="/Users/k/Downloads/Samvaad_Final_APP"
LLAMA_MODEL_HF="unsloth/gemma-4-E4B-it-GGUF"
LLAMA_MODEL_FILE="gemma-4-E4B-it-Q5_K_M.gguf"

source /opt/anaconda3/etc/profile.d/conda.sh
conda activate fin_env

cd "$ROOT"
mkdir -p logs

cleanup_port() {
    local port=$1
    lsof -ti:$port | xargs kill -9 2>/dev/null || true
}

echo "════════════════════════════════════════════════════════"
echo "  Starting Samvaad Financial RAG"
echo "════════════════════════════════════════════════════════"

# 1. Redis ───────────────────────────────────────────────────
if ! redis-cli ping >/dev/null 2>&1; then
    echo "[1/5] Starting Redis…"
    redis-server --daemonize yes
    sleep 1
fi
echo "      Redis ✓  ($(redis-cli ping))"

# 2. llama.cpp server ────────────────────────────────────────
if ! curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null | grep -q "200"; then
    echo "[2/5] Starting llama.cpp server on :8000…"
    cleanup_port 8000
    nohup llama-server -hf "$LLAMA_MODEL_HF" \
        -hff "$LLAMA_MODEL_FILE" \
        --host 127.0.0.1 \
        --port 8000 \
        --n-gpu-layers 20 \
        --ctx-size 8192 \
        --threads 8 \
        --chat-template-kwargs '{"enable_thinking":false}' \
        > "$ROOT/logs/llama.log" 2>&1 &
    echo "      llama.cpp PID=$!"
    printf "      Waiting for model to load"
    until curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null | grep -q "200"; do
        sleep 2
        printf "."
    done
    echo ""
fi
echo "      llama.cpp ✓  (Gemma-4-E4B)"

# 3. Celery worker ───────────────────────────────────────────
echo "[3/5] Starting Celery worker (solo pool)…"
pkill -f "celery.*samvaad_rag.*worker" 2>/dev/null || true
sleep 1
cd "$ROOT/backend"
export PYTHONPATH="$ROOT/backend:$PYTHONPATH"
nohup celery -A tasks.celery_app worker --loglevel=info --pool=solo \
    > "$ROOT/logs/celery.log" 2>&1 &
echo "      Celery PID=$!"
sleep 5
echo "      Celery ✓"

# 4. FastAPI backend ─────────────────────────────────────────
echo "[4/5] Starting FastAPI backend on :8002…"
cleanup_port 8002
USE_SQLITE_FALLBACK=true nohup python main.py > "$ROOT/logs/backend.log" 2>&1 &
echo "      Backend PID=$!"
until curl -s http://localhost:8002/api/health >/dev/null 2>&1; do
    sleep 1
done
echo "      Backend ✓"

# 5. Build frontend ──────────────────────────────────────────
echo "[5/6] Building frontend for production…"
cd "$ROOT/frontend"
npm run build > "$ROOT/logs/frontend-build.log" 2>&1
echo "      Build ✓"

# 6. NGINX reverse proxy ─────────────────────────────────────
echo "[6/6] Starting NGINX reverse proxy on :80…"
brew services start nginx >/dev/null 2>&1
sleep 1
echo "      NGINX ✓"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✓  All services running"
echo "════════════════════════════════════════════════════════"
echo "  → Open  http://localhost"
echo ""
echo "  Logs:"
echo "    tail -f $ROOT/logs/llama.log"
echo "    tail -f $ROOT/logs/celery.log"
echo "    tail -f $ROOT/logs/backend.log"
echo "    tail -f $ROOT/logs/frontend-build.log"
echo "    tail -f $ROOT/logs/nginx-*.log"
echo ""
echo "  Stop everything:  ./stop.sh"
echo "════════════════════════════════════════════════════════"
