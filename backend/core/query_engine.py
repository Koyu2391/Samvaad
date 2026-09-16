# import streamlit as st
# from langchain_core.runnables import RunnablePassthrough
# from langchain_core.output_parsers import StrOutputParser
# from langchain_core.prompts import PromptTemplate

# try:
#     from langchain_ollama import OllamaLLM as LangchainOllama
# except ImportError:
#     try:
#         from langchain_community.llms import Ollama as LangchainOllama
#     except ImportError:
#         LangchainOllama = None

# from config import DEFAULT_MODELS, OLLAMA_BASE_URL, OLLAMA_KEEP_ALIVE, DEFAULT_K, MAX_K, K_PER_FILE
# from core.indexer import load_vectorstore
# from core.reranker import load_reranker
# from core.retriever import HybridRetriever
# from utils.text_utils import get_chat_history
# import re



# NEMO_PROMPT_TEMPLATE = PromptTemplate(
#     template="""You are an intelligent document assistant with memory and the ability to understand structured data.

# You have access to {num_docs} document(s): {doc_names}.

# Conversation History:
# ---------------------
# {chat_history}
# ---------------------

# Document Context:
# ---------------------
# {context}
# ---------------------

# Instructions:

# 1. Use conversation history for context continuity.

# 2. Carefully analyze the document context before answering.

# 3. Response must not include any internal reasoning, thought processes, or explanations. Only provide the final answer.


# 3. Table Handling:
#    - If the context contains structured data (tables, rows, repeated patterns), interpret it carefully.
#    - Convert messy or unstructured data into a clean markdown table when appropriate.
#    - Only include relevant columns for the query.
#    - Do NOT guess or invent missing values — use "Unknown" if needed.

# 4. STRICT OUTPUT RULES:
#    - Do NOT include <think> or </think>
#    - Do NOT include reasoning, explanations about thinking, or internal steps
#    - Output ONLY the final answer

# 5. Knowledge Rule:
#    - First use Document Context
#    - If not found, write EXACTLY:
#      "The provided document does not contain information about [topic]."
#    - Then answer using general knowledge

# 6. Formatting:
#    - Use bullet points or paragraphs where helpful
#    - If structured data is involved → use a clean markdown table
#    - Otherwise → normal text answer

# Query: {input}

# Response Format:

# <answer>
# [Final clean answer only]
# </answer>""",
#     input_variables=["context", "input", "chat_history", "num_docs", "doc_names"],
# )



# # PROMPT
# _PROMPT_TEMPLATE = PromptTemplate(
#     template="""You are an intelligent, helpful document assistant with memory and access to structured table data.

# You have access to {num_docs} document(s): {doc_names}.

# Conversation History:
# ---------------------
# {chat_history}
# ---------------------

# Document Context (may include text passages and markdown tables):
# ---------------------
# {context}
# ---------------------

# Instructions:
# 1. Use Conversation History to remember what was discussed before.
# 2. Carefully review the Document Context to answer the query.
# 3. When context includes [TABLE SOURCE: ...] blocks, read the markdown table carefully to answer questions about data, numbers, comparisons, or structured information. Mention which page/document the table came from.
# 4. **Flexible Knowledge (IMPORTANT)**:
#    - First, always prioritize the Document Context.
#    - If the Document Context does NOT contain the answer, write EXACTLY one line:
#      "The provided document does not contain information about [topic]."
#    - Then immediately provide a detailed, helpful answer using your own general knowledge.
# 5. Never refuse to answer. If the docs don't help, use your knowledge.
# 6. Format answers clearly with bullet points and paragraphs where helpful.

# Query: {input}

# Please follow this format:

# <answer>
# [Your detailed and helpful final response]
# </answer>""",
#     input_variables=["context", "input", "chat_history", "num_docs", "doc_names"],
# )


