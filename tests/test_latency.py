"""Every trace step carries a per-stage latency (ms)."""
from pathlib import Path

from app.engine.registry import Registry
from app.engine.runtime import Engine

AGENTS = Path(__file__).parents[1] / "agents"


def test_every_stage_has_non_negative_ms():
    r = Registry()
    r.load_file(AGENTS / "faq-helper.json")
    result = Engine().run_turn(r.get("faq-helper"), "What are your support hours?")
    assert result.trace
    for step in result.trace:
        assert "ms" in step
        assert isinstance(step["ms"], (int, float))
        assert step["ms"] >= 0
    total = sum(s["ms"] for s in result.trace)
    assert total >= 0
