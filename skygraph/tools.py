"""The fourteen tools, and the reasoning behind their shape.

These are what a coding agent sees. The whole point of the project is that the agent
should not read the repository to build context, so every tool here is shaped by one
question: **does this let the agent take one fewer turn, or carry less text, than
reading the folder would?**

Three rules come out of that, and they are worth stating because they are what make the
surface different from a search box.

**Look before you fetch.** Only `read_source` returns code. Everything else returns
structure — names, kinds, line ranges, relations. An agent can locate a symbol, see its
shape, check its callers and decide it is the wrong one, having spent a few hundred
tokens instead of a file.

**Answer the whole question in one call.** `expand_symbol` and `related_symbols`
bundle what an agent would otherwise ask for in four or five round trips. A round trip
costs the whole conversation being re-sent, so a bundled answer is cheaper than the sum
of its parts by a wide margin.

**Say what you do not know.** `index_health` exists because an agent that cannot
see the gaps in an index will answer over them, confidently. An index that is nine
tenths inferred by a language model is a different object from one that is nine tenths
parsed, and nothing in the rows themselves says which you have.
"""
from __future__ import annotations
import json
from pathlib import Path

from .ontology import ONTOLOGIES, describe
from .store import Store

#: How much source one `read_source` call may return. A tool that can be asked for a
#: whole file defeats the purpose of the surface, so the cap is small and the response
#: says when it truncated rather than quietly sending less.
MAX_SOURCE_LINES = 400
#: The most rows any tool will return, whatever was asked for. A tool that can be
#: asked for everything is a way to spend a context window in one call: `list_files`
#: with the old default of 500 was already 18,000 tokens on a large repository, and
#: nothing stopped a caller asking for 100,000.
MAX_ROWS = 200

#: Used when a front end could not record where a declaration ends — see `_end` in
#: frontends. A window around the start is honest; a guessed range is not.
FALLBACK_WINDOW = 40


def _rows(args: dict, default: int = 20) -> int:
    """A caller's `limit`, clamped. Asking for more is not an error; it is capped."""
    try:
        asked = int(args.get("limit", default))
    except (TypeError, ValueError):
        asked = default
    return max(1, min(MAX_ROWS, asked))


#: Bytes `context_for` may return unless asked otherwise: about 1,500 tokens, which is
#: the whole point of a bundle — one call, one budget, the far edges trimmed first.
DEFAULT_BUDGET = 6_000


def _compact(row: dict, scope: bool = True) -> dict:
    """A row without what every other row in the list already said.

    `repo` and `branch` are the same on every row of a scoped answer, `ontology` is
    `code_ontology` nearly always, and an empty `summary` says nothing. On a real index
    the five fields were a third of every list response.
    """
    out = {}
    for key, value in row.items():
        if key in ("repo", "branch") and scope:
            continue
        if key == "ontology" and value == "code_ontology":
            continue
        if key in ("summary", "degraded") and not value:
            continue
        out[key] = value
    return out


def _need(args: dict, key: str, tool: str):
    if key not in args or args[key] in (None, ""):
        raise KeyError(f"{tool} needs a {key!r} argument")
    return args[key]


# ── find ───────────────────────────────────────────────────────────────────

def list_repos(store: Store, args: dict) -> dict:
    """Start here. What is indexed, and how big."""
    return {"repos": store.repos(),
            "ontologies": [o for o in ONTOLOGIES]}


def find_symbols(store: Store, args: dict) -> dict:
    """Find symbols by name fragment. `repo` is optional on purpose.

    An agent usually meets a symptom before it knows which repository is involved, so
    this is the one tool that works without a repo. Narrow it once you know.
    """
    query = _need(args, "query", "find_symbols")
    repo, branch = args.get("repo", ""), args.get("branch", "main")
    asked = int(args.get("limit", 10)) if str(args.get("limit", 10)).lstrip("-").isdigit() else 10
    found = store.search(query, repo, branch, _rows(args, default=10), args.get("ontology", ""))
    out: dict = {"results": [_compact(r, scope=bool(repo)) for r in found]}
    if repo:
        out.update(repo=repo, branch=branch)
    if asked > MAX_ROWS:
        out["note"] = f"limit capped at {MAX_ROWS}; narrow the query rather than paging"
    return out


