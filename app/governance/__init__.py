"""Governance block — kill switch, quotas, rollout."""
from .checks import GovernanceError, enforce

__all__ = ["GovernanceError", "enforce"]
