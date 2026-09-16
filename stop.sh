#!/usr/bin/env bash
# Samvaad Financial RAG — stop all services.

echo "Stopping Samvaad services…"

# NGINX
brew services stop nginx 2>/dev/null && echo "  ✓ NGINX stopped" || echo "  - NGINX was not running"

# Kill processes by port
lsof -ti:5173 | xargs kill -9 2>/dev/null && echo "  ✓ Frontend (:5173) stopped" || echo "  - Frontend was not running"
lsof -ti:8002 | xargs kill -9 2>/dev/null && echo "  ✓ Backend (:8002) stopped"  || echo "  - Backend was not running"
lsof -ti:8000 | xargs kill -9 2>/dev/null && echo "  ✓ llama.cpp (:8000) stopped" || echo "  - llama.cpp was not running"

# Kill Celery worker
if pkill -f "celery.*samvaad_rag.*worker" 2>/dev/null; then
    echo "  ✓ Celery worker stopped"
else
    echo "  - Celery worker was not running"
fi

# Optional: stop Redis
# Comment out the next two lines if you want Redis to stay running
if redis-cli ping >/dev/null 2>&1; then
    redis-cli shutdown nosave 2>/dev/null && echo "  ✓ Redis stopped" || echo "  - Could not stop Redis"
fi

echo "Done."
