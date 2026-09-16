"""
image_store.py — In-memory image vector store for Multimodal RAG.

Instead of adding a second Chroma collection (which complicates the schema),
this module uses a lightweight numpy-based store held in session memory.
It stores:
    - embeddings:  np.ndarray  shape (N, 512)
    - metadata:    list of dicts with keys: img_id, path, filename, page, width, height, ocr_text, caption

API:
    store = ImageStore()
    store.add(image_records, embeddings)        -> None
    store.search(query_emb, k, query_text=None) -> list[dict]  top-k records (with score)
    store.clear()                               -> None
    store.is_empty()                            -> bool
"""

import numpy as np
import re
from typing import Optional


def _tokenize_simple(text: str) -> set[str]:
    """Simple tokenization for text matching."""
    text = text.lower()
    # Remove special characters but keep numbers and letters
    text = re.sub(r'[^a-z0-9\s√∑∏±×÷≈≤≥]', ' ', text)
    tokens = set(text.split())
    return tokens


def _extract_page_number_from_query(query: str) -> Optional[int]:
    """Extract the page number from a query like 'page 3', 'page three', etc."""
    match = re.search(r'\bpage\s+(\d+)\b', query.lower())
    if match:
        return int(match.group(1))

    match = re.search(r'\bpage\s+(one|two|three|four|five|six|seven|eight|nine|ten)\b', query.lower())
    word_map = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    }
    if match:
        return word_map.get(match.group(1))
    return None


def _extract_number_from_query(query: str) -> Optional[int]:
    """Extract figure/table number from query like 'show me table 2' or 'figure 1'."""
    # Patterns to extract numbers
    patterns = [
        r'\b(?:table|figure|fig\.?)\s*(\d+)',
        r'\b(\d+)\s*(?:st|nd|rd|th)?\s*(?:table|figure)',
    ]
    for pattern in patterns:
        match = re.search(pattern, query.lower())
        if match:
            return int(match.group(1))
    return None


def _requested_visual_type(query: str) -> Optional[str]:
    """Infer preferred visual type from query text."""
    q = query.lower()
    if re.search(r"\btable\b", q):
        return "table"
    if re.search(r"\b(image|figure|fig\.?|diagram|chart|graph|visualization|visual)\b", q):
        return "figure"
    return None


def _compute_text_similarity(query: str, text: str, caption: str = "", img_type: str = "figure") -> float:
    """
    Compute text similarity using Jaccard + keyword matching + number matching.
    Returns a score between 0 and 1.
    """
    if not text and not caption:
        return 0.0

    query_lower = query.lower()
    combined_text = f"{text} {caption}".lower()

    # Check for exact number match in caption (e.g., "Table 2" matching query "show me table 2")
    query_num = _extract_number_from_query(query_lower)
    if query_num is not None and caption:
        caption_num_match = re.search(r'(?:table|figure|fig\.?)\s*(\d+)', caption.lower())
        if caption_num_match and int(caption_num_match.group(1)) == query_num:
            # Exact number match - very strong signal!
            return 0.95

    query_tokens = _tokenize_simple(query_lower)
    text_tokens = _tokenize_simple(combined_text)

    if not query_tokens:
        return 0.0

    # Jaccard similarity
    intersection = query_tokens & text_tokens
    union = query_tokens | text_tokens
    jaccard = len(intersection) / len(union) if union else 0.0

    # Type matching: if query asks for "table" and this is a table, boost
    if 'table' in query_lower and img_type == 'table':
        jaccard += 0.2
    elif ('figure' in query_lower or 'fig' in query_lower) and img_type == 'figure':
        jaccard += 0.1

    # Keyword boost: if query contains specific technical terms, boost matches
    technical_terms = {'table', 'figure', 'fig', 'equation', 'formula',
                       'attention', 'scaling', 'matrix', 'vector', 'diagram',
                       'bleu', 'score', 'translation', 'transformer',
                       'query', 'key', 'value', 'softmax', 'head', 'multi-head',
                       'dk', 'sqrt', 'architecture'}
    query_technical = query_tokens & technical_terms
    text_technical = text_tokens & technical_terms
    tech_overlap = len(query_technical & text_technical)
    tech_boost = min(0.3, tech_overlap * 0.1)

    # Caption overlap is often a stronger signal than OCR text.
    caption_tokens = _tokenize_simple(caption or "")
    caption_overlap = len(query_tokens & caption_tokens)
    caption_boost = min(0.25, caption_overlap * 0.08)

    return min(1.0, jaccard + tech_boost + caption_boost)


