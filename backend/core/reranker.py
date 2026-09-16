"""
Document reranker.

Primary: FlashRank (fast, CPU-optimized, no heavy GPU model).
Fallback: sentence-transformers CrossEncoder.
"""
from functools import lru_cache
from typing import List, Optional

from langchain_core.documents import Document


class Reranker:
    """Wraps either FlashRank or a CrossEncoder behind a common API."""

    def __init__(self, backend: str = "flashrank", model: Optional[str] = None):
        self.backend = backend
        self.model_name = model
        self._impl = None
        self._load()

    def _load(self):
        if self.backend == "flashrank":
            try:
                from flashrank import Ranker
                self._impl = Ranker(
                    model_name=self.model_name or "ms-marco-MiniLM-L-12-v2",
                    cache_dir="/tmp/flashrank_cache",
                )
                print(f"[reranker] Loaded FlashRank (model={self.model_name or 'ms-marco-MiniLM-L-12-v2'})")
                return
            except ImportError:
                print("[reranker] FlashRank not installed; falling back to CrossEncoder")
                self.backend = "crossencoder"

        if self.backend == "crossencoder":
            try:
                from sentence_transformers import CrossEncoder
                self._impl = CrossEncoder(
                    self.model_name or "cross-encoder/ms-marco-MiniLM-L-6-v2"
                )
                print(f"[reranker] Loaded CrossEncoder")
                return
            except Exception as e:
                print(f"[reranker] CrossEncoder load failed: {e}")
                self._impl = None

    def is_ready(self) -> bool:
        return self._impl is not None

    def rerank(
        self,
        query: str,
        docs: List[Document],
        top_k: Optional[int] = None,
    ) -> List[Document]:
        """Score and reorder docs by relevance to query. Returns top_k (or all)."""
        if not self.is_ready() or not docs:
            return docs[: top_k] if top_k else docs

        try:
            if self.backend == "flashrank":
                from flashrank import RerankRequest
                passages = [
                    {"id": i, "text": d.page_content, "meta": d.metadata}
                    for i, d in enumerate(docs)
                ]
                req = RerankRequest(query=query, passages=passages)
                ranked = self._impl.rerank(req)
                # ranked is sorted desc by relevance score
                reordered = []
                for r in ranked:
                    idx = r.get("id")
                    if idx is not None and 0 <= idx < len(docs):
                        d = docs[idx]
                        d.metadata["rerank_score"] = float(r.get("score", 0.0))
                        reordered.append(d)
                if top_k:
                    return reordered[:top_k]
                return reordered

            # CrossEncoder path
            pairs = [(query, d.page_content) for d in docs]
            scores = self._impl.predict(pairs)
            scored = list(zip(docs, scores))
            scored.sort(key=lambda x: x[1], reverse=True)
            out = []
            for d, s in scored:
                d.metadata["rerank_score"] = float(s)
                out.append(d)
            if top_k:
                return out[:top_k]
            return out

        except Exception as e:
            print(f"[reranker] rerank failed: {e}; returning original order")
            return docs[: top_k] if top_k else docs


@lru_cache(maxsize=1)
def load_reranker() -> Optional[Reranker]:
    """Return a cached singleton reranker, or None if neither backend installs."""
    rr = Reranker(backend="flashrank")
    return rr if rr.is_ready() else None
