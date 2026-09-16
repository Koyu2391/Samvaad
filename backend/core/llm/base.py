"""
Abstract LLM provider interface.

All providers expose:
  - generate(prompt, **kwargs) -> str
  - as_langchain_llm() -> LangChain LLM (for use in chains / graphs)
  - info() -> dict with model metadata
"""
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models.llms import LLM


class LLMProvider(ABC):
    """Abstract base class for all LLM backends."""

    name: str = "abstract"

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from a prompt synchronously."""
        ...

    @abstractmethod
    def as_langchain_llm(self) -> LLM:
        """Return a LangChain-compatible LLM for use in LCEL/LangGraph."""
        ...

    def info(self) -> dict:
        return {"provider": self.name}
