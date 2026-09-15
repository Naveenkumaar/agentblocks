"""Connector base class — where tenant scope is enforced, below the model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ConnectorResult:
    ok: bool
    data: Any
    connector: str


class Connector:
    """Base connector. Subclasses implement :meth:`_call`.

    :meth:`invoke` is the only public entry point. It merges the caller's
    trust-scope into the parameter map *before* dispatching, so an agent (or a
    prompt injected into it) can never widen its own scope.
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config = config or {}

    def invoke(self, params: dict[str, Any], scope: dict[str, Any] | None = None) -> ConnectorResult:
        scoped = dict(params)
        if scope:
            # Scope wins — it is injected last and cannot be overridden by params.
            scoped.update(scope)
        try:
            return ConnectorResult(ok=True, data=self._call(scoped), connector=self.name)
        except Exception as exc:  # surfaced to the trace, never crashes a turn
            return ConnectorResult(ok=False, data=str(exc), connector=self.name)

    def _call(self, params: dict[str, Any]) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError
