import base64
import requests
from typing import Optional, List, Any

from langchain_core.language_models.llms import LLM
from langchain_core.callbacks.manager import CallbackManagerForLLMRun


class LlamaCppServerLLM(LLM):
    base_url: str = "http://127.0.0.1:8000"
    model: str = "unsloth/Qwen3.5-9B-GGUF"
    temperature: float = 0.2
    max_tokens: int = 4096
    top_p: float = 0.95
    stop: List[str] = [
        "<|im_end|>",
        "<|endoftext|>",
        "</answer>",
    ]
    timeout: int = 1000

    @property
    def _llm_type(self) -> str:
        return "llama_cpp_server"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        stop_sequences = stop or self.stop

        payload = {
            "prompt": prompt,
            "temperature": self.temperature,
            "n_predict": self.max_tokens,
            "top_p": self.top_p,
            "stop": stop_sequences,
            "stream": False,
        }

        try:
            response = requests.post(
                f"{self.base_url}/v1/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()

            # Safety check
            if "choices" not in data or not data["choices"]:
                raise RuntimeError(f"Invalid response format: {data}")

            return data["choices"][0]["text"].strip()

        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to llama.cpp server at {self.base_url}"
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"llama.cpp server timed out after {self.timeout}s"
            )
        except requests.exceptions.HTTPError as e:
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise RuntimeError(f"llama.cpp server error: {e} | {err}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error: {e}")

    @property
    def _identifying_params(self) -> dict:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    # ── Multimodal: chat with images via /v1/chat/completions ──────────────

    def chat_with_images(
        self,
        text_prompt: str,
        image_base64_list: list[str],
        system_prompt: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """
        Send a multimodal request to llama.cpp's /v1/chat/completions endpoint,
        passing images along with text so the vision-capable model can 'see' them.

        Args:
            text_prompt:      The user's text query.
            image_base64_list:  List of base64-encoded PNG image strings.
            system_prompt:    Optional system-level instruction.
            max_tokens:       Max tokens for the response.

        Returns:
            The model's text response.
        """
        content_parts: list[dict] = []

        if system_prompt:
            content_parts.append({"type": "text", "text": system_prompt + "\n\n"})

        content_parts.append({"type": "text", "text": text_prompt})

        for b64 in image_base64_list:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": content_parts,
                }
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "top_p": self.top_p,
            "stop": self.stop,
            "stream": False,
        }

        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()

            if "choices" not in data or not data["choices"]:
                raise RuntimeError(f"Invalid multimodal response: {data}")

            return data["choices"][0]["message"]["content"].strip()

        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to llama.cpp server at {self.base_url}"
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"llama.cpp server timed out after {self.timeout}s"
            )
        except requests.exceptions.HTTPError as e:
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise RuntimeError(f"llama.cpp server error: {e} | {err}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error: {e}")