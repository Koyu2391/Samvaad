from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from pydantic import Field

from utils.text_utils import tokenize


class HybridRetriever(BaseRetriever):
    vector_retriever: object = Field()
    bm25: object = Field(default=None)
    all_splits: list = Field(default_factory=list)
    k: int = Field(default=8)
    reranker: object = Field(default=None)

    class Config:
        arbitrary_types_allowed = True

    # RRF fusion
    def rrf_fusion(self, vector_docs: list, bm25_docs: list, k: int = 60) -> list:
        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        for rank, doc in enumerate(vector_docs):
            key = doc.page_content
            doc_map[key] = doc
            scores[key] = scores.get(key, 0) + 1 / (k + rank)

        for rank, doc in enumerate(bm25_docs):
            key = doc.page_content
            doc_map[key] = doc
            scores[key] = scores.get(key, 0) + 1 / (k + rank)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_map[key] for key, _ in ranked]

    # Main retrieval
    def _get_relevant_documents(self, query: str) -> list[Document]:

        # 1. Dense vector search
        try:
            vector_docs = self.vector_retriever.get_relevant_documents(query)
        except Exception:
            vector_docs = []

        # 2. BM25 keyword search
        bm25_docs = []
        if self.bm25 is not None:
            try:
                tokenized_query = tokenize(query)
                raw_scores = self.bm25.get_scores(tokenized_query)

                # Boost table chunks — they tend to be under-scored by BM25
                boosted: list[float] = []
                for i, score in enumerate(raw_scores):
                    if self.all_splits[i].metadata.get("type") == "table":
                        score *= 1.5
                    boosted.append(score)

                top_indices = sorted(
                    range(len(boosted)),
                    key=lambda i: boosted[i],
                    reverse=True,
                )[: self.k * 3]

                bm25_docs = [self.all_splits[i] for i in top_indices]
            except Exception:
                bm25_docs = []

        # 3. RRF fusion
        merged = self.rrf_fusion(vector_docs, bm25_docs)

        # 4. Reranking via FlashRank / CrossEncoder wrapper (optional)
        if self.reranker is not None and len(merged) > 1:
            try:
                # New Reranker wrapper exposes .rerank(query, docs, top_k)
                if hasattr(self.reranker, "rerank"):
                    merged = self.reranker.rerank(query, merged, top_k=self.k)
                else:
                    # Legacy CrossEncoder fallback
                    pairs = [[query, doc.page_content] for doc in merged]
                    rerank_scores = self.reranker.predict(pairs)
                    merged = [
                        doc
                        for _, doc in sorted(
                            zip(rerank_scores, merged),
                            key=lambda x: x[0],
                            reverse=True,
                        )
                    ]
            except Exception as e:
                print(f"[retriever] rerank failed (non-fatal): {e}")

        return merged[: self.k]