# def get_prompt_for_model(model_name: str) -> PromptTemplate:
#     nemotron_models = ["nemotron", "nemotron-3-nano", "nemotron-3-nano:4b"]
    
#     if any(nm in model_name.lower() for nm in nemotron_models):
#         print(f"Custom prompt template loaded for {model_name}")
#         return NEMO_PROMPT_TEMPLATE
#     else:
#         print(f"Default prompt template loaded for {model_name}")
#         return _PROMPT_TEMPLATE

# # DOCUMENT FORMATTER
# def _format_docs(docs: list) -> str:
#     parts = []
#     for doc in docs:
#         doc_type = doc.metadata.get("type", "text")
#         source = doc.metadata.get("source_file", "unknown")
#         if doc_type == "table":
#             parts.append(f"[TABLE SOURCE: {source}]\n{doc.page_content}")
#         else:
#             parts.append(f"[TEXT SOURCE: {source}]\n{doc.page_content}")
#     return "\n\n---\n\n".join(parts)

# # Add this to your existing strip function (already written)
# def strip_thinking(text: str) -> str:
#     # Handle: random thinking content ... </think> actual answer
#     if '</think>' in text:
#         text = text.split('</think>', 1)[-1]
#     # Also handle normal closed blocks just in case
#     text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
#     return text.strip()


# # PUBLIC BUILDER
# def build_query_engine(persist_dir: str, selected_model: str):
#     """
#     Build and return the full LCEL RAG chain, or None if prerequisites are missing.

#     Requires:
#       - A persisted ChromaDB vectorstore at persist_dir
#       - LangchainOllama available
#     """
#     if LangchainOllama is None:
#         st.error(
#             "langchain_ollama not installed. Run: pip install langchain-ollama"
#         )
#         return None

#     vectorstore = load_vectorstore(persist_dir)
#     if vectorstore is None:
#         return None

#     # Dynamic k based on number of indexed files
#     num_files = len(st.session_state.get("indexed_files", []))
#     k_value = max(DEFAULT_K, min(K_PER_FILE * max(num_files, 1), MAX_K))

#     vector_retriever = vectorstore.as_retriever(search_kwargs={"k": k_value})

#     # Wrap with hybrid retriever if BM25 is available
#     bm25 = st.session_state.get("bm25")
#     all_splits = st.session_state.get("all_splits", [])
#     reranker = load_reranker() if st.session_state.get("use_reranker", True) else None

#     if bm25 is not None and all_splits:
#         retriever = HybridRetriever(
#             vector_retriever=vector_retriever,
#             bm25=bm25,
#             all_splits=all_splits,
#             k=k_value,
#             reranker=reranker,
#         )
#     else:
#         retriever = vector_retriever

#     # Store vectorstore ref for later cleanup
#     st.session_state.vectorstore = vectorstore

#     llm = LangchainOllama(
#         model=selected_model,
#         base_url=OLLAMA_BASE_URL,
#         keep_alive=OLLAMA_KEEP_ALIVE,
#     )

#     prompt_template = get_prompt_for_model(selected_model)

#     chain = (
#         {
#             "context": retriever | _format_docs,
#             "input": RunnablePassthrough(),
#             "chat_history": lambda _: get_chat_history(),
#             "num_docs": lambda _: len(st.session_state.get("indexed_files", [])),
#             "doc_names": lambda _: ", ".join(st.session_state.get("indexed_files", [])) or "No documents",
#         }
#         | prompt_template
#         | llm
#         | StrOutputParser()
#         | strip_thinking
#     )

#     print(get_chat_history())
#     return chain



# For llama.cpp server, we can use the same prompt templates and chain structure, just swap out the LLM class

# import streamlit as st
# from langchain_core.runnables import RunnablePassthrough
# from langchain_core.output_parsers import StrOutputParser
# from langchain_core.prompts import PromptTemplate

