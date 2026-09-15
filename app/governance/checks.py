"""Governance checks run before a turn is admitted.

These checks gate execution (kill switch, per-session quota) and raise
:class:`GovernanceError` when a turn must be refused.
"""
from __future__ import annotations

from app.engine.definition import Governance


class GovernanceError(Exception):
    """Raised when governance refuses a turn."""


def enforce(governance: Governance, turn_count: int) -> None:
    if governance.kill_switch:
        raise GovernanceError("agent is disabled by kill switch")
    if turn_count >= governance.max_turns_per_session:
        raise GovernanceError(
            f"session quota exceeded ({turn_count}/{governance.max_turns_per_session})"
        )
