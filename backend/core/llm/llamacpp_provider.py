"""
llama.cpp provider — wraps the existing LlamaCppServerLLM as a Provider.
"""
from typing import Any

from langchain_core.language_models.llms import LLM

from core.llm.base import LLMProvider
from core.llamacpp import LlamaCppServerLLM


class LlamaCppProvider(LLMProvider):
    name = "llama.cpp"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        model: str = "unsloth/Qwen3.5-9B-GGUF",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        top_p: float = 0.95,
        timeout: int = 1000,
    ):
        self._llm = LlamaCppServerLLM(
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout=timeout,
        )

    def generate(self, prompt: str, **kwargs: Any) -> str:
        return self._llm.invoke(prompt)

    def as_langchain_llm(self) -> LLM:
        return self._llm

    def info(self) -> dict:
        return {
            "provider": self.name,
            "base_url": self._llm.base_url,
            "model": self._llm.model,
            "max_tokens": self._llm.max_tokens,
            "temperature": self._llm.temperature,
        }
