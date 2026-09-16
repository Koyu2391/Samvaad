"""
vLLM provider — stub for future NVIDIA GPU deployment.

To activate later:
  1. pip install vllm
  2. Set LLM_PROVIDER=vllm in env
  3. Set VLLM_MODEL=meta-llama/Llama-2-13b-hf (or your model)
"""
from typing import Any
from langchain_core.language_models.llms import LLM
from core.llm.base import LLMProvider


class VLLMProvider(LLMProvider):
    name = "vllm"

    def __init__(self, model_name: str = "meta-llama/Llama-2-13b-hf", **kwargs):
        try:
            from vllm import LLM as VLLMEngine, SamplingParams
        except ImportError as e:
            raise RuntimeError(
                "vllm not installed. Install with `pip install vllm` on an NVIDIA host."
            ) from e
        self._engine = VLLMEngine(
            model=model_name,
            trust_remote_code=kwargs.get("trust_remote_code", True),
            gpu_memory_utilization=kwargs.get("gpu_memory_utilization", 0.9),
            tensor_parallel_size=kwargs.get("tensor_parallel_size", 1),
        )
        self._sampling = SamplingParams(
            temperature=kwargs.get("temperature", 0.2),
            top_p=kwargs.get("top_p", 0.95),
            max_tokens=kwargs.get("max_tokens", 1024),
        )
        self._model_name = model_name

    def generate(self, prompt: str, **kwargs: Any) -> str:
        outputs = self._engine.generate([prompt], self._sampling)
        return outputs[0].outputs[0].text

    def as_langchain_llm(self) -> LLM:
        from langchain_core.language_models.llms import LLM as BaseLLM
        from langchain_core.callbacks.manager import CallbackManagerForLLMRun
        from typing import Optional, List

        engine = self._engine
        sampling = self._sampling

        class _VLLMLangchain(BaseLLM):
            @property
            def _llm_type(self) -> str:
                return "vllm"

            def _call(
                self,
                prompt: str,
                stop: Optional[List[str]] = None,
                run_manager: Optional[CallbackManagerForLLMRun] = None,
                **kwargs,
            ) -> str:
                outputs = engine.generate([prompt], sampling)
                return outputs[0].outputs[0].text

        return _VLLMLangchain()

    def info(self) -> dict:
        return {"provider": self.name, "model": self._model_name}