def list_files(store: Store, args: dict) -> dict:
    repo = _need(args, "repo", "list_files")
    found = store.files(repo, args.get("branch", "main"), args.get("prefix", ""),
                        _rows(args, default=MAX_ROWS))
    out: dict = {"repo": repo, "files": [_compact(f) for f in found]}
    if len(found) == MAX_ROWS:
        out["note"] = (f"{MAX_ROWS} shown; use `prefix` to narrow, or map_coverage to "
                       "see the shape of the tree without listing it")
    return out


def map_coverage(store: Store, args: dict) -> dict:
    """Is this part of the repository indexed, and how well — without paging the files.

    A directory with files but no definitions holds no functions or classes (SQL,
    config, templates). It is still indexed and still searchable; it simply declares
    nothing, and that is a different thing from not being read.
    """
    repo = _need(args, "repo", "map_coverage")
    prefix = args.get("path_prefix", "")
    return {"repo": repo, "path_prefix": prefix,
            "children": store.coverage(repo, args.get("branch", "main"), prefix)}


# ── understand ─────────────────────────────────────────────────────────────

def describe_symbol(store: Store, args: dict) -> dict:
    """Everything about one symbol except its source.

    Returns `result` and `near_matches`. When `result` is empty the near matches usually
    hold the name that was meant — a qualified name is easy to get slightly wrong and a
    bare miss would cost the agent a turn to recover from.
    """
    name = _need(args, "qualified_name", "describe_symbol")
    found = store.definition(name, args.get("repo", ""), args.get("branch", "main"))
    return {"result": found or {},
            "near_matches": [] if found else store.near_matches(name)}


def expand_symbol(store: Store, args: dict) -> dict:
    """One call: the definition, what it contains, what it calls and is called by.

    For an endpoint it also returns the trace — handler, entity, table. That chain is
    the reason the graph has five ontologies rather than one, and asking for it should
    not cost a second round trip: an agent that has just found an endpoint is about to
    ask what it writes to.
    """
    name = _need(args, "qualified_name", "expand_symbol")
    repo = args.get("repo", "")
    branch = args.get("branch", "main")
    found = store.definition(name, repo, branch)
    if not found:
        return {"result": {}, "near_matches": store.near_matches(name)}
    scope = found["repo"], found["branch"]
    hops = store.neighbours(name, *scope)
    out = {"result": found,
           "contains": [_compact(c) for c in store.children(name, *scope)],
           "calls": [_hop(h) for h in hops if h["dir"] == "out"],
           "called_by": [_hop(h) for h in hops if h["dir"] == "in"]}
    if found["kind"] == "Endpoint":
        out["trace"] = store.trace(name, *scope)["chain"]
    return out


def _hop(hop: dict) -> dict:
    """A neighbour without the direction the list already states, and without the
    relation when it is the usual one."""
    out = {"other": hop["other"], "tier": hop["tier"]}
    if hop["rel"] != "CALLS":
        out["rel"] = hop["rel"]
    return out


def outline_file(store: Store, args: dict) -> dict:
    """Every declaration in a file, with its line range — the shape, not the bodies.

    This is the cheap way to understand a file. An agent that would otherwise read two
    thousand lines to learn that a module has nine functions gets the nine names.
    """
    repo = _need(args, "repo", "outline_file")
    path = _need(args, "filepath", "outline_file")
    branch = args.get("branch", "main")
    found = store.resolve_path(path, repo, branch)
    if found is None:
        return _not_indexed(repo, path)
    rows = store.in_file(found, repo, branch)
    return {"repo": repo, "filepath": found,
            "signatures": [_compact({k: r[k] for k in
                                     ("name", "kind", "line", "end_line", "tier", "summary")})
                           for r in rows]}


def _not_indexed(repo: str, path: str) -> dict:
    """An empty list would also mean "indexed, declares nothing" — a SQL file, a
    template — and an agent cannot tell the two apart. A file the index has never seen
    is a different fact, and it is the one that should send the agent to the file."""
    return {"error": f"{path} is not indexed in {repo}: no such file, or more than one "
                     "file ends with that path. Use list_files or map_coverage, or "
                     "re-run `skygraph index`."}


