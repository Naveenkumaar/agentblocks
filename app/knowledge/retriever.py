"""A dependency-free TF-IDF vector retriever.

Ranks documents by **cosine similarity** between TF-IDF vectors of the query and
each candidate — a real vector-search retriever with no external deps (pure
Python + ``math``). IDF is computed once over the whole corpus at construction;
``retrieve`` scores only the agent's candidate ``doc_ids``.

Swap this for embeddings + a vector DB (ChromaDB / pgvector + bge-small) without
touching the engine — the interface stays ``retrieve(query, doc_ids) -> list[str]``.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# A small synthetic corpus keyed by doc id. Replace with a real index later.
_CORPUS: dict[str, str] = {
    "faq-hours": "Support is available Monday to Friday, 9am to 6pm local time.",
    "faq-refunds": "Refunds are processed within 5 business days of approval.",
    "travel-visa": "Most short visits under 30 days are visa-exempt for many passports.",
    "travel-weather": "Pack layers for mountain regions; weather changes quickly at altitude.",
}

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Retriever:
    def __init__(self, corpus: dict[str, str] | None = None) -> None:
        self.corpus = corpus or _CORPUS
        n = len(self.corpus) or 1
        # document frequency across the whole corpus → idf
        df: Counter[str] = Counter()
        self._doc_tokens: dict[str, list[str]] = {}
        for doc_id, text in self.corpus.items():
            toks = _tokens(text)
            self._doc_tokens[doc_id] = toks
            for term in set(toks):
                df[term] += 1
        # smoothed idf so a term in every doc still has weight > 0
        self._idf = {term: math.log((1 + n) / (1 + c)) + 1.0 for term, c in df.items()}
        # precompute normalized tf-idf vectors per doc
        self._vectors = {d: self._vector(toks) for d, toks in self._doc_tokens.items()}

    def _vector(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        vec = {t: (tf[t] / len(tokens)) * self._idf.get(t, math.log(len(self.corpus) + 1) + 1.0)
               for t in tf}
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        return {t: w / norm for t, w in vec.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        return sum(a[t] * b[t] for t in common)  # vectors already normalized

    def retrieve(self, query: str, doc_ids: list[str], top_k: int = 3) -> list[str]:
        q = self._vector(_tokens(query))
        scored: list[tuple[float, str, str]] = []
        for doc_id in doc_ids:
            if doc_id not in self.corpus:
                continue
            scored.append((self._cosine(q, self._vectors[doc_id]), doc_id, self.corpus[doc_id]))
        scored.sort(key=lambda t: (-t[0], t[1]))   # score desc, then doc_id for determinism
        hits = [text for score, _, text in scored[:top_k] if score > 0]
        return hits or [self.corpus[d] for d in doc_ids[:top_k] if d in self.corpus]

    def scores(self, query: str, doc_ids: list[str]) -> list[tuple[str, float]]:
        """Doc ids with their cosine score (for inspection / debugging)."""
        q = self._vector(_tokens(query))
        out = [(d, round(self._cosine(q, self._vectors[d]), 4))
               for d in doc_ids if d in self.corpus]
        return sorted(out, key=lambda t: (-t[1], t[0]))
