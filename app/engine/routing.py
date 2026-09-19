"""Pluggable routers — score how well each agent fits a sub-task.

One interface, three backends, selected by ``ROUTER_BACKEND`` (see ADR 0002 in
my design journal — swap a backend behind a stable contract, always keep a
deterministic fallback):

    (unset) / "overlap"   → token overlap over stemmed profiles (default, offline)
    "vector" / "tfidf"    → TF-IDF cosine (weights distinctive terms, length-normalized)
    "embedding" / "ollama"→ real embeddings via a local model, cosine similarity

Every router implements ``rank(task, profiles) -> [(agent, score)]`` sorted best
first with non-positive scores dropped, so the orchestrator's decide/clarify
logic is unchanged whichever backend is active. The richer backends fall back to
a simpler one on any error or empty result, so routing never breaks offline.
"""
from __future__ import annotations

import math
import os
from collections import Counter

from app.knowledge.retriever import Retriever, _tokens


def _stem(tokens) -> set[str]:
    """Crude singular/plural fold so 'refund' matches 'refunds'."""
    return {(t[:-1] if t.endswith("s") and len(t) > 3 else t) for t in tokens}


class OverlapRouter:
    name = "overlap"

    def rank(self, task: str, profiles: dict[str, str]) -> list[tuple[str, float]]:
        task_toks = _stem(_tokens(task))
        scored = [(n, len(task_toks & _stem(_tokens(p)))) for n, p in profiles.items()]
        scored = [(n, s) for n, s in scored if s > 0]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored


class VectorRouter:
    name = "vector"

    def __init__(self, fallback=None) -> None:
        self.fallback = fallback or OverlapRouter()

    def rank(self, task: str, profiles: dict[str, str]) -> list[tuple[str, float]]:
        try:
            # TF-IDF space over the agent profiles; score the task against each
            r = Retriever(corpus=profiles)
            scored = [(n, round(s, 4)) for n, s in r.scores(task, list(profiles))]
            scored = [(n, s) for n, s in scored if s > 0]
            scored.sort(key=lambda x: (-x[1], x[0]))
            if scored:
                return scored
        except Exception:
            pass
        return self.fallback.rank(task, profiles)


class EmbeddingRouter:
    name = "embedding"

    def __init__(self, fallback=None) -> None:
        self.fallback = fallback or VectorRouter()

    def rank(self, task: str, profiles: dict[str, str]) -> list[tuple[str, float]]:
        try:
            vecs = {n: self._embed(text) for n, text in profiles.items()}
            q = self._embed(task)
            scored = [(n, round(self._cosine(q, v), 4)) for n, v in vecs.items()]
            scored = [(n, s) for n, s in scored if s > 0]
            scored.sort(key=lambda x: (-x[1], x[0]))
            if scored:
                return scored
        except Exception:
            pass
        return self.fallback.rank(task, profiles)

    def _embed(self, text: str) -> list[float]:
        import httpx

        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        resp = httpx.post(f"{host}/api/embeddings",
                          json={"model": model, "prompt": text}, timeout=60)
        resp.raise_for_status()
        return resp.json()["embedding"]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0


def get_router(name: str | None = None):
    name = (name or os.getenv("ROUTER_BACKEND", "overlap")).lower()
    if name in ("vector", "tfidf"):
        return VectorRouter()
    if name in ("embedding", "embed", "ollama"):
        return EmbeddingRouter()
    return OverlapRouter()
