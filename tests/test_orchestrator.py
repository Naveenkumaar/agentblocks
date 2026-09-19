"""Autonomous orchestrator: decompose a goal, route each part to a specialist."""
from pathlib import Path

from app.engine.orchestrator import Orchestrator, plan_goal, split_goal
from app.engine.registry import Registry


class _FakeReply:
    def __init__(self, text): self.text = text


class _FakeLLM:
    """Stand-in for an Ollama-backed model that decomposes a goal to JSON."""
    backend = "ollama"

    def __init__(self, text): self._text = text

    def generate(self, system, user, context=""): return _FakeReply(self._text)

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


def test_planner_falls_back_to_rules_offline():
    # no model / stub model → deterministic regex split
    assert plan_goal("plan a trip and then check refunds") == \
        split_goal("plan a trip and then check refunds")


def test_planner_uses_llm_decomposition_when_available():
    llm = _FakeLLM('Here you go: ["book the flight", "reserve a hotel", "check the weather"]')
    assert plan_goal("arrange my trip", llm) == \
        ["book the flight", "reserve a hotel", "check the weather"]


def test_planner_falls_back_on_bad_llm_output():
    llm = _FakeLLM("sorry I cannot help with that")   # no JSON array
    assert plan_goal("plan a trip and check refunds", llm) == \
        split_goal("plan a trip and check refunds")


def test_clear_match_is_high_confidence_with_scores():
    res = Orchestrator(_registry()).run("check the refund policy")
    step = res.steps[0]
    assert step.agent == "faq-helper" and step.confidence == "high"
    assert step.score > 0
    assert step.alternatives and step.alternatives[0]["agent"] == "faq-helper"
    assert not step.needs_clarification


def test_no_match_asks_to_clarify_instead_of_guessing():
    res = Orchestrator(_registry()).run("zzzzqqqq")
    step = res.steps[0]
    assert step.agent is None and step.confidence == "none"
    assert step.needs_clarification and "clarify" in step.reply.lower()


def test_tie_is_flagged_ambiguous_not_guessed():
    from app.engine.definition import AgentDefinition
    r = Registry()
    # two agents whose only distinctive token is the same → a one-word task ties
    for name in ("alpha-widget", "beta-widget"):
        r.add_version(AgentDefinition(
            name=name, version=1, description="handles widget requests",
            default_topic="main",
            topics=[{"name": "main", "mode": "chat",
                     "system_prompt": "help with widgets", "skills": []}]))
    res = Orchestrator(r).run("widget")
    step = res.steps[0]
    assert step.agent is None and step.confidence == "low"
    assert step.needs_clarification
    assert {a["agent"] for a in step.alternatives} == {"alpha-widget", "beta-widget"}
    assert "need clarification" in res.summary


def test_max_steps_caps_delegation():
    res = Orchestrator(_registry()).run("a and b and c and d and e and f", max_steps=3)
    assert len(res.steps) == 3
