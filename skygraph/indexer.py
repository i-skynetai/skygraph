"""Walk a repository, parse every file a front end claims, write the graph."""
from __future__ import annotations
import os
from pathlib import Path
from . import frontends
from .store import Store

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".next", "target", "vendor", ".pytest_cache", ".mypy_cache"}
MAX_BYTES = 1_000_000


def index(root: str | Path, repo: str | None = None, branch: str = "main",
          db: str = "code-index.db") -> dict:
    root = Path(root).resolve()
    repo = repo or root.name
    store = Store(db)
    seen = skipped = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = str(p.relative_to(root))
            if frontends.language_of(rel) is None and p.suffix not in (".md", ".txt"):
                continue
            if frontends.language_of(rel) is None:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    skipped += 1
                    continue
                source = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped += 1
                continue
            store.write(frontends.parse(rel, source), repo, branch)
            seen += 1

    out = store.stats(repo, branch)
    out.update(repo=repo, branch=branch, indexed=seen, skipped=skipped,
               degraded=len(store.degraded(repo, branch)))
    return out
