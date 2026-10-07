"""The runtime emits a normalized event stream that drives the agent map."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.events import EventBus, EventType, bus
from app.main import app

client = TestClient(app)

TERMINALS = {"run.completed", "run.blocked", "run.approval_required", "run.failed"}


def test_event_bus_ring_buffer_and_since_seq():
    b = EventBus(maxlen=5)
    for i in range(8):
        b.emit("r1", "agent-a", EventType.STAGE, stage="assemble", i=i)
    recent = b.recent()
    assert len(recent) == 5                      # bounded
    seqs = [e["seq"] for e in recent]
    assert seqs == sorted(seqs)                  # ascending
    # since_seq streams only newer events
    newer = b.recent(since_seq=seqs[-2])
    assert [e["seq"] for e in newer] == seqs[-1:]


def test_bus_groups_runs_with_terminal_status():
    b = EventBus()
    b.emit("runX", "agent-a", EventType.RUN_STARTED)
    b.emit("runX", "agent-a", EventType.STAGE, stage="ingress")
    b.emit("runX", "agent-a", EventType.RUN_COMPLETED)
    runs = b.runs()
    assert runs[0]["run_id"] == "runX"
    assert runs[0]["status"] == "run.completed"
    assert len(runs[0]["events"]) == 3


def test_turn_emits_full_lifecycle_via_api():
    bus.clear()
    agents = client.get("/agents").json()
    assert agents, "expected at least one seeded agent"
    name = agents[0]["name"]

    r = client.post(f"/v1/agents/{name}/turns", json={"message": "hello there"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("run_id")                    # turn result carries its run id

    types = [e["type"] for e in client.get("/events").json()["events"]]
    assert "run.started" in types
    assert "run.stage" in types
    assert TERMINALS & set(types), f"no terminal event in {types}"

    runs = client.get("/events/runs").json()["runs"]
    assert runs and runs[0]["events"]
    # our turn's run is present (a delegating agent may spawn further sub-runs,
    # so it is not necessarily the newest).
    assert any(r["run_id"] == body["run_id"] for r in runs)
