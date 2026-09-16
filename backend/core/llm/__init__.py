"""
LLM Provider abstraction.

Usage:
    from core.llm import get_llm
    llm = get_llm()  # returns a LangChain-compatible LLM (configured via env)
"""
from core.llm.base import LLMProvider
from core.llm.factory import get_llm, get_provider

__all__ = ["LLMProvider", "get_llm", "get_provider"]
