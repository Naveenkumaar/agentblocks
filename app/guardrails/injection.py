"""Lightweight prompt-injection detection.

A deny-list of well-known override phrasings. Real systems layer this with a
classifier and, more importantly, keep the *connector* — not the prompt — as the
trust boundary (see ``connectors/base.py``). This catches the obvious attempts
and is what the adversarial eval suite exercises.
"""
from __future__ import annotations

import re

_SIGNALS = [
    r"ignore (all |the )?(previous|prior|above) instructions",
    r"disregard (the )?(system|previous) prompt",
    r"you are now .{0,40}(dan|developer mode|unfiltered)",
    r"reveal (your )?(system|hidden) prompt",
    r"print (your )?instructions",
    r"show me (other|all) (users|customers|tenants)",
]
_COMPILED = [re.compile(s, re.IGNORECASE) for s in _SIGNALS]


def detect_injection(text: str) -> tuple[bool, str | None]:
    """Return (is_injection, matched_signal)."""
    for pattern in _COMPILED:
        if pattern.search(text):
            return True, pattern.pattern
    return False, None
