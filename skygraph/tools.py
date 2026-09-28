"""The thirteen tools, and the reasoning behind their shape.

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
    asked = int(args.get("limit", 20)) if str(args.get("limit", 20)).lstrip("-").isdigit() else 20
    found = store.search(query, args.get("repo", ""), args.get("branch", "main"),
                         _rows(args), args.get("ontology", ""))
    out = {"results": found}
    if asked > MAX_ROWS:
        out["note"] = f"limit capped at {MAX_ROWS}; narrow the query rather than paging"
    return out


def list_files(store: Store, args: dict) -> dict:
    repo = _need(args, "repo", "list_files")
    found = store.files(repo, args.get("branch", "main"), args.get("prefix", ""),
                        _rows(args, default=MAX_ROWS))
    out = {"files": found}
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
           "contains": store.children(name, *scope),
           "calls": [h for h in hops if h["dir"] == "out"],
           "called_by": [h for h in hops if h["dir"] == "in"]}
    if found["kind"] == "Endpoint":
        out["trace"] = store.trace(name, *scope)["chain"]
    return out


def outline_file(store: Store, args: dict) -> dict:
    """Every declaration in a file, with its line range — the shape, not the bodies.

    This is the cheap way to understand a file. An agent that would otherwise read two
    thousand lines to learn that a module has nine functions gets the nine names.
    """
    repo = _need(args, "repo", "outline_file")
    path = _need(args, "filepath", "outline_file")
    branch = args.get("branch", "main")
    rows = store.in_file(path, repo, branch)
    if not rows:
        # A suffix is what an agent usually has to hand, so try it before giving up.
        match = [f["path"] for f in store.files(repo, branch, limit=5000)
                 if f["path"].endswith("/" + path) or f["path"] == path]
        if match:
            rows = store.in_file(match[0], repo, branch)
            path = match[0]
    return {"repo": repo, "filepath": path,
            "signatures": [{k: r[k] for k in
                            ("name", "kind", "line", "end_line", "tier", "summary")}
                           for r in rows]}


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
    out: dict = {"repo": repo, "filepath": path, "direction": which}
    if which in ("imports", "both"):
        out["imports"] = [r["dst"] for r in
                          _import_edges(store, repo, branch, path, "imports")]
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
    report["ontology_reference"] = describe()
    return report


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
