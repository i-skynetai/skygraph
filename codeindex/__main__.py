"""CLI:  index a repository, query it, or serve it over MCP."""
from __future__ import annotations
import argparse, json, sys
from .indexer import index
from .store import Store
from . import mcp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="codeindex", description="Code intelligence for agents.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="walk a repository and build the graph")
    p.add_argument("path"); p.add_argument("--repo"); p.add_argument("--branch", default="main")
    p.add_argument("--db", default="code-index.db")

    p = sub.add_parser("search", help="find symbols by name")
    p.add_argument("query"); p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="main"); p.add_argument("--db", default="code-index.db")

    p = sub.add_parser("neighbours", help="one hop over CALLS and IMPORTS")
    p.add_argument("symbol"); p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="main"); p.add_argument("--db", default="code-index.db")

    p = sub.add_parser("degraded", help="files that did not parse at their best tier")
    p.add_argument("--repo", required=True); p.add_argument("--branch", default="main")
    p.add_argument("--db", default="code-index.db")

    p = sub.add_parser("serve", help="run the MCP server on stdio")
    p.add_argument("--db", default="code-index.db")

    a = ap.parse_args(argv)
    if a.cmd == "index":
        print(json.dumps(index(a.path, a.repo, a.branch, a.db), indent=2))
    elif a.cmd == "search":
        print(json.dumps(Store(a.db).search(a.query, a.repo, a.branch), indent=2))
    elif a.cmd == "neighbours":
        print(json.dumps(Store(a.db).neighbours(a.symbol, a.repo, a.branch), indent=2))
    elif a.cmd == "degraded":
        print(json.dumps(Store(a.db).degraded(a.repo, a.branch), indent=2))
    elif a.cmd == "serve":
        mcp.serve(a.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
