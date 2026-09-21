"""An MCP server over stdio. Five read-only tools; the index is never written here.

Tool names carry the `code_` prefix, so a host sees `mcp__<server>__code_search`.
"""
from __future__ import annotations
import json, sys
from .store import Store

TOOLS = [
    {"name": "code_search", "description": "Find symbols whose name matches a query.",
     "inputSchema": {"type": "object", "required": ["repo", "query"], "properties": {
         "repo": {"type": "string"}, "query": {"type": "string"},
         "branch": {"type": "string", "default": "main"}, "limit": {"type": "integer", "default": 20}}}},
    {"name": "code_neighbours", "description": "One hop over CALLS and IMPORTS from a symbol, both directions.",
     "inputSchema": {"type": "object", "required": ["repo", "symbol"], "properties": {
         "repo": {"type": "string"}, "symbol": {"type": "string"}, "branch": {"type": "string", "default": "main"}}}},
    {"name": "code_repos", "description": "List indexed repositories and branches.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "code_stats", "description": "Counts for one repository: files, symbols, edges, languages, tiers.",
     "inputSchema": {"type": "object", "required": ["repo"], "properties": {
         "repo": {"type": "string"}, "branch": {"type": "string", "default": "main"}}}},
    {"name": "code_degraded", "description": "Files that did not parse at their best tier, and why.",
     "inputSchema": {"type": "object", "required": ["repo"], "properties": {
         "repo": {"type": "string"}, "branch": {"type": "string", "default": "main"}}}},
]


def call(store: Store, name: str, args: dict):
    if name == "code_search":
        return store.search(args["query"], args["repo"], args.get("branch", "main"), args.get("limit", 20))
    if name == "code_neighbours":
        return store.neighbours(args["symbol"], args["repo"], args.get("branch", "main"))
    if name == "code_repos":
        return store.repos()
    if name == "code_stats":
        return store.stats(args["repo"], args.get("branch", "main"))
    if name == "code_degraded":
        return store.degraded(args["repo"], args.get("branch", "main"))
    raise KeyError(f"no such tool: {name}")


def serve(db: str = "code-index.db") -> None:
    store = Store(db)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid, method = req.get("id"), req.get("method")
        try:
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "skynet-code-index", "version": "0.1.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                p = req.get("params", {})
                payload = call(store, p["name"], p.get("arguments", {}))
                result = {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}
            else:
                raise KeyError(f"unsupported method: {method}")
            out = {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as exc:                                   # noqa: BLE001
            out = {"jsonrpc": "2.0", "id": rid,
                   "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
