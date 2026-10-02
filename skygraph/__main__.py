"""CLI:  index a repository, query it, or serve it over MCP."""
from __future__ import annotations

import argparse, json, sys
from .indexer import NoProjectFolder, index
from .model import DEFAULT_BUDGET, Model
from .store import IndexNewerThanServer, Store, writer_lock
from . import __version__, mcp

#: One store, not one per project. `list_repos` only means anything if several
#: repositories share it, and an agent that has to be told which database to open has
#: already lost the round trip this project exists to save. Defined in `store.py`.
from .store import DEFAULT_DB                                     # noqa: E402,F401


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (IndexNewerThanServer, NoProjectFolder) as exc:
        print(f"skygraph: {exc}", file=sys.stderr)
        return 2


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="skygraph", description="Code intelligence for agents.")
    ap.add_argument("--version", action="version", version=f"skygraph {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="walk a repository and build the graph")
    p.add_argument("path", nargs="?",
                   help="the project folder; leave it out to refresh the folder --repo "
                        "was last indexed from")
    p.add_argument("--repo"); p.add_argument("--branch", default="main")
    p.add_argument("--full", action="store_true", help="re-read every file, not only what changed")
    p.add_argument("--model-key", default="",
                   help="enable tier 3 for files no parser could read "
                        "(or set SKYGRAPH_MODEL_KEY)")
    p.add_argument("--model-budget", type=int, default=0,
                   help=f"most files to send in one run (default {DEFAULT_BUDGET})")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--summary", action="store_true",
                   help="one line instead of the JSON report (what a hook prints)")

    p = sub.add_parser("init", help="wire a project to Claude Code and Codex, then index it")
    p.add_argument("path"); p.add_argument("--repo")
    p.add_argument("--no-hook", action="store_true", help="do not install the session-start hook")
    p.add_argument("--codex", action="store_true", help="also write ~/.codex/config.toml")
    p.add_argument("--no-index", action="store_true", help="write the config only")
    p.add_argument("--db", default=DEFAULT_DB)

    p = sub.add_parser("search", help="find symbols by name")
    p.add_argument("query"); p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="main"); p.add_argument("--db", default=DEFAULT_DB)

    p = sub.add_parser("neighbours", help="one hop over CALLS and IMPORTS")
    p.add_argument("symbol"); p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="main"); p.add_argument("--db", default=DEFAULT_DB)

    p = sub.add_parser("forget", help="drop one repository from the index")
    p.add_argument("--repo", required=True); p.add_argument("--branch", default="main")
    p.add_argument("--db", default=DEFAULT_DB)

    p = sub.add_parser("degraded", help="files that did not parse at their best tier")
    p.add_argument("--repo", required=True); p.add_argument("--branch", default="main")
    p.add_argument("--db", default=DEFAULT_DB)

    p = sub.add_parser("serve", help="run the MCP server on stdio")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--repo", default=None,
                   help="the repository a tool means when the call names none")

    p = sub.add_parser("ontologies", help="the five ontologies, as JSON — the shared definition")

    sub.add_parser("demo", help="index a sample project and answer an agent's questions about it")

    a = ap.parse_args(argv)
    if a.cmd == "index":
        report = index(a.path, a.repo, a.branch, a.db, full=a.full,
                       model=Model.from_environment(a.model_key, a.model_budget))
        if a.summary:
            from .install import summary_line
            print(summary_line(report))
        else:
            print(json.dumps(report, indent=2))
    elif a.cmd == "init":
        from .install import init
        init(a.path, a.repo, a.db, hook=not a.no_hook, codex=a.codex, run_index=not a.no_index)
    elif a.cmd == "demo":
        from .demo import run
        return run()
    elif a.cmd == "ontologies":
        from .ontology import describe
        print(json.dumps(describe(), indent=2))
    elif a.cmd == "search":
        print(json.dumps(Store(a.db).search(a.query, a.repo, a.branch), indent=2))
    elif a.cmd == "neighbours":
        print(json.dumps(Store(a.db).neighbours(a.symbol, a.repo, a.branch), indent=2))
    elif a.cmd == "forget":
        with writer_lock(a.db):
            forgotten = Store(a.db).forget(a.repo, a.branch)
        print(json.dumps({"repo": a.repo, "branch": a.branch, "files_forgotten": forgotten}))
    elif a.cmd == "degraded":
        print(json.dumps(Store(a.db).degraded(a.repo, a.branch), indent=2))
    elif a.cmd == "serve":
        mcp.serve(a.db, default_repo=a.repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())


def serve_entry() -> None:
    """Console-script entry point for the MCP server.

    A host is given one command and no working directory, so the server it starts must
    not depend on where it was started. `pip install` puts this on PATH; the
    `skygraph-mcp` script beside this file does the same job for a plain checkout.
    """
    import argparse
    ap = argparse.ArgumentParser(prog="skygraph-mcp")
    ap.add_argument("--version", action="version", version=f"skygraph-mcp {__version__}")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--repo", default=None)
    a = ap.parse_args()
    mcp.serve(a.db, default_repo=a.repo)
