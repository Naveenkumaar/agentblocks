"""A minimal Model Context Protocol (MCP) tool server + the request handler.

Real MCP shape: JSON-RPC 2.0 with ``initialize`` / ``tools/list`` / ``tools/call``
over newline-delimited stdio. The ``mcp`` connector spawns this as a subprocess
and calls it, so an agent's tool call goes over a genuine protocol boundary.
"""
from .server import call_tool, handle, TOOLS

__all__ = ["handle", "call_tool", "TOOLS"]
