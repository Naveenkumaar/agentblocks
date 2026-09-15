"""A tiny, dependency-free keyword retriever.

Enough to demonstrate the knowledge block end to end. Swap this for a real
vector store (e.g. ChromaDB / pgvector + bge-small embeddings) without touching
the engine — the interface is just ``retrieve(query, doc_ids) -> list[str]``.
"""
from __future__ import annotations

# A small synthetic corpus keyed by doc id. Replace with a real index later.
_CORPUS: dict[str, str] = {
    "faq-hours": "Support is available Monday to Friday, 9am to 6pm local time.",
    "faq-refunds": "Refunds are processed within 5 business days of approval.",
    "travel-visa": "Most short visits under 30 days are visa-exempt for many passports.",
    "travel-weather": "Pack layers for mountain regions; weather changes quickly at altitude.",
}


class Retriever:
    def __init__(self, corpus: dict[str, str] | None = None) -> None:
        self.corpus = corpus or _CORPUS

    def retrieve(self, query: str, doc_ids: list[str], top_k: int = 3) -> list[str]:
        query_terms = {w.lower() for w in query.split()}
        scored: list[tuple[int, str]] = []
        for doc_id in doc_ids:
            text = self.corpus.get(doc_id)
            if not text:
                continue
            overlap = len(query_terms & {w.lower().strip(".,") for w in text.split()})
            scored.append((overlap, text))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [text for score, text in scored[:top_k] if score > 0] or [
            self.corpus[d] for d in doc_ids[:top_k] if d in self.corpus
        ]
