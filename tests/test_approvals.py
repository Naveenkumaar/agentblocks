"""Maker-checker approval tests."""
from pathlib import Path

import pytest

from app.engine.registry import Registry
from app.engine.runtime import Engine
from app.governance import ApprovalError, ApprovalStore

AGENTS = Path(__file__).parents[1] / "agents"


def _agent():
    r = Registry()
    return r.load_file(AGENTS / "mc-verify-agent.json")


def test_high_risk_effector_suspends_the_turn():
    engine = Engine(approvals=ApprovalStore())
    result = engine.run_turn(_agent(), "please refund my order", audience="alice")
    assert result.suspended
    assert result.approval_id
    assert not result.blocked
    pending = engine.approvals.pending()
    assert len(pending) == 1 and pending[0].maker == "alice"


def test_checker_must_differ_from_maker():
    engine = Engine(approvals=ApprovalStore())
    result = engine.run_turn(_agent(), "refund please", audience="alice")
    with pytest.raises(ApprovalError):
        engine.approvals.decide(result.approval_id, checker="alice", approve=True)


def test_second_approver_executes_the_action():
    engine = Engine(approvals=ApprovalStore())
    agent = _agent()
    result = engine.run_turn(agent, "refund please", audience="alice")
    appr = engine.approvals.decide(result.approval_id, checker="bob", approve=True)
    assert appr.status == "approved"
    engine.execute_approved(appr, agent)
    assert appr.status == "executed"
    assert appr.result == {"status": "refund issued"}


def test_a_decided_approval_cannot_be_decided_again():
    engine = Engine(approvals=ApprovalStore())
    result = engine.run_turn(_agent(), "refund please", audience="alice")
    engine.approvals.decide(result.approval_id, checker="bob", approve=False)
    with pytest.raises(ApprovalError):
        engine.approvals.decide(result.approval_id, checker="carol", approve=True)