# from config import DEFAULT_K, MAX_K, K_PER_FILE
# from core.indexer import load_vectorstore
# from core.reranker import load_reranker
# from core.retriever import HybridRetriever
# from core.llamacpp import LlamaCppServerLLM
# from utils.text_utils import get_chat_history
# import re


# NEMO_PROMPT_TEMPLATE = PromptTemplate(
#     template="""You are an intelligent document assistant with memory and the ability to understand structured data.

# You have access to {num_docs} document(s): {doc_names}.

# Conversation History:
# ---------------------
# {chat_history}
# ---------------------

# Document Context:
# ---------------------
# {context}
# ---------------------

# Instructions:

# 1. Use conversation history for context continuity.

# 2. Carefully analyze the document context before answering.

# 3. Response must not include any internal reasoning, thought processes, or explanations. Only provide the final answer.


# 4. Table Handling:
#    - If the context contains structured data (tables, rows, repeated patterns), interpret it carefully.
#    - Convert messy or unstructured data into a clean markdown table when appropriate.
#    - Only include relevant columns for the query.
#    - Do NOT guess or invent missing values — use "Unknown" if needed.

# 5. STRICT OUTPUT RULES:
#    - Do NOT include <think> or </think>
#    - Do NOT include reasoning, explanations about thinking, or internal steps
#    - Output ONLY the final answer

# 6. Knowledge Rule:
#    - First use Document Context
#    - If not found, write EXACTLY:
#      "The provided document does not contain information about [topic]."
#    - Then answer using general knowledge

# 7. Formatting:
#    - Use bullet points or paragraphs where helpful
#    - If structured data is involved → use a clean markdown table
#    - Otherwise → normal text answer

# Query: {input}

# Response Format:

# <answer>
# [Final clean answer only]
# </answer>""",
#     input_variables=["context", "input", "chat_history", "num_docs", "doc_names"],
# )


# _PROMPT_TEMPLATE = PromptTemplate(
#     template="""You are an intelligent, helpful document assistant with memory and access to structured table data.

# You have access to {num_docs} document(s): {doc_names}.

# Conversation History:
# ---------------------
# {chat_history}
# ---------------------

# Document Context (may include text passages and markdown tables):
# ---------------------
# {context}
# ---------------------

# Instructions:
# 1. Use Conversation History to remember what was discussed before.
# 2. Carefully review the Document Context to answer the query.
# 3. When context includes [TABLE SOURCE: ...] blocks, read the markdown table carefully to answer questions about data, numbers, comparisons, or structured information. Mention which page/document the table came from.
# 4. **Flexible Knowledge (IMPORTANT)**:
#    - First, always prioritize the Document Context.
#    - If the Document Context does NOT contain the answer, write EXACTLY one line:
#      "The provided document does not contain information about [topic]."
#    - Then immediately provide a detailed, helpful answer using your own general knowledge.
# 5. Never refuse to answer. If the docs don't help, use your knowledge.
# 6. Formatting:
#    - Use bullet points or paragraphs where helpful
#    - If structured data is involved → use a clean markdown table
#    - Otherwise → normal text answer

# Query: {input}

# Please follow this format:

# <answer>
# [Your detailed and helpful final response]
# </answer>""",
#     input_variables=["context", "input", "chat_history", "num_docs", "doc_names"],
# )

# # Gemma prompt — simpler, no XML tags, direct "Answer:" suffix
# GEMMA_PROMPT_TEMPLATE = PromptTemplate(
#     template="""You are a helpful document assistant. Answer the user's question using the document context provided.
 
# Documents: {doc_names}
 
# Previous conversation:
# {chat_history}
 
# Relevant document content:
# {context}
 
# Rules:
# - Answer directly and concisely.
# - Use only the document context above to answer.
# - If the answer is not in the documents, say: "The provided document does not contain information about [topic]." Then answer from general knowledge if possible.
# - If the context contains tables, present relevant data as a clean markdown table.
# - Do NOT repeat these instructions or any placeholder text in your response.
 
