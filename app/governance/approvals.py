"""Maker-checker (four-eyes) approvals for high-risk effector skills.

A ``hydrator`` skill only *reads*, so it runs inline. An ``effector`` skill
*acts* — and when its ``risk_tier`` is at or above the agent's
``approval_required_tier``, the turn does **not** execute it. Instead it records
a pending :class:`Approval` (the *maker*'s request) and suspends. A different
person (the *checker* — enforced ``checker != maker``) must approve before the
action runs. This is the platform's core "don't let one identity both request
and authorise a risky action" control.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ApprovalError(Exception):
    """Raised when an approval decision is invalid."""


@dataclass
class Approval:
    id: str
    agent: str
    skill: str
    maker: str
    params: dict[str, Any]
    status: str = "pending"          # pending | approved | rejected | executed
    checker: str | None = None
    result: Any = None


class ApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, Approval] = {}
        self._seq = 0

    def create(self, agent: str, skill: str, maker: str, params: dict[str, Any]) -> Approval:
        self._seq += 1
        appr = Approval(id=f"AP-{self._seq:04d}", agent=agent, skill=skill,
                        maker=maker, params=dict(params))
        self._items[appr.id] = appr
        return appr

    def get(self, approval_id: str) -> Approval | None:
        return self._items.get(approval_id)

    def pending(self) -> list[Approval]:
        return [a for a in self._items.values() if a.status == "pending"]

    def decide(self, approval_id: str, checker: str, approve: bool) -> Approval:
        appr = self._items.get(approval_id)
        if appr is None:
            raise ApprovalError(f"no such approval: {approval_id}")
        if appr.status != "pending":
            raise ApprovalError(f"approval {approval_id} is already {appr.status}")
        if checker == appr.maker:
            raise ApprovalError("checker must differ from maker (four-eyes control)")
        appr.checker = checker
        appr.status = "approved" if approve else "rejected"
        return appr
