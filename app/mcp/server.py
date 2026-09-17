"""A minimal MCP tool server — JSON-RPC 2.0 over newline-delimited stdio.

Run standalone:  python -m app.mcp.server
It answers ``initialize``, ``tools/list`` and ``tools/call``. Three demo tools
(echo / add / upper) keep it deterministic and dependency-free.
"""
from __future__ import annotations

import json
import sys

TOOLS = {
    "echo": {"description": "Echo the input text back.", "params": ["text"]},
    "add": {"description": "Add two numbers a and b.", "params": ["a", "b"]},
    "upper": {"description": "Uppercase the input text.", "params": ["text"]},
}


def call_tool(name: str, args: dict) -> str:
    if name == "echo":
        return str(args.get("text", ""))
    if name == "add":
        return str(float(args.get("a", 0)) + float(args.get("b", 0)))
    if name == "upper":
        return str(args.get("text", "")).upper()
    raise ValueError(f"unknown tool: {name}")


def handle(req: dict) -> dict:
    method, rid = req.get("method"), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "agentblocks-mcp", "version": "0.1.0"},
            "capabilities": {"tools": {}}}}
    if method == "tools/list":
        tools = [{"name": n, "description": t["description"],
                  "inputSchema": {"type": "object",
                                  "properties": {p: {"type": "string"} for p in t["params"]}}}
                 for n, t in TOOLS.items()]
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}}
    if method == "tools/call":
        p = req.get("params", {})
        try:
            text = call_tool(p.get("name"), p.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}}
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        sys.stdout.write(json.dumps(handle(req)) + "\n")
        sys.stdout.flush()
        if req.get("method") == "shutdown":
            break


if __name__ == "__main__":
    main()
