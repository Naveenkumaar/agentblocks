"""Agents calling agents: a coordinating agent delegates via an agent connector."""
from pathlib import Path

from app.connectors import AgentConnector, build_connector
from app.engine.definition import Connector
from app.engine.registry import Registry
from app.engine.runtime import Engine

AGENTS = Path(__file__).parents[1] / "agents"


def test_build_connector_resolves_agent_kind():
    spec = Connector(name="c", kind="agent", config={"agent": "faq-helper"})
    assert isinstance(build_connector(spec), AgentConnector)


def test_agent_connector_runs_a_subturn():
    c = AgentConnector("faq-specialist", {"agent": "faq-helper"})
    res = c.invoke({"query": "what are the support hours"})
    assert res.ok
    assert res.data["agent"] == "faq-helper"
    assert res.data["reply"]                      # the specialist actually replied


def test_missing_target_degrades_gracefully():
    res = AgentConnector("c", {}).invoke({"query": "hi"})
    assert res.ok is False                        # base wrapper catches the ValueError


def test_concierge_agent_delegates_end_to_end():
    reg = Registry()
    reg.load_file(AGENTS / "faq-helper.json")
    reg.load_file(AGENTS / "concierge-agent.json")
    turn = Engine().run_turn(reg.get("concierge-agent"), "what are the support hours")
    # the concierge folded the faq-helper's delegated answer into its own turn
    assert turn.reply
    assert any(t.get("connector") == "faq-specialist" for t in turn.trace)
