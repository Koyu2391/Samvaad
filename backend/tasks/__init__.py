"""
Background task package. Sets up sys.path so worker subprocesses can
import sibling packages (core, models, database).
"""
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from tasks.celery_app import celery_app
from tasks.ingest import ingest_document_task, get_task_status

__all__ = ["celery_app", "ingest_document_task", "get_task_status"]
