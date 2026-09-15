"""Agent + version registry with an activation gate.

Versions are immutable once created. A version cannot be *activated* (made
live) until it passes its eval gate — enforced by :meth:`activate`, which calls
back into the eval runner.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.engine.definition import AgentDefinition


class Registry:
    def __init__(self) -> None:
        # name -> {version:int -> AgentDefinition}
        self._versions: dict[str, dict[int, AgentDefinition]] = {}
        # name -> active version int
        self._active: dict[str, int] = {}

    # ---- authoring -----------------------------------------------------
    def add_version(self, definition: AgentDefinition) -> AgentDefinition:
        versions = self._versions.setdefault(definition.name, {})
        if definition.version in versions:
            raise ValueError(
                f"{definition.name} v{definition.version} already exists (versions are immutable)"
            )
        versions[definition.version] = definition
        return definition

    def load_file(self, path: str | Path) -> AgentDefinition:
        data = json.loads(Path(path).read_text())
        return self.add_version(AgentDefinition(**data))

    # ---- lookup --------------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self._versions)

    def get(self, name: str, version: int | None = None) -> AgentDefinition:
        versions = self._versions.get(name)
        if not versions:
            raise KeyError(f"no such agent: {name}")
        if version is None:
            version = self._active.get(name) or max(versions)
        return versions[version]

    def is_active(self, name: str) -> bool:
        return name in self._active

    # ---- activation gate ----------------------------------------------
    def activate(self, name: str, version: int, gate) -> dict:
        """Activate ``version`` only if ``gate(definition)`` passes.

        ``gate`` is a callable returning a dict with a boolean ``passed`` — the
        eval runner. This is the single most important control in the platform.
        """
        definition = self.get(name, version)
        result = gate(definition)
        if not result.get("passed"):
            raise PermissionError(
                f"{name} v{version} failed the eval gate: {result.get('summary')}"
            )
        self._active[name] = version
        return result
