"""An MCP server over stdio. Thirteen read-only tools; the index is never written here.

The surface itself — what each tool does and why it is shaped that way — lives in
`tools.py`. This module is only the protocol: framing, dispatch and errors. There is no
write tool of any kind, because indexing is a separate and deliberate act.

**A notification is never answered.** In JSON-RPC a message with no `id` is a
notification: the sender is not waiting and must not be replied to. Every host sends
`notifications/initialized` immediately after the handshake, and this server used to
answer it with an error carrying `"id": null` — a reply to something that asked no
question, and a made-up id. A strict host is entitled to drop the connection there.

**The protocol version is negotiated, not asserted.** The server used to state one
version whatever the client asked for. Now it echoes the client's version when it is one
this server speaks, and otherwise answers with its own so the client can decide.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from . import __version__
from .ontology import ONTOLOGIES
from .store import DEFAULT_DB, Store
from .tools import TOOLS as SURFACE

#: Versions this server speaks. The first is what it offers when it cannot agree.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: Argument shapes, by name. Declared once rather than per tool, because the same
#: argument means the same thing everywhere and an agent should not have to check.
ARGUMENT = {
    "repo":        {"type": "string", "description": "Repository name as list_repos reports it."},
    "branch":      {"type": "string", "default": "main"},
    "query":       {"type": "string", "description": "Name fragment, e.g. 'login' or 'RetryPolicy'."},
    "qualified_name": {"type": "string", "description": "Full symbol name as the graph stores it, e.g. 'src/auth.py::Session.renew'. Get one from find_symbols."},
    "filepath":    {"type": "string", "description": "Repo-relative file path, e.g. 'src/auth/session.py'."},
    "symbol":      {"type": "string", "description": "Symbol name or fragment."},
    "prefix":      {"type": "string", "description": "Limit to paths starting with this."},
    "path_prefix": {"type": "string", "description": "Directory to group under, with a trailing slash. Empty means the top level."},
    "ontology":    {"type": "string", "enum": list(ONTOLOGIES), "description": "Limit to one ontology."},
    "direction":   {"type": "string", "description": "'imports', 'imported_by' or 'both'; for blast_radius, 'down', 'up' or 'both'."},
    "hops":        {"type": "integer", "default": 1, "description": "How many levels to walk (1-10)."},
    "limit":       {"type": "integer", "default": 20},
}

#: Which optional arguments each tool accepts, beyond the ones it requires.
OPTIONAL = {
    "find_symbols": ("repo", "branch", "ontology", "limit"),
    "list_files": ("branch", "prefix", "limit"),
    "map_coverage": ("branch", "path_prefix"),
    "describe_symbol": ("repo", "branch"),
    "expand_symbol": ("repo", "branch"),
    "outline_file": ("branch",),
    "read_source": ("repo", "branch"),
    "related_symbols": ("repo", "branch"),
    "file_imports": ("branch", "direction"),
    "blast_radius": ("branch", "direction", "hops", "limit"),
    "repo_summary": ("branch",),
    "index_health": ("branch",),
}


def tool_list() -> list[dict]:
    """The MCP tool list, derived from the surface in `tools.py`."""
    out = []
    for name, (_fn, description, required) in SURFACE.items():
        props = {k: dict(ARGUMENT[k]) for k in required}
        props.update({k: dict(ARGUMENT[k]) for k in OPTIONAL.get(name, ())})
        out.append({"name": name, "description": description,
                    "inputSchema": {"type": "object", "required": list(required),
                                    "properties": props}})
    return out


TOOLS = tool_list()


def call(store: Store, name: str, args: dict):
    """Dispatch. A tool that does not exist and a missing argument both raise KeyError,
    and the protocol layer turns either into an invalid-params error the caller can act
    on rather than a stack trace."""
    try:
        handler = SURFACE[name][0]
    except KeyError:
        raise KeyError(f"no such tool: {name}") from None
    return handler(store, args)


class ProtocolError(Exception):
    """A request this server can answer, but not the way it was asked."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def negotiate(asked: str | None) -> str:
    """Echo the client's version when we speak it; otherwise offer ours."""
    return asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


def handle(store: Store, req: dict) -> dict | None:
    """One request in, one response out — or None when nothing may be sent back."""
    if not isinstance(req, dict) or req.get("jsonrpc") != "2.0":
        raise ProtocolError(INVALID_REQUEST, "a request must be JSON-RPC 2.0")

    method = req.get("method")
    if not isinstance(method, str):
        raise ProtocolError(INVALID_REQUEST, "a request must name a method")

    # No id means a notification: the sender is not waiting, so nothing goes back —
    # not a result, and not an error either.
    if "id" not in req:
        return None

    if method == "initialize":
        asked = (req.get("params") or {}).get("protocolVersion")
        return {"protocolVersion": negotiate(asked),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "skygraph", "version": __version__}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        if not isinstance(name, str):
            raise ProtocolError(INVALID_PARAMS, "tools/call needs a tool name")
        try:
            payload = call(store, name, params.get("arguments") or {})
        except KeyError as exc:
            # A missing argument and an unknown tool are both the caller's mistake,
            # and both are recoverable — say which, without a Python class name and
            # without making the caller guess which argument was meant.
            detail = str(exc).strip("'")
            if not detail.startswith("no such tool"):
                detail = f"{name} needs a {detail!r} argument"
            raise ProtocolError(INVALID_PARAMS, detail) from exc
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}

    raise ProtocolError(METHOD_NOT_FOUND, f"unsupported method: {method}")


def _fingerprint(db: str) -> tuple:
    """Enough of the database file to notice it has been replaced."""
    try:
        info = Path(db).expanduser().stat()
        return (info.st_ino, info.st_mtime_ns, info.st_size)
    except OSError:
        return ()


def _reply(out: dict) -> None:
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def serve(db: str = DEFAULT_DB) -> None:
    store = Store(db)
    watched = _fingerprint(db)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            # Nothing was parsed, so there is no id to answer against. The spec's
            # answer is a null id, and this is the one case where that is correct.
            _reply({"jsonrpc": "2.0", "id": None,
                    "error": {"code": PARSE_ERROR, "message": "invalid JSON"}})
            continue

        rid = req.get("id") if isinstance(req, dict) else None

        # An index is rebuilt by a separate command, which replaces the file. A server
        # holding the old handle keeps serving a database that no longer exists —
        # answering from a deleted inode, with line numbers that no longer match the
        # tree. It looks like it is working, which is why it has to be checked.
        now = _fingerprint(db)
        if now != watched:
            store = Store(db)
            watched = now

        try:
            result = handle(store, req)
        except ProtocolError as exc:
            if "id" not in req:
                continue                       # still a notification: say nothing
            _reply({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": exc.code, "message": str(exc)}})
            continue
        except Exception as exc:                                   # noqa: BLE001
            if isinstance(req, dict) and "id" not in req:
                continue
            _reply({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": INTERNAL_ERROR, "message": str(exc)}})
            continue

        if result is None:                     # a notification: nothing goes back
            continue
        _reply({"jsonrpc": "2.0", "id": rid, "result": result})
