"""Governance block — kill switch, quotas, rollout, maker-checker approvals."""
from .approvals import Approval, ApprovalError, ApprovalStore
from .checks import GovernanceError, enforce

__all__ = ["GovernanceError", "enforce", "Approval", "ApprovalError", "ApprovalStore"]
