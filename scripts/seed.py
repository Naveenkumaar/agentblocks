"""Validate and summarise the seeded agent definitions.

    python scripts/seed.py

Loads every agent JSON through the real :class:`AgentDefinition` model (so a
malformed block fails loudly) and prints a one-line summary per agent.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.engine.registry import Registry  # noqa: E402

AGENTS = Path(__file__).parents[1] / "agents"


def main() -> int:
    registry = Registry()
    for path in sorted(AGENTS.glob("*.json")):
        registry.load_file(path)

    for name in registry.names():
        d = registry.get(name)
        print(
            f"{name:20} v{d.version}  topics={len(d.topics)} "
            f"skills={len(d.skills)} connectors={len(d.connectors)} "
            f"knowledge={len(d.knowledge)}"
        )
    print(f"\nLoaded {len(registry.names())} agents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
