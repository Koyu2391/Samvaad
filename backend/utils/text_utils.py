import re
import json
import os
from datetime import datetime
import streamlit as st

from config import USE_STEMMING, CHAT_HISTORY_WINDOW

# STEMMER SETUP
if USE_STEMMING:
    from nltk.stem import PorterStemmer
    _stemmer = PorterStemmer()
else:
    _stemmer = None


def tokenize(text: str) -> list[str]:
    """Tokenize and optionally stem text for BM25 indexing."""
    words = re.findall(r"\b\w+\b", text.lower())
    if USE_STEMMING and _stemmer:
        return [_stemmer.stem(w) for w in words]
    return words


# CHAIN-OF-THOUGHT PARSER
def parse_cot_response(text: str) -> tuple[str | None, str]:
    """
    Extract <thought> and <answer> tags from a model response.
    Returns (thought, answer). If no <answer> tag found, returns full text as answer.
    """
    thought_match = re.search(r"<thought>(.*?)</thought>", text, re.DOTALL)
    answer_match = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL)

    thought = thought_match.group(1).strip() if thought_match else None
    answer = answer_match.group(1).strip() if answer_match else text.strip()

    # Clean up leftover tags if closing tag was missing
    if not answer_match and thought:
        answer = text.replace(f"<thought>{thought}</thought>", "").strip()
        answer = re.sub(r"<(/?)(thought|answer)>", "", answer).strip()

    return thought, answer


# CHAT HISTORY BUILDER
def get_chat_history() -> str:
    """
    Build a conversation history string from the last N messages
    in st.session_state.messages, for inclusion in the RAG prompt.
    """
    history = []
    messages = st.session_state.get("messages", [])[-CHAT_HISTORY_WINDOW:]

    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "assistant":
            _, answer = parse_cot_response(content)
            history.append(f"Assistant: {answer}")
        else:
            history.append(f"User: {content}")

    return "\n".join(history)


# CONVERSATION SAVER
def save_conversation(save_dir: str = "conversations") -> str:
    """
    Auto-save the current conversation to a JSON file.

    Each conversation is saved to:
        conversations/conversation_YYYYMMDD_HHMMSS.json

    The file is only created once per session (on the first message)
    and updated in-place on every subsequent message.

    Returns the path of the saved file.
    """
    os.makedirs(save_dir, exist_ok=True)

    # Create a stable filename for this session so updates go to the same file
    if "conversation_file" not in st.session_state:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"conversation_{timestamp}.json"
        st.session_state.conversation_file = os.path.join(save_dir, filename)

    filepath = st.session_state.conversation_file

    messages = st.session_state.get("messages", [])

    # Build human-readable structure
    payload = {
        "saved_at": datetime.now().isoformat(),
        "model": st.session_state.get("selected_model", "unknown"),
        "documents": st.session_state.get("indexed_files", []),
        "messages": [
            {
                "role": msg["role"],
                "content": parse_cot_response(msg["content"])[1]
                if msg["role"] == "assistant"
                else msg["content"],
            }
            for msg in messages
        ],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return filepath