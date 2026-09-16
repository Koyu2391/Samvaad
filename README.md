# Samvaad — Multi-User Financial RAG

A fully-local, multi-user RAG system for financial documents with multimodal (image+text) reasoning. Built with llama.cpp, LangGraph, ChromaDB, OpenCLIP, and Gemma 4 vision.

---

## Prerequisites

| Tool | Linux | macOS | Windows |
|------|-------|-------|---------|
| Conda | [Miniconda Linux](https://docs.anaconda.com/miniconda/) | [Miniconda macOS](https://docs.anaconda.com/miniconda/) | [Miniconda Windows](https://docs.anaconda.com/miniconda/) |
| Git | `apt install git` | `brew install git` | [git-scm.com](https://git-scm.com/) |
| Redis | `apt install redis` | `brew install redis` | [Memurai](https://www.memurai.com/) (Windows Redis) |
| llama.cpp | `brew install llama.cpp` or [build from source](https://github.com/ggerganov/llama.cpp) | `brew install llama.cpp` | [Download release](https://github.com/ggerganov/llama.cpp/releases) or WSL |
| NGINX | `apt install nginx` | `brew install nginx` | [nginx.org](https://nginx.org/en/download.html) or skip (see below) |

---

## Setup (one time)

### 1. Clone and create environment

```bash
git clone <repo-url> Samvaad_Final_APP
cd Samvaad_Final_APP

conda create -n fin_env python=3.11 -y
conda activate fin_env
```

### 2. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

> **Windows note**: If Celery install fails, run: `pip install celery[eventlet]`
>
> **Apple Silicon note**: Some torch/CUDA wheels may need `pip install torch --index-url https://download.pytorch.org/whl/cpu`

### 3. Install frontend dependencies

```bash
cd ../frontend
npm install
```

---

## How to run (manual, cross-platform)

Open **4 terminals**.

### Terminal 1 — llama.cpp (LLM server)

```bash
conda activate fin_env
llama-server -hf unsloth/gemma-4-E4B-it-GGUF \
    -hff gemma-4-E4B-it-Q5_K_M.gguf \
    --host 127.0.0.1 --port 8000 \
    --n-gpu-layers 20 --ctx-size 8192 --threads 8 \
    --chat-template-kwargs '{"enable_thinking":false}'
```

> **No GPU?** Set `--n-gpu-layers 0` (CPU-only, slower).
>
> **Windows**: Download the GGUF model file from HuggingFace, use: `llama-server.exe -m gemma-4-E4B-it-Q5_K_M.gguf --host 127.0.0.1 --port 8000`

### Terminal 2 — Redis

```bash
# Linux / macOS
redis-server --daemonize yes

# Windows (Memurai)
memurai.exe
```

### Terminal 3 — Celery worker (background indexing)

```bash
conda activate fin_env
cd backend
export PYTHONPATH=$(pwd):$PYTHONPATH   # Linux/macOS
set PYTHONPATH=%cd%                    # Windows (cmd)

celery -A tasks.celery_app worker --loglevel=info --pool=solo
```

> **Windows**: Use `--pool=eventlet` instead of `--pool=solo` (install `pip install eventlet`).

### Terminal 4 — FastAPI backend

```bash
conda activate fin_env
cd backend
export USE_SQLITE_FALLBACK=true        # Linux/macOS
set USE_SQLITE_FALLBACK=true           # Windows (cmd)
python main.py
```

### Terminal 5 — Frontend

```bash
cd frontend
npm run build    # production build (do once, or after changes)
npx serve dist   # serves at http://localhost:3000
```

Or use the Vite dev server (hot reload):

```bash
npm run dev      # serves at http://localhost:5173
```

---

## How to run (Linux/macOS — one script)

The included `start.sh` handles all services automatically:

```bash
./start.sh
```

> **Windows**: Not supported directly. Use the manual steps above, or run the script via **Git Bash** / **WSL**.

---

## Access the app

| Method | URL |
|--------|-----|
| Frontend (build) | http://localhost:3000 |
| Frontend (dev) | http://localhost:5173 |
| API directly | http://localhost:8002/docs |

Register the first user → becomes admin.

---

## NGINX setup (optional, Linux/macOS)

For a production-like setup with NGINX reverse proxy on port 80:

```bash
# Copy config
sudo cp nginx/nginx.conf /etc/nginx/nginx.conf   # Linux
# or
cp nginx/nginx.conf /opt/homebrew/etc/nginx/     # macOS (brew)

# Build frontend first
cd frontend && npm run build

# Start NGINX
sudo nginx            # Linux
brew services start nginx   # macOS
```

Then access at **http://localhost**.

---

## Default accounts (dev)

| Email | Password | Role |
|-------|----------|------|
| aditya@example.com | test123 | admin |
| sumk@gmail.com | test1234 | analyst |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `redis.exceptions.ConnectionError` | Start Redis: `redis-server --daemonize yes` / start Memurai |
| `No module named 'core'` (Celery) | Set `PYTHONPATH` to the `backend/` directory |
| `Worker exited with SIGSEGV` (macOS) | Use `--pool=solo` |
| `Worker exited with signal` (Windows) | Use `--pool=eventlet` (`pip install eventlet`) |
| llama.cpp slow | Lower `--n-gpu-layers` or add `--threads` |
| `psycopg2.OperationalError` | Ignore — backend uses SQLite automatically |
| PDF charts showing blank | Full-page rendering captures vector charts; re-upload the PDF to regenerate |
