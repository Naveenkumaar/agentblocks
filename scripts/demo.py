#!/usr/bin/env python3
"""One-command, offline end-to-end demo of the autonomous multi-agent platform.

    python scripts/demo.py

Runs entirely on the deterministic stub model (no keys, no network). Walks
through: loading a registry of specialist agents, previewing an autonomous plan,
running it (routing → dependency chaining → synthesis), the topological
schedule, agents-calling-agents, and the clarify-don't-guess safety flag.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.orchestrator import Orchestrator  # noqa: E402
from app.engine.registry import Registry  # noqa: E402
from app.engine.routing import VectorRouter  # noqa: E402
from app.engine.runtime import Engine  # noqa: E402

AGENTS = Path(__file__).resolve().parents[1] / "agents"


def rule(title: str) -> None:
    print(f"\n\033[1m{'─' * 3} {title} {'─' * (66 - len(title))}\033[0m")


def load_registry() -> Registry:
    reg = Registry()
    for f in sorted(AGENTS.glob("*.json")):
        try:
            reg.load_file(f)
        except ValueError:
            pass
    return reg


def main() -> int:
    reg = load_registry()
    # the TF-IDF vector router weights distinctive terms — sharper than raw token
    # overlap when many specialists share generic words (ROUTER_BACKEND=vector).
    orch = Orchestrator(reg, router=VectorRouter())

    rule("Registry")
    print(f"Loaded {len(reg.names())} specialist agents: {', '.join(reg.names())}")
    print("Router backend: vector (TF-IDF cosine)")

    goal = "plan a trip with nice weather and then check the refund policy for it"
    rule("Autonomous plan (preview, not yet run)")
    print(f'Goal: "{goal}"')
    preview = orch.plan(goal)
    for s in preview["steps"]:
        dep = f"  needs {s['deps']}" if s["deps"] else ""
        print(f"  [{s['index']}] {s['task']!r} → {s['routed_agent']} "
              f"({s['confidence']}){dep}")
    print(f"Schedule layers (parallelizable groups): {preview['layers']}")

    rule("Run it — route, chain dependencies, synthesize")
    res = orch.run(goal)
    for i, s in enumerate(res.steps):
        tag = " (chained on earlier result)" if s.depends_on_prior else ""
        print(f"  [{i}] {s.agent or '—'}{tag}: {s.reply[:70]}")
    print(f"\nSummary:   {res.summary}")
    print(f"Synthesis: {res.synthesis[:80]}...")

    rule("Agents calling agents (concierge delegates to faq-helper)")
    if "concierge-agent" in reg.names():
        turn = Engine().run_turn(reg.get("concierge-agent"), "what are the support hours")
        delegated = [t for t in turn.trace if t.get("connector") == "faq-specialist"]
        print(f"Delegated via agent connector: {bool(delegated)}")
        print(f"Reply: {turn.reply[:80]}")

    rule("Clarify, don't guess")
    unclear = orch.run("zzzqqq nonsense")
    step = unclear.steps[0]
    print(f"Unroutable task → agent={step.agent}, confidence={step.confidence}, "
          f"needs_clarification={step.needs_clarification}")

    rule("Done")
    print("Everything above ran offline on the stub model. "
          "Set MODEL_BACKEND=ollama for real generations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
