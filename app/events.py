"""A normalized, in-process event stream for the agent runtime.

Every turn the engine runs emits a small sequence of typed events — one when the
run starts, one per pipeline stage, and one terminal event (completed / blocked /
approval-required / failed). They are the data behind the operator console's live
**agent map / execution timeline**: a safe, structured view of *what the runtime
is doing* (current stage, tool, status) that never exposes the model's private
reasoning.

Deliberately dependency-free and in-process: a bounded ring buffer plus optional
subscriber callbacks. Emission is best-effort — a failing subscriber can never
break a turn.
"""
from __future__ import annotations

import itertools
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class EventType(str, Enum):
    RUN_STARTED = "run.started"
    STAGE = "run.stage"
    APPROVAL_REQUIRED = "run.approval_required"
    RUN_COMPLETED = "run.completed"
    RUN_BLOCKED = "run.blocked"
    RUN_FAILED = "run.failed"


# Terminal event types — exactly one ends every run.
TERMINAL = {EventType.RUN_COMPLETED, EventType.RUN_BLOCKED,
            EventType.APPROVAL_REQUIRED, EventType.RUN_FAILED}


@dataclass
class AgentEvent:
    seq: int
    ts: float
    run_id: str
    agent: str
    type: EventType
    stage: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "run_id": self.run_id,
            "agent": self.agent,
            "type": self.type.value,
            "stage": self.stage,
            "detail": self.detail,
        }


class EventBus:
    """Bounded ring buffer of recent events + best-effort fan-out to subscribers."""

    def __init__(self, maxlen: int = 2000) -> None:
        self._events: deque[AgentEvent] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)
        self._subscribers: list[Callable[[AgentEvent], None]] = []

    def subscribe(self, fn: Callable[[AgentEvent], None]) -> None:
        self._subscribers.append(fn)

    def emit(self, run_id: str, agent: str, type: EventType,
             stage: str | None = None, **detail: Any) -> AgentEvent:
        ev = AgentEvent(seq=next(self._seq), ts=time.time(), run_id=run_id,
                        agent=agent, type=type, stage=stage, detail=detail)
        self._events.append(ev)
        for fn in list(self._subscribers):
            try:
                fn(ev)
            except Exception:  # noqa: BLE001 — a subscriber must never break a turn
                pass
        return ev

    def recent(self, limit: int = 200, since_seq: int = 0) -> list[dict[str, Any]]:
        """Newest-relevant events as plain dicts. Poll with the last `seq` you saw
        to stream only new ones (ascending order)."""
        out = [e.to_dict() for e in self._events if e.seq > since_seq]
        return out[-limit:]

    def runs(self, limit: int = 25) -> list[dict[str, Any]]:
        """Group recent events into runs (newest run first) for the agent map."""
        by_run: dict[str, dict[str, Any]] = {}
        for e in self._events:
            g = by_run.setdefault(e.run_id, {
                "run_id": e.run_id, "agent": e.agent, "events": [], "started": e.ts,
                "status": "running",
            })
            g["events"].append(e.to_dict())
            if e.type in TERMINAL:
                g["status"] = e.type.value
            g["latest"] = e.ts
        ordered = sorted(by_run.values(), key=lambda g: g.get("latest", 0), reverse=True)
        return ordered[:limit]

    def clear(self) -> None:
        self._events.clear()


# Process-wide bus the engine and API share.
bus = EventBus()
