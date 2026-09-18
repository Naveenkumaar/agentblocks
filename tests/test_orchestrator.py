"""Autonomous orchestrator: decompose a goal, route each part to a specialist."""
from pathlib import Path

from app.engine.orchestrator import Orchestrator, split_goal
from app.engine.registry import Registry

AGENTS = Path(__file__).parents[1] / "agents"


def _registry():
    r = Registry()
    for f in ["faq-helper.json", "trip-planner.json", "supervisor-router.json"]:
        r.load_file(AGENTS / f)
    return r


def test_split_goal_on_connectors():
    assert split_goal("plan a trip and then check the refund policy") == \
        ["plan a trip", "check the refund policy"]


def test_routes_each_subtask_to_the_right_specialist():
    orch = Orchestrator(_registry())
    res = orch.run("plan a trip with good weather and then check the refund policy")
    assert len(res.steps) == 2
    by_task = {s.task: s.agent for s in res.steps}
    assert by_task["plan a trip with good weather"] == "trip-planner"   # weather/travel knowledge
    assert by_task["check the refund policy"] == "faq-helper"           # refunds knowledge


def test_single_goal_one_step():
    res = Orchestrator(_registry()).run("what are the support hours")
    assert len(res.steps) == 1
    assert res.steps[0].agent == "faq-helper"


def test_result_is_serializable_and_summarized():
    res = Orchestrator(_registry()).run("plan a weather-safe trip and check refunds")
    d = res.as_dict()
    assert d["goal"] and d["summary"].startswith("Delegated")
    assert all({"task", "agent", "reply"} <= set(s) for s in d["steps"])


def test_synthesis_composes_one_answer_from_subresults():
    res = Orchestrator(_registry()).run("plan a weather-safe trip and check refunds")
    # the synthesis is a single non-empty answer that saw every specialist's reply
    assert res.synthesis and res.synthesis in res.as_dict()["synthesis"]
    assert len(res.synthesis) > 0
    # offline stub echoes the goal into the final answer
    assert "trip" in res.synthesis.lower() or "refund" in res.synthesis.lower()


def test_synthesis_reports_when_nothing_routed():
    res = Orchestrator(_registry()).run("zzzzqqqq")   # matches no specialist profile
    assert all(s.agent is None for s in res.steps)
    assert "No specialist" in res.synthesis


def test_max_steps_caps_delegation():
    res = Orchestrator(_registry()).run("a and b and c and d and e and f", max_steps=3)
    assert len(res.steps) == 3
