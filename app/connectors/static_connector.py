"""Static connector — returns canned data from its config.

Useful for demos and tests: an agent can declare a ``static`` connector whose
``config["data"]`` is returned verbatim, so a definition is fully runnable with
no external dependency.
"""
from __future__ import annotations

from typing import Any

from .base import Connector


class StaticConnector(Connector):
    def _call(self, params: dict[str, Any]) -> Any:
        return self.config.get("data", {"echo": params})
