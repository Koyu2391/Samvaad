"""
memory.py — Persistent User Fact Memory for Samvaad RAG

Stores personal facts about the user (name, preferences, context) across turns.
Facts are extracted from each user message using the existing LlamaCpp server
and persisted as JSON per session.

Public API:
    update_memory(session_id, message)   -> dict  (merged facts after update)
    format_memory_for_prompt(session_id) -> str   (formatted for prompt injection)
    load_memory(session_id)              -> dict  (raw facts dict)
    clear_memory(session_id)             -> None
"""

import json
import os
import re
import requests
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────────
# Store memory files in backend/conversations/ (same dir as conv. logs)
MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # core/
    "..",                                         # backend/
    "conversations",
)

# ── LLM config — same server as main.py (port 8000) ──────────────────────────
from core.llamacpp import LlamaCppServerLLM

# ── Extraction prompt ─────────────────────────────────────────────────────────
_EXTRACTION_PROMPT = """<|im_start|>system
You are a memory extraction assistant. Your only job is to extract personal facts about the user from their message.

Rules:
- Extract ONLY facts explicitly stated or clearly implied about the USER (not about documents or topics).
- Facts can include: name, age, location, interests, profession, language, travel plans, or any personal context.
- Return a flat JSON object with short snake_case keys and concise string values.
- If no personal facts are found, return an empty object: {{}}
- Return ONLY valid JSON. No explanation, no markdown, no extra text.
<|im_end|>
<|im_start|>user
User message: "{message}"
<|im_end|>
<|im_start|>assistant
```json
"""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _memory_path(session_id: str) -> str:
    os.makedirs(MEMORY_DIR, exist_ok=True)
    return os.path.join(MEMORY_DIR, f"memory_{session_id}.json")


def _call_llm(prompt: str, timeout: int = 20) -> str:
    """Send a prompt to the local llama.cpp server and return raw text."""
    try:
        llm = LlamaCppServerLLM(max_tokens=256, temperature=0.0)
        resp = llm._call(prompt)
        # Strip thinking tags if generated
        resp = re.sub(r'<think>.*?</think>', '', resp, flags=re.DOTALL)
        return resp
    except Exception as e:
        print(f"[memory] LLM call failed: {e}")
        return "{}"


def _clean_json(raw: str) -> str:
    """Strip common markdown wrappers from LLM JSON output."""
    raw = raw.strip()
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    raw = raw.rstrip("```").strip()
    return raw


# ── Core CRUD ─────────────────────────────────────────────────────────────────

def load_memory(session_id: str) -> dict:
    """Load persisted user facts for a session. Returns {} if none."""
    path = _memory_path(session_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("facts", {})
    except Exception:
        return {}


def save_memory(session_id: str, facts: dict) -> None:
    """Persist user facts dict to disk."""
    path = _memory_path(session_id)
    payload = {
        "session_id": session_id,
        "updated_at": datetime.now().isoformat(),
        "facts":      facts,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def extract_user_facts(message: str) -> dict:
    """
    Use the local LLM to extract personal user facts from a message.
    Returns a dict of snake_case_key → value, or {} if none found.
    """
    prompt = _EXTRACTION_PROMPT.format(message=message.replace('"', "'"))
    raw    = _call_llm(prompt)
    raw    = _clean_json(raw)

    try:
        facts = json.loads(raw)
        if not isinstance(facts, dict):
            return {}
        # Drop blank/null values
        return {k: v for k, v in facts.items() if v and str(v).strip()}
    except json.JSONDecodeError:
        print(f"[memory] Could not parse LLM output as JSON: {repr(raw)}")
        return {}


# ── Public API ────────────────────────────────────────────────────────────────

def update_memory(session_id: str, message: str) -> dict:
    """
    Extract facts from `message`, merge with existing memory, save, and return
    the updated facts dict.  Safe to call on every user turn — no-ops if no
    new facts are found.
    """
    existing  = load_memory(session_id)
    new_facts = extract_user_facts(message)

    if new_facts:
        existing.update(new_facts)
        save_memory(session_id, existing)
        print(f"[memory] +{len(new_facts)} fact(s) for session {session_id[:8]}: {new_facts}")

    return existing


def format_memory_for_prompt(session_id: str) -> str:
    """
    Return a human-readable string of known user facts, ready for injection
    into a prompt.  Returns empty string if no facts are stored.

    Example output:
        Known facts about the user:
          - Name: Deepak
          - Location: Pune
    """
    facts = load_memory(session_id)
    if not facts:
        return ""

    lines = ["Known facts about the user:"]
    for key, value in facts.items():
        label = key.replace("_", " ").capitalize()
        lines.append(f"  - {label}: {value}")

    return "\n".join(lines)


def get_memory_summary(session_id: str) -> dict:
    """Return a dict with session_id, fact_count, facts, and last update time."""
    path = _memory_path(session_id)
    payload = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            pass
            
    facts = payload.get("facts", {})
    return {
        "session_id": session_id,
        "fact_count": len(facts),
        "facts":      facts,
        "updated_at": payload.get("updated_at"),
    }


def clear_memory(session_id: str) -> None:
    """Delete persisted memory for a session."""
    path = _memory_path(session_id)
    if os.path.exists(path):
        os.remove(path)
    print(f"[memory] Cleared memory for session {session_id[:8]}")