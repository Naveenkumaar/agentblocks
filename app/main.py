"""FastAPI entrypoint — control plane + runtime plane + operator console.

Run:  uvicorn app.main:app --reload --port 8080
Then open http://localhost:8080/ for the console.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.engine.definition import AgentDefinition
from app.engine.registry import Registry
from app.engine.runtime import Engine

# Make the eval gate importable (evals/ is a sibling of app/).
sys.path.insert(0, str(Path(__file__).parents[1]))
from evals.run_eval import make_gate  # noqa: E402

app = FastAPI(title="agentblocks", version="0.1.0")
registry = Registry()
engine = Engine()
_gate = make_gate()

AGENTS_DIR = Path(__file__).parents[1] / "agents"
CONSOLE = Path(__file__).parent / "ui" / "console.html"


def _seed() -> None:
    for path in sorted(AGENTS_DIR.glob("*.json")):
        try:
            registry.load_file(path)
        except ValueError:
            pass  # already loaded (idempotent across reloads)


# Seed at import so the app is populated under any ASGI server or test client.
_seed()


# ---- schemas ----------------------------------------------------------
class TurnRequest(BaseModel):
    message: str
    session_id: str = "default"
    topic: str | None = None
    audience: str = "user"


# ---- control plane ----------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agents": registry.names()}


@app.get("/agents")
def list_agents() -> list[dict]:
    out = []
    for name in registry.names():
        d = registry.get(name)
        out.append({"name": name, "version": d.version, "active": registry.is_active(name),
                    "description": d.description})
    return out


@app.post("/agents/versions")
def add_version(definition: AgentDefinition) -> dict:
    try:
        registry.add_version(definition)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"name": definition.name, "version": definition.version}


@app.post("/agents/{name}/activate")
def activate(name: str, version: int) -> dict:
    try:
        result = registry.activate(name, version, _gate)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"name": name, "version": version, "activated": True, "eval": result}


# ---- runtime plane ----------------------------------------------------
@app.post("/v1/agents/{name}/turns")
def run_turn(name: str, req: TurnRequest) -> dict:
    try:
        agent = registry.get(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    result = engine.run_turn(agent, req.message, session_id=req.session_id,
                             topic_name=req.topic, audience=req.audience)
    return {"reply": result.reply, "blocked": result.blocked,
            "reason": result.reason, "suspended": result.suspended,
            "approval_id": result.approval_id, "trace": result.trace}


# ---- approvals (maker-checker) ----------------------------------------
@app.get("/approvals")
def list_approvals() -> list[dict]:
    return [{"id": a.id, "agent": a.agent, "skill": a.skill, "maker": a.maker,
             "status": a.status} for a in engine.approvals.pending()]


@app.post("/approvals/{approval_id}/decide")
def decide_approval(approval_id: str, checker: str, approve: bool = True) -> dict:
    from app.governance import ApprovalError
    try:
        appr = engine.approvals.decide(approval_id, checker, approve)
    except ApprovalError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if appr.status == "approved":
        engine.execute_approved(appr, registry.get(appr.agent))
    return {"id": appr.id, "status": appr.status, "checker": appr.checker,
            "result": appr.result}


# ---- operator console -------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def console() -> str:
    return CONSOLE.read_text()
