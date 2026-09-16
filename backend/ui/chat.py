import re
import streamlit as st

from config import LOCAL_MODEL_DIR
from utils.text_utils import parse_cot_response, save_conversation

import os

def get_session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state.session_id = os.urandom(8).hex()
    return st.session_state.session_id

def _no_engine_message(persist_dir: str) -> str:
    """Return a helpful message when the query engine is not available."""
    if os.path.exists(persist_dir) and os.listdir(persist_dir):
        if not os.path.exists(LOCAL_MODEL_DIR):
            return (
                f"Embedding model not found at `{LOCAL_MODEL_DIR}`. "
                "Please download it first (see sidebar instructions)."
            )
        return "Vector store exists but failed to load. Please re-process your documents."
    return "Please upload and process documents to initialise the vector database first."


def render_chat(query_engine, persist_dir: str, selected_model: str) -> None:
    # Header row
    col1, col2 = st.columns([6, 1])
    with col1:
        st.header(f"Chat — {selected_model}")
    with col2:
        if st.button("Clear ↺"):
            st.session_state.messages = []
            st.session_state.context = None
            # Reset conversation file so next session gets a fresh file
            st.session_state.pop("conversation_file", None)
            st.rerun()

    # Session init
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Render history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                _, answer = parse_cot_response(message["content"])
                st.markdown(answer)
            else:
                st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Ask a question…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            full_response = ""
            placeholder = st.empty()

            if query_engine is None:
                full_response = _no_engine_message(persist_dir)
                placeholder.markdown(full_response)
            else:
                try:
                    for chunk in query_engine.stream(prompt):
                        full_response += chunk
                        display_text = re.sub(r"</?answer>", "", full_response).strip()
                        placeholder.markdown(display_text)
                except Exception as e:
                    full_response = f"Error querying the model: {e}"
                    placeholder.markdown(full_response)

            st.session_state.messages.append(
                {"role": "assistant", "content": full_response}
            )

            # Auto-save conversation after every assistant message
            try:
                saved_path = save_conversation()
                print(f"Conversation saved to {saved_path}")
            except Exception as e:
                print(f"Could not save conversation: {e}")