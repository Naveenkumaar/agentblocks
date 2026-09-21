"""Preview a plan without running, edit it, then run that exact plan."""
from pathlib import Path

from app.engine.orchestrator import Orchestrator
from app.engine.registry import Registry

AGENTS = Path(__file__).parents[1] / "agents"


def _orch():
    r = Registry()
    for f in ["faq-helper.json", "trip-planner.json"]:
        r.load_file(AGENTS / f)
    return Orchestrator(r)


def test_plan_previews_routing_without_running():
    preview = _orch().plan("plan a weather-safe trip and then check the refund policy")
    steps = preview["steps"]
    assert len(steps) == 2
    assert steps[0]["routed_agent"] == "trip-planner"
    assert steps[1]["routed_agent"] == "faq-helper"
    # each preview step exposes its edges + routing decision
    assert {"index", "task", "deps", "routed_agent", "confidence"} <= set(steps[0])
    # offline the lexical detector finds no back-reference here (no pronoun,
    # "refund" isn't a dependency keyword) → independent. That's exactly why a
    # caller can add an explicit edge via the editable plan (tested below).
    assert steps[1]["deps"] == []


def test_run_executes_a_supplied_edited_plan():
    orch = _orch()
    # a caller-authored plan (order/edges of their choosing)
    edited = [{"task": "check the refund policy", "deps": []},
              {"task": "plan a trip with nice weather", "deps": [0]}]
    res = orch.run(plan=edited)
    assert [s.agent for s in res.steps] == ["faq-helper", "trip-planner"]
    assert res.steps[1].depends_on_prior          # honored the edited edge


def test_supplied_plan_deps_are_sanitized():
    orch = _orch()
    bad = [{"task": "check the refund policy", "deps": [9]},      # out of range
           {"task": "plan a trip", "deps": [1, 0]}]               # forward dep 1
    res = orch.run(plan=bad)
    assert res.steps[0].deps == []
    assert res.steps[1].deps == [0]


def test_empty_tasks_in_a_plan_are_dropped():
    res = _orch().run(plan=[{"task": "  ", "deps": []},
                            {"task": "check the refund policy", "deps": []}])
    assert len(res.steps) == 1 and res.steps[0].agent == "faq-helper"