# Question: {input}
 
# Answer:""",
#     input_variables=["context", "input", "chat_history", "num_docs", "doc_names"],
# )


# def get_prompt_for_model(model_name: str) -> PromptTemplate:
#     nemotron_models = ["nemotron", "nemotron-3-nano", "nemotron-3-nano:4b"]
#     if any(nm in model_name.lower() for nm in nemotron_models):
#         print(f"Custom prompt template loaded for {model_name}")
#         return NEMO_PROMPT_TEMPLATE
#     elif "gemma" in model_name.lower():
#         print(f"Gemma prompt template loaded for {model_name}")
#         return GEMMA_PROMPT_TEMPLATE
#     else:
#         print(f"Default prompt template loaded for {model_name}")
#         return _PROMPT_TEMPLATE


# def _format_docs(docs: list) -> str:
#     parts = []
#     for doc in docs:
#         doc_type = doc.metadata.get("type", "text")
#         source = doc.metadata.get("source_file", "unknown")
#         if doc_type == "table":
#             parts.append(f"[TABLE SOURCE: {source}]\n{doc.page_content}")
#         else:
#             parts.append(f"[TEXT SOURCE: {source}]\n{doc.page_content}")
#     return "\n\n---\n\n".join(parts)


# def strip_thinking(text: str) -> str:
#     if '</think>' in text:
#         text = text.split('</think>', 1)[-1]
#     text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
#     return text.strip()


# def build_query_engine(persist_dir: str, selected_model: str):
#     """
#     Build and return the full LCEL RAG chain, or None if prerequisites are missing.

#     Requires:
#       - A persisted ChromaDB vectorstore at persist_dir
#       - llama.cpp server running at http://127.0.0.1:8000
#     """
#     vectorstore = load_vectorstore(persist_dir)
#     if vectorstore is None:
#         return None

#     # Dynamic k based on number of indexed files
#     num_files = len(st.session_state.get("indexed_files", []))
#     k_value = max(DEFAULT_K, min(K_PER_FILE * max(num_files, 1), MAX_K))

#     vector_retriever = vectorstore.as_retriever(search_kwargs={"k": k_value})

#     # Wrap with hybrid retriever if BM25 is available
#     bm25 = st.session_state.get("bm25")
#     all_splits = st.session_state.get("all_splits", [])
#     reranker = load_reranker() if st.session_state.get("use_reranker", True) else None

#     if bm25 is not None and all_splits:
#         retriever = HybridRetriever(
#             vector_retriever=vector_retriever,
#             bm25=bm25,
#             all_splits=all_splits,
#             k=k_value,
#             reranker=reranker,
#         )
#     else:
#         retriever = vector_retriever

#     st.session_state.vectorstore = vectorstore

#     llm = LlamaCppServerLLM()

#     prompt_template = get_prompt_for_model(selected_model)

#     chain = (
#         {
#             "context": retriever | _format_docs,
#             "input": RunnablePassthrough(),
#             "chat_history": lambda _: get_chat_history(),
#             "num_docs": lambda _: len(st.session_state.get("indexed_files", [])),
#             "doc_names": lambda _: ", ".join(st.session_state.get("indexed_files", [])) or "No documents",
#         }
#         | prompt_template
#         | llm
#         | StrOutputParser()
#         #| strip_thinking
#     )

#     # print(get_chat_history()) Debug: log conversation history for troubleshooting
#     return chain

from core.memory import load_memory
import streamlit as st
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from config import DEFAULT_K, MAX_K, K_PER_FILE
from core.indexer import load_vectorstore
from core.reranker import load_reranker
from core.retriever import HybridRetriever
from core.llamacpp import LlamaCppServerLLM
from utils.text_utils import get_chat_history
import re


