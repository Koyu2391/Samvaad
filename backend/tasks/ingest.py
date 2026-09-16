"""
Background document ingestion task.

Flow:
  1. Parse document via financial_parser (Docling/pdfplumber + OCR)
  2. Chunk for financial RAG
  3. Embed + add to user's existing vectorstore (incremental add)
  4. Update DB document status: processing → indexed (or failed)

The frontend can poll /api/documents/status to see progress without blocking chat.
"""
import os
import sys

# Make sibling packages importable from forked worker subprocesses
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from datetime import datetime
from typing import Optional

from tasks.celery_app import celery_app
from database import SessionLocal
from models.document import Document


@celery_app.task(bind=True, name="ingest_document")
def ingest_document_task(
    self,
    document_id: str,
    file_path: str,
    organization_id: str,
    session_id: str,
) -> dict:
    """
    Ingest a single document into the user's vector index.

    Imports are lazy to avoid loading heavy ML deps when the worker boots.
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return {"status": "failed", "error": "Document record not found"}

        doc.status = "processing"
        db.commit()

        # Lazy imports — keep worker startup fast
        from core.parsing import parse_document, chunk_for_financial_rag
        from core.embeddings import load_embeddings

        # 1. Parse
        parsed = parse_document(file_path, filename=doc.filename)
        if parsed.error:
            doc.status = "failed"
            doc.error_message = parsed.error
            db.commit()
            return {"status": "failed", "error": parsed.error}

        # 2. Chunk
        chunks = chunk_for_financial_rag(parsed)
        if not chunks:
            doc.status = "failed"
            doc.error_message = "No content extracted"
            db.commit()
            return {"status": "failed", "error": "No content"}

        # 3. Add to the user's existing vectorstore (incremental)
        # Note: session-level vectorstore lives in main process memory.
        # In eager mode this works directly. In distributed mode, the worker
        # writes PGVector rows that the API process reads on next chat.
        embeddings = load_embeddings()
        if embeddings is None:
            doc.status = "failed"
            doc.error_message = "Embedding model not available"
            db.commit()
            return {"status": "failed", "error": "Embeddings unavailable"}

        from core.vector_pg import add_chunks as pg_add_chunks

        pg_add_chunks(
            chunks, session_id, None,
            embeddings=embeddings,
            document_id=document_id,
            filename=doc.filename,
        )

        # 4. Mark indexed
        doc.status = "indexed"
        doc.chunks_count = len(chunks)
        doc.indexed_at = datetime.utcnow()
        doc.error_message = None
        db.commit()

        return {
            "status": "indexed",
            "document_id": document_id,
            "chunks": len(chunks),
            "tables": len(parsed.tables),
            "used_ocr": parsed.used_ocr,
            "used_docling": parsed.used_docling,
        }

    except Exception as e:
        try:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc:
                doc.status = "failed"
                doc.error_message = str(e)[:500]
                db.commit()
        except Exception:
            pass
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()


def get_task_status(task_id: str) -> dict:
    """Inspect a Celery task by ID. Returns state + result if ready.
    Gracefully degrades when Redis is unavailable (eager mode)."""
    try:
        result = celery_app.AsyncResult(task_id)
        response: dict = {"task_id": task_id, "state": result.state}
        if result.ready():
            try:
                response["result"] = (
                    result.result if result.successful() else str(result.result)
                )
            except Exception:
                response["result"] = None
        return response
    except Exception as e:
        # Redis unreachable or eager mode without backend — return generic ack
        return {
            "task_id": task_id,
            "state": "UNKNOWN",
            "note": (
                "Result backend unavailable (eager mode or Redis down). "
                "Check document status via /api/documents instead."
            ),
            "error": str(e),
        }
