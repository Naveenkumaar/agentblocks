"""In-memory session store (swap for Redis/Postgres in production).

Keeps a bounded history per session so follow-up turns have context. The
``max_turns`` bound is enforced here and mirrored by governance quotas.
"""
from __future__ import annotations

from collections import defaultdict, deque


class MemoryStore:
    def __init__(self, max_turns: int = 20) -> None:
        self._sessions: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_turns))

    def append(self, session_id: str, role: str, text: str) -> None:
        self._sessions[session_id].append((role, text))

    def history(self, session_id: str) -> list[tuple[str, str]]:
        return list(self._sessions[session_id])

    def context(self, session_id: str) -> str:
        return "\n".join(f"{role}: {text}" for role, text in self.history(session_id))

    def turn_count(self, session_id: str) -> int:
        return len(self._sessions[session_id])
