"""SQLite store. Nodes, edges, and the repo/branch scope every row carries.

Scope is on the row, not on the query. A query that forgets to filter returns nothing
rather than another repository's code — the failure is empty, not wrong.

**A file's rows are replaced, never added to.** Writing a file first forgets everything
that file previously contributed, then writes what it contributes now. Appending instead
was the original behaviour and it was wrong twice over: re-indexing unchanged code
doubled every edge, and a symbol that had been renamed or deleted stayed in the graph
answering searches forever. Both are the quiet-incompleteness this project refuses — a
stale answer looks exactly like a correct one.

**A file that has not changed is not re-read.** Every file row carries a content hash,
and the indexer skips a file whose hash has not moved. This is the economic argument of
the whole project: an agent that re-derives context every session pays for the whole
repository every time, and an index that re-parses every run does the same thing one
layer down.
"""
from __future__ import annotations
import json
import posixpath
import re
import sqlite3
from pathlib import Path
from .ontology import PARSED_TIERS
from .schema import FileResult

#: Where the index lives when nobody says otherwise. Defined here, in the module that
#: owns the database, because it was defined twice: the CLI used `~/.skygraph/index.db`
#: and `index()` defaulted to `code-index.db` in the working directory. A caller that
#: used the library rather than the command wrote a second index somewhere else and
#: found the first one empty.
DEFAULT_DB = "~/.skygraph/index.db"

#: Bumped when the table shape changes. An index is derived from source and is never the
#: authority, so a change rebuilds it rather than migrating it — but it says so.
SCHEMA_VERSION = 7

DDL = """
CREATE TABLE IF NOT EXISTS symbols (
  name TEXT, kind TEXT, path TEXT, line INTEGER, end_line INTEGER, tier TEXT,
  ontology TEXT NOT NULL, summary TEXT, returns TEXT,
  repo TEXT NOT NULL, branch TEXT NOT NULL,
  -- The ontology is part of the identity. One name is often two things: a SQLAlchemy
  -- model is a Class in code_ontology and an Entity in data_ontology, and they are both
  -- true. Keying on the name alone let whichever was written second delete the other,
  -- silently, so a repository's class count fell as its model count rose.
  PRIMARY KEY (name, ontology, repo, branch)
);
CREATE TABLE IF NOT EXISTS edges (
  src TEXT, rel TEXT, dst TEXT, tier TEXT,
  ontology TEXT NOT NULL, path TEXT,
  -- What `dst` was before resolution, and how resolution went. A call site names a
  -- bare callee; only a whole-repository pass can say which declaration it meant.
  raw_dst TEXT, resolution TEXT,
  repo TEXT NOT NULL, branch TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  path TEXT, language TEXT, tier TEXT, degraded TEXT, digest TEXT,
  repo TEXT NOT NULL, branch TEXT NOT NULL,
  PRIMARY KEY (path, repo, branch)
);
CREATE TABLE IF NOT EXISTS roots (
  repo TEXT NOT NULL, branch TEXT NOT NULL, root TEXT NOT NULL,
  PRIMARY KEY (repo, branch)
);
CREATE INDEX IF NOT EXISTS ix_sym_scope ON symbols(repo, branch);
CREATE INDEX IF NOT EXISTS ix_sym_path  ON symbols(path, repo, branch);
CREATE INDEX IF NOT EXISTS ix_sym_onto  ON symbols(ontology, repo, branch);
CREATE INDEX IF NOT EXISTS ix_edge_src  ON edges(src, repo, branch);
CREATE INDEX IF NOT EXISTS ix_edge_dst  ON edges(dst, repo, branch);
CREATE INDEX IF NOT EXISTS ix_edge_path ON edges(path, repo, branch);
"""

DERIVED = ("symbols", "edges", "files")
#: `roots` is dropped with the rest on a schema change; it is derived too.
ALL_TABLES = DERIVED + ("roots",)


#: What an import may land on, by the importing file's language. A Python import never
#: names a `.ts` file. Go names a package directory rather than a file and is left
#: external; a language not listed is too.
IMPORT_TARGETS: dict[str, tuple[str, ...]] = {
    "python":     (".py", "/__init__.py"),
    "typescript": (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs",
                   "/index.ts", "/index.tsx", "/index.js"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
                   "/index.js", "/index.ts", "/index.tsx"),
    "java":       (".java",),
    "kotlin":     (".kt",),
    "csharp":     (".cs",),
    "rust":       (".rs", "/mod.rs"),
    "ruby":       (".rb",),
    "php":        (".php",),
    "swift":      (".swift",),
}

#: Languages where a class in the same package is in scope without an import — a
#: Java package, a C# namespace folder, a Kotlin package, a Swift module.
PACKAGE_SCOPED = {"java", "kotlin", "csharp", "swift", "scala"}
#: Source roots under which the directory *is* the package. `src/main/java/com/x`
#: and `src/test/java/com/x` are one package in two directories, and a test calling
#: `Foo.bar()` on the class next door was untyped until the two were read as one.
SOURCE_ROOTS = re.compile(r"^(.*?)/src/[^/]+/(?:java|kotlin|scala)/(.*)$")


def _package_of(path: str) -> str:
    """The scope a same-package receiver is looked up in: project + package.

    Two services in one monorepo both declare `com.x.Foo`; keying on the package
    alone would let one service's class answer for the other's, so the part of the
    path before the source root stays in the key.
    """
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    m = SOURCE_ROOTS.match(path)
    if m:
        return f"{m.group(1)}|{m.group(2).rsplit('/', 1)[0] if '/' in m.group(2) else ''}"
    return folder
#: Languages where a bare `name()` inside a class means `this.name()`.
IMPLICIT_THIS = {"java", "kotlin", "csharp", "swift", "scala", "ruby"}


def _exact(base: str, files: dict, targets: tuple[str, ...]) -> str:
    """The one indexed path `base` names, trying each extension the language allows."""
    for ext in ("",) + targets:
        cand = posixpath.normpath(base + ext)
        if cand in files:
            return cand
    return ""


def _shared_dirs(a: str, b: str) -> int:
    """How many leading directories two paths share."""
    x, y = a.split("/")[:-1], b.split("/")[:-1]
    n = 0
    while n < len(x) and n < len(y) and x[n] == y[n]:
        n += 1
    return n


