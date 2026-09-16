import gc
import os
import re
import uuid
import base64
import shutil
from typing import List, Optional, Tuple

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

from config import (
    CHUNK_SIZE, CHUNK_OVERLAP, DEFAULT_K, MAX_K, K_PER_FILE, IMAGE_TOP_K,
    CORS_ORIGINS, REDIS_URL,
)
from core.cache import (
    cache_conversations, get_cached_conversations, invalidate_conversations,
    cache_status, get_cached_status, invalidate_status,
)
from core.embeddings import load_embeddings
from core.vector_pg import (
    PGVectorRetriever,
    add_chunks as pg_add_chunks,
    count_scope as pg_count_scope,
    delete_scope as pg_delete_scope,
    load_splits as pg_load_splits,
)
from core.llamacpp import LlamaCppServerLLM
from core.reranker import load_reranker
from core.retriever import HybridRetriever
from core.image_embedder import get_embedder
from core.image_store import ImageStore
from utils.pdf_utils import load_pdf_as_markdown
from utils.image_utils import extract_images_from_pdf
from utils.text_utils import tokenize, parse_cot_response, save_conversation

# Re-use prompt templates and helpers from query_engine
from core.query_engine import (
    get_prompt_for_model,
    _format_docs,
    strip_thinking,
)

# Memory system
from core.memory import (
    update_memory,
    format_memory_for_prompt,
    get_memory_summary,
    clear_memory,
)

# ── Auth + Database (Phase 1) ──────────────────────────────────────────────
from database import get_db, init_db, SessionLocal
from models.user import User
from models.document import Document
from models.conversation import Conversation, Message as DBMessage
from core.security import get_current_user
from api.auth import router as auth_router

# ── Phase 2-5: New RAG stack ──────────────────────────────────────────────
from core.parsing import parse_document as financial_parse, chunk_for_financial_rag
from core.graph import run_query as graph_run_query
from core.llm import get_provider as get_llm_provider
from tasks.ingest import ingest_document_task, get_task_status


# ── Phase 5: observability (JSON logs, request IDs, metrics) ──────────────
from core.observability import configure_logging, request_id_middleware
from core import metrics as metrics_mod


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    init_db()
    print("[startup] Database initialized")
    yield


app = FastAPI(
    title="Samvaad Financial RAG API",
    description="Multi-user financial RAG backend",
    lifespan=lifespan,
)

app.add_middleware(BaseHTTPMiddleware, dispatch=request_id_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
PERSIST_DIR_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db_api")
CONVERSATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PERSIST_DIR_BASE, exist_ok=True)
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

CONVS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "convs")
os.makedirs(CONVS_DIR, exist_ok=True)

class SessionState:
    def __init__(self, session_id: str, conv_id: str = None):
        self.session_id = session_id
        self.conv_id = conv_id
        if conv_id:
            self.persist_dir = os.path.join(PERSIST_DIR_BASE, "convs", conv_id)
            self.upload_dir = os.path.join(CONVS_DIR, conv_id)
        else:
            self.persist_dir = os.path.join(PERSIST_DIR_BASE, session_id)
            self.upload_dir = os.path.join(UPLOAD_DIR, session_id)
        os.makedirs(self.upload_dir, exist_ok=True)
        self.bm25 = None
        self.all_splits: list = []
        self.indexed_files: list[str] = []
        self.vectorstore = None
        self.query_engine = None
        self.messages: list[dict] = []
        self.selected_model: str = "default"
        self.use_reranker: bool = True
        self.last_sources: list = []
        self.conversation_file: Optional[str] = None
        # ── LangGraph retrieval components ──────────────────────────────────
        self.retriever = None              # HybridRetriever or vector retriever
        self.reranker_instance = None      # FlashRank/CrossEncoder reranker
        # ── Multimodal image store ──────────────────────────────────────────
        self.image_store: ImageStore = ImageStore()

    def get_chat_history(self, window: int = 6) -> str:
        history = []
        for msg in self.messages[-window:]:
            if msg["role"] == "assistant":
                _, answer = parse_cot_response(msg["content"])
                history.append(f"Assistant: {answer}")
            else:
                history.append(f"User: {msg['content']}")
        return "\n".join(history)

    def reset_chat(self):
        self.messages = []
        self.conversation_file = None

    def release_vectorstore(self):
        """Clear retrieval state (PG vectors live in Postgres, nothing to close)."""
        self.vectorstore = None
        self.bm25 = None
        self.all_splits = []
        self.query_engine = None
        self.image_store.clear()
        gc.collect()


# In-memory session store: session_id -> SessionState
_sessions: dict[str, SessionState] = {}


def get_session(session_id: str, conv_id: str = None) -> SessionState:
    key = session_id if conv_id is None else f"{session_id}_{conv_id}"
    if key not in _sessions:
        _sessions[key] = SessionState(session_id, conv_id)
    return _sessions[key]

class ChatRequest(BaseModel):
    prompt: str
    model: str = "default"
    use_reranker: bool = True
    conversation_id: str = None


class ClearRequest(BaseModel):
    pass  # session derived from auth


class DeleteDocRequest(BaseModel):
    filename: str


def _user_session_id(user: User) -> str:
    """Derive a stable per-user session ID from the authenticated user."""
    return f"user_{user.id}"


