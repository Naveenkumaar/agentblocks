"""Agent connector — one agent calls another agent as a tool.

A skill with a ``kind: "agent"`` connector runs a full turn on a *target* agent
and returns its reply, so a coordinating agent can delegate to a specialist
inside its own turn (agents calling agents). Config:

    agent:  the target agent's name (required)
    topic:  optional topic on the target

Guard against cycles in your definitions — this runs a real sub-turn. Base
``Connector.invoke`` still wraps it, so a bad target degrades to ``ok=False``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Connector

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"


class AgentConnector(Connector):
    def _call(self, params: dict[str, Any]) -> Any:
        from app.engine.registry import Registry
        from app.engine.runtime import Engine

        target = self.config.get("agent")
        if not target:
            raise ValueError("agent connector requires config.agent")

        reg = Registry()
        for f in sorted(_AGENTS_DIR.glob("*.json")):
            try:
                reg.load_file(f)
            except ValueError:
                pass

        turn = Engine().run_turn(reg.get(target), str(params.get("query", "")),
                                 topic_name=self.config.get("topic"),
                                 session_id=f"delegate-{target}")
        return {"agent": target, "reply": turn.reply, "blocked": turn.blocked}
