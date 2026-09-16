import os
import streamlit as st

from langchain_huggingface import HuggingFaceEmbeddings

from config import LOCAL_MODEL_DIR


@st.cache_resource(show_spinner=False)
def load_embeddings() -> HuggingFaceEmbeddings | None:
    if not os.path.exists(LOCAL_MODEL_DIR):
        return None

    return HuggingFaceEmbeddings(
        model_name=LOCAL_MODEL_DIR,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )