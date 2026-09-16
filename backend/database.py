"""
Database setup with SQLAlchemy.
Supports PostgreSQL (production) and SQLite (local fallback).
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from config import DATABASE_URL, USE_SQLITE_FALLBACK, SQLITE_PATH


def _get_engine():
    """Try PostgreSQL first, fall back to SQLite if unavailable (dev only).

    In prod (APP_ENV=prod) SQLite fallback is disabled in config.py, so this
    always connects to PostgreSQL and fails fast on misconfiguration.
    """
    if USE_SQLITE_FALLBACK:
        try:
            eng = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
            with eng.connect():
                pass
            print(f"[DB] Connected to PostgreSQL: {DATABASE_URL.split('@')[-1]}")
            return eng
        except Exception as e:
            print(f"[DB] PostgreSQL unavailable ({e}); falling back to SQLite")
            sqlite_url = f"sqlite:///{SQLITE_PATH}"
            eng = create_engine(
                sqlite_url,
                connect_args={"check_same_thread": False},
            )
            print(f"[DB] Using SQLite: {SQLITE_PATH}")
            return eng
    else:
        eng = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        # Fail fast in prod: verify connectivity at startup.
        with eng.connect():
            pass
        print(f"[DB] Connected to PostgreSQL: {DATABASE_URL.split('@')[-1]}")
        return eng


engine = _get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called on startup."""
    from models import user, organization, document, conversation, document_chunk  # noqa
    from sqlalchemy import text
    # pgvector extension (no-op on hosts without the .so; required for Vector type)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as e:
        print(f"[DB] vector extension unavailable (non-fatal in dev): {e}")
    Base.metadata.create_all(bind=engine)
    # HNSW cosine index for ANN search at scale (exact search below this size)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
                    "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
                )
            )
    except Exception as e:
        print(f"[DB] HNSW index skipped (non-fatal): {e}")
    print("[DB] Tables created/verified")