def read_source(store: Store, args: dict) -> dict:
    """The only tool that returns code, and it returns as little of it as it can.

    The index records where a symbol is, never what it says: source copied into a
    database is doubled and goes stale the moment someone edits the file. So this reads
    the file live, off the root recorded at index time.
    """
    name = _need(args, "qualified_name", "read_source")
    found = store.definition(name, args.get("repo", ""), args.get("branch", "main"))
    if not found:
        return {"result": {}, "near_matches": store.near_matches(name)}

    root = store.root_of(found["repo"], found["branch"])
    if not root:
        return {"error": f"no indexed root for {found['repo']}; re-run `skygraph index`"}
    target = Path(root) / found["path"]
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"error": f"cannot read {found['path']}: {exc}. The index is older than "
                         "the tree — re-run `skygraph index`."}

    # A line range is only exact against the file it was recorded from. If the file
    # has moved on, the range is a guess about a file nobody indexed.
    moved = store.stale(found["path"], found["repo"], found["branch"], root)
    start = max(1, found["line"])
    end = found["end_line"] or min(len(lines), start + FALLBACK_WINDOW)
    exact = bool(found["end_line"]) and not moved
    if moved:
        end = min(len(lines), start + FALLBACK_WINDOW)
    body = lines[start - 1:end]
    truncated = len(body) > MAX_SOURCE_LINES
    body = body[:MAX_SOURCE_LINES]
    return {"result": {k: found[k] for k in ("name", "kind", "path", "line", "tier")},
            "from_line": start, "to_line": start + len(body) - 1,
            "exact_range": exact,
            "stale": moved,
            "note": ("this file has changed since it was indexed, so the recorded line "
                     "range no longer describes it — this is a window around the old "
                     "start line. Re-run `skygraph index` before trusting it."
                     if moved else
                     "" if exact else
                     f"this tier records where a declaration starts but not where it "
                     f"ends, so this is a {FALLBACK_WINDOW}-line window, not the symbol"),
            "truncated": truncated,
            "source": "\n".join(body)}


# ── traverse ───────────────────────────────────────────────────────────────

def related_symbols(store: Store, args: dict) -> dict:
    """Everything adjacent to one symbol in a single call."""
    name = _need(args, "qualified_name", "related_symbols")
    found = store.definition(name, args.get("repo", ""), args.get("branch", "main"))
    if not found:
        return {"result": {}, "near_matches": store.near_matches(name)}
    repo, branch, path = found["repo"], found["branch"], found["path"]
    siblings = [s for s in store.in_file(path, repo, branch) if s["name"] != name]
    hops = store.neighbours(name, repo, branch)
    return {"result": found,
            "siblings": [{k: s[k] for k in ("name", "kind", "line")} for s in siblings],
            "calls": [h["other"] for h in hops if h["dir"] == "out"],
            "called_by": [h["other"] for h in hops if h["dir"] == "in"],
            "imported_by": store.importers_of(path, repo, branch)}


def _import_edges(store: Store, repo: str, branch: str, path: str,
                  direction: str) -> list[dict]:
    if direction == "imports":
        rows = store.db.execute(
            "SELECT src, dst, tier FROM edges WHERE repo=? AND branch=? AND rel='IMPORTS' "
            "AND src=?", (repo, branch, path)).fetchall()
    else:
        rows = store.db.execute(
            "SELECT src, dst, tier FROM edges WHERE repo=? AND branch=? AND rel='IMPORTS' "
            "AND (dst=? OR ? LIKE '%' || dst || '%')", (repo, branch, path, path)).fetchall()
    return [dict(r) for r in rows]


