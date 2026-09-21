"""SQLite store. Symbols, edges, and the repo/branch scope every row carries.

Scope is on the row, not on the query. A query that forgets to filter returns nothing
rather than another repository's code — the failure is empty, not wrong.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .schema import FileResult

DDL = """
CREATE TABLE IF NOT EXISTS symbols (
  name TEXT, kind TEXT, path TEXT, line INTEGER, tier TEXT,
  repo TEXT NOT NULL, branch TEXT NOT NULL,
  PRIMARY KEY (name, repo, branch)
);
CREATE TABLE IF NOT EXISTS edges (
  src TEXT, rel TEXT, dst TEXT,
  repo TEXT NOT NULL, branch TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  path TEXT, language TEXT, tier TEXT, degraded TEXT,
  repo TEXT NOT NULL, branch TEXT NOT NULL,
  PRIMARY KEY (path, repo, branch)
);
CREATE INDEX IF NOT EXISTS ix_sym_scope  ON symbols(repo, branch);
CREATE INDEX IF NOT EXISTS ix_edge_src   ON edges(src, repo, branch);
CREATE INDEX IF NOT EXISTS ix_edge_dst   ON edges(dst, repo, branch);
"""


class Store:
    def __init__(self, path: str | Path = "code-index.db") -> None:
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(DDL)

    def write(self, result: FileResult, repo: str, branch: str) -> None:
        cur = self.db.cursor()
        cur.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)",
                    (result.path, result.language, result.tier, result.degraded, repo, branch))
        for s in result.symbols:
            cur.execute("INSERT OR REPLACE INTO symbols VALUES (?,?,?,?,?,?,?)",
                        (s.name, s.kind, s.path, s.line, s.tier, repo, branch))
        for e in result.edges:
            cur.execute("INSERT INTO edges VALUES (?,?,?,?,?)", (e.src, e.rel, e.dst, repo, branch))
        self.db.commit()

    # ── reads, all scoped ──────────────────────────────────────────────────

    def search(self, query: str, repo: str, branch: str = "main", limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            "SELECT name, kind, path, line, tier FROM symbols "
            "WHERE repo=? AND branch=? AND name LIKE ? ORDER BY length(name) LIMIT ?",
            (repo, branch, f"%{query}%", limit)).fetchall()
        return [dict(r) for r in rows]

    def neighbours(self, symbol: str, repo: str, branch: str = "main",
                   rels: tuple[str, ...] = ("CALLS", "IMPORTS")) -> list[dict]:
        """One hop, both directions — the callee in another file, and the caller."""
        marks = ",".join("?" * len(rels))
        out = self.db.execute(
            f"SELECT dst AS other, rel, 'out' AS dir FROM edges "
            f"WHERE repo=? AND branch=? AND src=? AND rel IN ({marks}) "
            f"UNION ALL "
            f"SELECT src AS other, rel, 'in' AS dir FROM edges "
            f"WHERE repo=? AND branch=? AND dst=? AND rel IN ({marks})",
            (repo, branch, symbol, *rels, repo, branch, symbol, *rels)).fetchall()
        return [dict(r) for r in out]

    def repos(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT repo, branch, COUNT(*) AS files FROM files GROUP BY repo, branch").fetchall()
        return [dict(r) for r in rows]

    def degraded(self, repo: str, branch: str = "main") -> list[dict]:
        """Every file that did not parse at its best tier, and why. Read this."""
        rows = self.db.execute(
            "SELECT path, language, tier, degraded FROM files "
            "WHERE repo=? AND branch=? AND degraded IS NOT NULL", (repo, branch)).fetchall()
        return [dict(r) for r in rows]

    def stats(self, repo: str, branch: str = "main") -> dict:
        f = self.db.execute("SELECT COUNT(*) FROM files WHERE repo=? AND branch=?", (repo, branch)).fetchone()[0]
        s = self.db.execute("SELECT COUNT(*) FROM symbols WHERE repo=? AND branch=?", (repo, branch)).fetchone()[0]
        e = self.db.execute("SELECT COUNT(*) FROM edges WHERE repo=? AND branch=?", (repo, branch)).fetchone()[0]
        langs = self.db.execute("SELECT COUNT(DISTINCT language) FROM files WHERE repo=? AND branch=?", (repo, branch)).fetchone()[0]
        tiers = {r["tier"]: r["n"] for r in self.db.execute(
            "SELECT tier, COUNT(*) AS n FROM files WHERE repo=? AND branch=? GROUP BY tier", (repo, branch))}
        return {"files": f, "symbols": s, "edges": e, "languages": langs, "tiers": tiers}
