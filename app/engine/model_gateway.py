"""Pluggable model gateway.

The default backend is a deterministic ``StubModel`` so the whole platform runs
end to end with **no API key and no network** — ideal for tests, CI, and a
first clone. Set ``MODEL_BACKEND=ollama`` to use a local model instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ModelReply:
    text: str
    backend: str


class StubModel:
    """Offline, deterministic model. Proves the pipeline without dependencies."""

    backend = "stub"

    def _text(self, user: str, context: str) -> str:
        ctx = f" [+{len(context)} chars context]" if context else ""
        return (f"(stub){ctx} Regarding '{user.strip()}': this is a placeholder "
                f"answer from the offline model. Set MODEL_BACKEND=ollama for a real one.")

    def generate(self, system: str, user: str, context: str = "") -> ModelReply:
        return ModelReply(text=self._text(user, context), backend=self.backend)

    def generate_stream(self, system: str, user: str, context: str = ""):
        """Yield the reply token by token (word-at-a-time) so callers can stream."""
        words = self._text(user, context).split(" ")
        for i, w in enumerate(words):
            yield (w if i == 0 else " " + w)


class OllamaModel:
    """Local model via Ollama (https://ollama.com) — no cloud, no API key."""

    backend = "ollama"

    def __init__(self) -> None:
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    def generate(self, system: str, user: str, context: str = "") -> ModelReply:
        import httpx

        prompt = f"{system}\n\nContext:\n{context}\n\nUser: {user}\nAssistant:"
        resp = httpx.post(
            f"{self.host}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return ModelReply(text=resp.json().get("response", "").strip(), backend=self.backend)

    def generate_stream(self, system: str, user: str, context: str = ""):
        import json

        import httpx

        prompt = f"{system}\n\nContext:\n{context}\n\nUser: {user}\nAssistant:"
        with httpx.stream("POST", f"{self.host}/api/generate",
                          json={"model": self.model, "prompt": prompt, "stream": True},
                          timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                tok = json.loads(line).get("response", "")
                if tok:
                    yield tok


def get_model():
    """Resolve the configured backend (defaults to the offline stub)."""
    if os.getenv("MODEL_BACKEND", "stub").lower() == "ollama":
        return OllamaModel()
    return StubModel()