def _resolve_import(raw: str, importer: str, language: str, files: dict,
                    suffixes: dict, aliases: list) -> tuple[str, str]:
    """(indexed path, "resolved") or ("", "external" | "ambiguous").

    Relative imports — `./b`, `../lib`, `from .sibling` — resolve against the importing
    file's directory and must hit an exact path. Path aliases from `tsconfig` are
    expanded first. Everything else — `pkg.models.User`, `com.app.Repo`, `crate::a::b`
    — becomes a path and is matched as a suffix of an indexed path, longest form first,
    so `pkg.models.User` finds `pkg/models.py` once `pkg/models/User.py` does not
    exist. Several hits: the one sharing the most leading directories with the importer
    wins; a tie is ambiguous, because two `app/models.py` in a monorepo are exactly the
    case where guessing produced the wrong importers.
    """
    targets = IMPORT_TARGETS.get(language)
    raw = (raw or "").strip()
    if not targets or not raw:
        return "", "external"
    here = posixpath.dirname(importer)
    if language == "java" and raw.startswith("static "):
        raw = raw[len("static "):]

    if language in ("typescript", "javascript"):
        for pattern, subs in aliases:
            if pattern.endswith("/*") and raw.startswith(pattern[:-1]):
                rest = raw[len(pattern) - 1:]
                for sub in subs:
                    # `libs/*/src/index.ts`: the star is wherever the tsconfig put it.
                    base = sub.replace("*", rest, 1)
                    found = _exact(base, files, targets)
                    if found:
                        return found, "resolved"
            elif raw == pattern:
                for sub in subs:
                    found = _exact(sub, files, targets)
                    if found:
                        return found, "resolved"

    if raw.startswith(("./", "../")) or raw == ".":
        found = _exact(posixpath.join(here, raw), files, targets)
        return (found, "resolved") if found else ("", "external")

    if language == "python" and raw.startswith("."):
        level = len(raw) - len(raw.lstrip("."))
        base = here
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        parts = [x for x in raw.lstrip(".").split(".") if x]
        for n in range(len(parts), -1, -1):
            cand = posixpath.join(base, *parts[:n]) if parts[:n] else (base or ".")
            found = _exact(cand, files, targets)
            if found:
                return found, "resolved"
        return "", "external"

    parts = [x for x in raw.replace("::", "/").replace(".", "/").split("/")
             if x and x not in ("crate", "self", "super")]
    for n in range(len(parts), 0, -1):
        base = "/".join(parts[:n])
        hits: list[str] = []
        for ext in targets:
            hits += suffixes.get(posixpath.normpath(base + ext), [])
        if not hits:
            continue
        hits = sorted(set(hits), key=lambda h: (-_shared_dirs(h, importer), h))
        if len(hits) == 1 or _shared_dirs(hits[0], importer) > _shared_dirs(hits[1], importer):
            return hits[0], "resolved"
        return "", "ambiguous"
    return "", "external"


def _strip_comments(text: str) -> str:
    """JSON-with-comments, minus the comments — but only outside strings.

    A regex did this first and ate `"@lib/*": ["libs/*/src/index.ts"]`: the `/*` in the
    alias and the `*/` in its target look exactly like a block comment. Every tsconfig
    path pattern has a `/*` in it, so the regex broke on precisely the input that
    matters.
    """
    out, i, n, in_string = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True; out.append(ch)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _path_aliases(root: str | None) -> list[tuple[str, list[str]]]:
    """`compilerOptions.paths` from a tsconfig at the repository root, if any.

    Nearly every TypeScript monorepo imports its own libraries through one — 4,798 of
    one repository's imports begin with an alias — and without it every one of them is
    "external". Comments and trailing commas are tolerated because tsconfig allows them.
    """
    if not root:
        return []
    for name in ("tsconfig.base.json", "tsconfig.json"):
        target = Path(root) / name
        if not target.is_file():
            continue
        try:
            text = re.sub(r",\s*([}\]])", r"\1", _strip_comments(
                target.read_text(encoding="utf-8")))
            options = json.loads(text).get("compilerOptions") or {}
        except (OSError, ValueError, AttributeError):
            continue
        base = options.get("baseUrl") or "."
        out = []
        for pattern, subs in (options.get("paths") or {}).items():
            if isinstance(subs, list):
                out.append((pattern, [posixpath.normpath(posixpath.join(base, s))
                                      for s in subs if isinstance(s, str)]))
        if out:
            return out
    return []


