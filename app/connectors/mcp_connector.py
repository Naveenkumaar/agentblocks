"""MCP connector (stub).

Placeholder for a Model Context Protocol tool server. The interface mirrors the
others so an agent definition can declare ``kind: mcp`` today and get a wired
implementation later without any engine changes.
"""
from __future__ import annotations

from typing import Any

from .base import Connector


class McpConnector(Connector):
    def _call(self, params: dict[str, Any]) -> Any:
        tool = params.get("tool", "unknown")
        # TODO: connect to an MCP server (self.config["server"]) and call `tool`.
        return {
            "note": "MCP connector stub — wire an MCP server here.",
            "server": self.config.get("server"),
            "tool": tool,
            "params": {k: v for k, v in params.items() if k != "tool"},
        }
