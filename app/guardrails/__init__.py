"""Request/response guardrails.

Everything here operates on **synthetic data only** (faker-style names, emails,
and fake identifiers). The point is to demonstrate the *pattern* — tokenize PII
on the way in, defend against prompt injection, re-mask per audience on the way
out — not to process anyone's real information.
"""
from .redact import redact_pii, restore
from .injection import detect_injection

__all__ = ["redact_pii", "restore", "detect_injection"]
