"""MCP connector — a real Model Context Protocol client.

Spawns an MCP tool server (default: this repo's ``app.mcp.server``) as a
subprocess, performs the JSON-RPC handshake, and calls a tool — so an agent's
skill invocation crosses a genuine protocol boundary. Base ``Connector.invoke``
still wraps this in try/except, so a missing/faulty server degrades to
``ok=False`` rather than crashing the turn.

Config:
  command:   argv list to launch the server (default runs app.mcp.server)
  tool:      which tool to call (e.g. "echo", "add", "upper")
  arguments: static arguments merged into every call
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import Connector

_REPO_ROOT = Path(__file__).resolve().parents[2]


class McpConnector(Connector):
    def _call(self, params: dict[str, Any]) -> Any:
        command = self.config.get("command") or [sys.executable, "-m", "app.mcp.server"]
        tool = params.pop("tool", None) or self.config.get("tool", "echo")

        arguments = dict(self.config.get("arguments", {}))
        # map the hydrator's free-text query to a "text" argument when useful
        if "query" in params and "text" not in arguments:
            arguments["text"] = params["query"]
        for k, v in params.items():
            if k != "query":
                arguments[k] = v

        proc = subprocess.Popen(command, cwd=str(_REPO_ROOT), text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            def rpc(method: str, p: dict | None = None, rid: int = 1) -> dict:
                proc.stdin.write(json.dumps(
                    {"jsonrpc": "2.0", "id": rid, "method": method, "params": p or {}}) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            rpc("initialize", rid=0)
            resp = rpc("tools/call", {"name": tool, "arguments": arguments}, rid=1)
        finally:
            try:
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "shutdown"}) + "\n")
                proc.stdin.flush()
                proc.stdin.close()
            except Exception:
                pass
            proc.terminate()

        result = resp.get("result", {})
        content = result.get("content") or [{}]
        return {"tool": tool, "text": content[0].get("text"),
                "is_error": result.get("isError", False)}
