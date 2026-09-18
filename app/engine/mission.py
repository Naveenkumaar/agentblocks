"""Mission mode — long-running, resumable tasks with waits and checkpoints.

A ``mission`` topic defines an ordered list of ``steps`` (see
:class:`~app.engine.definition.Topic`). A step is either a **skill name** (run
it now) or ``"wait:<event>"`` (pause until that event arrives). The runner
executes steps until it hits a wait, then **checkpoints** — the run's cursor,
status, and accumulated results are the checkpoint, so a waiting mission can be
**resumed** later by posting the awaited event.

State lives in a :class:`MissionStore` (in-memory here; persist it the same way
as the registry to survive restarts).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.connectors import build_connector
from app.engine.definition import AgentDefinition


@dataclass
class MissionRun:
    id: str
    agent: str
    topic: str
    cursor: int = 0
    status: str = "running"          # running | waiting | done
    waiting_for: str | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "agent": self.agent, "topic": self.topic,
                "cursor": self.cursor, "status": self.status,
                "waiting_for": self.waiting_for, "results": self.results, "trace": self.trace}


class MissionStore:
    def __init__(self) -> None:
        self._runs: dict[str, MissionRun] = {}
        self._seq = 0

    def create(self, agent: str, topic: str) -> MissionRun:
        self._seq += 1
        run = MissionRun(id=f"MR-{self._seq:04d}", agent=agent, topic=topic)
        self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> MissionRun | None:
        return self._runs.get(run_id)

    def all(self) -> list[MissionRun]:
        return list(self._runs.values())


class MissionRunner:
    def __init__(self, store: MissionStore | None = None) -> None:
        self.store = store or MissionStore()

    def start(self, agent: AgentDefinition, topic_name: str | None = None) -> MissionRun:
        topic = agent.topic(topic_name)
        run = self.store.create(agent.name, topic.name if topic else "?")
        if topic is None:
            run.status = "done"
            run.trace.append({"error": "no topic"})
            return run
        self._advance(run, agent, topic)
        return run

    def resume(self, run: MissionRun, event: str, agent: AgentDefinition) -> MissionRun:
        if run.status != "waiting":
            run.trace.append({"ignored_event": event, "reason": f"status={run.status}"})
            return run
        if run.waiting_for != event:
            run.trace.append({"ignored_event": event, "expected": run.waiting_for})
            return run
        run.trace.append({"resumed_on": event})
        run.cursor += 1                      # advance past the wait step
        run.status = "running"
        run.waiting_for = None
        self._advance(run, agent, agent.topic(run.topic))
        return run

    # ------------------------------------------------------------------
    def _advance(self, run: MissionRun, agent: AgentDefinition, topic) -> None:
        steps = topic.steps
        while run.cursor < len(steps):
            step = steps[run.cursor]
            if step.startswith("wait:"):
                run.status = "waiting"
                run.waiting_for = step[len("wait:"):]
                run.trace.append({"checkpoint": run.cursor, "waiting_for": run.waiting_for})
                return
            skill = next((s for s in agent.skills if s.name == step), None)
            spec = agent.connector(skill.connector) if skill else None
            res = build_connector(spec).invoke({"step": step}) if spec else None
            run.results.append({"step": step, "ok": bool(res and res.ok),
                                "data": res.data if res else None})
            run.trace.append({"ran": step, "ok": bool(res and res.ok)})
            run.cursor += 1
        run.status = "done"
        run.trace.append({"done": True})
