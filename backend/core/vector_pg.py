"""
Phase 2: PGVector text-chunk store.

Replaces Chroma `persist_directory` scopes with rows in `document_chunks`,
scoped by (session_id, conv_id). Same isolation semantics, one ACID store.

HybridRetriever + LangGraph only need `get_relevant_documents(query)` /
`invoke(query)` on the inner vector retriever — provided by PGVectorRetriever.
BM25 splits come from `load_splits` (replaces `vectorstore.get()`).
Image vectors stay in the numpy ImageStore (unchanged).
"""
from langchain_core.documents import Document

from database import SessionLocal
from models.document_chunk import DocumentChunk


def _conv_key(conv_id) -> str:
    return conv_id or ""


def count_scope(session_id: str, conv_id=None) -> int:
    db = SessionLocal()
    try:
        return (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.session_id == session_id,
                DocumentChunk.conv_id == _conv_key(conv_id),
            )
            .count()
        )
    finally:
        db.close()


def delete_scope(session_id: str, conv_id=None) -> int:
    """Delete all chunks for a (session, conv) scope. Returns rows deleted."""
    db = SessionLocal()
    try:
        n = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.session_id == session_id,
                DocumentChunk.conv_id == _conv_key(conv_id),
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        return n
    finally:
        db.close()


def delete_document_chunks(document_id: str) -> int:
    db = SessionLocal()
    try:
        n = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .delete(synchronize_session=False)
        )
        db.commit()
        return n
    finally:
        db.close()


def add_chunks(
    chunks: list,
    session_id: str,
    conv_id=None,
    embeddings=None,
    document_id: str = None,
    filename: str = None,
) -> int:
    """Embed + insert LangChain Documents. Returns rows inserted."""
    if not chunks:
        return 0
    if embeddings is None:
        from core.embeddings import load_embeddings

        embeddings = load_embeddings()
    if embeddings is None:
        raise RuntimeError("Embedding model not available")

    texts = [d.page_content for d in chunks]
    vectors = embeddings.embed_documents(texts)

    db = SessionLocal()
    try:
        rows = [
            DocumentChunk(
                session_id=session_id,
                conv_id=_conv_key(conv_id),
                document_id=document_id,
                filename=filename or d.metadata.get("source_file"),
                content=d.page_content,
                embedding=v,
                chunk_metadata=dict(d.metadata or {}),
            )
            for d, v in zip(chunks, vectors)
        ]
        db.add_all(rows)
        db.commit()
        return len(rows)
    finally:
        db.close()


def insert_rows(
    rows: list,
    session_id: str,
    conv_id=None,
) -> int:
    """Insert pre-embedded rows: list of (content, vector, metadata, doc_id, filename)."""
    if not rows:
        return 0
    db = SessionLocal()
    try:
        db.add_all(
            [
                DocumentChunk(
                    session_id=session_id,
                    conv_id=_conv_key(conv_id),
                    document_id=r[3] if len(r) > 3 else None,
                    filename=(r[4] if len(r) > 4 else None) or (r[2] or {}).get("source_file"),
                    content=r[0],
                    embedding=r[1],
                    chunk_metadata=dict(r[2] or {}),
                )
                for r in rows
            ]
        )
        db.commit()
        return len(rows)
    finally:
        db.close()


def load_splits(session_id: str, conv_id=None) -> list:
    """Load all chunks for a scope as LangChain Documents (BM25 rebuild)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.session_id == session_id,
                DocumentChunk.conv_id == _conv_key(conv_id),
            )
            .order_by(DocumentChunk.created_at)
            .all()
        )
        return [
            Document(page_content=r.content, metadata=dict(r.chunk_metadata or {}))
            for r in rows
        ]
    finally:
        db.close()


def similarity_search(
    query: str,
    session_id: str,
    conv_id=None,
    k: int = 8,
    embeddings=None,
) -> list:
    """Cosine ANN search (embeddings are L2-normalized)."""
    if embeddings is None:
        from core.embeddings import load_embeddings

        embeddings = load_embeddings()
    if embeddings is None:
        return []
    qvec = embeddings.embed_query(query)
    db = SessionLocal()
    try:
        rows = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.session_id == session_id,
                DocumentChunk.conv_id == _conv_key(conv_id),
            )
            .order_by(DocumentChunk.embedding.cosine_distance(qvec))
            .limit(k)
            .all()
        )
        return [
            Document(page_content=r.content, metadata=dict(r.chunk_metadata or {}))
            for r in rows
        ]
    finally:
        db.close()


class PGVectorRetriever:
    """Drop-in inner retriever for HybridRetriever (replaces Chroma retriever)."""

    def __init__(self, session_id: str, conv_id=None, k: int = 8, embeddings=None):
        self.session_id = session_id
        self.conv_id = conv_id
        self.k = k
        self.embeddings = embeddings

    def get_relevant_documents(self, query: str) -> list:
        try:
            return similarity_search(
                query, self.session_id, self.conv_id, k=self.k,
                embeddings=self.embeddings,
            )
        except Exception as e:
            print(f"[pgvector] search failed (non-fatal): {e}")
            return []

    # LangGraph calls retriever.invoke(q)
    def invoke(self, query: str) -> list:
        return self.get_relevant_documents(query)
