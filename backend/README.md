# RAG API

Offline Retrieval-Augmented Generation system built with llama.cpp, LangChain, and ChromaDB.
Fully local — no external API calls.

---

## Stack

| Component | Technology |
|---|---|
| LLM Inference | llama.cpp server (any GGUF model) |
| Memory Extraction | Second llama.cpp server — small 0.5B–1B model |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` (CPU) |
| Vector Store | ChromaDB (persisted, per-session) |
| Sparse Retrieval | BM25Okapi |
| Reranker | CrossEncoder `ms-marco-MiniLM-L-6-v2` (optional) |
| PDF Parsing | pymupdf4llm (markdown-first, table-aware) |
| API Framework | FastAPI + Uvicorn |

---

## Port Allocation

| Port | Service | Notes |
|---|---|---|
| 8000 | llama.cpp — main LLM | Use a 7B–9B model |
| 8001 | llama.cpp — memory LLM | Use a 0.5B–1B model |
| 8002 | FastAPI | This API |

---

## Quick Start

**1. Start the main LLM**
```bash
llama-server -hf unsloth/Qwen3.5-9B-GGUF --host 127.0.0.1 --port 8000 --n-gpu-layers 20
```

**2. Start the memory LLM**
```bash
llama-server -hf unsloth/Qwen2.5-0.5B-Instruct-GGUF --host 127.0.0.1 --port 8001 --n-gpu-layers 99
```

**3. Start the API**
```bash
pip install -r requirements.txt
python main.py
```

Interactive API docs available at `http://localhost:8002/docs`

---

## Request Flow

```
# 1. Create session
GET http://localhost:8002/api/session/new
→ { "session_id": "abc-123" }

# 2. Upload PDF (multipart/form-data)
POST http://localhost:8002/api/documents/upload
     session_id = abc-123    ← form field
     files      = ticket.pdf ← file field

# 3. Chat
POST http://localhost:8002/api/chat
     { "session_id": "abc-123", "prompt": "Extract passenger details", "model": "qwen3.5" }

# 4. Check learned user facts
GET http://localhost:8002/api/memory?session_id=abc-123
```

---

## API Endpoints

### Sessions
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/session/new` | Create a new session |
| DELETE | `/api/session/{session_id}` | Delete session and free resources |

### Documents
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/documents/upload` | Upload PDFs and build index (`multipart/form-data`) |
| DELETE | `/api/documents/{filename}?session_id=` | Delete a PDF and rebuild index |
| GET | `/api/documents` | List all uploaded PDFs |

### Chat
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/chat` | Send a message, get a RAG response |
| POST | `/api/chat/clear` | Clear chat history and memory |
| GET | `/api/chat/history?session_id=` | Get full conversation history |

### Memory
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/memory?session_id=` | View learned user facts |
| DELETE | `/api/memory/{session_id}` | Clear user memory |

### Status
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/status?session_id=` | Pipeline status for a session |

---

## RAG Pipeline

```
PDF Upload
  └─► pymupdf4llm (page → markdown, tables preserved)
      └─► RecursiveCharacterTextSplitter (1200 chars, 200 overlap)
          └─► HuggingFace Embeddings → ChromaDB
              └─► BM25Okapi index

Query
  └─► Dense search (ChromaDB cosine similarity)
  └─► Sparse search (BM25, table chunks boosted 1.5×)
      └─► RRF Fusion (score = Σ 1/(60 + rank))
          └─► CrossEncoder Reranker (optional)
              └─► Context cleaning (<br>, duplicates, invisible chars)
                  └─► Prompt assembly (context + history + memory)
                      └─► llama.cpp → response → strip <think>/<answer> → deduplicate
```

---

## User Memory

On every user message a small LLM extracts personal facts (name, preferences, travel context etc.) and persists them to `conversations/memory_<session_id>.json`. Facts are injected into the prompt on subsequent turns.

```json
{
  "session_id": "abc-123",
  "updated_at": "2026-04-06T14:30:22",
  "facts": {
    "name": "Rahul",
    "travel_context": "Agra to Banaras on 3 Apr",
    "catering_preference": "vegetarian"
  }
}
```

---

## Configuration (`config.py`)

| Parameter | Default | Description |
|---|---|---|
| `CHUNK_SIZE` | 1200 | Max characters per chunk |
| `CHUNK_OVERLAP` | 200 | Overlap between chunks |
| `DEFAULT_K` | 8 | Min chunks to retrieve |
| `MAX_K` | 20 | Max chunks to retrieve |
| `K_PER_FILE` | 6 | Chunks per indexed file |

**LLM config (`core/llamacpp.py`)**

| Parameter | Default | Description |
|---|---|---|
| `base_url` | `http://127.0.0.1:8000` | Main llama.cpp server |
| `temperature` | 0.2 | Sampling temperature |
| `max_tokens` | 1024 | Max tokens per response |
| `timeout` | 120s | Request timeout |

**Memory LLM config (`memory.py`)**

| Parameter | Default | Description |
|---|---|---|
| `LLAMA_URL` | `http://127.0.0.1:8001/completion` | Memory extraction model |
| `temperature` | 0.0 | Deterministic JSON extraction |
| `n_predict` | 200 | Max tokens for extraction |

---

## Project Structure

```
project/
├── main.py                 ← FastAPI entry point
├── memory.py               ← User memory extraction
├── config.py               ← Configuration constants
├── app.py                  ← Streamlit UI
├── uploads/                ← Uploaded PDFs
├── conversations/          ← Saved conversations + memory files
├── chroma_db_api/          ← ChromaDB (one dir per session)
├── core/
│   ├── embeddings.py
│   ├── llamacpp.py         ← LangChain wrapper for llama.cpp
│   ├── query_engine.py     ← Prompt templates + chain builder
│   ├── reranker.py
│   └── retriever.py        ← HybridRetriever (BM25 + vector + RRF)
└── utils/
    ├── pdf_utils.py        ← pymupdf4llm loader
    └── text_utils.py       ← Tokenizer, history, conversation saver
```

---

## Prompt Templates

| Template | Triggered for | Notes |
|---|---|---|
| Default | Qwen, Mistral, LLaMA, others | `<answer>` XML tags, flexible knowledge fallback |
| NEMO | Models with `nemotron` in name | Strict no-reasoning output |
| Gemma | Models with `gemma` in name | Plain `Answer:` suffix, no XML tags |
