"""MCP tool server + connector tests (real JSON-RPC over a subprocess)."""
from pathlib import Path

from app.connectors import OpenMeteoConnector  # noqa: F401 (ensures registry import ok)
from app.connectors import build_connector
from app.engine.definition import Connector as Spec
from app.engine.registry import Registry
from app.engine.runtime import Engine
from app.mcp import TOOLS, call_tool, handle

AGENTS = Path(__file__).parents[1] / "agents"


def test_server_handler_lists_and_calls_tools():
    assert set(TOOLS) == {"echo", "add", "upper"}
    listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names == {"echo", "add", "upper"}
    r = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "add", "arguments": {"a": "2", "b": "3"}}})
    assert r["result"]["content"][0]["text"] == "5.0"
    assert r["result"]["isError"] is False


def test_call_tool_unknown_raises():
    try:
        call_tool("nope", {})
    except ValueError:
        return
    raise AssertionError("unknown tool should raise")


def test_connector_calls_the_real_subprocess_server():
    c = build_connector(Spec(name="mcp-server", kind="mcp", config={"tool": "upper"}))
    res = c.invoke({"query": "hello mcp"})
    assert res.ok
    assert res.data["text"] == "HELLO MCP"
    assert res.data["is_error"] is False


def test_connector_add_tool():
    c = build_connector(Spec(name="m", kind="mcp", config={"tool": "add"}))
    res = c.invoke({"a": "10", "b": "5"})
    assert res.ok and res.data["text"] == "15.0"


def test_pipeline_hydrates_from_mcp():
    r = Registry()
    r.load_file(AGENTS / "mcp-tools-agent.json")
    result = Engine().run_turn(r.get("mcp-tools-agent"), "ping over mcp")
    hydrate = [s for s in result.trace if s["stage"] == "hydrate"]
    assert hydrate and hydrate[0]["ok"]
    assert not result.blocked