class ImageStore:
    """Lightweight numpy-backed image embedding store (per session, in memory)."""

    def __init__(self):
        self._embeddings: np.ndarray | None = None   # (N, 512) float32
        self._metadata:   list[dict]         = []

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def add(self, records: list[dict], embeddings: np.ndarray) -> None:
        """
        Add image records and their embeddings to the store.

        Args:
            records:    list of dicts from image_utils.extract_images_from_pdf()
            embeddings: np.ndarray shape (len(records), 512), L2-normalised
        """
        if len(records) == 0 or embeddings.shape[0] == 0:
            return

        if self._embeddings is None:
            self._embeddings = embeddings.astype(np.float32)
        else:
            self._embeddings = np.vstack(
                [self._embeddings, embeddings.astype(np.float32)]
            )

        self._metadata.extend(records)
        print(f"[image_store] Added {len(records)} images. Total: {len(self._metadata)}")

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def search(
        self,
        query_emb: np.ndarray,
        k: int = 3,
        query_text: Optional[str] = None,
        preferred_type: Optional[str] = None,
        preferred_pages: Optional[set[int]] = None,
    ) -> list[dict]:
        """
        Find the top-k images most similar to query using hybrid search.

        Args:
            query_emb:   shape (1, 512) float32, L2-normalised (visual embedding)
            k:           number of results
            query_text:      optional text query for hybrid text+visual search
            preferred_type:  optional "table" or "figure" intent
            preferred_pages: optional set of page numbers to boost

        Returns:
            list of metadata dicts, each with an added "score" field, sorted desc.
        """
        if self._embeddings is None or len(self._metadata) == 0:
            return []

        # Visual similarity (cosine similarity via dot product of normalized vectors)
        visual_scores: np.ndarray = (query_emb @ self._embeddings.T).squeeze(0)

        # If query_text provided, compute hybrid scores
        if query_text:
            text_scores = np.zeros(len(self._metadata))
            for idx, meta in enumerate(self._metadata):
                text_scores[idx] = _compute_text_similarity(
                    query_text,
                    meta.get('ocr_text', ''),
                    meta.get('caption', ''),
                    meta.get('type', 'figure')
                )

            # Hybrid scoring with adaptive weighting
            # If text score is very high (e.g., exact number match), prioritize it heavily
            # Otherwise balance visual and text
            hybrid_scores = np.zeros(len(self._metadata))
            inferred_type = preferred_type or _requested_visual_type(query_text)
            for idx in range(len(self._metadata)):
                if text_scores[idx] > 0.85:  # Very strong text match (e.g., "Table 2")
                    visual_weight = 0.3
                    text_weight = 0.7
                elif text_scores[idx] > 0.3:  # Good text match
                    visual_weight = 0.5
                    text_weight = 0.5
                elif text_scores[idx] > 0.1:  # Weak text match
                    visual_weight = 0.7
                    text_weight = 0.3
                else:  # No text match - rely on visual
                    visual_weight = 0.95
                    text_weight = 0.05

                hybrid_scores[idx] = (visual_weight * visual_scores[idx] +
                                      text_weight * text_scores[idx])

                # Prefer requested type (table vs figure/diagram)
                item_type = self._metadata[idx].get("type", "figure")
                if inferred_type == "table" and item_type == "table":
                    hybrid_scores[idx] += 0.20
                elif inferred_type == "figure" and item_type == "figure":
                    hybrid_scores[idx] += 0.15

                # Bias images on pages that text retriever already marked relevant.
                if preferred_pages and self._metadata[idx].get("page") in preferred_pages:
                    hybrid_scores[idx] += 0.30

                # Big boost if query explicitly mentions this page number
                if query_text:
                    q_page = _extract_page_number_from_query(query_text)
                    if q_page is not None and self._metadata[idx].get("page") == q_page:
                        hybrid_scores[idx] += 0.50

            final_scores = hybrid_scores
        else:
            # Pure visual search
            final_scores = visual_scores

        # Top-k indices
        k_actual = min(k, len(self._metadata))
        top_idx  = np.argsort(final_scores)[::-1][:k_actual]

        results = []
        for idx in top_idx:
            record = dict(self._metadata[idx])
            record["score"] = float(final_scores[idx])
            results.append(record)

        return results

    # ── Housekeeping ──────────────────────────────────────────────────────────

    def clear(self) -> None:
        self._embeddings = None
        self._metadata   = []

    def is_empty(self) -> bool:
        return len(self._metadata) == 0

    def __len__(self) -> int:
        return len(self._metadata)
