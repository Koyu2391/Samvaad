import gc
import uuid
import streamlit as st

from config import LOCAL_MODEL_DIR, PERSIST_BASE_DIR
from core.indexer import build_index
from utils.ollama_utils import get_available_models, check_embedding_model

import os


def _reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.context = None
    st.session_state.bm25 = None
    st.session_state.all_splits = []
    st.session_state.indexed_files = []

    if "vectorstore" in st.session_state:
        try:
            st.session_state.vectorstore._client.close()
        except Exception:
            pass

    gc.collect()


def _close_existing_vectorstore() -> None:
    if "vectorstore" in st.session_state:
        try:
            st.session_state.vectorstore._client.close()
        except Exception:
            pass
        del st.session_state.vectorstore


def render_sidebar() -> tuple[str, str]:
    """
    Render the full sidebar UI.

    Returns:
        (selected_model: str, persist_dir: str)
    """
    # Session initialisation (idempotent)
    if "id" not in st.session_state:
        st.session_state.id = uuid.uuid4()
        st.session_state.file_cache = {}
        st.session_state.bm25 = None
        st.session_state.all_splits = []
        st.session_state.indexed_files = []

    persist_dir = os.path.join(PERSIST_BASE_DIR, str(st.session_state.id))

    with st.sidebar:
        st.header("Configuration")

        # Embedding model status
        model_exists, model_path = check_embedding_model()
        if model_exists:
            st.success("Embedding model: LOCAL (offline)")
        else:
            st.error("Embedding model: NOT DOWNLOADED")
            st.info(
                f"Download the model first:\n\n"
                f"```bash\nmkdir -p models\n"
                f"python -c \"from sentence_transformers import SentenceTransformer; "
                f"SentenceTransformer('all-MiniLM-L6-v2').save('./models/all-MiniLM-L6-v2')\"\n```\n\n"
                f"Or place it in:\n`{model_path}`"
            )

        # Model selector
        available_models = get_available_models()
        selected_model = st.selectbox("Select Ollama model", available_models)

        # Reranker toggle
        use_reranker = st.toggle("Use reranker (slower, more accurate)", value=True)
        st.session_state.use_reranker = use_reranker

        # File uploader + indexing
        st.header("Add your documents")
        uploaded_files = st.file_uploader(
            "Choose PDF file(s)", type="pdf", accept_multiple_files=True
        )

        if uploaded_files and st.button("Process & index documents"):
            _close_existing_vectorstore()
            st.session_state.bm25 = None
            st.session_state.all_splits = []
            st.session_state.indexed_files = []

            success, splits, bm25 = build_index(uploaded_files, persist_dir)

            if success:
                st.session_state.bm25 = bm25
                st.session_state.all_splits = splits
                st.session_state.indexed_files = [f.name for f in uploaded_files]
                _reset_chat()
                st.success(
                    f"Indexed {len(uploaded_files)} file(s) → "
                    f"{len(splits)} chunks."
                )

        # Pipeline status panel
        with st.expander("Pipeline status", expanded=False):
            st.markdown("**Retrieval:** Hybrid (BM25 + Vector)")
            st.markdown(
                f"**Reranker:** {'ON' if st.session_state.get('use_reranker', True) else 'OFF'}"
            )
            bm25_ready = st.session_state.get("bm25") is not None
            st.markdown(f"**BM25 index:** {'ready' if bm25_ready else 'not built'}")
            files = st.session_state.get("indexed_files", [])
            st.markdown(f"**Indexed files:** {len(files)}")
            for f in files:
                st.markdown(f"  - {f}")

    return selected_model, persist_dir