def _is_visual_query(prompt: str) -> bool:
    """Detect whether the user is explicitly asking for image/figure/diagram content."""
    query = prompt.lower()
    query = re.sub(r"\bfigure\s+out\b", "", query)

    # Never return image cards for table-focused queries.
    if re.search(r"\btable\b", query):
        return False

    visual_terms = r"(?:image|figure|fig|diagram|digram|chart|graph|visualization|visual)"

    explicit_patterns = [
        rf"\bshow\s+(?:me\s+)?(?:the\s+)?{visual_terms}\b",
        rf"\bdisplay\s+(?:the\s+)?{visual_terms}\b",
        rf"\b{visual_terms}\s+\d+\b",
        r"\bfig\.?\s+\d+\b",
        r"\bvisuali[sz]ation\b",
        r"\b(?:diagram|digram)\b",
        r"\bflowchart\b",
        r"\barchitecture\s+(?:diagram|digram)\b",
        rf"\bwhat\s+(?:does|is)\b[^.?!]{{0,120}}\b{visual_terms}\b",
        rf"\b(?:explain|describe|interpret|analy[sz]e|summari[sz]e)\b[^.?!]{{0,120}}\b{visual_terms}\b",
        rf"\b(?:in|within|from|inside)\s+(?:the\s+)?(?:[\w-]+\s+){{0,8}}?{visual_terms}\b",
    ]

    return any(re.search(pattern, query) for pattern in explicit_patterns)


def _requested_visual_type(prompt: str) -> Optional[str]:
    """Infer whether query prefers a table or a figure/diagram."""
    query = prompt.lower()
    if re.search(r"\btable\b", query):
        return "table"
    if re.search(r"\b(image|figure|fig\.?|diagram|chart|graph|visualization|visual)\b", query):
        return "figure"
    return None


def _source_pages_from_last_sources(sources: list[dict]) -> set[int]:
    """Collect retrieved text pages to bias image selection towards relevant pages."""
    pages: set[int] = set()
    for src in sources:
        page = src.get("page")
        if isinstance(page, int):
            pages.add(page)
    return pages


def _load_existing_index(session: SessionState) -> bool:
    """
    Try to load an existing PGVector index + images from disk.
    Returns True if successful (engine initialized), False if nothing exists.
    """
    if session.conv_id:
        persist_dir = os.path.join(PERSIST_DIR_BASE, "convs", session.conv_id)
    else:
        persist_dir = os.path.join(PERSIST_DIR_BASE, session.session_id)

    try:
        n = pg_count_scope(session.session_id, session.conv_id)
    except Exception as e:
        print(f"[index] PGVector scope check failed: {e}")
        return False
    if n == 0:
        return False

    embed_model = load_embeddings()
    if embed_model is None:
        return False

    try:
        session.release_vectorstore()
        session.persist_dir = persist_dir

        session.vectorstore = PGVectorRetriever(
            session.session_id, session.conv_id, k=DEFAULT_K,
            embeddings=embed_model,
        )

        # List files from upload dir
        supported_exts = (".pdf", ".txt", ".eml", ".md")
        try:
            files = [
                f for f in os.listdir(session.upload_dir)
                if f.lower().endswith(supported_exts)
            ]
        except OSError:
            files = []
        session.indexed_files = files

        # Load all splits from PG (replaces Chroma vectorstore.get())
        try:
            session.all_splits = pg_load_splits(session.session_id, session.conv_id)
            if BM25Okapi is not None and session.all_splits:
                tokenized_corpus = [tokenize(d.page_content) for d in session.all_splits]
                session.bm25 = BM25Okapi(tokenized_corpus)
        except Exception as e:
            print(f"[index] Could not load splits from PGVector: {e}")

        # Rebuild image store from existing images on disk
        _rebuild_image_store_from_disk(session)

        _init_query_engine(session)
        print(f"[index] Loaded existing PG index ({n} chunks, {len(files)} files)")
        return True
    except Exception as e:
        print(f"[index] Failed to load existing index: {e}")
        return False


def _rebuild_image_store_from_disk(session: SessionState) -> None:
    """Rebuild the in-memory image store from existing PNG files on disk."""
    img_dir = os.path.join(session.upload_dir, "images")
    if not os.path.exists(img_dir):
        return

    try:
        embedder = get_embedder()
    except Exception:
        return

    # Only rebuild images for files that still have PDFs on disk
    valid_sources = set()
    for fname in (session.indexed_files or []):
        stem, _ = os.path.splitext(fname)
        valid_sources.add(stem)
    png_files = sorted([f for f in os.listdir(img_dir) if f.endswith(".png")])
    if not png_files:
        return

    from PIL import Image as PILImage
    records: list[dict] = []
    pil_images: list = []

    for fname in png_files:
        path = os.path.join(img_dir, fname)
        base = fname.rsplit(".", 1)[0]
        try:
            pil_img = PILImage.open(path).convert("RGB")
        except Exception as e:
            print(f"[image_store] Skip {fname}: {e}")
            continue

        # Handle two naming formats:
        #   XREF:  {stem}_p{page}_img{idx}.png    e.g. doc_p3_img0.png
        #   Full:  {stem}_page{page}_full.png      e.g. doc_page3_full.png
        if "_page" in base and base.endswith("_full"):
            # Full-page render format
            parts = base.rsplit("_page", 1)
            source_file = parts[0]
            page_str = parts[1].replace("_full", "")
            page = int(page_str) if page_str.isdigit() else 0
            idx = 999
            img_id = base
        else:
            # XREF format: {stem}_p{page}_img{idx}.png
            parts = base.rsplit("_img", 1)
            rest = parts[0] if len(parts) > 1 else base
            page_part = rest.rsplit("_p", 1)
            source_file = page_part[0] if len(page_part) > 1 else base
            idx = int(parts[1]) if len(parts) > 1 else 0
            page = int(page_part[1]) if len(page_part) > 1 else 0
            img_id = base

        # Skip images from deleted files
        if source_file not in valid_sources:
            continue

        pil_images.append(pil_img)
        records.append({
            "img_id":   img_id,
            "filename": source_file,
            "page":     page,
            "type":     "figure",
            "caption":  "",
            "ocr_text": "",
        })

    if not records:
        return

    embeddings = embedder.embed_images(pil_images)
    session.image_store.clear()
    session.image_store.add(records, embeddings)
    print(f"[image_store] Rebuilt from disk: {len(records)} images")