def file_imports(store: Store, args: dict) -> dict:
    """Direct imports of a file, in either direction."""
    repo = _need(args, "repo", "file_imports")
    path = _need(args, "filepath", "file_imports")
    branch = args.get("branch", "main")
    which = args.get("direction", "imports")
    found = store.resolve_path(path, repo, branch)
    if found is None:
        return _not_indexed(repo, path)
    path = found
    out: dict = {"repo": repo, "filepath": path, "direction": which}
    if which in ("imports", "both"):
        # `from x import a, b, c` is three edges to one file; say the file once.
        out["imports"] = sorted({r["dst"] for r in
                                 _import_edges(store, repo, branch, path, "imports")})
    if which in ("imported_by", "both"):
        out["imported_by"] = store.importers_of(path, repo, branch)
    return out


def blast_radius(store: Store, args: dict) -> dict:
    """The blast radius around a symbol, deepest rows first.

    Deepest-first because a hot symbol can have more direct callees than `limit`, and
    the far edge of the radius is the part nobody can guess. Truncating the near edge
    loses what the caller could have worked out; truncating the far edge loses the
    reason they asked.
    """
    symbol = _need(args, "symbol", "blast_radius")
    repo = _need(args, "repo", "blast_radius")
    branch = args.get("branch", "main")
    direction = args.get("direction", "down")
    hops = max(1, min(10, int(args.get("hops", 1))))
    limit = _rows(args, default=MAX_ROWS)

    def walk(start: str, outward: bool) -> list[dict]:
        seen, frontier, rows = {start}, [start], []
        for depth in range(1, hops + 1):
            nxt = []
            for node in frontier:
                for h in store.neighbours(node, repo, branch, rels=("CALLS",)):
                    if h["dir"] != ("out" if outward else "in") or h["other"] in seen:
                        continue
                    seen.add(h["other"])
                    rows.append({"symbol": h["other"], "depth": depth, "tier": h["tier"]})
                    nxt.append(h["other"])
            frontier = nxt
            if not frontier:
                break
        return sorted(rows, key=lambda r: -r["depth"])

    out: dict = {"symbol": symbol, "repo": repo, "direction": direction, "hops": hops}
    if direction in ("down", "both"):
        rows = walk(symbol, True)
        out["callees"], out["callees_truncated"] = rows[:limit], len(rows) > limit
    if direction in ("up", "both"):
        rows = walk(symbol, False)
        out["callers"], out["callers_truncated"] = rows[:limit], len(rows) > limit
    return out


# ── trust ──────────────────────────────────────────────────────────────────

def repo_summary(store: Store, args: dict) -> dict:
    repo = _need(args, "repo", "repo_summary")
    branch = args.get("branch", "main")
    stats = store.stats(repo, branch)
    stats.update(repo=repo, branch=branch, root=store.root_of(repo, branch),
                 indexed=stats["files"] > 0)
    return stats


def index_health(store: Store, args: dict) -> dict:
    """How much of this index was read, how much was guessed, and what is missing."""
    repo = _need(args, "repo", "index_health")
    report = store.health(repo, args.get("branch", "main"))
    # Two kilobytes that never change, on every call. Ask for them once.
    if args.get("reference"):
        report["ontology_reference"] = describe()
    else:
        report["ontology_reference"] = "pass reference=true for the five ontologies"
    return report