NEMO_PROMPT_TEMPLATE = PromptTemplate(
    template="""You are an intelligent document assistant with memory and the ability to understand structured data.

You have access to {num_docs} document(s): {doc_names}.

{user_memory}

Conversation History:
---------------------
{chat_history}
---------------------

Document Context:
---------------------
{context}
---------------------

Instructions:

1. Use conversation history for context continuity.

2. If user memory is provided above, use it to personalize your response.

3. Carefully analyze the document context before answering.

4. Response must not include any internal reasoning, thought processes, or explanations. Only provide the final answer.

5. Table Handling:
   - If the context contains structured data (tables, rows, repeated patterns), interpret it carefully.
   - Convert messy or unstructured data into a clean markdown table when appropriate.
   - Only include relevant columns for the query.
   - Do NOT guess or invent missing values — use "Unknown" if needed.

6. STRICT OUTPUT RULES:
   - Do NOT include <think> or </think>
   - Do NOT include reasoning, explanations about thinking, or internal steps
   - Output ONLY the final answer

7. Knowledge Rule:
   - First use Document Context
   - If not found, write EXACTLY:
     "The provided document does not contain information about [topic]."
   - Then answer using general knowledge

8. Formatting:
   - Use bullet points or paragraphs where helpful
   - If structured data is involved → use a clean markdown table
   - Otherwise → normal text answer

Query: {input}

Response Format:

<answer>
[Final clean answer only]
</answer>""",
    input_variables=["context", "input", "chat_history", "num_docs", "doc_names", "user_memory"],
)


# Default prompt — for Qwen, Mistral, LLaMA etc.
_PROMPT_TEMPLATE = PromptTemplate(
    template="""You are an intelligent, helpful document assistant with memory and access to structured table data.

You have access to {num_docs} document(s): {doc_names}.

{user_memory}

Conversation History:
---------------------
{chat_history}
---------------------

Document Context (may include text passages and markdown tables):
---------------------
{context}
---------------------

Instructions:
1. Use Conversation History to remember what was discussed before.
2. If user memory is provided above, use it to address the user personally.
3. Carefully review the Document Context to answer the query.
4. When context includes [TABLE SOURCE: ...] blocks, read the markdown table carefully to answer questions about data, numbers, comparisons, or structured information. Mention which page/document the table came from.
5. Flexible Knowledge (IMPORTANT):
   - First, always prioritize the Document Context.
   - If the Document Context does NOT contain the answer, write EXACTLY one line:
     "The provided document does not contain information about [topic]."
   - Then immediately provide a detailed, helpful answer using your own general knowledge.
6. Never refuse to answer. If the docs don't help, use your knowledge.
7. Format answers clearly with bullet points and paragraphs where helpful.

Query: {input}

Please follow this format:

<answer>
[Your detailed and helpful final response]
</answer>""",
    input_variables=["context", "input", "chat_history", "num_docs", "doc_names", "user_memory"],
)


# Gemma prompt — simpler, no XML tags, direct "Answer:" suffix
GEMMA_PROMPT_TEMPLATE = PromptTemplate(
    template="""You are a helpful document assistant. Answer the user's question using the document context provided.

Documents: {doc_names}

{user_memory}

Previous conversation:
{chat_history}

Relevant document content:
{context}

Rules:
- Answer directly and concisely.
- If user memory is provided, use it to personalise your response.
- Use only the document context above to answer.
- If the answer is not in the documents, say: "The provided document does not contain information about [topic]." Then answer from general knowledge if possible.
- If the context contains tables, present relevant data as a clean markdown table.
- Do NOT repeat these instructions or any placeholder text in your response.

Question: {input}

Answer:""",
    input_variables=["context", "input", "chat_history", "num_docs", "doc_names", "user_memory"],
)


