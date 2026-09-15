from pathlib import Path

from app.engine.registry import Registry
from app.engine.runtime import Engine
from evals.run_eval import evaluate

AGENTS = Path(__file__).parents[1] / "agents"


def _registry() -> Registry:
    registry = Registry()
    for path in sorted(AGENTS.glob("*.json")):
        registry.load_file(path)
    return registry


def test_all_agents_load():
    names = _registry().names()
    assert {"faq-helper", "trip-planner", "supervisor-router"} <= set(names)


def test_versions_are_immutable():
    registry = _registry()
    definition = registry.get("faq-helper")
    try:
        registry.add_version(definition)
    except ValueError:
        return
    raise AssertionError("re-adding an existing version should raise")


def test_turn_runs_and_traces_all_stages():
    engine = Engine()
    result = engine.run_turn(_registry().get("faq-helper"), "What are your support hours?")
    assert not result.blocked
    stages = [step["stage"] for step in result.trace]
    assert stages[0] == "ingress"
    assert "reason-act" in stages
    assert stages[-1] == "egress"


def test_hydrator_skill_calls_connector():
    engine = Engine()
    result = engine.run_turn(_registry().get("trip-planner"), "weather for my trip please")
    assert any(step["stage"] == "hydrate" for step in result.trace)


def test_eval_gate_passes_for_every_seeded_agent():
    registry = _registry()
    for name in registry.names():
        assert evaluate(registry.get(name))["passed"], name