class Store:
    #: True when opening this database discarded an index built by an older version.
    rebuilt: bool

    def __init__(self, path: str | Path = "code-index.db") -> None:
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(path).expanduser()))
        self.db.row_factory = sqlite3.Row
        self.rebuilt = self._reset_if_stale()
        self.db.executescript(DDL)

    def _reset_if_stale(self) -> bool:
        found = self.db.execute("PRAGMA user_version").fetchone()[0]
        if found == SCHEMA_VERSION:
            return False
        present = {r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        had_rows = any(t in present and self.db.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
                       for t in DERIVED)
        for table in ALL_TABLES:
            self.db.execute(f"DROP TABLE IF EXISTS {table}")
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.db.commit()
        return had_rows

    # ── writes ─────────────────────────────────────────────────────────────

    def resolve_path(self, path: str, repo: str, branch: str = "main") -> str | None:
        """The indexed path this names — exactly, or as the unique suffix an agent
        usually has to hand (`auth/session.py` for `src/app/auth/session.py`).

        None when nothing matches, and None when two files match: `models.py` names
        twenty-five files on one codebase, and picking the first would answer about
        whichever one sorts earliest.
        """
        rows = self.db.execute(
            "SELECT path FROM files WHERE repo=? AND branch=? AND (path=? OR path LIKE ?) "
            "ORDER BY path LIMIT 2", (repo, branch, path, f"%/{path}")).fetchall()
        if not rows:
            return None
        if rows[0]["path"] == path or len(rows) == 1:
            return rows[0]["path"]
        return None

    def digest_of(self, path: str, repo: str, branch: str) -> str | None:
        """The content hash recorded for this file, or None if it is not indexed."""
        row = self.db.execute(
            "SELECT digest FROM files WHERE path=? AND repo=? AND branch=?",
            (path, repo, branch)).fetchone()
        return row["digest"] if row else None

    def stale(self, path: str, repo: str, branch: str, root: str | None = None) -> bool:
        """True when the file on disk no longer matches what was indexed.

        The index records a content hash per file, and nothing read it back. So a tool
        that returns a line range kept answering with yesterday's line numbers against
        today's file — confidently, because the range itself was exact when it was
        recorded. That is the worst shape of wrong answer this project has: correct
        data, correct machinery, and an answer that points at the wrong function.
        """
        recorded = self.digest_of(path, repo, branch)
        if recorded is None:
            return False
        root = root or self.root_of(repo, branch)
        if not root:
            return False
        from .indexer import digest                      # local: avoids a cycle
        try:
            return digest(Path(root).joinpath(path).read_text(encoding="utf-8",
                                                              errors="replace")) != recorded
        except OSError:
            return True

    def _forget(self, cur: sqlite3.Cursor, path: str, repo: str, branch: str) -> None:
        for table in DERIVED:
            cur.execute(f"DELETE FROM {table} WHERE path=? AND repo=? AND branch=?",
                        (path, repo, branch))

    def write(self, result: FileResult, repo: str, branch: str) -> None:
        """Replace this file's contribution. Re-writing unchanged input is a no-op."""
        with self.db:                       # one transaction: never half-replaced
            cur = self.db.cursor()
            self._forget(cur, result.path, repo, branch)
            cur.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)",
                        (result.path, result.language, result.tier, result.degraded,
                         result.digest, repo, branch))
            for s in result.symbols:
                cur.execute("INSERT OR REPLACE INTO symbols VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (s.name, s.kind, s.path, s.line, s.end_line, s.tier,
                             s.ontology, s.summary, s.returns, repo, branch))
            for e in result.edges:
                cur.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (e.src, e.rel, e.dst, e.tier, e.ontology, result.path,
                             e.dst, "unresolved", repo, branch))

    def prune(self, keep: set[str], repo: str, branch: str) -> list[str]:
        """Forget indexed files that no longer exist. Returns their paths.

        Without this a deleted file keeps answering searches, which is the same failure
        as a stale symbol: confidently wrong rather than visibly short.
        """
        indexed = [r["path"] for r in self.db.execute(
            "SELECT path FROM files WHERE repo=? AND branch=?", (repo, branch))]
        gone = sorted(p for p in indexed if p not in keep)
        if gone:
            with self.db:
                cur = self.db.cursor()
                for path in gone:
                    self._forget(cur, path, repo, branch)
        return gone

    def remember_root(self, repo: str, branch: str, root: str) -> None:
        """Where this repository lives on disk, so `read_source` can read the file.

        The index holds structure; the disk holds text. Copying source into the database
        would double it and let it go stale the moment someone edits a file, so the one
        tool that returns code reads it live and the index only says where to look.
        """
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO roots VALUES (?,?,?)",
                            (repo, branch, root))

    def root_of(self, repo: str, branch: str = "main") -> str | None:
        row = self.db.execute("SELECT root FROM roots WHERE repo=? AND branch=?",
                              (repo, branch)).fetchone()
        return row["root"] if row else None

    def resolve_imports(self, repo: str, branch: str = "main") -> dict:
        """Point each import at the file it names, once, before anything reads them.

        An import is written as a module — `./thing`, `.store`, `pkg.models.User`,
        `com.app.Repo` — and which file that is takes the whole repository. Matching
        on the last segment was wrong in a way only a large repository shows: 81 of
        1,265 module names on one codebase are shared, so two unrelated `models.py`
        reported the same 162 importers. Now the import is turned into a path and
        matched as one — see `_resolve_import`.

        `raw_dst` keeps the import exactly as written; `dst` becomes the file when
        there is one, and the resolution says which.
        """
        files = {r["path"]: r["language"] for r in self.db.execute(
            "SELECT path, language FROM files WHERE repo=? AND branch=?", (repo, branch))}
        suffixes: dict[str, list[str]] = {}
        for path in files:
            parts = path.split("/")
            for i in range(len(parts)):
                suffixes.setdefault("/".join(parts[i:]), []).append(path)
        aliases = _path_aliases(self.root_of(repo, branch))

        counts = {"resolved": 0, "ambiguous": 0, "external": 0}
        with self.db:
            cur = self.db.cursor()
            for row in self.db.execute(
                    "SELECT rowid, path, raw_dst FROM edges WHERE repo=? AND branch=? "
                    "AND rel='IMPORTS'", (repo, branch)).fetchall():
                found, why = _resolve_import(row["raw_dst"], row["path"],
                                             files.get(row["path"], ""), files,
                                             suffixes, aliases)
                if found:
                    cur.execute("UPDATE edges SET dst=?, resolution='resolved' "
                                "WHERE rowid=?", (found, row["rowid"]))
                else:
                    cur.execute("UPDATE edges SET dst=raw_dst, resolution=? WHERE rowid=?",
                                (why, row["rowid"]))
                counts[why] += 1
        return counts

    def resolve_calls(self, repo: str, branch: str = "main") -> dict:
        """Turn bare call targets into qualified names, using scope before name.

        A parser sees `helper()` and can honestly report only the word. Which
        declaration that is takes the whole repository, so it happens here, once, after
        every file is in — not in the front end, which can only see one file.

        **Name alone does not work at real scale.** On a 270-file repository `run` is
        declared twenty-two times and `get` is called from 1,354 places. Matching on the
        name left 91% of in-repo calls ambiguous, which made the cross-file traversal
        this project exists for mostly empty. So the search runs narrowest first:

        1. `self.x()` inside a class — that class, then any class in the same file.
        2. Same file. A call with no receiver usually means something local.
        3. A module this file imports that declares the name.
        4. Declared exactly once in the whole repository.

        Anything still matching several declarations keeps its bare target and is
        counted as ambiguous. A missing edge makes an agent look; a wrong edge makes it
        confident.
        """
        by_tail: dict[str, list[str]] = {}
        by_file: dict[str, dict[str, str]] = {}
        by_owner: dict[str, dict[str, str]] = {}
        #: Only what a bare `name()` could reach — no methods.
        plain_tail: dict[str, list[str]] = {}
        plain_file: dict[str, dict[str, str]] = {}
        #: Classes by the file that declares them, to tell a receiver naming a class
        #: from one naming a module.
        classes_in: dict[str, dict[str, str]] = {}
        dir_classes: dict[str, dict[str, str]] = {}
        class_names: set[str] = set()
        #: Declared return types, for `x = make(); x.run()`.
        returns_of: dict[str, str] = {}
        #: Every class by bare name, for a typed receiver whose class is declared once.
        class_by_bare: dict[str, list[str]] = {}
        for row in self.db.execute(
                "SELECT name, path, kind, returns FROM symbols WHERE repo=? AND branch=? "
                "AND kind IN ('Function','Method','Class')", (repo, branch)):
            name, path = row["name"], row["path"]
            if row["returns"]:
                returns_of[name] = row["returns"]
            tail = name.rsplit("::", 1)[-1]
            bare = tail.rsplit(".", 1)[-1]
            by_tail.setdefault(bare, []).append(name)
            by_file.setdefault(path, {}).setdefault(bare, name)
            if "." in tail:
                owner = name.rsplit(".", 1)[0]          # path::Class
                by_owner.setdefault(owner, {})[bare] = name
            else:
                # Reachable by a bare `name()`: a module-level function, or a class
                # being constructed. A method is not — it needs a receiver, and
                # treating one as reachable let the builtin `set(...)` resolve to
                # `RuntimeConfig.set`.
                plain_tail.setdefault(bare, []).append(name)
                plain_file.setdefault(path, {}).setdefault(bare, name)
                if row["kind"] == "Class":
                    classes_in.setdefault(path, {})[bare] = name
                    # A Java package is a directory: a class there is in scope for
                    # every file beside it, with no import to record it.
                    dir_classes.setdefault(_package_of(path), {}).setdefault(bare, name)
            if row["kind"] == "Class":
                class_names.add(name)
                class_by_bare.setdefault(bare, []).append(name)

        # module stem -> the file that defines it, for following an import
        #: Which language each file is, so a name is never matched across one. A Java
        #: test calling `put()` was resolving to a TypeScript `ApiClient.put`, because
        #: the name was declared exactly once — in another language entirely.
        language: dict[str, str] = {r["path"]: r["language"] for r in self.db.execute(
            "SELECT path, language FROM files WHERE repo=? AND branch=?",
            (repo, branch))}

        imports: dict[str, set[str]] = {}
        #: Per file, every name it imported and the repository file that name refers
        #: to — or None for a standard-library or third-party import. That None is
        #: what tells `sys.stdout.write` apart from `store.write`.
        named: dict[str, dict[str, tuple[str | None, str]]] = {}
        for row in self.db.execute(
                "SELECT path, raw_dst, dst, resolution FROM edges WHERE repo=? AND "
                "branch=? AND rel='IMPORTS'", (repo, branch)):
            raw = str(row["raw_dst"] or "").lstrip("./").replace("/", ".")
            leaf = raw.split(".")[-1]
            root = raw.split(".")[0] or leaf
            # The outcome matters as much as the path. An import that did not
            # resolve because it is third-party is a different fact from one that did
            # not resolve because two files in this repository share the name, and
            # collapsing both to None made every call through the second look
            # external — a claim we had no basis for.
            target = row["dst"] if row["resolution"] == "resolved" else None
            if target:
                imports.setdefault(row["path"], set()).add(target)
            for alias in {leaf, root}:
                named.setdefault(row["path"], {}).setdefault(
                    alias, (target, row["resolution"]))

        methods = {name for names in by_owner.values() for name in names}
        #: Classes grouped by the file that declares them. Both lookups below used to
        #: scan every class in the repository for every call site — fine on a few
        #: hundred files, and quadratic on seventeen thousand, where one index stopped
        #: making progress entirely.
        owners_in: dict[str, list[tuple[str, dict]]] = {}
        for _owner, _members in by_owner.items():
            owners_in.setdefault(_owner.split("::")[0], []).append((_owner, _members))
        # `untyped` is not `external`: see `unplaced` below. Counting them
        # together hid the difference the whole distinction exists to make.
        counts = {"resolved": 0, "ambiguous": 0, "external": 0, "untyped": 0}
        how: dict[str, int] = {}

        def unplaced(bare: str) -> str:
            """Why a call went unplaced — and the difference is a claim, not a label.

            `external` says the callee is not declared in this repository. When the
            receiver could not be typed we are in no position to say that: both real
            `store.write(...)` call sites were reported external while `Store.write`
            sat in the next file, so "who calls this" answered a confident nothing.
            `untyped` says the true thing, which is that the question was not
            answerable from the receiver we were given.
            """
            return "untyped" if (bare in methods or bare in plain_tail) else "external"

        def place_class(path: str, name: str, mine: str | None) -> str | None:
            """The class a receiver type name means from this file, or None.

            Same file, then an import alias, then a class in an imported file, then
            the same package, then the one class in this language with that name.
            A declared type is a strong claim — `FooService svc` names a class — so
            the unique-class step is safe here where it is not for a bare method name.
            """
            own = classes_in.get(path, {}).get(name)
            if own:
                return own
            target, _outcome = named.get(path, {}).get(name, (None, ""))
            if target and name in classes_in.get(target, {}):
                return classes_in[target][name]
            owners = [classes_in[other][name] for other in imports.get(path, ())
                      if name in classes_in.get(other, {})]
            if len(owners) == 1:
                return owners[0]
            if mine in PACKAGE_SCOPED:
                owner = dir_classes.get(_package_of(path), {}).get(name)
                if owner:
                    return owner
            candidates = [c for c in class_by_bare.get(name, [])
                          if language.get(c.split("::", 1)[0]) == mine]
            return candidates[0] if len(candidates) == 1 else None

        def pick(src: str, path: str, raw: str) -> tuple[str, str]:
            """(qualified name, how it was found) — or ("", reason)."""
            bare = raw.rsplit(".", 1)[-1]
            mine = language.get(path)

            if "()." in raw:
                # `make().run`: a receiver typed by what a function is declared to
                # return. Place the function, read its return type, place that class.
                head, _sep, member = raw.partition("().")
                fn = ""
                owner = src.rsplit(".", 1)[0] if "." in src.rsplit("::", 1)[-1] else ""
                if head.startswith("self."):
                    fn = by_owner.get(owner, {}).get(head[len("self."):], "") if owner in class_names else ""
                elif "." in head:
                    cls = place_class(path, head.split(".")[0], mine)
                    fn = by_owner.get(cls or "", {}).get(head.split(".")[-1], "")
                elif (mine in IMPLICIT_THIS and owner in class_names
                      and head in by_owner.get(owner, {})):
                    fn = by_owner[owner][head]           # `Make()` inside the class is `this.Make()`
                elif head in plain_file.get(path, {}):
                    fn = plain_file[path][head]
                else:
                    seen = [plain_file[o][head] for o in imports.get(path, ())
                            if head in plain_file.get(o, {})]
                    fn = seen[0] if len(seen) == 1 else ""
                rtype = returns_of.get(fn, "")
                cls = place_class(path, rtype, mine) if rtype else None
                if cls and member in by_owner.get(cls, {}):
                    return by_owner[cls][member], "returns"
                return "", unplaced(member)

            if raw.startswith("self."):
                owner = src.rsplit(".", 1)[0] if "." in src.rsplit("::", 1)[-1] else ""
                if owner and bare in by_owner.get(owner, {}):
                    return by_owner[owner][bare], "self"
                for _other, members in owners_in.get(path, ()):
                    if bare in members:
                        return members[bare], "self-in-file"
                # Not `ambiguous`: that word means several candidates share the name.
                # Here there may be exactly one, and we still cannot say it is the one
                # — the reason is the receiver, not the count.
                return "", unplaced(bare)

            if "." in raw:
                # A method on a named receiver. Only the receiver says which one, so a
                # receiver naming something outside this repository — `sys`, `json` —
                # must not be matched on the method name alone.
                root = raw.split(".")[0]
                known = named.get(path, {})
                if raw.count(".") == 1 and root in classes_in.get(path, {}):
                    members = by_owner.get(classes_in[path][root], {})
                    if bare in members:
                        return members[bare], "same-file-class"
                    return "", unplaced(bare)
                if root in known:
                    target, outcome = known[root]
                    if target is None:
                        # Third-party is knowable; ambiguous is not.
                        return "", ("external" if outcome == "external"
                                    else unplaced(bare))
                    # `Store.save()` and `store.save()` are different questions. A
                    # receiver naming a class puts that class's methods in scope; one
                    # naming a module puts only the module's top level in scope — a
                    # module attribute is never a method of a class that happens to
                    # live in the same file.
                    owner = classes_in.get(target, {}).get(root)
                    if owner:
                        members = by_owner.get(owner, {})
                        if bare in members:
                            return members[bare], "receiver"
                        return "", unplaced(bare)
                    if bare in plain_file.get(target, {}):
                        return plain_file[target][bare], "receiver"
                    # The alias names a module with no such top-level function. Either
                    # the callee is elsewhere, or this name is a local shadowing the
                    # module — and we cannot tell which.
                    return "", unplaced(bare)

                # `from store import Store` records only the module it came from, so
                # `Store` is not a known alias — but it is a class in a file this one
                # imports, which is enough to say whose method is being called.
                owners = [classes_in[other][root] for other in imports.get(path, ())
                          if root in classes_in.get(other, {})]
                if len(owners) == 1:
                    members = by_owner.get(owners[0], {})
                    if bare in members:
                        return members[bare], "imported-class"
                    return "", unplaced(bare)
                # A Java package needs no import: `TenantContext.getTenantId()` from
                # the class next door is a receiver this file can see.
                if mine in PACKAGE_SCOPED:
                    owner = dir_classes.get(_package_of(path), {}).get(root)
                    if owner:
                        members = by_owner.get(owner, {})
                        if bare in members:
                            return members[bare], "same-package"
                        return "", unplaced(bare)
                # A receiver written as a type name — the front end rewrote `svc.find`
                # to `FooService.find` from the field's declaration — and that class is
                # declared once in this language.
                if raw.count(".") == 1 and root[:1].isupper():
                    candidates = [c for c in class_by_bare.get(root, [])
                                  if language.get(c.split("::", 1)[0]) == mine]
                    if len(candidates) == 1:
                        members = by_owner.get(candidates[0], {})
                        if bare in members:
                            return members[bare], "unique-class"
                        return "", unplaced(bare)
                # An unknown receiver: a local, a parameter, a return value. We do not
                # know its type, so we do not know whose method this is. Resolving on
                # the name being unique is the guess this refuses everywhere else —
                # `config.get("a")` is a dictionary in almost every file holding one.
                return "", unplaced(bare)

            # In Java and its relatives a bare `name()` inside a class is `this.name()`
            # — but only when the class actually declares it; anything else is a
            # static import or an inherited member, and that is not knowable here.
            if mine in IMPLICIT_THIS and "." in src.rsplit("::", 1)[-1]:
                owner = src.rsplit(".", 1)[0]
                if owner in class_names and bare in by_owner.get(owner, {}):
                    return by_owner[owner][bare], "implicit-this"

            # A bare call reaches a function or a class, never a method.
            if bare in plain_file.get(path, {}):
                return plain_file[path][bare], "same-file"
            seen = [plain_file[other][bare] for other in imports.get(path, ())
                    if bare in plain_file.get(other, {}) and language.get(other) == mine]
            if len(seen) == 1:
                return seen[0], "imported"
            candidates = [c for c in plain_tail.get(bare, [])
                          if language.get(c.split("::", 1)[0]) == mine]
            if len(candidates) == 1:
                return candidates[0], "unique"
            return "", ("ambiguous" if candidates else unplaced(bare))

        with self.db:
            cur = self.db.cursor()
            for row in self.db.execute(
                    "SELECT rowid, src, path, raw_dst FROM edges WHERE repo=? AND "
                    "branch=? AND rel='CALLS'", (repo, branch)).fetchall():
                found, why = pick(row["src"], row["path"], row["raw_dst"])
                if found:
                    cur.execute("UPDATE edges SET dst=?, resolution='resolved' "
                                "WHERE rowid=?", (found, row["rowid"]))
                    counts["resolved"] += 1
                    how[why] = how.get(why, 0) + 1
                else:
                    cur.execute("UPDATE edges SET dst=raw_dst, resolution=? "
                                "WHERE rowid=?", (why, row["rowid"]))
                    counts[why] += 1
        counts["how"] = how
        return counts

    def link_layers(self, repo: str, branch: str = "main") -> dict:
        """Join the ontologies. This is the pass that makes the graph worth building.

        `code_ontology` alone is a better grep. What no single file states is the chain
        an agent actually asks about — *which endpoint ends up writing which table* —
        because the route handler never names a table and the model never names a route.

        Two joins arrive free and one is derived:

        * `HANDLED_BY` is emitted by the extractor. A route decorator sits on the
          function in the tree, so endpoint and handler are connected by a fact.
        * `MAPS_TO` likewise: `__tablename__` and `CREATE TABLE` say the name outright.
        * `PERSISTS_TO` is inferred here, from a resolved call whose target is also an
          entity. Constructing or querying a model is how ORM code touches a table, so
          a function that calls `User(...)` almost certainly persists to `users`.

        "Almost certainly" is the honest word, so these edges are tier `query` and never
        `native`. An agent that wants only facts can filter them out; one that wants a
        lead can follow them. What it must not do is mistake one for the other.
        """
        entities = {r["name"]: r["name"] for r in self.db.execute(
            "SELECT name FROM symbols WHERE repo=? AND branch=? AND kind='Entity'",
            (repo, branch))}
        if not entities:
            return {"persists_to": 0,
                    "handled_by": self._count_rel(repo, branch, "HANDLED_BY"),
                    "maps_to": self._count_rel(repo, branch, "MAPS_TO"),
                    "configured_by": self.join_env(repo, branch),
                "deployed_by": self.join_deploys(repo, branch)}

        made = 0
        with self.db:
            cur = self.db.cursor()
            cur.execute("DELETE FROM edges WHERE repo=? AND branch=? AND rel='PERSISTS_TO'",
                        (repo, branch))
            seen: set[tuple[str, str]] = set()
            for row in self.db.execute(
                    "SELECT DISTINCT src, dst, path FROM edges WHERE repo=? AND branch=? "
                    "AND rel='CALLS' AND resolution='resolved'", (repo, branch)).fetchall():
                target = entities.get(row["dst"])
                if not target or (row["src"], target) in seen:
                    continue
                seen.add((row["src"], target))
                cur.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (row["src"], "PERSISTS_TO", target, "query", "link",
                             row["path"], target, "derived", repo, branch))
                made += 1
        return {"persists_to": made,
                "handled_by": self._count_rel(repo, branch, "HANDLED_BY"),
                "maps_to": self._count_rel(repo, branch, "MAPS_TO"),
                "configured_by": self.join_env(repo, branch),
                "deployed_by": self.join_deploys(repo, branch)}

    def join_deploys(self, repo: str, branch: str = "main") -> int:
        """Point an image's command at the module it actually starts.

        `CMD ["uvicorn", "api:app"]` names `api`, and the Dockerfile has no way to know
        whether this repository declares a module by that name. With every file in, it
        does — and a `DEPLOYED_BY` edge answers *what ships this code*, which neither
        the Dockerfile nor the module states on its own.
        """
        modules: dict[str, str] = {}
        for row in self.db.execute(
                "SELECT name, path FROM symbols WHERE repo=? AND branch=? "
                "AND kind='Module'", (repo, branch)):
            stem = row["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            modules.setdefault(stem, row["name"])

        joined = 0
        with self.db:
            cur = self.db.cursor()
            cur.execute("DELETE FROM edges WHERE repo=? AND branch=? AND rel='DEPLOYED_BY'",
                        (repo, branch))
            for row in self.db.execute(
                    "SELECT rowid, src, raw_dst, path FROM edges WHERE repo=? AND branch=? "
                    "AND rel='DEPLOYS' AND resolution='unresolved'",
                    (repo, branch)).fetchall():
                module = modules.get(row["raw_dst"])
                if not module:
                    # The command names a binary or an installed package, not code in
                    # this repository. Correctly not a node here.
                    cur.execute("UPDATE edges SET resolution='external' WHERE rowid=?",
                                (row["rowid"],))
                    continue
                cur.execute("UPDATE edges SET dst=?, resolution='resolved' WHERE rowid=?",
                            (module, row["rowid"]))
                cur.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (module, "DEPLOYED_BY", row["src"], "query", "link",
                             row["path"], row["src"], "derived", repo, branch))
                joined += 1
        return joined

    def join_env(self, repo: str, branch: str = "main") -> int:
        """Point every environment read at the manifest that declares that variable.

        A `CONFIGURED_BY` edge arrives from the code side naming a bare variable —
        `DATABASE_URL` — because a file that reads one cannot know who sets it. Here,
        with every manifest in, the bare name is pointed at the declaration.

        This is the join that answers *if I change this variable, what breaks*, which
        no single file can answer: the manifest never names the code and the code never
        names the manifest.
        """
        declared: dict[str, str] = {}
        for row in self.db.execute(
                "SELECT name, summary FROM symbols WHERE repo=? AND branch=? "
                "AND kind='EnvVar'", (repo, branch)):
            declared.setdefault(row["summary"] or row["name"].rsplit("::", 1)[-1],
                                row["name"])
        joined = 0
        with self.db:
            cur = self.db.cursor()
            for row in self.db.execute(
                    "SELECT rowid, raw_dst FROM edges WHERE repo=? AND branch=? "
                    "AND rel='CONFIGURED_BY'", (repo, branch)).fetchall():
                target = declared.get(row["raw_dst"])
                if target:
                    cur.execute("UPDATE edges SET dst=?, resolution='resolved' "
                                "WHERE rowid=?", (target, row["rowid"]))
                    joined += 1
                else:
                    # Read but never declared in this repository: set by the platform,
                    # a secret store, or a developer's shell. Real, and correctly not a
                    # node here — but worth being able to list.
                    cur.execute("UPDATE edges SET resolution='undeclared' WHERE rowid=?",
                                (row["rowid"],))
        return joined

    def env_usage(self, repo: str, branch: str = "main") -> list[dict]:
        """Every environment variable, who declares it and who reads it."""
        rows = self.db.execute(
            "SELECT raw_dst AS name, path, resolution FROM edges "
            "WHERE repo=? AND branch=? AND rel='CONFIGURED_BY' ORDER BY raw_dst",
            (repo, branch)).fetchall()
        out: dict[str, dict] = {}
        for row in rows:
            entry = out.setdefault(row["name"], {"name": row["name"], "read_by": [],
                                                 "declared": row["resolution"] == "resolved"})
            if row["path"] not in entry["read_by"]:
                entry["read_by"].append(row["path"])
        for name, entry in out.items():
            entry["declared_in"] = [r["path"] for r in self.db.execute(
                "SELECT DISTINCT path FROM symbols WHERE repo=? AND branch=? "
                "AND kind='EnvVar' AND summary=?", (repo, branch, name))]
        return sorted(out.values(), key=lambda e: e["name"])

    def language_coverage(self, repo: str, branch: str = "main") -> list[dict]:
        """Per language: files, symbols, call edges and how they resolved.

        An agent cannot tell a thin graph from a complete one by querying it — both
        answer, one just answers less. A language read by a pattern has declarations
        and no calls; a language read by a parser but with most receivers untyped has
        calls that mostly go nowhere. Both are worth knowing before trusting
        `called_by`, and neither is visible in the rows.
        """
        out: dict[str, dict] = {}
        for r in self.db.execute(
                "SELECT language, COUNT(*) AS n FROM files WHERE repo=? AND branch=? "
                "GROUP BY language ORDER BY n DESC", (repo, branch)):
            out[r["language"]] = {"language": r["language"], "files": r["n"],
                                  "symbols": 0, "call_edges": 0, "resolved": 0,
                                  "untyped": 0, "traversable": False}
        for r in self.db.execute(
                "SELECT f.language, COUNT(*) AS n FROM symbols s JOIN files f "
                "ON f.path=s.path AND f.repo=s.repo AND f.branch=s.branch "
                "WHERE s.repo=? AND s.branch=? GROUP BY f.language", (repo, branch)):
            if r["language"] in out:
                out[r["language"]]["symbols"] = r["n"]
        for r in self.db.execute(
                "SELECT f.language, e.resolution, COUNT(*) AS n FROM edges e JOIN files f "
                "ON f.path=e.path AND f.repo=e.repo AND f.branch=e.branch "
                "WHERE e.repo=? AND e.branch=? AND e.rel='CALLS' "
                "GROUP BY f.language, e.resolution", (repo, branch)):
            row = out.get(r["language"])
            if row is None:
                continue
            row["call_edges"] += r["n"]
            if r["resolution"] in ("resolved", "untyped"):
                row[r["resolution"]] += r["n"]
        for row in out.values():
            row["traversable"] = row["call_edges"] > 0
        return list(out.values())

    def _absent(self, repo: str, branch: str, by_ontology: dict) -> list[str]:
        with_edges = {r["ontology"] for r in self.db.execute(
            "SELECT DISTINCT ontology FROM edges WHERE repo=? AND branch=?",
            (repo, branch))}
        found = set(by_ontology) | with_edges
        return [name for name in ("code_ontology", "data_ontology", "api_ontology",
                                  "deploy_ontology", "link") if name not in found]

    def _count_rel(self, repo: str, branch: str, rel: str) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM edges WHERE repo=? AND branch=? AND rel=?",
            (repo, branch, rel)).fetchone()[0]

    def trace(self, endpoint: str, repo: str, branch: str = "main") -> dict:
        """Endpoint → handler → entity → table, in one walk.

        The question this project exists to answer, and the one an agent would otherwise
        answer by opening the router, then the handler, then the model, then guessing.
        """
        handlers = [r["dst"] for r in self.db.execute(
            "SELECT dst FROM edges WHERE repo=? AND branch=? AND src=? AND rel='HANDLED_BY'",
            (repo, branch, endpoint))]
        chain = []
        for handler in handlers:
            entities = [r["dst"] for r in self.db.execute(
                "SELECT dst FROM edges WHERE repo=? AND branch=? AND src=? "
                "AND rel='PERSISTS_TO'", (repo, branch, handler))]
            for entity in entities:
                tables = [r["dst"] for r in self.db.execute(
                    "SELECT dst FROM edges WHERE repo=? AND branch=? AND src=? "
                    "AND rel='MAPS_TO'", (repo, branch, entity))]
                chain.append({"handler": handler, "entity": entity, "tables": tables,
                              "confidence": "derived — the handler calls the model"})
            if not entities:
                chain.append({"handler": handler, "entity": None, "tables": [],
                              "confidence": "no persistence found from this handler"})
        return {"endpoint": endpoint, "chain": chain}

    def call_resolution(self, repo: str, branch: str = "main") -> dict:
        return {r["resolution"]: r["n"] for r in self.db.execute(
            "SELECT resolution, COUNT(*) AS n FROM edges WHERE repo=? AND branch=? "
            "AND rel='CALLS' GROUP BY resolution", (repo, branch))}

    # ── reads, all scoped ──────────────────────────────────────────────────

    def search(self, query: str, repo: str = "", branch: str = "main",
               limit: int = 20, ontology: str = "") -> list[dict]:
        """Find symbols by name fragment. `repo` may be empty — see the tool doc."""
        where, args = ["name LIKE ?"], [f"%{query}%"]
        if repo:
            where += ["repo=?", "branch=?"]; args += [repo, branch]
        if ontology:
            where.append("ontology=?"); args.append(ontology)
        # The symbol whose own name is the query comes first, then names that start
        # with it, then anything containing it. Ordered by length alone, `set` returned
        # twenty rows of `Settings` and never `RuntimeConfig.set`.
        rank = ("CASE WHEN name = ? OR name LIKE '%::' || ? OR name LIKE '%.' || ? THEN 0 "
                "WHEN name LIKE '%::' || ? || '%' OR name LIKE '%.' || ? || '%' THEN 1 "
                "ELSE 2 END")
        args = [query] * 5 + args + [limit]
        rows = self.db.execute(
            "SELECT name, kind, path, line, end_line, tier, ontology, summary, returns, repo, branch, "
            f"{rank} AS rank FROM symbols WHERE {' AND '.join(where)} "
            "ORDER BY rank, length(name), name LIMIT ?", args).fetchall()
        return [{k: r[k] for k in r.keys() if k != "rank"} for r in rows]

    def definition(self, name: str, repo: str = "", branch: str = "main",
                   ontology: str = "") -> dict | None:
        """One symbol. `also_in` names the other ontologies that hold the same thing.

        A model class is a Class and an Entity. Returning one and hiding the other would
        let an agent ask what `User` is, be told "a class", and never learn it has a
        table — which is usually the half of the answer it wanted.
        """
        where, args = ["name=?"], [name]
        if repo:
            where += ["repo=?", "branch=?"]; args += [repo, branch]
        if ontology:
            where.append("ontology=?"); args.append(ontology)
        rows = self.db.execute(
            "SELECT name, kind, path, line, end_line, tier, ontology, summary, returns, "
            f"repo, branch FROM symbols WHERE {' AND '.join(where)} "
            "ORDER BY CASE ontology WHEN 'code_ontology' THEN 0 ELSE 1 END", args).fetchall()
        if not rows:
            return None
        found = dict(rows[0])
        found["also_in"] = [{"ontology": r["ontology"], "kind": r["kind"],
                             "summary": r["summary"]} for r in rows[1:]]
        return found

    def near_matches(self, name: str, limit: int = 5) -> list[dict]:
        """Same trailing symbol name, anywhere. What you usually meant."""
        tail = name.rsplit("::", 1)[-1]
        rows = self.db.execute(
            "SELECT name, kind, path, line, end_line, tier, ontology, repo, branch FROM symbols "
            "WHERE name LIKE ? AND name <> ? ORDER BY length(name) LIMIT ?",
            (f"%{tail}", name, limit)).fetchall()
        return [dict(r) for r in rows]

    def in_file(self, path: str, repo: str, branch: str = "main") -> list[dict]:
        """Every symbol declared in one file, in line order.

        There was no such query, so the callers that needed one paged a name search and
        filtered the page — which returned whatever happened to be in the first page and
        called it the file. On the busiest file in a real repository that was 8 rows of
        31, presented as the whole outline.
        """
        rows = self.db.execute(
            "SELECT name, kind, path, line, end_line, tier, ontology, summary, returns "
            "FROM symbols WHERE repo=? AND branch=? AND path=? ORDER BY line",
            (repo, branch, path)).fetchall()
        return [dict(r) for r in rows]

    def importers_of(self, path: str, repo: str, branch: str = "main") -> list[str]:
        """Files that import this one. Matched on the module, not on a substring.

        `LIKE '%' || dst || '%'` made `build-pptx.py` import itself, because it imports
        `pptx`. An import names a module; the comparison has to be against the module
        this file *is*, not against any text that happens to contain it.
        """
        rows = self.db.execute(
            "SELECT DISTINCT path FROM edges WHERE repo=? AND branch=? AND rel='IMPORTS' "
            "AND resolution='resolved' AND dst=? AND path <> ?",
            (repo, branch, path, path)).fetchall()
        return sorted(r["path"] for r in rows)

    def children(self, name: str, repo: str, branch: str = "main") -> list[dict]:
        """What this symbol contains — a class's methods, a file's declarations."""
        rows = self.db.execute(
            "SELECT s.name, s.kind, s.line, s.end_line, s.tier, s.summary FROM edges e "
            "JOIN symbols s ON s.name = e.dst AND s.repo = e.repo AND s.branch = e.branch "
            "WHERE e.repo=? AND e.branch=? AND e.src=? AND e.rel='CONTAINS' "
            "ORDER BY s.line", (repo, branch, name)).fetchall()
        return [dict(r) for r in rows]

    def neighbours(self, symbol: str, repo: str, branch: str = "main",
                   rels: tuple[str, ...] = ("CALLS", "IMPORTS")) -> list[dict]:
        """One hop, both directions — the callee in another file, and the caller."""
        marks = ",".join("?" * len(rels))
        out = self.db.execute(
            f"SELECT dst AS other, rel, tier, 'out' AS dir FROM edges "
            f"WHERE repo=? AND branch=? AND src=? AND rel IN ({marks}) "
            f"UNION ALL "
            f"SELECT src AS other, rel, tier, 'in' AS dir FROM edges "
            f"WHERE repo=? AND branch=? AND dst=? AND rel IN ({marks})",
            (repo, branch, symbol, *rels, repo, branch, symbol, *rels)).fetchall()
        return [dict(r) for r in out]

    def files(self, repo: str, branch: str = "main", prefix: str = "",
              limit: int = 500) -> list[dict]:
        rows = self.db.execute(
            "SELECT path, language, tier, degraded FROM files "
            "WHERE repo=? AND branch=? AND path LIKE ? ORDER BY path LIMIT ?",
            (repo, branch, f"{prefix}%", limit)).fetchall()
        return [dict(r) for r in rows]

    def repos(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT repo, branch, COUNT(*) AS files FROM files "
            "GROUP BY repo, branch ORDER BY repo, branch").fetchall()
        return [dict(r) for r in rows]

    def degraded(self, repo: str, branch: str = "main") -> list[dict]:
        """Every file that did not parse at its best tier, and why. Read this."""
        rows = self.db.execute(
            "SELECT path, language, tier, degraded FROM files "
            "WHERE repo=? AND branch=? AND degraded IS NOT NULL", (repo, branch)).fetchall()
        return [dict(r) for r in rows]

    def coverage(self, repo: str, branch: str = "main", prefix: str = "") -> list[dict]:
        """One row per child directory of `prefix`: files indexed, symbols declared."""
        rows = self.db.execute(
            "SELECT f.path, (SELECT COUNT(*) FROM symbols s "
            "                WHERE s.repo=f.repo AND s.branch=f.branch AND s.path=f.path) AS n "
            "FROM files f WHERE f.repo=? AND f.branch=? AND f.path LIKE ?",
            (repo, branch, f"{prefix}%")).fetchall()
        buckets: dict[str, dict] = {}
        for row in rows:
            rest = row["path"][len(prefix):]
            head = rest.split("/", 1)[0] if "/" in rest else rest
            b = buckets.setdefault(head, {"name": head, "files": 0, "definitions": 0})
            b["files"] += 1
            b["definitions"] += row["n"]
        return sorted(buckets.values(), key=lambda b: -b["files"])

    def stats(self, repo: str, branch: str = "main") -> dict:
        one = lambda q: self.db.execute(q, (repo, branch)).fetchone()[0]   # noqa: E731
        tiers = {r["tier"]: r["n"] for r in self.db.execute(
            "SELECT tier, COUNT(*) AS n FROM files WHERE repo=? AND branch=? "
            "GROUP BY tier", (repo, branch))}
        by_ontology = {r["ontology"]: r["n"] for r in self.db.execute(
            "SELECT ontology, COUNT(*) AS n FROM symbols WHERE repo=? AND branch=? "
            "GROUP BY ontology", (repo, branch))}
        return {
            "files": one("SELECT COUNT(*) FROM files WHERE repo=? AND branch=?"),
            "symbols": one("SELECT COUNT(*) FROM symbols WHERE repo=? AND branch=?"),
            "edges": one("SELECT COUNT(*) FROM edges WHERE repo=? AND branch=?"),
            "languages": one("SELECT COUNT(DISTINCT language) FROM files "
                             "WHERE repo=? AND branch=?"),
            "tiers": tiers,
            "by_ontology": by_ontology,
        }

    def health(self, repo: str, branch: str = "main") -> dict:
        """How much of this index was read, and how much was guessed.

        An agent that cannot see the gaps will answer over them, so this is a tool and
        not a log line. `parsed_share` below 1.0 means some of the graph is a language
        model's reading of code it could not parse, and should be treated as such.
        """
        marks = ",".join("?" * len(PARSED_TIERS))
        total = self.db.execute(
            "SELECT COUNT(*) FROM symbols WHERE repo=? AND branch=?",
            (repo, branch)).fetchone()[0]
        parsed = self.db.execute(
            f"SELECT COUNT(*) FROM symbols WHERE repo=? AND branch=? AND tier IN ({marks})",
            (repo, branch, *PARSED_TIERS)).fetchone()[0]
        gaps = self.degraded(repo, branch)
        stats = self.stats(repo, branch)
        calls = self.call_resolution(repo, branch)
        return {
            "repo": repo, "branch": branch,
            "files": stats["files"], "symbols": total, "edges": stats["edges"],
            "by_ontology": stats["by_ontology"],
            "parsed_symbols": parsed,
            "inferred_symbols": total - parsed,
            "parsed_share": round(parsed / total, 3) if total else 1.0,
            "call_edges": calls,
            "links": {rel: self._count_rel(repo, branch, rel)
                      for rel in ("HANDLED_BY", "PERSISTS_TO", "MAPS_TO",
                                  "DEPLOYED_BY", "CONFIGURED_BY")},
            "env_read_but_undeclared": [
                e["name"] for e in self.env_usage(repo, branch) if not e["declared"]][:20],
            # The tier names are short and two of them mislead on their own: "query"
            # is a line pattern or a naming convention, not a database query, and
            # never yields a call edge; "heuristic" is the floor.
            "tier_note": "native = a real parse (Python ast, tree-sitter): declarations "
                         "and calls; query = a line pattern or a naming convention: "
                         "declarations only, never calls; model = a language model's "
                         "reading of a file no parser could read; heuristic = the floor, "
                         "every row a guess",
            "link_note": "PERSISTS_TO is derived from a resolved call to a model, so it "
                         "is tier 'query' and a lead rather than a fact. HANDLED_BY and "
                         "MAPS_TO come from declarations and are tier 'native'.",
            "call_note": (
                "resolved: the callee is known. "
                "untyped: the receiver could not be typed — a local, a parameter or a "
                "return value — so which declaration it means is unknown. This is the "
                "usual outcome for `x.method()` and does NOT mean the callee is absent. "
                "ambiguous: several same-named functions could be meant. "
                "external: the callee is genuinely not declared in this repository. "
                "A 'who calls this' answer is only as complete as `resolved`; a large "
                "untyped count means callers are missing, not that there are none."),
            "languages": self.language_coverage(repo, branch),
            "language_note": "a language with files but no call edges is read by a "
                             "pattern, not a parser: it yields declarations only, so "
                             "blast_radius, related_symbols and called_by will be empty "
                             "for it",
            "degraded_files": len(gaps),
            "gaps": gaps[:20],
            # An ontology is present if it has nodes OR edges. `link` declares no
            # kinds at all — it only joins nodes other ontologies own — so counting
            # symbols alone reported it absent while it was holding the graph together.
            "ontologies_absent": self._absent(repo, branch, stats["by_ontology"]),
        }
