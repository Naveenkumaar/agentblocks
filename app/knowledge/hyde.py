"""HyDE — Hypothetical Document Embeddings (Gao et al., 2022).

A raw question is often a poor retrieval key: it's short and shares few terms
with the answer passage. HyDE first asks the model to *write a hypothetical
answer* to the question, then retrieves with **that** — the hypothetical answer
looks far more like the real passage than the question did, so it lands closer in
the embedding space.

This wraps the existing :class:`Retriever` (any embedding space) and any model
from the gateway. It degrades safely: the hypothetical text is *blended* with the
original query, so even when the model is the offline stub (which returns a
generic placeholder) HyDE is never worse than plain retrieval.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.retriever import Retriever

_HYDE_SYSTEM = (
    "Write a short, factual passage that would directly answer the user's "
    "question, as if it were an excerpt from a reference document. "
    "Do not say you are unsure — just write the passage.")


@dataclass
class HydeResult:
    query: str
    hypothetical: str
    hits: list[str]


class HydeRetriever:
    def __init__(self, retriever: Retriever, model, blend_query: bool = True) -> None:
        self.retriever = retriever
        self.model = model
        self.blend_query = blend_query

    def _hypothetical(self, query: str) -> str:
        try:
            text = self.model.generate(_HYDE_SYSTEM, query).text
        except Exception:
            text = ""
        return text or ""

    def _search_key(self, query: str, hypothetical: str) -> str:
        # blend so a weak/stub hypothetical can never do worse than the raw query
        return f"{hypothetical} {query}".strip() if self.blend_query else (hypothetical or query)

    def retrieve(self, query: str, doc_ids: list[str], top_k: int = 3) -> list[str]:
        hyp = self._hypothetical(query)
        return self.retriever.retrieve(self._search_key(query, hyp), doc_ids, top_k=top_k)

    def explain(self, query: str, doc_ids: list[str], top_k: int = 3) -> HydeResult:
        """Same retrieval, but also return the hypothetical answer used (for traces)."""
        hyp = self._hypothetical(query)
        hits = self.retriever.retrieve(self._search_key(query, hyp), doc_ids, top_k=top_k)
        return HydeResult(query=query, hypothetical=hyp, hits=hits)

    def scores(self, query: str, doc_ids: list[str]) -> list[tuple[str, float]]:
        hyp = self._hypothetical(query)
        return self.retriever.scores(self._search_key(query, hyp), doc_ids)
