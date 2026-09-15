"""Reversible PII tokenization for synthetic data.

``redact_pii`` replaces detected spans with stable ``[[TYPE_n]]`` tokens and
returns a vault mapping token -> original. ``restore`` reverses it for an
authorized audience. This is a demonstration of the tokenize/detokenize pattern
on fake data — not a production PII engine.
"""
from __future__ import annotations

import re

_PATTERNS = {
    "EMAIL": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "PHONE": re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\d{10}|\d{3}[\s-]\d{3}[\s-]\d{4})\b"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


def redact_pii(text: str) -> tuple[str, dict[str, str]]:
    """Return (redacted_text, vault) where vault maps token -> original value."""
    vault: dict[str, str] = {}
    counters: dict[str, int] = {}

    def _sub(kind: str):
        def repl(match: re.Match) -> str:
            counters[kind] = counters.get(kind, 0) + 1
            token = f"[[{kind}_{counters[kind]}]]"
            vault[token] = match.group(0)
            return token

        return repl

    for kind, pattern in _PATTERNS.items():
        text = pattern.sub(_sub(kind), text)
    return text, vault


def restore(text: str, vault: dict[str, str]) -> str:
    """Detokenize — only call this for an audience allowed to see raw values."""
    for token, original in vault.items():
        text = text.replace(token, original)
    return text