def get_prompt_for_model(model_name: str) -> PromptTemplate:
    name = model_name.lower()
    nemotron_models = ["nemotron", "nemotron-3-nano"]
    gemma_models = ["gemma", "default"]  # llama.cpp default is Gemma in this deployment

    if any(nm in name for nm in nemotron_models):
        print(f"Nemotron prompt template loaded for {model_name}")
        return NEMO_PROMPT_TEMPLATE
    elif any(gm in name for gm in gemma_models):
        print(f"Gemma prompt template loaded for {model_name}")
        return GEMMA_PROMPT_TEMPLATE
    else:
        print(f"Default (Gemma) prompt template loaded for {model_name}")
        return GEMMA_PROMPT_TEMPLATE


def _clean_context(text: str) -> str:
    # Replace <br> with newline so cell content stays readable
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    # Remove invisible characters
    text = text.replace('\u00a0', ' ').replace('\u200b', '')
    text = re.sub(r' {2,}', ' ', text)

    # Deduplicate repeated markdown table rows (same line appearing 2+ times)
    lines = text.split('\n')
    seen_lines = set()
    deduped = []
    for line in lines:
        stripped = line.strip()
        # Only deduplicate table rows (lines starting with |)
        if stripped.startswith('|'):
            if stripped in seen_lines:
                continue
            seen_lines.add(stripped)
        deduped.append(line)

    return '\n'.join(deduped).strip()


def _format_docs(docs: list) -> str:
    parts = []
    for doc in docs:
        doc_type = doc.metadata.get("type", "text")
        source = doc.metadata.get("source_file", "unknown")
        content = _clean_context(doc.page_content)
        if doc_type == "table":
            parts.append(f"[TABLE SOURCE: {source}]\n{content}")
        else:
            parts.append(f"[TEXT SOURCE: {source}]\n{content}")
    return "\n\n---\n\n".join(parts)


def strip_thinking(text: str) -> str:
    # Strip <think> blocks
    if '</think>' in text:
        text = text.split('</think>', 1)[-1]
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Strip <answer> tags if present (used by default/nemo templates)
    text = re.sub(r'<answer>\s*', '', text)
    text = re.sub(r'\s*</answer>', '', text)
    text = text.strip()

    # Deduplicate repeated paragraphs (Qwen repetition fix)
    # Split on double newline, keep only first occurrence of each paragraph
    paragraphs = text.split("\n\n")
    seen = set()
    deduped = []
    for para in paragraphs:
        key = para.strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(para)
    return "\n\n".join(deduped).strip()


def build_query_engine(persist_dir: str, selected_model: str):
    vectorstore = load_vectorstore(persist_dir)
    if vectorstore is None:
        return None

    # Dynamic k based on number of indexed files
    num_files = len(st.session_state.get("indexed_files", []))
    k_value = max(DEFAULT_K, min(K_PER_FILE * max(num_files, 1), MAX_K))

    vector_retriever = vectorstore.as_retriever(search_kwargs={"k": k_value})

    # Wrap with hybrid retriever if BM25 is available
    bm25 = st.session_state.get("bm25")
    all_splits = st.session_state.get("all_splits", [])
    reranker = load_reranker() if st.session_state.get("use_reranker", True) else None

    if bm25 is not None and all_splits:
        retriever = HybridRetriever(
            vector_retriever=vector_retriever,
            bm25=bm25,
            all_splits=all_splits,
            k=k_value,
            reranker=reranker,
        )
    else:
        retriever = vector_retriever

    st.session_state.vectorstore = vectorstore

    llm = LlamaCppServerLLM()

    prompt_template = get_prompt_for_model(selected_model)

    chain = (
        {
            "context": retriever | _format_docs,
            "input": RunnablePassthrough(),
            "chat_history": lambda _: get_chat_history(),
            "num_docs": lambda _: len(st.session_state.get("indexed_files", [])),
            "doc_names": lambda _: ", ".join(st.session_state.get("indexed_files", [])) or "No documents",
        }
        | prompt_template
        | llm
        | StrOutputParser()
        | strip_thinking
    )

    # print(get_chat_history())
    return chain