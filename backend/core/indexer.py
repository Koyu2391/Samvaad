# import os
# import shutil
# import tempfile

# import streamlit as st
# from langchain_community.document_loaders import PyPDFLoader
# from langchain_community.vectorstores import Chroma
# from langchain_text_splitters import RecursiveCharacterTextSplitter

# try:
#     from rank_bm25 import BM25Okapi
# except ImportError:
#     BM25Okapi = None

# from config import CHUNK_SIZE, CHUNK_OVERLAP
# from core.embeddings import load_embeddings
# from utils.pdf_utils import extract_tables_from_pdf
# from utils.text_utils import tokenize


# def build_index(uploaded_files: list, persist_dir: str) -> tuple:
#     """
#     Load, chunk, embed, and persist a set of uploaded PDF files.

#     Steps:
#       1. Save each uploaded file to a temp directory.
#       2. Load text pages via PyPDFLoader.
#       3. Extract table chunks via pdfplumber.
#       4. Split text chunks; keep table chunks intact.
#       5. Embed everything and store in ChromaDB.
#       6. Build a BM25 index over all chunks.

#     Returns:
#         (success: bool, splits: list, bm25: BM25Okapi | None)
#     """
#     embed_model = load_embeddings()
#     if embed_model is None:
#         st.error("Local embedding model not found. Please download it first (see sidebar).")
#         return False, [], None

#     try:
#         with tempfile.TemporaryDirectory() as temp_dir:
#             all_docs = []

#             for uploaded_file in uploaded_files:
#                 file_path = os.path.join(temp_dir, uploaded_file.name)
#                 with open(file_path, "wb") as f:
#                     f.write(uploaded_file.getvalue())

#                 # Text pages
#                 loader = PyPDFLoader(file_path)
#                 docs = loader.load()
#                 for doc in docs:
#                     doc.metadata["source_file"] = uploaded_file.name
#                     doc.metadata["type"] = "text"
#                 all_docs.extend(docs)
#                 st.write(f"Loaded: {uploaded_file.name} ({len(docs)} pages)")

#                 # Table chunks
#                 table_docs = extract_tables_from_pdf(file_path, uploaded_file.name)
#                 all_docs.extend(table_docs)
#                 if table_docs:
#                     st.write(f"  + {len(table_docs)} tables extracted from {uploaded_file.name}")

#             if not all_docs:
#                 st.warning("No content found in uploaded files.")
#                 return False, [], None

#             with st.spinner(f"Indexing {len(all_docs)} pages…"):
#                 splitter = RecursiveCharacterTextSplitter(
#                     chunk_size=CHUNK_SIZE,
#                     chunk_overlap=CHUNK_OVERLAP,
#                     length_function=len,
#                     separators=["\n\n", "\n", ". ", " ", ""],
#                 )

#                 text_docs = [d for d in all_docs if d.metadata.get("type") != "table"]
#                 table_only = [d for d in all_docs if d.metadata.get("type") == "table"]

#                 text_splits = splitter.split_documents(text_docs)
#                 for doc in text_splits:
#                     doc.metadata.setdefault("type", "text")

#                 splits = text_splits + table_only
#                 st.write(
#                     f"Total chunks: {len(text_splits)} text + {len(table_only)} tables"
#                 )

#                 # Clear stale index
#                 if os.path.exists(persist_dir):
#                     shutil.rmtree(persist_dir)

#                 # Persist to ChromaDB
#                 Chroma.from_documents(
#                     documents=splits,
#                     embedding=embed_model,
#                     persist_directory=persist_dir,
#                 )

#                 # Build BM25
#                 bm25 = None
#                 if BM25Okapi is not None:
#                     tokenized_corpus = [tokenize(doc.page_content) for doc in splits]
#                     bm25 = BM25Okapi(tokenized_corpus)

#             return True, splits, bm25

#     except Exception as e:
#         st.error(f"Indexing failed: {e}")
#         return False, [], None


# def load_vectorstore(persist_dir: str):
#     """
#     Load an existing ChromaDB vectorstore from disk.
#     Returns None if the directory is missing or embedding model is unavailable.
#     """
#     if not (os.path.exists(persist_dir) and os.listdir(persist_dir)):
#         return None

#     embed_model = load_embeddings()
#     if embed_model is None:
#         return None

#     return Chroma(persist_directory=persist_dir, embedding_function=embed_model)


# ver 2
import os
import shutil
import tempfile

import streamlit as st
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

from config import CHUNK_SIZE, CHUNK_OVERLAP
from core.embeddings import load_embeddings
from utils.pdf_utils import load_pdf_as_markdown
from utils.text_utils import tokenize


def build_index(uploaded_files: list, persist_dir: str) -> tuple:
    embed_model = load_embeddings()
    if embed_model is None:
        st.error("Local embedding model not found. Please download it first (see sidebar).")
        return False, [], None

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            all_docs = []

            for uploaded_file in uploaded_files:
                file_path = os.path.join(temp_dir, uploaded_file.name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getvalue())

                try:
                    docs = load_pdf_as_markdown(file_path, uploaded_file.name)
                    all_docs.extend(docs)
                    st.write(f"Loaded: {uploaded_file.name} ({len(docs)} pages)")
                except Exception as e:
                    st.warning(f"Failed to load {uploaded_file.name}: {e}")
                    continue

            if not all_docs:
                st.warning("No content found in uploaded files.")
                return False, [], None

            with st.spinner(f"Indexing {len(all_docs)} pages…"):
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=CHUNK_SIZE,
                    chunk_overlap=CHUNK_OVERLAP,
                    length_function=len,
                    separators=["\n\n", "\n", ". ", " ", ""],
                )

                splits = splitter.split_documents(all_docs)
                for doc in splits:
                    doc.metadata.setdefault("type", "text")

                st.write(f"Total chunks: {len(splits)}")

                # Clear stale index
                if os.path.exists(persist_dir):
                    shutil.rmtree(persist_dir)

                # Persist to ChromaDB
                Chroma.from_documents(
                    documents=splits,
                    embedding=embed_model,
                    persist_directory=persist_dir,
                )

                # Build BM25
                bm25 = None
                if BM25Okapi is not None:
                    tokenized_corpus = [tokenize(doc.page_content) for doc in splits]
                    bm25 = BM25Okapi(tokenized_corpus)

            return True, splits, bm25

    except Exception as e:
        st.error(f"Indexing failed: {e}")
        return False, [], None


def load_vectorstore(persist_dir: str):
    """
    Load an existing ChromaDB vectorstore from disk.
    Returns None if the directory is missing or embedding model is unavailable.
    """
    if not (os.path.exists(persist_dir) and os.listdir(persist_dir)):
        return None

    embed_model = load_embeddings()
    if embed_model is None:
        return None

    return Chroma(persist_directory=persist_dir, embedding_function=embed_model)