def _build_index(session: SessionState) -> dict:
    """
    Build the full vector + BM25 index for all documents in this session.
    Uses the Phase-2 financial parser (Docling + OCR fallback) and the
    Phase-5 financial chunker. Vectors go to PGVector (scoped by
    session/conv); if rows already exist and the session hasn't been indexed
    before, loads them instead of rebuilding (fast restart path).
    """
    # Try to load existing index first (fast path on restart).
    # Only do this when session.indexed_files is empty (first build).
    if not session.indexed_files and _load_existing_index(session):
        files = session.indexed_files or []
        return {
            "message": f"Loaded existing index ({len(files)} files).",
            "engine_initialized": session.query_engine is not None,
            "files": files,
        }

    supported_exts = (".pdf", ".txt", ".eml", ".md")
    files = [
        f for f in os.listdir(session.upload_dir)
        if f.lower().endswith(supported_exts)
    ]
    if not files:
        return {"message": "No supported documents found.", "engine_initialized": False}

    embed_model = load_embeddings()
    if embed_model is None:
        return {"message": "Embedding model not found.", "engine_initialized": False}

    all_chunks: list = []
    used_ocr_any = False
    used_docling_any = False
    tables_total = 0

    for filename in files:
        file_path = os.path.join(session.upload_dir, filename)
        try:
            parsed = financial_parse(file_path, filename=filename)
            if parsed.error:
                print(f"[index] {filename}: {parsed.error}")
                continue
            chunks = chunk_for_financial_rag(parsed)
            all_chunks.extend(chunks)
            used_ocr_any = used_ocr_any or parsed.used_ocr
            used_docling_any = used_docling_any or parsed.used_docling
            tables_total += len(parsed.tables)
            print(
                f"[index] {filename}: {len(chunks)} chunks, "
                f"{len(parsed.tables)} tables, "
                f"parser={'docling' if parsed.used_docling else 'pdfplumber'}"
                f"{'+ocr' if parsed.used_ocr else ''}"
            )
        except Exception as e:
            print(f"[index] Failed to parse {filename}: {e}")

    if not all_chunks:
        return {"message": "No content extracted.", "engine_initialized": False}

    for doc in all_chunks:
        doc.metadata.setdefault("type", "text")

    # Clear old index for this scope, then insert fresh rows
    session.release_vectorstore()
    if session.conv_id:
        session.persist_dir = os.path.join(PERSIST_DIR_BASE, "convs", session.conv_id)
    else:
        session.persist_dir = os.path.join(PERSIST_DIR_BASE, session.session_id)

    try:
        pg_delete_scope(session.session_id, session.conv_id)
        inserted = pg_add_chunks(
            all_chunks, session.session_id, session.conv_id,
            embeddings=embed_model,
        )
        print(f"[index] PGVector: inserted {inserted} chunks")
    except Exception as e:
        return {"message": f"Vector store write failed: {e}", "engine_initialized": False}

    session.vectorstore = PGVectorRetriever(
        session.session_id, session.conv_id, k=DEFAULT_K,
        embeddings=embed_model,
    )
    session.indexed_files = files
    session.all_splits = all_chunks

    if BM25Okapi is not None:
        tokenized_corpus = [tokenize(doc.page_content) for doc in all_chunks]
        session.bm25 = BM25Okapi(tokenized_corpus)

    # Image indexing (multimodal — PDFs only)
    pdf_only = [f for f in files if f.lower().endswith(".pdf")]
    _build_image_index(session, pdf_only)

    # Build query engine
    _init_query_engine(session)

    return {
        "message": f"Indexed {len(all_chunks)} chunks from {len(files)} files.",
        "engine_initialized": session.query_engine is not None,
        "files": files,
        "chunks": len(all_chunks),
        "tables": tables_total,
        "images_indexed": len(session.image_store),
        "used_ocr": used_ocr_any,
        "used_docling": used_docling_any,
    }