def context_for(store: Store, args: dict) -> dict:
    """Everything an agent needs to start on one symbol, in one call, under one budget.

    The definition, what its file declares, what the file imports, who calls it and
    what it calls, and the endpoint → table trace when there is one. Five tools' worth
    of round trips, and a round trip re-sends the whole conversation. Over budget, the
    far edges go first — the long caller list — and the answer says what it dropped.
    """
    name = _need(args, "qualified_name", "context_for")
    budget = max(1_000, int(args.get("budget", DEFAULT_BUDGET)))
    found = store.definition(name, args.get("repo", ""), args.get("branch", "main"))
    if not found:
        return {"result": {}, "near_matches": store.near_matches(name)}
    repo, branch, path = found["repo"], found["branch"], found["path"]
    hops = store.neighbours(name, repo, branch)
    outline = [{"name": r["name"].split("::", 1)[-1], "kind": r["kind"], "line": r["line"],
                **({"summary": r["summary"]} if r["summary"] else {})}
               for r in store.in_file(path, repo, branch) if r["kind"] != "Module"]
    # `from x import a, b, c` is three edges to one file; say the file once.
    imports = [r["dst"] for r in store.db.execute(
        "SELECT DISTINCT dst FROM edges WHERE repo=? AND branch=? AND rel='IMPORTS' "
        "AND src=? AND resolution='resolved' ORDER BY dst", (repo, branch, path))]
    coverage = next((c for c in store.language_coverage(repo, branch)
                     if c["language"] == store.db.execute(
                         "SELECT language FROM files WHERE repo=? AND branch=? AND path=?",
                         (repo, branch, path)).fetchone()[0]), None)
    out: dict = {"result": _compact(found, scope=False),
                 "file": {"path": path, "outline": outline, "imports_in_repo": imports},
                 "calls": [h["other"] for h in hops if h["dir"] == "out"],
                 "called_by": [h["other"] for h in hops if h["dir"] == "in"]}
    if found["kind"] == "Endpoint":
        out["trace"] = store.trace(name, repo, branch)["chain"]
    if coverage:
        out["coverage"] = {"language": coverage["language"],
                           "traversable": coverage["traversable"],
                           "untyped_share": round(coverage["untyped"] /
                                                  coverage["call_edges"], 2)
                           if coverage["call_edges"] else None}
    dropped: dict = {}
    lists = [("called_by", out), ("calls", out), ("outline", out["file"]),
             ("imports_in_repo", out["file"])]
    # Measured as the wire sends it — indented — or the budget is a third too generous.
    while len(json.dumps(out, indent=2)) > budget:
        key, holder = max(lists, key=lambda kv: len(kv[1][kv[0]]))
        if len(holder[key]) <= 5:
            break
        keep = len(holder[key]) // 2
        dropped[key] = dropped.get(key, 0) + (len(holder[key]) - keep)
        holder[key] = holder[key][:keep]
    if dropped:
        out["truncated"] = {k: f"{v} more; ask expand_symbol or blast_radius" for k, v in dropped.items()}
    return out


#: Name → (handler, one-line description, required arguments). The MCP layer turns this
#: into a tool list; nothing else needs to know the surface.
TOOLS = {
    "list_repos": (list_repos,
        "What is indexed and how big. Start here.", []),
    "find_symbols": (find_symbols,
        "Find symbols by name fragment. `repo` is optional — use it before you know "
        "which repository is involved.", ["query"]),
    "list_files": (list_files,
        "Indexed files in one repository, optionally under a prefix.", ["repo"]),
    "map_coverage": (map_coverage,
        "Files and definitions per child directory — is this module indexed, and how "
        "well, without paging the file list.", ["repo"]),
    "describe_symbol": (describe_symbol,
        "Metadata for one qualified symbol — kind, file, line range, tier. Never "
        "returns source; pass the name to read_source for that.", ["qualified_name"]),
    "expand_symbol": (expand_symbol,
        "One call: the definition, what it contains, what it calls and what calls it. "
        "For an endpoint, also the trace through handler and entity to the table.",
        ["qualified_name"]),
    "outline_file": (outline_file,
        "Every declaration in a file with its line range — the shape, not the bodies.",
        ["repo", "filepath"]),
    "read_source": (read_source,
        "The source of one symbol, read live off disk. The only tool that returns code.",
        ["qualified_name"]),
    "context_for": (context_for,
        "One call to start on a symbol: its definition, its file's outline and imports, "
        "callers, callees, and the endpoint trace — under a byte budget, far edges "
        "trimmed first.", ["qualified_name"]),
    "related_symbols": (related_symbols,
        "Everything adjacent to one symbol: file siblings, callees, callers, importers.",
        ["qualified_name"]),
    "file_imports": (file_imports,
        "Direct imports of a file, in either direction.", ["repo", "filepath"]),
    "blast_radius": (blast_radius,
        "Transitive callers or callees around a symbol, deepest first.",
        ["repo", "symbol"]),
    "repo_summary": (repo_summary,
        "Counts and root for one repository.", ["repo"]),
    "index_health": (index_health,
        "Parsed versus inferred, degraded files, and which ontologies found nothing. "
        "Read this before trusting an answer.", ["repo"]),
}
