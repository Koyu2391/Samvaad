# import os
# import ollama

# from config import DEFAULT_MODELS, LOCAL_MODEL_DIR


# def get_available_models() -> list[str]:
#     """
#     Fetch the list of locally available Ollama models.
#     Falls back to DEFAULT_MODELS if the Ollama daemon is unreachable.
#     """
#     try:
#         models_info = ollama.list()
#         models = [m["name"] for m in models_info.get("models", [])]
#         if models:
#             return models
#     except Exception:
#         pass
#     return DEFAULT_MODELS


# def check_embedding_model() -> tuple[bool, str]:
#     """
#     Check whether the local embedding model directory exists.

#     Returns:
#         (exists: bool, path: str)
#     """
#     exists = os.path.exists(LOCAL_MODEL_DIR)
#     return exists, LOCAL_MODEL_DIR



# For Ollama, we can use the same prompt templates and chain structure, just swap out the LLM class
import os
import requests

from config import DEFAULT_MODELS, LOCAL_MODEL_DIR


def get_available_models() -> list[str]:

    try:
        response = requests.get("http://127.0.0.1:8000/v1/models", timeout=3)
        response.raise_for_status()
        data = response.json()
        models = [m["id"] for m in data.get("data", [])]
        if models:
            return models
    except Exception:
        pass
    return DEFAULT_MODELS


def check_embedding_model() -> tuple[bool, str]:

    exists = os.path.exists(LOCAL_MODEL_DIR)
    return exists, LOCAL_MODEL_DIR