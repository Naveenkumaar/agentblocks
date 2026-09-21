"""Topological execution schedule — group independent steps into layers."""
from pathlib import Path

from app.engine.orchestrator import Orchestrator, schedule_layers
from app.engine.registry import Registry

AGENTS = Path(__file__).parents[1] / "agents"


def test_independent_steps_share_layer_zero():
    steps = [{"task": "a", "deps": []}, {"task": "b", "deps": []}]
    assert schedule_layers(steps) == [[0, 1]]


def test_chain_makes_one_layer_per_step():
    steps = [{"task": "a", "deps": []},
             {"task": "b", "deps": [0]},
             {"task": "c", "deps": [1]}]
    assert schedule_layers(steps) == [[0], [1], [2]]


def test_diamond_dependency():
    # 0 → {1, 2} → 3    (1 and 2 are independent, so they share a layer)
    steps = [{"task": "0", "deps": []},
             {"task": "1", "deps": [0]},
             {"task": "2", "deps": [0]},
             {"task": "3", "deps": [1, 2]}]
    assert schedule_layers(steps) == [[0], [1, 2], [3]]


def _orch():
    r = Registry()
    for f in ["faq-helper.json", "trip-planner.json"]:
        r.load_file(AGENTS / f)
    return Orchestrator(r)


def test_result_and_preview_expose_layers():
    orch = _orch()
    # two independent sub-tasks → both in layer 0
    res = orch.run("plan a weather-safe trip and check the refund policy")
    assert res.layers == [[0, 1]]
    assert res.as_dict()["layers"] == [[0, 1]]
    # an edited plan with an edge puts the dependent step in a later layer
    preview = orch.plan("plan a trip and check the refund policy")
    assert "layers" in preview
    edited = [{"task": "check the refund policy", "deps": []},
              {"task": "plan a trip with nice weather", "deps": [0]}]
    assert orch.run(plan=edited).layers == [[0], [1]]
