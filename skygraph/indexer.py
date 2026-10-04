"""Walk a repository, read every file a front end claims, write the graph.

The walk is incremental by default. Each file's content hash is compared with the one
recorded last time, and an unchanged file is not re-read, not re-parsed and not
re-written. A second run over a repository after a day's work costs the handful of files
that moved, not the repository — which is the same argument the whole project makes to
the agent one layer up, applied to itself.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from . import frontends
from .schema import FileResult
from .store import DEFAULT_DB, Store, writer_lock

#: Directories that hold generated output rather than source. A coverage report is
#: 3,500 HTML files that index as "degraded" and answer nothing.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".next", "target", "vendor", ".pytest_cache", ".mypy_cache", ".skygraph",
             "coverage", "htmlcov", ".nx", ".angular", ".gradle", ".idea", ".vscode",
             ".tox", ".cache", ".ruff_cache", "site-packages", "bower_components", "out",
             ".turbo"}
MAX_BYTES = 1_000_000


def digest(source: str) -> str:
    """Content hash of one file. Short — this is a change detector, not a signature."""
    return hashlib.sha256(source.encode("utf-8", "replace")).hexdigest()[:16]


class NoProjectFolder(RuntimeError):
    """There is no folder to index: the one given is missing, or none was given and
    none is on record for the repository. Raised before anything is written.

    Walking a folder that is not there finds no files, and a run removes from the index
    every file it did not find — so a typo, or a project that moved, used to empty that
    repository's index without a word.
    """


def index(root: str | Path | None, repo: str | None = None, branch: str = "main",
          db: str = DEFAULT_DB, full: bool = False, model=None) -> dict:
    """Index a tree. `full=True` re-reads every file instead of only what changed.

    `root=None` means the folder this repository was last indexed from, as recorded in
    the index. The session-start hook uses that, so the settings file it lives in names
    no path from one person's machine.

    `model` is an optional tier-3 fallback for files no parser could read. It is asked
    only about those, only up to its budget, and everything it returns is marked as its
    own — see `model.py`.

    One run at a time per index: a second run waits for the first, then reads only
    what is still out of date (see `writer_lock`).
    """
    with writer_lock(db):
        store = Store(db)
        # Closed here, not left to the garbage collector: Windows refuses to delete a
        # database file that any connection still holds, so a caller removing a
        # temporary index right after the run failed there.
        try:
            return _index(store, root, repo, branch, full, model)
        finally:
            store.db.close()


def _index(store: Store, root: str | Path | None, repo: str | None, branch: str,
           full: bool, model) -> dict:
    if root is None:
        root = store.root_of(repo, branch) if repo else None
        if root is None:
            raise NoProjectFolder(f"{repo or 'this repository'} is not indexed on this "
                                  "machine yet; run `skygraph init .` in the project")
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise NoProjectFolder(f"{root} is not a folder, so the index was left as it was; "
                              "if the project moved, run `skygraph init` in its new place")
    repo = repo or root.name
    store.remember_root(repo, branch, str(root))
    present: set[str] = set()
    unparsed: list[tuple[str, str, str]] = []
    read = unchanged = skipped = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            claimed = frontends.language_of(rel)
            if claimed is None and not frontends.unclaimed_source(rel):
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    skipped += 1
                    continue
                raw = p.read_bytes()
            except OSError:
                skipped += 1
                continue
            if b"\x00" in raw[:8192]:
                # A null byte in the first pages means this is not text, whatever the
                # extension says. Reading a .docx with errors="replace" produced
                # mojibake that the heuristic tier then found "functions" in.
                skipped += 1
                continue
            source = raw.decode("utf-8", "replace")

            present.add(rel)
            now = digest(source)
            if not full and store.digest_of(rel, repo, branch) == now:
                unchanged += 1
                continue

            result = frontends.parse(rel, source)
            result.digest = now
            store.write(result, repo, branch)
            read += 1
            if result.tier == "heuristic":
                # No parser claimed it. Tier 3 gets a look, if one is configured.
                unparsed.append((rel, result.language, now))

    model_report = _model_pass(store, root, repo, branch, unparsed, model)

    # A file that vanished from the tree must vanish from the graph. Leaving it is the
    # same failure as a stale symbol: the index answers confidently about code that is
    # no longer there.
    removed = store.prune(present, repo, branch)

    # Call targets can only be resolved once every file is in: a front end sees one
    # file and a call site names a bare callee. This is the pass that turns `helper`
    # into `src/util.py::helper` — and the one that makes the graph worth more than a
    # text search, because the callee usually lives in a different file.
    # Imports first: a call's receiver is resolved through them.
    import_counts = store.resolve_imports(repo, branch)
    resolution = store.resolve_calls(repo, branch)

    # And only once calls are resolved can the layers be joined: a handler reaches a
    # table through a model, and that middle step is a call.
    links = store.link_layers(repo, branch)

    out = store.stats(repo, branch)
    out.update(repo=repo, branch=branch,
               indexed=read, unchanged=unchanged, removed=len(removed), skipped=skipped,
               calls=resolution, imports=import_counts, links=links, model=model_report,
               degraded=len(store.degraded(repo, branch)))
    if store.rebuilt:
        out["rebuilt"] = "the index was built by an older schema and was rebuilt"
    return out


def _model_pass(store: Store, root: Path, repo: str, branch: str,
                unparsed: list[tuple[str, str, str]], model) -> dict:
    """Tier 3, over the files tiers 1 and 2 could not read. Never over the others.

    A failure here is never fatal. The heuristic result for that file is already
    written, so a file the model could not be asked about keeps the answer it had, plus
    a note saying why there is not a better one.
    """
    if model is None:
        return {"used": False,
                "reason": "no model configured — set SKYGRAPH_MODEL_KEY to enable tier 3"
                          if unparsed else "no model configured, and nothing needed one",
                "candidates": len(unparsed)}

    report = dict(model.describe(), used=True, candidates=len(unparsed),
                  attempted=0, accepted=0, failed=0, refused_rows=0,
                  over_budget=max(0, len(unparsed) - model.budget), problems=[])

    for path, language, digest in unparsed[:model.budget]:
        try:
            source = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        report["attempted"] += 1
        try:
            reply = model.read(path, source, language)
            symbols, edges, refused = model_rows(path, reply)
        except Exception as exc:                                   # noqa: BLE001
            report["failed"] += 1
            if len(report["problems"]) < 5:
                report["problems"].append(f"{path}: {exc}")
            continue

        report["refused_rows"] += len(refused)
        if not symbols:
            # A correct answer for a file that declares nothing, and not worth
            # replacing a heuristic guess with an empty one.
            continue
        note = f"no parser could read this; a model read it ({model.name})"
        if refused:
            note += f"; {len(refused)} row(s) refused as undeclared"
        store.write(FileResult(path=path, language=language, tier="model",
                               symbols=symbols, edges=edges, degraded=note,
                               digest=digest), repo, branch)
        report["accepted"] += 1
    return report


def model_rows(path: str, reply: dict):
    """Indirection so tests can drive the validator without importing the client."""
    from .model import to_rows
    return to_rows(path, reply)