def _build_image_index(session: SessionState, pdf_files: list[str]) -> None:
    """
    Extract images from each PDF and embed them with OpenCLIP.
    Uses TWO methods:
      1. XREF extraction — captures embedded image objects (logos, embedded charts)
      2. Full-page render — renders EVERY page as a PNG (captures vector charts,
         text tables, and anything XREF misses)

    This ensures every page is represented in the image store, so queries like
    "show me page 3" can find the full-page image even when no XREF images exist
    on that page.
    """
    session.image_store.clear()
    try:
        embedder = get_embedder()
    except Exception as e:
        print(f"[image_index] Could not load CLIP embedder: {e}")
        return

    from PIL import Image as PILImage
    import fitz

    for filename in pdf_files:
        file_path = os.path.join(session.upload_dir, filename)
        try:
            # ── Method 1: XREF extraction (embedded image objects) ────────
            records = extract_images_from_pdf(file_path, filename, session.upload_dir)
            if not records:
                records = []

            # ── Method 2: Render EVERY page as a full-page image ──────────
            stem = os.path.splitext(filename)[0]
            img_dir = os.path.join(session.upload_dir, "images")
            os.makedirs(img_dir, exist_ok=True)

            doc = fitz.open(file_path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                img_id = f"{stem}_page{page_num}_full"
                img_path = os.path.join(img_dir, f"{img_id}.png")

                if not os.path.exists(img_path):
                    pix = page.get_pixmap(dpi=100)
                    pix.save(img_path)

                img = PILImage.open(img_path).convert("RGB")
                text = page.get_text()
                from utils.image_utils import extract_ocr_text
                ocr_text = extract_ocr_text(img)

                records.append(
                    {
                        "path": img_path,
                        "filename": filename,
                        "page": page_num,
                        "img_index": 999,
                        "img_id": img_id,
                        "width": img.width,
                        "height": img.height,
                        "ocr_text": ocr_text,
                        "caption": f"Page {page_num}: {text[:300].strip()}",
                        "type": "figure",
                    }
                )
            doc.close()

            if not records:
                print(f"[image_index] No images from {filename}")
                continue

            pil_imgs = []
            valid_records = []
            for rec in records:
                try:
                    pil_imgs.append(PILImage.open(rec["path"]).convert("RGB"))
                    valid_records.append(rec)
                except Exception as ex:
                    print(f"[image_index] Skip {rec['img_id']}: {ex}")

            if not pil_imgs:
                continue

            embeddings = embedder.embed_images(pil_imgs)
            session.image_store.add(valid_records, embeddings)
            xref_count = sum(1 for r in valid_records if "full" not in r["img_id"])
            page_count = sum(1 for r in valid_records if "full" in r["img_id"])
            print(f"[image_index] {filename}: {len(valid_records)} images "
                  f"({xref_count} XREF + {page_count} full-page renders)")
        except Exception as e:
            print(f"[image_index] Failed for {filename}: {e}")
            import traceback
            traceback.print_exc()


def _describe_image(img_path: str) -> str:
    """
    Image captioning is disabled — the active llama.cpp server is text-only
    and cannot process image data.  Returns an empty string so image thumbnails
    are still shown in the frontend without blocking the response.
    """
    return ""


def _init_query_engine(session: SessionState):
    """
    Prepare the retriever + reranker for this session.
    Actual generation goes through the LangGraph pipeline at chat time
    (see _invoke_graph_pipeline). This function only sets up retrieval.
    """
    try:
        num_files = len(session.indexed_files)
        k_value = max(DEFAULT_K, min(K_PER_FILE * max(num_files, 1), MAX_K))

        # PGVector inner retriever (replaces Chroma as_retriever)
        if isinstance(session.vectorstore, PGVectorRetriever):
            session.vectorstore.k = k_value
            vector_retriever = session.vectorstore
        else:
            vector_retriever = PGVectorRetriever(
                session.session_id, session.conv_id, k=k_value,
            )

        reranker = load_reranker() if session.use_reranker else None

        if session.bm25 is not None and session.all_splits:
            retriever = HybridRetriever(
                vector_retriever=vector_retriever,
                bm25=session.bm25,
                all_splits=session.all_splits,
                k=k_value,
                reranker=None,  # rerank in the graph instead of here, to avoid double work
            )
        else:
            retriever = vector_retriever

        # Stash on session for graph invocation
        session.retriever = retriever
        session.reranker_instance = reranker
        session.query_engine = "graph"  # marker indicating engine is ready

    except Exception as e:
        print(f"Failed to init query engine: {e}")
        session.query_engine = None
        session.retriever = None
        session.reranker_instance = None


def _invoke_graph_pipeline(session: SessionState, prompt: str) -> tuple[str, list[dict], str]:
    """Run the LangGraph financial RAG pipeline. Returns (answer, sources, context)."""
    if not getattr(session, "retriever", None):
        return "Please upload and process documents first.", [], ""

    result = graph_run_query(
        query=prompt,
        retriever=session.retriever,
        reranker=session.reranker_instance,
        model_name=session.selected_model,
        chat_history=session.get_chat_history(),
        num_docs=len(session.indexed_files),
        doc_names=", ".join(session.indexed_files) or "No documents",
        user_memory=format_memory_for_prompt(session.session_id),
    )
    return result["answer"], result["sources"], result.get("context", "")


def _save_conversation(session: SessionState):
    """Save the session's conversation to a JSON file."""
    import json
    from datetime import datetime

    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

    if session.conversation_file is None:
        timestamp = session.session_id[:8]
        session.conversation_file = os.path.join(
            CONVERSATIONS_DIR, f"conversation_{timestamp}.json"
        )

    payload = {
        "saved_at": datetime.now().isoformat(),
        "session_id": session.session_id,
        "model": session.selected_model,
        "documents": session.indexed_files,
        "messages": [
            {
                "role": m["role"],
                "content": parse_cot_response(m["content"])[1]
                if m["role"] == "assistant"
                else m["content"],
            }
            for m in session.messages
        ],
    }

    with open(session.conversation_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

@app.get("/api/session/info")
def session_info(user: User = Depends(get_current_user)):
    """Return the session info for the authenticated user."""
    return {
        "session_id": _user_session_id(user),
        "user_id": user.id,
        "email": user.email,
        "organization_id": user.organization_id,
        "role": user.role,
    }


# ── Conversations API ───────────────────────────────────────────────────────


@app.get("/api/conversations")
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List conversations: newest/empty first, older below."""
    # Try Redis cache
    cached = get_cached_conversations(user.id)
    if cached is not None:
        return {"conversations": cached}

    rows = db.query(
        Conversation,
        sa_func.count(DBMessage.id).label("message_count"),
    ).outerjoin(
        DBMessage, DBMessage.conversation_id == Conversation.id,
    ).filter(
        Conversation.user_id == user.id,
    ).group_by(Conversation.id).order_by(
        Conversation.updated_at.desc(),
    ).all()

    convs: list[tuple[Conversation, int]] = []
    for conv, count in rows:
        convs.append((conv, count))

    convs.sort(key=lambda c: (
        0 if c[1] == 0 else 1,
        -(c[0].updated_at or c[0].created_at).timestamp() if c[0].updated_at or c[0].created_at else 0,
    ))
    result = {"conversations": [
        {
            "id": c.id,
            "title": c.title,
            "model_used": c.model_used,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "message_count": count,
        }
        for c, count in convs
    ]}
    cache_conversations(user.id, result["conversations"])
    return result


@app.post("/api/conversations")
def create_conversation(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new empty conversation."""
    conv = Conversation(
        user_id=user.id,
        organization_id=user.organization_id,
        title="New Conversation",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    invalidate_conversations(user.id)
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
    }


@app.put("/api/conversations/{conv_id}")
def update_conversation(
    conv_id: str,
    title: str = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update conversation title."""
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if title:
        conv.title = title
    db.commit()
    invalidate_conversations(user.id)
    invalidate_status(conv_id)
    return {"message": "Conversation updated."}


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(
    conv_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a conversation and all its documents and files."""
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    # Remove uploaded files for this conversation
    conv_upload_dir = os.path.join(CONVS_DIR, conv_id)
    if os.path.exists(conv_upload_dir):
        shutil.rmtree(conv_upload_dir, ignore_errors=True)

    # Remove persist dir (legacy Chroma; harmless if absent)
    conv_persist_dir = os.path.join(PERSIST_DIR_BASE, "convs", conv_id)
    if os.path.exists(conv_persist_dir):
        shutil.rmtree(conv_persist_dir, ignore_errors=True)

    # Remove PGVector rows for this conversation scope
    try:
        pg_delete_scope(_user_session_id(user), conv_id)
    except Exception as e:
        print(f"[index] PGVector conv delete failed (non-fatal): {e}")

    # Clean up in-memory session
    for key in list(_sessions.keys()):
        if conv_id in key:
            session_obj = _sessions[key]
            session_obj.release_vectorstore()
            del _sessions[key]

    db.delete(conv)
    db.commit()
    invalidate_conversations(user.id)
    invalidate_status(conv_id)
    return {"message": "Conversation deleted."}


@app.post("/api/documents/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    conversation_id: str = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload one or more PDFs and rebuild the index for this user."""
    if user.role == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot upload documents.")

    session = get_session(_user_session_id(user), conversation_id)

    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{file.filename} is not a PDF.")
        dest = os.path.join(session.upload_dir, file.filename)
        with open(dest, "wb") as f:
            f.write(await file.read())

        # Track in DB
        size_bytes = os.path.getsize(dest)
        existing = db.query(Document).filter(
            Document.organization_id == user.organization_id,
            Document.filename == file.filename,
            Document.conversation_id == conversation_id,
        ).first()
        if existing:
            existing.status = "processing"
            existing.size_bytes = size_bytes
            existing.storage_path = dest
        else:
            doc = Document(
                organization_id=user.organization_id,
                uploaded_by=user.id,
                conversation_id=conversation_id,
                filename=file.filename,
                size_bytes=size_bytes,
                storage_path=dest,
                status="processing",
            )
            db.add(doc)
    db.commit()

    result = _build_index(session)

    # Mark indexed in DB
    for filename in result.get("files", []):
        doc = db.query(Document).filter(
            Document.organization_id == user.organization_id,
            Document.filename == filename,
            Document.conversation_id == conversation_id,
        ).first()
        if doc:
            from datetime import datetime as _dt
            doc.status = "indexed"
            doc.indexed_at = _dt.utcnow()
    db.commit()

    if conversation_id:
        invalidate_status(conversation_id)
    invalidate_conversations(user.id)

    return result


@app.delete("/api/documents/{filename}")
async def delete_document(
    filename: str,
    conversation_id: str = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a PDF and rebuild the index."""
    if user.role == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot delete documents.")

    session = get_session(_user_session_id(user), conversation_id)
    file_path = os.path.join(session.upload_dir, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"{filename} not found.")

    try:
        os.remove(file_path)
    except PermissionError:
        os.rename(file_path, file_path + ".deleted")

    # Remove from DB
    doc = db.query(Document).filter(
        Document.organization_id == user.organization_id,
        Document.filename == filename,
        Document.conversation_id == conversation_id,
    ).first()
    if doc:
        db.delete(doc)
        db.commit()

    result = _build_index(session)
    if conversation_id:
        invalidate_status(conversation_id)
    invalidate_conversations(user.id)
    return result


@app.get("/api/documents")
def list_documents(
    conversation_id: str = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List documents for the user's organization (scoped to their org)."""
    q = db.query(Document).filter(
        Document.organization_id == user.organization_id
    )
    if conversation_id:
        q = q.filter(Document.conversation_id == conversation_id)
    docs = q.order_by(Document.uploaded_at.desc()).all()

    return {
        "files": [d.filename for d in docs],
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "conversation_id": d.conversation_id,
                "status": d.status,
                "uploaded_by": d.uploaded_by,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                "size_bytes": d.size_bytes,
                "chunks_count": d.chunks_count,
                "error_message": d.error_message,
            }
            for d in docs
        ],
    }


@app.post("/api/documents/upload/async")
async def upload_documents_async(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Concurrent (non-blocking) upload. Returns immediately with task IDs.
    Documents index in the background via Celery — user can keep chatting.

    Frontend polls /api/documents/tasks/{task_id} for status, or
    /api/documents to see status transitions: processing → indexed.
    """
    if user.role == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot upload documents.")

    session = get_session(_user_session_id(user), user.organization_id)
    queued: list[dict] = []

    for file in files:
        if not file.filename.lower().endswith((".pdf", ".txt", ".eml", ".md")):
            raise HTTPException(
                status_code=400,
                detail=f"{file.filename} is not a supported format (PDF/TXT/EML/MD).",
            )

        dest = os.path.join(session.upload_dir, file.filename)
        with open(dest, "wb") as f:
            f.write(await file.read())
        size_bytes = os.path.getsize(dest)

        # Create or update Document row
        doc = db.query(Document).filter(
            Document.organization_id == user.organization_id,
            Document.filename == file.filename,
        ).first()
        if not doc:
            doc = Document(
                organization_id=user.organization_id,
                uploaded_by=user.id,
                filename=file.filename,
                size_bytes=size_bytes,
                storage_path=dest,
                status="pending",
            )
            db.add(doc)
            db.flush()
        else:
            doc.status = "pending"
            doc.size_bytes = size_bytes
            doc.storage_path = dest
            doc.error_message = None

        db.commit()
        db.refresh(doc)

        # Queue background ingestion
        try:
            task = ingest_document_task.delay(
                document_id=doc.id,
                file_path=dest,
                organization_id=user.organization_id,
                session_id=_user_session_id(user),
            )
            queued.append({
                "document_id": doc.id,
                "filename": file.filename,
                "task_id": task.id,
            })
        except Exception as e:
            doc.status = "failed"
            doc.error_message = f"Failed to queue: {e}"
            db.commit()
            queued.append({
                "document_id": doc.id,
                "filename": file.filename,
                "task_id": None,
                "error": str(e),
            })

    return {
        "queued": queued,
        "message": f"{len(queued)} document(s) queued for background indexing.",
    }


@app.get("/api/documents/tasks/{task_id}")
def get_document_task_status(
    task_id: str,
    user: User = Depends(get_current_user),
):
    """Poll a Celery ingestion task's status."""
    return get_task_status(task_id)


@app.get("/api/llm/info")
def llm_info(user: User = Depends(get_current_user)):
    """Inspect the configured LLM provider (useful for debugging)."""
    try:
        return get_llm_provider().info()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/chat")
def chat(
    request: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a message and get a response from the RAG chain."""
    conv_id = request.conversation_id
    sid = _user_session_id(user)
    session = get_session(sid, conv_id)
    prev_model = session.selected_model
    session.selected_model = request.model
    session.use_reranker = request.use_reranker
    session.last_sources = []

    if session.query_engine is None or prev_model != request.model:
        if session.vectorstore is not None:
            _init_query_engine(session)

    session.messages.append({"role": "user", "content": request.prompt})

    try:
        update_memory(sid, request.prompt)
    except Exception as e:
        print(f"[memory] update failed (non-fatal): {e}")

    if session.query_engine is None:
        # Auto-build index if conv has files but no in-memory engine yet
        try:
            supported_exts = (".pdf", ".txt", ".eml", ".md")
            existing = [f for f in os.listdir(session.upload_dir) if f.lower().endswith(supported_exts)]
            if existing:
                result = _build_index(session)
                if result.get("engine_initialized"):
                    print(f"[chat] Auto-built index for conv {conv_id}: {len(existing)} files")
                    if conv_id:
                        invalidate_status(conv_id)
        except Exception as e:
            print(f"[chat] Auto-index failed: {e}")

    if session.query_engine is None:
        answer = "Please upload and process documents first."
        doc_context = ""
        graph_sources = []
        metrics_mod.incr("chat_no_docs")
    else:
        try:
            import time as _time

            _t0 = _time.perf_counter()
            answer, graph_sources, doc_context = _invoke_graph_pipeline(session, request.prompt)
            metrics_mod.observe_chat_latency((_time.perf_counter() - _t0) * 1000)
            metrics_mod.incr("chat_requests")
            session.last_sources = graph_sources
        except Exception as e:
            answer = f"Error: {e}"
            doc_context = ""
            session.last_sources = []
            metrics_mod.incr("chat_errors")

    session.messages.append({"role": "assistant", "content": answer})

    try:
        _save_conversation(session)
    except Exception as e:
        print(f"Could not save conversation: {e}")

    # ── Image retrieval + multimodal re-answer ─────────────────────────────
    image_sources: list[dict] = []
    multimodal_answer = None

    is_visual_query = _is_visual_query(request.prompt)
    preferred_type = _requested_visual_type(request.prompt)
    preferred_pages = _source_pages_from_last_sources(session.last_sources)

    if not session.image_store.is_empty():
        try:
            embedder  = get_embedder()
            query_emb = embedder.embed_text(request.prompt)
            candidate_k = max(IMAGE_TOP_K * 4, 8)
            top_imgs = session.image_store.search(
                query_emb,
                k=candidate_k,
                query_text=request.prompt,
                preferred_type=preferred_type,
                preferred_pages=preferred_pages,
            )
            print(f"[chat] Retrieved {len(top_imgs)} candidate images")
            for rec in top_imgs:
                if rec["score"] < 0.18:
                    continue
                image_sources.append({
                    "file":     rec["filename"],
                    "page":     rec["page"],
                    "img_id":   rec["img_id"],
                    "score":    round(rec["score"], 4),
                    "caption":  rec.get("caption", ""),
                    "ocr_text": rec.get("ocr_text", "")[:200],
                    "type":     rec.get("type", "figure"),
                    "is_image": True,
                })
                if len(image_sources) >= IMAGE_TOP_K:
                    break

            if not image_sources and top_imgs:
                fallback = top_imgs[0]
                image_sources.append({
                    "file":     fallback["filename"],
                    "page":     fallback["page"],
                    "img_id":   fallback["img_id"],
                    "score":    round(fallback["score"], 4),
                    "caption":  fallback.get("caption", ""),
                    "ocr_text": fallback.get("ocr_text", "")[:200],
                    "type":     fallback.get("type", "figure"),
                    "is_image": True,
                })

            # ── Re-answer with multimodal LLM when images are found ──────
            if image_sources and doc_context:
                print(f"[chat] Re-answering with multimodal LLM ({len(image_sources)} images)")
                image_base64_list: list[str] = []
                from PIL import Image as PILImage2
                for img_src in image_sources:
                    img_path = os.path.join(session.upload_dir, "images", f"{img_src['img_id']}.png")
                    if os.path.exists(img_path):
                        img = PILImage2.open(img_path).convert("RGB")
                        w, h = img.size
                        if max(w, h) > 800:
                            scale = 800.0 / max(w, h)
                            img = img.resize((int(w * scale), int(h * scale)))
                        import io
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        image_base64_list.append(b64)

                if image_base64_list:
                    mm_prompt = (
                        "You are a financial document analyst. Answer the user's question using "
                        "both the document context below AND the images provided (charts, tables, figures).\n\n"
                        f"Context from documents:\n{doc_context}\n\n"
                        f"User question: {request.prompt}\n\n"
                        "Instructions:\n"
                        "- Refer to specific charts/figures by their captions or page numbers when relevant.\n"
                        "- If the question asks to compare two visuals, describe what you see in each.\n"
                        "- Be precise about numbers and trends visible in the charts.\n"
                        "- If the images don't contain the answer, rely on the text context."
                    )
                    llm = LlamaCppServerLLM()
                    try:
                        multimodal_answer = llm.chat_with_images(
                            text_prompt=mm_prompt,
                            image_base64_list=image_base64_list,
                            max_tokens=2048,
                        )
                        print(f"[chat] Multimodal answer received ({len(multimodal_answer)} chars)")
                    except Exception as e:
                        print(f"[chat] Multimodal LLM call failed, using text-only answer: {e}")

        except Exception as e:
            print(f"[chat] Image retrieval/multimodal failed: {e}")

    if multimodal_answer:
        answer = multimodal_answer
        session.messages[-1]["content"] = answer

    # ── Persist message to DB ───────────────────────────────────────────────
    try:
        conv = None
        if conv_id:
            conv = db.query(Conversation).filter(
                Conversation.id == conv_id,
                Conversation.user_id == user.id,
            ).first()
        if not conv:
            conv = db.query(Conversation).filter(
                Conversation.user_id == user.id
            ).order_by(Conversation.updated_at.desc()).first()
        if not conv:
            conv = Conversation(
                user_id=user.id,
                organization_id=user.organization_id,
                title=request.prompt[:80],
                model_used=request.model,
            )
            db.add(conv)
            db.flush()
        elif conv.title == "New Conversation":
            conv.title = request.prompt[:80]
            conv.model_used = request.model

        db.add(DBMessage(conversation_id=conv.id, role="user", content=request.prompt))
        db.add(DBMessage(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            sources=session.last_sources,
            image_sources=image_sources,
        ))
        db.commit()
    except Exception as e:
        print(f"[chat] DB persist failed (non-fatal): {e}")
        db.rollback()

    return {
        "response": answer,
        "sources": session.last_sources,
        "image_sources": image_sources,
        "conversation_id": conv_id or (conv.id if conv else None),
        "messages": [
            {"role": m["role"], "content": m["content"]}
            for m in session.messages
        ],
    }


@app.post("/api/chat/clear")
def clear_chat(
    conversation_id: str = Form(None),
    user: User = Depends(get_current_user),
):
    """Clear chat history for this user's session."""
    session = get_session(_user_session_id(user), conversation_id)
    session.reset_chat()
    return {"message": "Chat cleared."}


@app.get("/api/chat/history")
def get_history(
    conversation_id: str = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get chat history for a conversation."""
    conv = None
    if conversation_id:
        conv = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        ).first()
    if not conv:
        conv = db.query(Conversation).filter(
            Conversation.user_id == user.id
        ).order_by(Conversation.updated_at.desc()).first()

    if not conv:
        return {"messages": [], "conversation_id": None}

    return {
        "messages": [
            {"role": m.role, "content": m.content}
            for m in conv.messages
        ],
        "conversation_id": conv.id,
        "title": conv.title,
    }


@app.get("/api/status")
def status(
    conversation_id: str = Query(None),
    user: User = Depends(get_current_user),
):
    """Get pipeline status for this user's conversation."""
    sid = _user_session_id(user)
    session = get_session(sid, conversation_id)

    if conversation_id:
        cached = get_cached_status(conversation_id)
        if cached is not None:
            return cached

    # If session hasn't been built yet, list files from disk
    indexed_files = session.indexed_files
    if not indexed_files and conversation_id:
        try:
            supported_exts = (".pdf", ".txt", ".eml", ".md")
            indexed_files = [
                f for f in os.listdir(session.upload_dir)
                if f.lower().endswith(supported_exts)
            ]
        except Exception:
            pass

    result = {
        "session_id": sid,
        "conversation_id": conversation_id,
        "indexed_files": indexed_files,
        "engine_ready": session.query_engine is not None,
        "bm25_ready": session.bm25 is not None,
        "use_reranker": session.use_reranker,
        "model": session.selected_model,
    }
    if conversation_id:
        cache_status(conversation_id, result)
    return result


@app.get("/api/memory")
def get_memory(user: User = Depends(get_current_user)):
    """Return the stored user facts."""
    return get_memory_summary(_user_session_id(user))


@app.delete("/api/memory")
def delete_memory(user: User = Depends(get_current_user)):
    """Clear all stored user facts."""
    clear_memory(_user_session_id(user))
    return {"message": "Memory cleared."}


@app.get("/api/images/{img_id}")
def serve_image(
    img_id: str,
    conversation_id: str = Query(None),
    user: User = Depends(get_current_user),
):
    """Serve a stored PNG image by its img_id (scoped to user/conversation)."""
    session = get_session(_user_session_id(user), conversation_id)
    img_dir = os.path.join(session.upload_dir, "images")
    img_path = os.path.join(img_dir, f"{img_id}.png")
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found.")
    with open(img_path, "rb") as f:
        data = f.read()
    return Response(content=data, media_type="image/png")


@app.delete("/api/session")
def delete_session(user: User = Depends(get_current_user)):
    """Clean up the current user's session and free resources."""
    sid = _user_session_id(user)
    if sid in _sessions:
        session = _sessions[sid]
        session.release_vectorstore()
        del _sessions[sid]
    try:
        clear_memory(sid)
    except Exception:
        pass
    return {"message": "Session cleared."}


@app.get("/api/health")
def health():
    """Public liveness check endpoint."""
    return {"status": "ok", "service": "samvaad-financial-rag"}


@app.get("/api/ready")
def ready():
    """Readiness: DB required; Redis/LLM reported best-effort.

    Returns 200 with per-component status. Orchestrators should gate on
    `ready == true` (DB reachable). Healthchecks in compose use /api/health
    for liveness; use /api/ready for deploy gating.
    """
    from sqlalchemy import text as sa_text

    components: dict = {}

    try:
        db = SessionLocal()
        try:
            db.execute(sa_text("SELECT 1"))
            components["postgres"] = True
        finally:
            db.close()
    except Exception:
        components["postgres"] = False

    try:
        import redis as redis_lib

        r = redis_lib.from_url(REDIS_URL, socket_timeout=2)
        r.ping()
        components["redis"] = True
    except Exception:
        components["redis"] = False

    try:
        import requests as req_lib

        llm_base = os.getenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        resp = req_lib.get(f"{llm_base}/health", timeout=5)
        components["llm"] = resp.ok
    except Exception:
        components["llm"] = False

    is_ready = bool(components.get("postgres"))
    status_code = 200 if is_ready else 503
    return Response(
        content=__import__("json").dumps(
            {"ready": is_ready, "components": components}
        ),
        media_type="application/json",
        status_code=status_code,
    )


@app.get("/api/metrics")
def api_metrics(user: User = Depends(get_current_user)):
    """JSON metrics snapshot (auth required)."""
    from sqlalchemy import text as sa_text

    snap = metrics_mod.snapshot()
    try:
        db = SessionLocal()
        try:
            snap["pg_chunks_total"] = db.execute(
                sa_text("SELECT count(*) FROM document_chunks")
            ).scalar()
        finally:
            db.close()
    except Exception:
        snap["pg_chunks_total"] = None
    return snap


@app.get("/api/metrics/prom")
def api_metrics_prom(user: User = Depends(get_current_user)):
    """Prometheus exposition format (auth required)."""
    return PlainTextResponse(metrics_mod.snapshot_prometheus())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
