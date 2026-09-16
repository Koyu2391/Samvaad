"""
One-shot Chroma → PGVector migration (Phase 2).

Reads every chroma.sqlite3 scope under the Chroma base dir (reusing stored
vectors — no re-embedding) and inserts rows into `document_chunks`.

Scope mapping (preserves current isolation semantics):
  <base>/<session_id>/            → (session_id, conv="")
  <base>/convs/<conv_id>/         → (user_<owner>, conv_id) via conversations.user_id
  legacy top-level uuid dirs      → (dirname, conv="")

Usage (inside backend container):
  python scripts/migrate_chroma_to_pg.py [--base /app/chroma_db_api] [--dry-run]

Parity gate: PG total must equal Chroma total (baseline: 2771).
"""
import argparse
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

BATCH = 200


def _iter_scopes(base: str):
    for root, _dirs, files in os.walk(base):
        if "chroma.sqlite3" not in files:
            continue
        rel = os.path.relpath(root, base)
        parts = rel.split(os.sep)
        if len(parts) == 2 and parts[0] == "convs":
            yield root, ("conv", parts[1])
        elif len(parts) == 1:
            yield root, ("session", parts[0])
        else:
            print(f"[migrate] SKIP unexpected layout: {rel}")


def _resolve_session(db, kind: str, key: str) -> tuple:
    if kind == "session":
        return key, ""
    # conv scope → owner via conversations table
    from models.conversation import Conversation

    conv = db.query(Conversation).filter(Conversation.id == key).first()
    if conv is None:
        print(f"[migrate] WARN conv {key} not in DB; attributing to session 'unknown'")
        return "unknown", key
    return f"user_{conv.user_id}", key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from config import BASE_DIR

    base = args.base or os.path.join(BASE_DIR, "chroma_db_api")
    if not os.path.isdir(base):
        print(f"[migrate] base dir missing: {base}")
        return 1

    from core.embeddings import load_embeddings

    embeddings = load_embeddings()
    if embeddings is None:
        print("[migrate] embedding model not found (needed to open Chroma collections)")
        return 1

    from langchain_community.vectorstores import Chroma
    from database import SessionLocal, init_db
    from core.vector_pg import insert_rows, delete_scope

    init_db()  # ensure extension + tables + HNSW index exist

    db = SessionLocal()
    chroma_total = 0
    pg_total = 0
    try:
        for persist_dir, (kind, key) in sorted(_iter_scopes(base), key=lambda x: x[0]):
            session_id, conv_id = _resolve_session(db, kind, key)
            try:
                vs = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
                data = vs.get(include=["documents", "metadatas", "embeddings"])
            except Exception as e:
                print(f"[migrate] SKIP {persist_dir}: {e}")
                continue
            docs = data.get("documents") or []
            metas = data.get("metadatas")
            vecs = data.get("embeddings")
            if metas is None:
                metas = [{}] * len(docs)
            if vecs is None:
                print(f"[migrate] SKIP {persist_dir}: no stored embeddings ({len(docs)} docs)")
                continue
            if not docs or len(vecs) != len(docs):
                print(f"[migrate] SKIP {persist_dir}: embedding count mismatch")
                continue
            rows = [
                (t, list(v), dict(m or {}), None, (m or {}).get("source_file"))
                for t, m, v in zip(docs, metas, vecs)
            ]
            chroma_total += len(rows)
            if args.dry_run:
                print(f"[dry-run] {persist_dir} → ({session_id}/{conv_id}): {len(rows)}")
                pg_total += len(rows)
                continue
            delete_scope(session_id, conv_id)  # idempotent re-runs
            n = 0
            for i in range(0, len(rows), BATCH):
                n += insert_rows(rows[i : i + BATCH], session_id, conv_id)
            pg_total += n
            print(f"[migrate] {persist_dir} → ({session_id}/{conv_id}): {n}")
    finally:
        db.close()

    print(f"[migrate] Chroma total={chroma_total} PG inserted={pg_total}")
    if not args.dry_run and chroma_total != pg_total:
        print("[migrate] PARITY FAIL")
        return 2
    print("[migrate] PARITY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
