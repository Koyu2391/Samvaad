"""
LangGraph orchestration for the Financial RAG pipeline.

Workflow:
    expand_query → hybrid_retrieve → rerank → assemble_context → generate → post_process

State flows through nodes. Each node mutates and returns the next state.

Fall-through: if any optional component (expander, reranker) is unavailable,
the graph degrades gracefully.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langgraph.graph import StateGraph, END

from core.llm import get_llm
from core.query_engine import (
    get_prompt_for_model,
    _format_docs,
    strip_thinking,
)


# ── Graph state ────────────────────────────────────────────────────────────

class GraphState(TypedDict, total=False):
    """Mutable state passed between nodes."""
    # Inputs
    query: str
    model_name: str
    chat_history: str
    num_docs: int
    doc_names: str
    user_memory: str

    # Components (injected per-invocation)
    retriever: Any
    reranker: Any

    # Intermediate
    expanded_queries: List[str]
    retrieved_docs: List[Document]
    reranked_docs: List[Document]
    context: str

    # Output
    answer: str
    sources: List[dict]


# ── Query expansion ────────────────────────────────────────────────────────

_QUERY_EXPANSION_PROMPT = PromptTemplate.from_template(
    """Generate 2 alternative phrasings of the following financial question to improve retrieval.
Return only the alternatives, one per line, no numbering, no commentary.

Question: {query}

Alternative phrasings:"""
)


def expand_query_node(state: GraphState) -> GraphState:
    """Use the LLM to generate query variants (cheap operation, single call)."""
    query = state["query"]
    expansions: List[str] = [query]

    try:
        llm = get_llm()
        prompt = _QUERY_EXPANSION_PROMPT.format(query=query)
        raw = llm.invoke(prompt)
        for line in str(raw).strip().splitlines():
            line = line.strip("-*•0123456789. ").strip()
            if line and line.lower() != query.lower():
                expansions.append(line)
            if len(expansions) >= 3:
                break
    except Exception as e:
        print(f"[graph] query expansion failed (non-fatal): {e}")

    state["expanded_queries"] = expansions
    return state


# ── Hybrid retrieval ───────────────────────────────────────────────────────

def hybrid_retrieve_node(state: GraphState) -> GraphState:
    """Retrieve docs using the configured retriever for each query variant.
    Results are deduplicated by content hash."""
    retriever = state.get("retriever")
    if retriever is None:
        state["retrieved_docs"] = []
        return state

    queries = state.get("expanded_queries") or [state["query"]]
    seen: set[str] = set()
    out: List[Document] = []

    for q in queries:
        try:
            docs = (
                retriever.invoke(q)
                if hasattr(retriever, "invoke")
                else retriever.get_relevant_documents(q)
            )
            for d in docs:
                key = d.page_content[:200]  # dedupe by content prefix
                if key in seen:
                    continue
                seen.add(key)
                out.append(d)
        except Exception as e:
            print(f"[graph] retrieval failed for '{q[:40]}...': {e}")

    state["retrieved_docs"] = out
    return state


# ── Reranking ──────────────────────────────────────────────────────────────

def rerank_node(state: GraphState) -> GraphState:
    """Apply FlashRank/CrossEncoder reranking on the merged candidate pool."""
    reranker = state.get("reranker")
    docs = state.get("retrieved_docs", [])

    if reranker is None or not docs:
        state["reranked_docs"] = docs
        return state

    try:
        if hasattr(reranker, "rerank"):
            ranked = reranker.rerank(state["query"], docs, top_k=10)
        else:
            ranked = docs[:10]
        state["reranked_docs"] = ranked
    except Exception as e:
        print(f"[graph] rerank failed: {e}")
        state["reranked_docs"] = docs[:10]

    return state


# ── Context assembly ───────────────────────────────────────────────────────

def assemble_context_node(state: GraphState) -> GraphState:
    """Format the top docs into the context string and collect source metadata."""
    docs = state.get("reranked_docs", [])
    state["context"] = _format_docs(docs)

    seen: set[tuple] = set()
    sources: List[dict] = []
    for d in docs:
        key = (d.metadata.get("source_file"), d.metadata.get("page"))
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "file": d.metadata.get("source_file", "unknown"),
            "page": d.metadata.get("page"),
            "type": d.metadata.get("type", "text"),
            "financial_section": d.metadata.get("financial_section"),
            "rerank_score": d.metadata.get("rerank_score"),
        })
    state["sources"] = sources
    return state


# ── Generation ─────────────────────────────────────────────────────────────

def generate_node(state: GraphState) -> GraphState:
    """Final LLM call with the financial-aware prompt template."""
    prompt_template = get_prompt_for_model(state.get("model_name", "default"))
    llm = get_llm()

    # Compose the prompt with all variables expected by the existing templates
    inputs = {
        "context":      state.get("context", ""),
        "input":        state["query"],
        "chat_history": state.get("chat_history", ""),
        "num_docs":     state.get("num_docs", 0),
        "doc_names":    state.get("doc_names", "No documents"),
        "user_memory":  state.get("user_memory", ""),
    }

    try:
        rendered = prompt_template.format(**{k: v for k, v in inputs.items()
                                              if k in prompt_template.input_variables})
        raw = llm.invoke(rendered)
        state["answer"] = strip_thinking(str(raw))
    except Exception as e:
        state["answer"] = f"Error generating response: {e}"

    return state


# ── Graph builder ──────────────────────────────────────────────────────────

def build_financial_rag_graph():
    """Build and compile the LangGraph for the financial RAG pipeline.
    Returns a compiled graph that can be `.invoke(state)`-ed."""
    workflow = StateGraph(GraphState)

    workflow.add_node("expand_query", expand_query_node)
    workflow.add_node("retrieve", hybrid_retrieve_node)
    workflow.add_node("rerank", rerank_node)
    workflow.add_node("assemble_context", assemble_context_node)
    workflow.add_node("generate", generate_node)

    workflow.set_entry_point("expand_query")
    workflow.add_edge("expand_query", "retrieve")
    workflow.add_edge("retrieve", "rerank")
    workflow.add_edge("rerank", "assemble_context")
    workflow.add_edge("assemble_context", "generate")
    workflow.add_edge("generate", END)

    return workflow.compile()


# Cached singleton graph (compile once)
_graph_singleton = None


def _get_graph():
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = build_financial_rag_graph()
    return _graph_singleton


def run_query(
    query: str,
    retriever: Any,
    reranker: Any = None,
    model_name: str = "default",
    chat_history: str = "",
    num_docs: int = 0,
    doc_names: str = "No documents",
    user_memory: str = "",
) -> dict:
    """
    Run the full LangGraph pipeline for a single query.
    Returns {answer, sources}.
    """
    graph = _get_graph()
    initial: GraphState = {
        "query":        query,
        "model_name":   model_name,
        "chat_history": chat_history,
        "num_docs":     num_docs,
        "doc_names":    doc_names,
        "user_memory":  user_memory,
        "retriever":    retriever,
        "reranker":     reranker,
    }
    final_state = graph.invoke(initial)
    return {
        "answer":  final_state.get("answer", ""),
        "sources": final_state.get("sources", []),
        "context": final_state.get("context", ""),
        "expanded_queries": final_state.get("expanded_queries", [query]),
    }
