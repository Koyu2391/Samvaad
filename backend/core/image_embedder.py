

import numpy as np
import torch
import open_clip

from config import CLIP_MODEL_NAME, CLIP_PRETRAINED


class ImageEmbedder:
    """Wraps OpenCLIP to create image and text embeddings."""

    def __init__(self):
        # Device selection: MPS → CPU
        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
            print("[image_embedder] Using MPS (Apple Silicon GPU)")
        else:
            self.device = torch.device("cpu")
            print("[image_embedder] MPS not available — using CPU")

        print(f"[image_embedder] Loading OpenCLIP {CLIP_MODEL_NAME} / {CLIP_PRETRAINED} …")
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL_NAME,
            pretrained=CLIP_PRETRAINED,
        )
        self.model = self.model.to(self.device)
        self.model.eval()

        self.tokenizer = open_clip.get_tokenizer(CLIP_MODEL_NAME)
        print("[image_embedder] OpenCLIP ready.")

    # ── Image embeddings ──────────────────────────────────────────────────────

    def embed_images(self, pil_images: list) -> np.ndarray:
        """
        Embed a list of PIL Images.
        Returns float32 ndarray of shape (N, 512), L2-normalised.
        """
        if not pil_images:
            return np.empty((0, 512), dtype=np.float32)

        tensors = torch.stack(
            [self.preprocess(img) for img in pil_images]
        ).to(self.device)

        with torch.no_grad(), torch.autocast(device_type="cpu"):
            features = self.model.encode_image(tensors)
            features = features / features.norm(dim=-1, keepdim=True)

        return features.cpu().float().numpy()

    # ── Text embedding (query) ────────────────────────────────────────────────

    def embed_text(self, query: str) -> np.ndarray:
        """
        Embed a text string for image retrieval.
        Returns float32 ndarray of shape (1, 512), L2-normalised.
        """
        tokens = self.tokenizer([query]).to(self.device)

        with torch.no_grad(), torch.autocast(device_type="cpu"):
            features = self.model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True)

        return features.cpu().float().numpy()

    # ── Similarity ────────────────────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(query_emb: np.ndarray, image_embs: np.ndarray) -> np.ndarray:
        """Dot product (both already L2-normalised) → cosine similarity."""
        return (query_emb @ image_embs.T).squeeze(0)


# ── Singleton ─────────────────────────────────────────────────────────────────
_embedder: ImageEmbedder | None = None


def get_embedder() -> ImageEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = ImageEmbedder()
    return _embedder
