"""`skygraph demo` — see skygraph answer, on a sample project, in one command.

Seeing skygraph work used to need your own project and an agent wired to it. Someone
evaluating it should need neither. This copies a small sample shop — a Python API, an
order service, stock, two tables, a TypeScript client, a Dockerfile and a CI file —
into a temporary folder, indexes it into a temporary database, and asks it the
questions a coding agent asks, through the same tool functions the MCP server serves.
Everything is removed afterwards; your own index is not touched.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .indexer import index
from .store import Store
from .tools import TOOLS

SAMPLE = Path(__file__).parent / "demo_sample"
REPO = "shop"


def _short(name: str) -> str:
    """`shop/orders.py::OrderService.place` → `OrderService.place (shop/orders.py)`."""
    path, _sep, symbol = name.partition("::")
    return f"{symbol} ({path})" if symbol else name


def _ask(store: Store, tool: str, **args) -> tuple[dict, int]:
    args.setdefault("repo", REPO)
    answer = TOOLS[tool][0](store, args)
    return answer, len(json.dumps(answer))


def _where(answer: dict) -> list[str]:
    rows = answer.get("results") or []
    if not rows:
        return ["(not found)"]
    row = rows[0]
    line = f"{row['path']}:{row['line']}" + (f"–{row['end_line']}" if row.get("end_line") else "")
    summary = f' — "{row["summary"]}"' if row.get("summary") else ""
    return [f"{line}   {row['kind'].lower()} {row['name'].split('::')[-1]}{summary}"]


def _trace(answer: dict) -> list[str]:
    lines = []
    for hop in answer.get("trace") or []:
        tables = ", ".join(hop.get("tables") or []) or "(no table)"
        lines.append(f"→ {_short(hop['handler'])}")
        lines.append(f"→ {_short(hop['entity'])} → table {tables}")
        lines.append(f"  ({hop.get('confidence', '')})")
    return lines or ["(no handler found)"]


def _callers(answer: dict) -> list[str]:
    rows = answer.get("called_by") or []
    return [f"← {_short(r['other'])}" for r in rows] or ["(no callers)"]


def _calls(answer: dict) -> list[str]:
    rows = [r for r in answer.get("calls") or [] if "::" in r["other"]]
    return [f"→ {_short(r['other'])}" for r in rows] or ["(no calls into this project)"]


def _blast(answer: dict) -> list[str]:
    rows = sorted(answer.get("callers") or [], key=lambda r: r["depth"])
    return [f"{'  ' * (r['depth'] - 1)}← {_short(r['symbol'])}" for r in rows] or ["(nothing)"]


def _health(answer: dict) -> list[str]:
    parsed = [r["language"] for r in answer.get("languages", []) if r.get("traversable")]
    other = [r["language"] for r in answer.get("languages", []) if not r.get("traversable")]
    lines = [f"parsed, with calls: {', '.join(parsed) or 'none'}"]
    if other:
        lines.append(f"read for what they declare: {', '.join(other)}")
    lines.append(f"files degraded: {answer.get('degraded_files', 0)}")
    return lines


def run(out=sys.stdout) -> int:
    say = lambda text="": print(text, file=out)                      # noqa: E731
    say("skygraph demo — a sample shop: a Python API, an order service, stock, two")
    say("tables, a TypeScript client, a Dockerfile and a CI file.")
    say()
    with tempfile.TemporaryDirectory(prefix="skygraph-demo-") as tmp:
        project = Path(tmp) / REPO
        shutil.copytree(SAMPLE, project, ignore=shutil.ignore_patterns("__pycache__"))
        started = time.monotonic()
        report = index(project, repo=REPO, db=str(Path(tmp) / "index.db"))
        took = time.monotonic() - started
        calls = report.get("calls", {})
        took_text = f"{took * 1000:.0f} ms" if took < 1 else f"{took:.1f} s"
        say(f"Indexed {report['files']} files in {took_text}: {report['symbols']} symbols, "
            f"{calls.get('resolved', 0)} calls resolved, {report['degraded']} files degraded.")
        say("These are the questions a coding agent asks instead of opening files:")

        store = Store(Path(tmp) / "index.db")
        try:
            endpoint = next((r["name"] for r in store.search("", REPO, ontology="api_ontology",
                                                              limit=20)
                             if r["name"].endswith("POST /orders")), "")
            questions = [
                ("Where is OrderService declared?",
                 "find_symbols", {"query": "OrderService"}, _where),
                ("What does POST /orders write to?",
                 "expand_symbol", {"qualified_name": endpoint}, _trace),
                ("Who calls Inventory.reserve?",
                 "expand_symbol", {"qualified_name": "shop/inventory.py::Inventory.reserve"},
                 _callers),
                ("What is affected if Inventory.reserve changes?",
                 "blast_radius", {"symbol": "shop/inventory.py::Inventory.reserve",
                                  "direction": "up", "hops": 3}, _blast),
                ("What does the TypeScript checkout call?",
                 "expand_symbol", {"qualified_name": "web/src/checkout.ts::Checkout.submit"},
                 _calls),
                ("Can the agent trust this index?",
                 "index_health", {}, _health),
            ]
            for number, (question, tool, args, render) in enumerate(questions, 1):
                answer, size = _ask(store, tool, **args)
                say()
                say(f"{number}. {question}")
                say(f"   {tool} · {size:,} bytes back to the agent")
                for line in render(answer):
                    say(f"   {line}")
        finally:
            store.db.close()
    say()
    say("Each answer is what Claude Code or Codex receives through skygraph's fourteen")
    say("tools, instead of opening the files. The sample and its index were temporary and")
    say("are gone.")
    say()
    say("Try it on your own code:  skygraph init /path/to/your/project")
    return 0
