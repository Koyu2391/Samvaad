"""
Celery application — used for background document ingestion.
Allows users to keep chatting while new documents are being processed.

To run the worker:
    cd backend && celery -A tasks.celery_app worker --loglevel=info
"""
import os
import sys

# Ensure the backend directory is on sys.path so worker subprocesses
# can import `core.*`, `models.*`, `database`, etc.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from celery import Celery
from config import REDIS_URL


celery_app = Celery(
    "samvaad_rag",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.ingest"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Allow long-running ingestion jobs (up to 30 min)
    task_time_limit=1800,
    task_soft_time_limit=1500,
)


# Synchronous-fallback mode for when Redis is not running.
# When CELERY_TASK_ALWAYS_EAGER=true, .delay() executes inline (in-process),
# useful for local dev without a Redis container.
if os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true":
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    print("[celery] Running in eager (synchronous) mode — no Redis required")
