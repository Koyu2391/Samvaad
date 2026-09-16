"""
Factory for LLM providers.
Config-driven: set LLM_PROVIDER env var to 'llama.cpp' or 'vllm'.
"""
import os
from functools import lru_cache

from langchain_core.language_models.llms import LLM
from core.llm.base import LLMProvider


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    """Return a cached singleton LLM provider based on env config."""
    provider_name = os.getenv("LLM_PROVIDER", "llama.cpp").lower()

    if provider_name in ("llama.cpp", "llamacpp", "llama_cpp"):
        from core.llm.llamacpp_provider import LlamaCppProvider
        return LlamaCppProvider(
            base_url=os.getenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8000"),
            model=os.getenv("LLAMACPP_MODEL", "unsloth/Qwen3.5-9B-GGUF"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        )

    if provider_name == "vllm":
        from core.llm.vllm_provider import VLLMProvider
        return VLLMProvider(
            model_name=os.getenv("VLLM_MODEL", "meta-llama/Llama-2-13b-hf"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER='{provider_name}'. Use 'llama.cpp' or 'vllm'."
    )


def get_llm() -> LLM:
    """Convenience: return the LangChain LLM directly."""
    return get_provider().as_langchain_llm()
