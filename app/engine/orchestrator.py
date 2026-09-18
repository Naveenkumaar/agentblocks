"""Autonomous orchestrator — plan a goal, delegate to specialists, aggregate.

Given a high-level ``goal``, the orchestrator **decomposes** it into sub-tasks,
**routes** each sub-task to the best-matching agent in the registry *on its own*
(no hand-authored membership), runs a turn per sub-task, and **aggregates** the
results. Routing is by token overlap against a per-agent profile built from its
name, description, skills, and knowledge — deterministic and offline. Swap the
splitter/router for an LLM planner without changing the loop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.engine.registry import Registry
from app.engine.runtime import Engine
from app.knowledge.retriever import _tokens

_SPLIT = re.compile(r"\s*(?:;|\band then\b|\bthen\b|\band also\b|\band\b)\s*", re.IGNORECASE)


def _stem(tokens) -> set[str]:
    # crude singular/plural fold so "refund" matches "refunds", "trip" ~ "trips"
    return {(t[:-1] if t.endswith("s") and len(t) > 3 else t) for t in tokens}


def split_goal(goal: str) -> list[str]:
    return [p.strip() for p in _SPLIT.split(goal) if p.strip()]


@dataclass
class OrchestrationStep:
    task: str
    agent: str | None
    reply: str

    def as_dict(self) -> dict[str, Any]:
        return {"task": self.task, "agent": self.agent, "reply": self.reply}


@dataclass
class OrchestrationResult:
    goal: str
    steps: list[OrchestrationStep] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "summary": self.summary,
                "steps": [s.as_dict() for s in self.steps]}


class Orchestrator:
    def __init__(self, registry: Registry, engine: Engine | None = None) -> None:
        self.registry = registry
        self.engine = engine or Engine()

    def _profile(self, name: str) -> set[str]:
        d = self.registry.get(name)
        text = name + " " + d.description
        text += " " + " ".join(s.description + " " + s.name for s in d.skills)
        corpus = getattr(self.engine.retriever, "corpus", {})
        text += " " + " ".join(corpus.get(doc, "") for doc in d.knowledge)
        return _stem(_tokens(text))

    def _route(self, task: str) -> str | None:
        task_toks = _stem(_tokens(task))
        best, best_score = None, 0
        for name in self.registry.names():
            score = len(task_toks & self._profile(name))
            if score > best_score:
                best, best_score = name, score
        return best

    def run(self, goal: str, max_steps: int = 5) -> OrchestrationResult:
        result = OrchestrationResult(goal=goal)
        for i, task in enumerate(split_goal(goal)[:max_steps]):
            agent_name = self._route(task)
            if agent_name is None:
                result.steps.append(OrchestrationStep(task, None, "(no suitable agent)"))
                continue
            turn = self.engine.run_turn(self.registry.get(agent_name), task,
                                        session_id=f"orch-{i}")
            result.steps.append(OrchestrationStep(task, agent_name, turn.reply))
        routed = [s for s in result.steps if s.agent]
        result.summary = (f"Delegated {len(routed)}/{len(result.steps)} sub-task(s): "
                          + "; ".join(f"{s.agent} ← “{s.task}”" for s in routed))
        return result
