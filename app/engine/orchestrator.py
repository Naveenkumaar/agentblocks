"""Autonomous orchestrator — plan a goal, delegate to specialists, aggregate.

Given a high-level ``goal``, the orchestrator **decomposes** it into sub-tasks,
**routes** each sub-task to the best-matching agent in the registry *on its own*
(no hand-authored membership), runs a turn per sub-task, and **aggregates** the
results. Routing is by token overlap against a per-agent profile built from its
name, description, skills, and knowledge — deterministic and offline. Swap the
splitter/router for an LLM planner without changing the loop.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.engine.registry import Registry
from app.engine.routing import get_router
from app.engine.runtime import Engine

_SPLIT = re.compile(r"\s*(?:;|\band then\b|\bthen\b|\band also\b|\band\b)\s*", re.IGNORECASE)

# a sub-task that points back at an earlier one's output — makes it dependent
_BACKREF = re.compile(
    r"\b(it|its|it'?s|that|this|these|those|them|they|"
    r"the (booking|reservation|confirmation|result|answer|trip|table|order|details?))\b",
    re.IGNORECASE)


def depends_on_prior(task: str) -> bool:
    return bool(_BACKREF.search(task))


def split_goal(goal: str) -> list[str]:
    return [p.strip() for p in _SPLIT.split(goal) if p.strip()]


_PLAN_SYSTEM = ("Decompose the user's goal into independent sub-tasks. "
                "Reply with ONLY a JSON array of short task strings, nothing else.")


def plan_goal(goal: str, model=None) -> list[str]:
    """Decompose a goal into sub-tasks — LLM-backed, rule-based fallback.

    With a real model (``MODEL_BACKEND=ollama``) the goal is decomposed by the
    LLM and parsed as a JSON array; offline (stub), on a parse error, or on an
    empty result we fall back to the deterministic regex `split_goal`. The
    planner never raises — a bad plan degrades to the rule-based split.
    """
    if model is None or getattr(model, "backend", "stub") == "stub":
        return split_goal(goal)
    try:
        raw = model.generate(_PLAN_SYSTEM, goal).text
        start, end = raw.find("["), raw.rfind("]")
        tasks = json.loads(raw[start:end + 1]) if start != -1 and end != -1 else []
        tasks = [str(t).strip() for t in tasks if str(t).strip()]
        return tasks or split_goal(goal)
    except Exception:
        return split_goal(goal)


_PLAN_DAG_SYSTEM = (
    "Decompose the user's goal into ordered sub-tasks with dependencies. "
    "Reply with ONLY a JSON array of objects "
    '[{"task": "...", "deps": [earlier indices this task needs]}]. '
    "deps are 0-based indices of earlier tasks; use [] for independent tasks. "
    "Declare a dependency whenever a task needs an earlier task's result, even "
    "if it does not mention it explicitly.")


def _infer_deps(tasks: list[str]) -> list[dict[str, Any]]:
    """Rule-based edges: a back-referencing task depends on all earlier ones."""
    steps: list[dict[str, Any]] = []
    for i, t in enumerate(tasks):
        steps.append({"task": t, "deps": list(range(i)) if depends_on_prior(t) else []})
    return steps


def plan_steps(goal: str, model=None) -> list[dict[str, Any]]:
    """Plan a goal into ``[{task, deps}]`` — LLM edges, rule-based fallback.

    With a real model the planner can declare **explicit dependency edges**, so a
    task that needs an earlier result but never names it is still ordered
    correctly. Offline / on any parse error we fall back to `split_goal` +
    lexical back-reference inference. Never raises. Out-of-range or forward deps
    are dropped, so the result is always a valid DAG in task order.
    """
    if model is None or getattr(model, "backend", "stub") == "stub":
        return _infer_deps(split_goal(goal))
    try:
        raw = model.generate(_PLAN_DAG_SYSTEM, goal).text
        start, end = raw.find("["), raw.rfind("]")
        data = json.loads(raw[start:end + 1]) if start != -1 and end != -1 else []
        steps: list[dict[str, Any]] = []
        for i, item in enumerate(data):
            task = str(item.get("task", "")).strip()
            if not task:
                continue
            deps = sorted({d for d in item.get("deps", [])
                           if isinstance(d, int) and 0 <= d < i})
            steps.append({"task": task, "deps": deps})
        return steps or _infer_deps(split_goal(goal))
    except Exception:
        return _infer_deps(split_goal(goal))


@dataclass
class OrchestrationStep:
    task: str
    agent: str | None
    reply: str
    score: int = 0
    confidence: str = "none"                       # high | low | none
    alternatives: list = field(default_factory=list)  # [{"agent","score"}, ...]
    needs_clarification: bool = False
    depends_on_prior: bool = False                 # chained on earlier results
    deps: list = field(default_factory=list)       # indices of steps this one needs

    def as_dict(self) -> dict[str, Any]:
        return {"task": self.task, "agent": self.agent, "reply": self.reply,
                "score": self.score, "confidence": self.confidence,
                "alternatives": self.alternatives,
                "needs_clarification": self.needs_clarification,
                "depends_on_prior": self.depends_on_prior, "deps": self.deps}


@dataclass
class OrchestrationResult:
    goal: str
    steps: list[OrchestrationStep] = field(default_factory=list)
    summary: str = ""
    synthesis: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "summary": self.summary,
                "synthesis": self.synthesis,
                "steps": [s.as_dict() for s in self.steps]}


class Orchestrator:
    def __init__(self, registry: Registry, engine: Engine | None = None,
                 router=None) -> None:
        self.registry = registry
        self.engine = engine or Engine()
        self.router = router or get_router()   # ROUTER_BACKEND selects the default

    def _profile_text(self, name: str) -> str:
        """The text an agent declares about itself — the routing signal."""
        d = self.registry.get(name)
        text = name + " " + d.description
        text += " " + " ".join(s.description + " " + s.name for s in d.skills)
        corpus = getattr(self.engine.retriever, "corpus", {})
        text += " " + " ".join(corpus.get(doc, "") for doc in d.knowledge)
        return text

    def _rank(self, task: str) -> list[tuple[str, float]]:
        """Rank agents for a sub-task via the active router backend."""
        profiles = {name: self._profile_text(name) for name in self.registry.names()}
        return self.router.rank(task, profiles)

    def _route(self, task: str) -> str | None:
        ranked = self._rank(task)
        return ranked[0][0] if ranked else None

    def _decide(self, task: str) -> OrchestrationStep:
        """Pick an agent for a sub-task, or flag it when the choice is unsafe.

        - no positive match  → confidence "none", ask to clarify (don't guess).
        - top two tied        → confidence "low", ambiguous, ask to clarify.
        - a clear winner      → confidence "high", delegate.
        """
        ranked = self._rank(task)
        alts = [{"agent": n, "score": s} for n, s in ranked[:3]]
        if not ranked:
            return OrchestrationStep(task, None,
                                     "(no suitable specialist — please clarify the request)",
                                     score=0, confidence="none", needs_clarification=True)
        if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
            tied = [n for n, s in ranked if s == ranked[0][1]]
            return OrchestrationStep(
                task, None,
                f"(ambiguous — could be {', '.join(tied)}; please clarify)",
                score=ranked[0][1], confidence="low", alternatives=alts,
                needs_clarification=True)
        return OrchestrationStep(task, ranked[0][0], "", score=ranked[0][1],
                                 confidence="high", alternatives=alts)

    def _context_for(self, deps: list[int], results: dict[int, str]) -> str | None:
        """Assemble context from ONLY the referenced dependency results."""
        chosen = [results[d] for d in deps if d in results]
        return ("Earlier results:\n" + "\n".join(chosen)) if chosen else None

    def run(self, goal: str, max_steps: int = 5) -> OrchestrationResult:
        result = OrchestrationResult(goal=goal)
        results: dict[int, str] = {}   # index → that step's result, for dependents
        for i, pstep in enumerate(plan_steps(goal, self.engine.model)[:max_steps]):
            task, deps = pstep["task"], [d for d in pstep["deps"] if d in results]
            step = self._decide(task)
            step.deps = deps
            step.depends_on_prior = bool(deps)
            if step.agent is not None:
                ctx = self._context_for(deps, results)
                turn = self.engine.run_turn(self.registry.get(step.agent), task,
                                            session_id=f"orch-{i}", extra_context=ctx)
                step.reply = turn.reply
                results[i] = f"- {step.agent} on “{task}”: {step.reply}"
            result.steps.append(step)
        routed = [s for s in result.steps if s.agent]
        unclear = [s for s in result.steps if s.needs_clarification]
        result.summary = (f"Delegated {len(routed)}/{len(result.steps)} sub-task(s): "
                          + "; ".join(f"{s.agent} ← “{s.task}”" for s in routed))
        if unclear:
            result.summary += f" · {len(unclear)} need clarification"
        result.synthesis = self._synthesize(goal, result.steps)
        return result

    def _synthesize(self, goal: str, steps: list[OrchestrationStep]) -> str:
        """Compose one final answer from the sub-results.

        The specialists' replies are handed to the model as context so it can
        weave them into a single response to the original goal. Offline this is
        the deterministic stub; ``MODEL_BACKEND=ollama`` makes it a real
        synthesis. Falls back to concatenation if the model errors.
        """
        done = [s for s in steps if s.agent]
        if not done:
            return "No specialist could handle any part of the goal."
        context = "\n".join(f"- {s.agent} on “{s.task}”: {s.reply}" for s in done)
        try:
            return self.engine.model.generate(
                "Combine the specialists' findings into one answer for the guest.",
                goal, context=context).text
        except Exception:
            return " ".join(s.reply for s in done)
