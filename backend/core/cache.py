"""
Redis-backed cache for conversation list and pipeline status.
Gracefully falls back to no-op when Redis is unavailable.
"""
import json
import os
from typing import Optional

try:
    import redis as redis_lib
    _redis: Optional[redis_lib.Redis] = None
    _url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        _redis = redis_lib.from_url(_url, socket_timeout=1, decode_responses=True)
        _redis.ping()
    except Exception:
        _redis = None
except ImportError:
    _redis = None


def _key(prefix: str, *parts: str) -> str:
    return f"samvaad:{prefix}:" + ":".join(parts)


# ── Conversation list cache ─────────────────────────────────────

CONV_LIST_TTL = 30

def cache_conversations(user_id: str, data: list[dict]) -> None:
    if _redis is None:
        return
    try:
        _redis.setex(_key("conv_list", user_id), CONV_LIST_TTL, json.dumps(data))
    except Exception:
        pass

def get_cached_conversations(user_id: str) -> Optional[list[dict]]:
    if _redis is None:
        return None
    try:
        raw = _redis.get(_key("conv_list", user_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None

def invalidate_conversations(user_id: str) -> None:
    if _redis is None:
        return
    try:
        _redis.delete(_key("conv_list", user_id))
    except Exception:
        pass


# ── Pipeline status cache ───────────────────────────────────────

STATUS_TTL = 10

def cache_status(conv_id: str, data: dict) -> None:
    if _redis is None:
        return
    try:
        _redis.setex(_key("status", conv_id), STATUS_TTL, json.dumps(data))
    except Exception:
        pass

def get_cached_status(conv_id: str) -> Optional[dict]:
    if _redis is None:
        return None
    try:
        raw = _redis.get(_key("status", conv_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None

def invalidate_status(conv_id: str) -> None:
    if _redis is None:
        return
    try:
        _redis.delete(_key("status", conv_id))
    except Exception:
        pass
