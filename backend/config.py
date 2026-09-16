import os
from dotenv import load_dotenv

load_dotenv()

# PATHS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_MODEL_DIR = os.path.join(BASE_DIR, "models", "all-MiniLM-L6-v2")
PERSIST_BASE_DIR = os.path.join(BASE_DIR, "chroma_db_langchain")

# CHUNKING
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 300

# RETRIEVAL
DEFAULT_K = 8
MAX_K = 20
K_PER_FILE = 6

# LLM (llama.cpp local)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_KEEP_ALIVE = -1
DEFAULT_MODELS = ["qwen:7b", "gemma3n:e2b", "qwen3.5:2b", "nemotron-3-nano:4b", "qwen3.5:0.8b", "mistral"]

USE_STEMMING = True
CHAT_HISTORY_WINDOW = 6

# Multimodal / Image RAG
CLIP_MODEL_NAME = "ViT-B-32"
CLIP_PRETRAINED = "laion2b_s34b_b79k"
IMAGE_TOP_K = 3
MIN_IMAGE_SIZE_PX = 50
IMAGE_EMBED_DIM = 512

# ─────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION & DATABASE (Phase 1 — prod hardened)
# ─────────────────────────────────────────────────────────────────────────────

IS_PROD = os.getenv("APP_ENV", "dev").lower() == "prod"

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rag_user:rag_password@localhost:5432/rag_financial"
)

# Use SQLite for quick local dev if PostgreSQL not available.
# In prod (APP_ENV=prod) fallback is always disabled — fail fast instead.
_USE_SQLITE_RAW = os.getenv("USE_SQLITE_FALLBACK", "true").lower() == "true"
USE_SQLITE_FALLBACK = False if IS_PROD else _USE_SQLITE_RAW
SQLITE_PATH = os.path.join(BASE_DIR, "rag_financial.db")

# JWT Authentication — fail fast on insecure defaults in prod.
_JWT_DEFAULT = "change-this-secret-key-in-production-use-openssl-rand-hex-32"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", _JWT_DEFAULT)
if IS_PROD:
    if not JWT_SECRET_KEY or JWT_SECRET_KEY == _JWT_DEFAULT or len(JWT_SECRET_KEY) < 32:
        raise RuntimeError(
            "APP_ENV=prod requires JWT_SECRET_KEY env (>=32 chars, "
            "generate with: openssl rand -hex 32)"
        )
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("APP_ENV=prod requires DATABASE_URL env")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")  # 60 min prod default
)
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Password Hashing
BCRYPT_ROUNDS = 12

# Redis (for sessions cache + Celery)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# CORS - allowed origins for frontend. No localhost default in prod.
_CORS_RAW = os.getenv("CORS_ORIGINS", "")
if _CORS_RAW:
    CORS_ORIGINS = [o.strip() for o in _CORS_RAW.split(",") if o.strip()]
elif IS_PROD:
    raise RuntimeError("APP_ENV=prod requires CORS_ORIGINS env (your https domain)")
else:
    CORS_ORIGINS = ["http://localhost:5174", "http://localhost:5173", "http://localhost:3000"]

# Default organization for new users (single-org mode initially)
DEFAULT_ORG_NAME = "Default Organization"

# Document upload limits per user role
UPLOAD_LIMITS = {
    "viewer": 0,          # Can only read
    "analyst": 50,        # Can upload 50 documents
    "admin": 500,         # Can upload 500 documents
}

# Max file size (50 MB for financial PDFs)
MAX_UPLOAD_SIZE_MB = 50
