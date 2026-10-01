"""Language front ends. Three tiers, one shared output.

Adding a language means adding a front end here. Nothing downstream — the writer, the
store, the query layer — knows a language exists.

    tier 1  native     a real parse — Python via `ast`, everything else via
                       tree-sitter when it is installed.
    tier 2  query       a declarative pattern set. Declarations only: a pattern can
                       see a declaration and cannot see a call.
    tier 3  model       optional, needs a key; for what no parser could read.
    tier 4  heuristic   the floor, and it marks everything it produces as a guess.

A construct a tier cannot handle degrades to the tier below and records why. It never
disappears silently.
"""
from __future__ import annotations
import ast, re
from . import extractors, miniyaml, treesitter
from .schema import Symbol, Edge, FileResult

#: Files that hold no code but do hold a data model or an API contract. They are walked
#: and indexed like any other file; they simply contribute to a different ontology, so
#: running the code_ontology heuristic over them would invent functions that are not
#: there.
DATA_LANGUAGES = {".sql": "sql", ".prisma": "prisma",
                  ".yaml": "yaml", ".yml": "yaml", ".json": "json"}

#: Dockerfiles have no extension to match on, so they are matched by name — including
#: the `Dockerfile.prod` and `api.Dockerfile` spellings that real repositories use.
def _is_dockerfile(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name == "Dockerfile" or name.startswith("Dockerfile.") \
        or name.endswith(".Dockerfile") or name.endswith(".dockerfile")

# ── tier 2 patterns ────────────────────────────────────────────────────────
# One entry per language: how a declaration looks, and how an import looks.
QUERY_LANGUAGES: dict[str, dict] = {
    "javascript": {"ext": (".js", ".jsx", ".mjs"),
                   "class": r"^\s*class\s+(\w+)", "func": r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)",
                   "import": r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]"""},
    "typescript": {"ext": (".ts", ".tsx"),
                   "class": r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", "func": r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)",
                   "import": r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]"""},
    "go":         {"ext": (".go",), "class": r"^\s*type\s+(\w+)\s+struct", "func": r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)",
                   "import": r'^\s*"([^"]+)"'},
    "java":       {"ext": (".java",), "class": r"^\s*(?:public\s+|final\s+|abstract\s+)*class\s+(\w+)",
                   "func": r"^\s*(?:public|private|protected)\s+[\w<>\[\]]+\s+(\w+)\s*\(", "import": r"^\s*import\s+([\w.]+);"},
    "ruby":       {"ext": (".rb",), "class": r"^\s*class\s+(\w+)", "func": r"^\s*def\s+(\w+)",
                   "import": r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]"},
    "rust":       {"ext": (".rs",), "class": r"^\s*(?:pub\s+)?struct\s+(\w+)", "func": r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)",
                   "import": r"^\s*use\s+([\w:]+)"},
    "csharp":     {"ext": (".cs",), "class": r"^\s*(?:public\s+|internal\s+)?class\s+(\w+)",
                   "func": r"^\s*(?:public|private|protected|internal)\s+[\w<>\[\]]+\s+(\w+)\s*\(", "import": r"^\s*using\s+([\w.]+);"},
    "php":        {"ext": (".php",), "class": r"^\s*class\s+(\w+)", "func": r"^\s*function\s+(\w+)",
                   "import": r"^\s*(?:require|include)(?:_once)?\s+['\"]([^'\"]+)['\"]"},
    "kotlin":     {"ext": (".kt",), "class": r"^\s*(?:data\s+)?class\s+(\w+)", "func": r"^\s*fun\s+(\w+)",
                   "import": r"^\s*import\s+([\w.]+)"},
    "swift":      {"ext": (".swift",), "class": r"^\s*(?:public\s+)?class\s+(\w+)", "func": r"^\s*(?:public\s+)?func\s+(\w+)",
                   "import": r"^\s*import\s+(\w+)"},
}


#: Extensions that are text but are not code. A file ending in one of these is walked
#: past, not guessed at: running a declaration pattern over a changelog finds "functions"
#: that are sentences.
NOT_SOURCE = {
    ".md", ".markdown", ".rst", ".txt", ".adoc", ".tex",
    ".csv", ".tsv", ".log", ".lock", ".sum", ".map", ".min.js", ".min.css",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".pdf",
    ".zip", ".gz", ".tar", ".whl", ".jar", ".so", ".dylib", ".dll", ".exe",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".wav",
    ".pyc", ".class", ".o", ".a", ".bin", ".db", ".sqlite",
    # SQLite's sidecar files — an index kept inside the tree it indexes must not
    # index its own write-ahead log.
    ".db-wal", ".db-shm", ".db-journal", ".sqlite-wal", ".sqlite-shm", ".sqlite-journal",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".rtf",
    ".jsonl", ".ndjson", ".parquet", ".avro", ".pickle", ".pkl", ".npy",
    ".html", ".htm", ".xhtml",                 # usually generated; never declarations
    ".mmd", ".mermaid", ".dot", ".puml",       # diagrams: text, not code
    ".scm",                                    # tree-sitter queries: read by the parser, not indexed
    # templates: markup with holes, not code — a Ruby site had 100 of them "degraded"
    ".erb", ".haml", ".slim", ".erubis", ".hamlit", ".str", ".liquid", ".mustache",
    ".hbs", ".ejs", ".jinja", ".jinja2", ".j2", ".twig", ".njk", ".vue",
    # IDE and build-system project files
    ".xcscheme", ".xctestplan", ".storyboard", ".xib", ".pbxproj", ".xcworkspacedata",
    ".podspec", ".sln", ".csproj", ".iml", ".gradle.kts.lock",
    ".css", ".scss", ".less", ".plist", ".properties", ".ini", ".cfg", ".env",
}

#: Backups and pre-rename copies keep their real extension and add a suffix, so the
#: extension check never sees them. `policy.yaml.backup-2026-09-12` is not a manifest.
BACKUP_SUFFIX = re.compile(r"\.(bak|backup|orig|old|save|tmp|swp)"
                           r"|\.(backup|pre)-[\w-]+$", re.I)


def unclaimed_source(path: str) -> bool:
    """A file no front end reads, that still looks like something worth reading.

    This is what tier 3 exists for, and for a long time nothing ever reached it: the
    walk skipped every file no front end claimed, so a language without a pattern was
    not merely read badly — it was not read at all, and neither a model nor the
    heuristic ever saw it.

    The rule is deliberately narrow. It must have an extension, that extension must not
    be a document, an archive or an image, and no front end may already claim it.
    """
    name = path.rsplit("/", 1)[-1]
    if name.startswith(".") or "." not in name:
        return False
    lower = name.lower()                    # a `.PDF` is a PDF
    if any(lower.endswith(ext) for ext in NOT_SOURCE):
        return False
    if BACKUP_SUFFIX.search(lower):
        return False
    return language_of(path) is None


def language_of(path: str) -> str | None:
    if path.endswith(".py"):
        return "python"
    if extractors.is_manifest(path):
        return "manifest"                      # before `.json`: package.json is not data
    for lang, spec in QUERY_LANGUAGES.items():
        if path.endswith(spec["ext"]):
            return lang
    for ext, lang in DATA_LANGUAGES.items():
        if path.endswith(ext):
            return lang
    if _is_dockerfile(path):
        return "dockerfile"
    return None


def parse(path: str, source: str) -> FileResult:
    """Route one file to the highest tier that can handle it, in every ontology.

    A file is read twice over: once for what the language declares, and once for what a
    framework declares on top of it. A module of SQLAlchemy models is both — the classes
    are classes, and they are also entities with table names — so the second pass
    appends rather than replacing.
    """
    lang = language_of(path)
    tree: ast.AST | None = None

    if lang == "python":
        try:
            result = _native_python(path, source)
            tree = ast.parse(source)
        except SyntaxError as exc:
            # Degrade, loudly. A file we cannot parse is still a file that exists.
            result = _heuristic(path, source, "python")
            result.degraded = (f"python AST failed ({exc.msg} line {exc.lineno}); "
                               "fell to heuristic")
    elif lang == "dockerfile" or lang == "manifest" or lang in DATA_LANGUAGES.values():
        # No code to find. An empty shell that the ontology pass fills, or does not.
        result = FileResult(path=path, language=lang, tier="native")
    elif treesitter.claims(lang):
        # A real parse, when tree-sitter is installed. It is the only thing here that
        # can see a call, so without it every non-Python language is a list of
        # declarations with nothing to traverse.
        try:
            result = treesitter.parse(path, source, lang)
        except Exception as exc:                                  # noqa: BLE001
            result = _query(path, source, lang)
            reason = (str(exc) if isinstance(exc, treesitter.GrammarUnavailable)
                      else type(exc).__name__)
            result.degraded = f"tree-sitter failed ({reason}); fell to the pattern tier"
    elif lang in QUERY_LANGUAGES:
        result = _query(path, source, lang)
    else:
        result = _heuristic(path, source, lang or "unknown")

    _enrich(result, path, source, lang, tree)
    return result


def _enrich(result: FileResult, path: str, source: str, lang: str | None,
            tree: ast.AST | None) -> None:
    """Add data_ontology and api_ontology rows to a file already read for its structure."""
    symbols: list[Symbol] = []
    edges: list[Edge] = []

    if tree is not None:
        found, joined, _certain = extractors.data_ontology_from_python(path, tree)
        symbols += found
        edges += joined
        found, joined = extractors.api_ontology_from_python(path, tree)
        symbols += found
        edges += joined
    elif lang == "dockerfile":
        symbols, edges = extractors.deploy_from_dockerfile(path, source)
    elif lang == "sql":
        symbols, edges = extractors.data_ontology_from_sql(path, source)
    elif lang == "prisma":
        symbols, edges = extractors.data_ontology_from_prisma(path, source)
    elif lang in ("yaml", "json"):
        reader = (extractors.api_ontology_from_json if lang == "json"
                  else extractors.api_ontology_from_yaml)
        found = reader(path, source)
        if found is not None:
            symbols, edges = found
        elif lang == "yaml":
            symbols, edges, refused = _deploy_yaml(path, source)
            if refused and not result.degraded:
                # Not silence: a CI file the reader cannot follow used to index as an
                # empty, healthy file, and `index_health` had nothing to report (SG-001).
                result.degraded = f"YAML this reader does not implement ({refused}); read as empty"
    elif lang == "manifest":
        symbols, edges = extractors.deploy_from_manifest(path, source)
    elif lang == "java":
        symbols, edges = extractors.api_ontology_from_java(path, source)
        found, joined = extractors.data_ontology_from_java(path, source)
        symbols += found
        edges += joined
    elif lang in ("javascript", "typescript"):
        symbols, edges = extractors.api_ontology_from_pattern(path, source, lang)

    # An environment read is not a declaration, so it is not a symbol. It is recorded
    # against the file and joined to whatever manifest sets that variable, in the link
    # pass, once every manifest is in.
    for line, name in extractors.env_reads(path, source, lang):
        edges.append(Edge(f"{path}::env:{name}", "CONFIGURED_BY", name, "query"))

    result.symbols += symbols
    result.edges += edges


def _deploy_yaml(path: str, source: str) -> tuple[list[Symbol], list[Edge], str]:
    """Compose files, Kubernetes manifests and CI workflows — all YAML, all different.

    A file that is none of them yields nothing, which is the right answer for the
    ordinary config YAML that makes up most of a repository. The third value is why the
    reader refused the file, or "".
    """
    try:
        documents = miniyaml.load_all(source)
    except miniyaml.MiniYamlError as exc:
        # The reader is a subset on purpose and says when a file is beyond it. Better
        # to index the file as declaring nothing than to write half a manifest — and
        # to say so, so the gap is visible.
        return [], [], str(exc).removeprefix("unsupported YAML ").strip(" ():")[:80]

    symbols: list[Symbol] = []
    edges: list[Edge] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        for extract in (extractors.deploy_from_compose, extractors.deploy_from_k8s,
                        extractors.deploy_from_pipeline):
            found, joined = extract(path, doc)
            symbols += found
            edges += joined
    return symbols, edges, ""


def _end(node) -> int:
    """Last line of an AST node. Only tier 1 can answer this honestly.

    A tier that matched a line with a pattern knows where a declaration starts and has
    no idea where it ends, so it records 0 and `read_source` returns a window instead of
    a confidently wrong range.
    """
    return getattr(node, "end_lineno", 0) or 0


def _native_python(path: str, source: str) -> FileResult:
    tree = ast.parse(source)
    out = FileResult(path=path, language="python", tier="native")
    out.symbols.append(Symbol(path, "Module", path, 1, source.count("\n") + 1, "native",
                              summary=_doc(tree)))

    def qualified(node, prefix: str) -> str:
        return f"{path}::{prefix}{node.name}" if prefix else f"{path}::{node.name}"

    def walk(node, prefix: str = "", owner: str | None = None,
             fields: dict | None = None) -> None:
        fields = fields or {}
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qn = qualified(child, prefix)
                out.symbols.append(Symbol(qn, "Class", path, child.lineno, _end(child), "native",
                                          summary=_doc(child)))
                out.edges.append(Edge(owner or path, "CONTAINS", qn))
                for base in child.bases:
                    if isinstance(base, ast.Name):
                        out.edges.append(Edge(qn, "INHERITS", base.id))
                walk(child, f"{child.name}.", qn, _class_fields(child))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = qualified(child, prefix)
                kind = "Method" if owner and "::" in owner and prefix else "Function"
                out.symbols.append(Symbol(qn, kind, path, child.lineno, _end(child), "native",
                                          summary=_doc(child),
                                          returns=_annotation_name(child.returns)))
                out.edges.append(Edge(owner or path, "CONTAINS", qn))
                # What this function knows about its receivers: parameters by their
                # annotation, locals by their annotation or the constructor that made
                # them, and `self.x` by what the class assigned or declared it to be.
                bound = {**_typed_params(child), **_constructed_locals(child)}
                for call in ast.walk(child):
                    if isinstance(call, ast.Call):
                        target = _call_name(call.func)
                        if target:
                            parts = target.split(".")
                            if len(parts) == 2 and parts[0] in bound:
                                target = f"{bound[parts[0]]}.{parts[1]}"
                            elif len(parts) == 3 and parts[0] == "self" and parts[1] in fields:
                                target = f"{fields[parts[1]]}.{parts[2]}"
                            out.edges.append(Edge(qn, "CALLS", target))
                walk(child, f"{prefix}{child.name}.", qn, fields)
            elif isinstance(child, ast.Import):
                for a in child.names:
                    out.edges.append(Edge(path, "IMPORTS",
                                          f"{a.name} as {a.asname}" if a.asname else a.name))
            elif isinstance(child, ast.ImportFrom):
                # `from pkg import a, b` binds `a` and `b`, so each is recorded as
                # `pkg.a`, `pkg.b`: the resolver finds `pkg/a.py` when `a` is a module
                # and falls back to `pkg.py` when it is a name inside one. Recording
                # only `pkg` lost the difference, and `from app import service` then
                # left every `service.f()` untyped. Leading dots are kept — `from
                # .sibling import x` names nothing without them.
                module = "." * (child.level or 0) + (child.module or "")
                for a in child.names:
                    if a.name == "*":
                        target = module
                    elif module.endswith(".") or not module:
                        target = f"{module}{a.name}"
                    else:
                        target = f"{module}.{a.name}"
                    if target:
                        out.edges.append(Edge(path, "IMPORTS",
                                              f"{target} as {a.asname}" if a.asname else target))
            else:
                walk(child, prefix, owner, fields)

    walk(tree)
    # Calls at module level — `app = FastAPI()`, `router.include_router(...)`, a
    # `main()` guard — belong to the module. They belonged to nothing.
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for call in ast.walk(stmt):
            if isinstance(call, ast.Call):
                target = _call_name(call.func)
                if target:
                    out.edges.append(Edge(path, "CALLS", target))
    return out


def _doc(node) -> str:
    """The first line of a docstring, or nothing.

    It is what `outline_file` shows beside a name, and the reason an agent can pick the
    right function without `read_source`: nine names cost nine lines; nine names with
    what each one does cost nine lines and usually save a file.
    """
    try:
        text = ast.get_docstring(node, clean=True) or ""
    except TypeError:
        return ""
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    return first[:100]


def _annotation_name(node) -> str:
    """The bare class name an annotation means: `Foo`, `pkg.Foo`, `Optional[Foo]`,
    `list[Foo]`, `Foo | None`, `"Foo"`."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.rsplit(".", 1)[-1].strip("'\"")
    if isinstance(node, ast.Subscript):
        outer = _annotation_name(node.value)
        if outer in ("Optional", "list", "List", "set", "Set", "Sequence", "Iterable",
                     "Iterator", "Type", "type", "Annotated", "ClassVar", "Final"):
            inner = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) and node.slice.elts \
                else node.slice
            return _annotation_name(inner)
        return outer
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _annotation_name(node.left)
        return left if left not in ("None",) else _annotation_name(node.right)
    return ""


def _class_fields(cls) -> dict[str, str]:
    """`self.x = Cls(...)`, `self.x: T`, and class-body `x: T` — the receiver types a
    class's methods can see. `self.x = make()` records `make()` so the resolver can
    follow the factory's declared return type."""
    fields: dict[str, str] = {}
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            kind = _annotation_name(stmt.annotation)
            if kind:
                fields.setdefault(stmt.target.id, kind)
    for node in ast.walk(cls):
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                kind = _annotation_name(node.annotation)
                if kind:
                    fields.setdefault(target.attr, kind)
                    continue
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and target.value.id == "self"):
            continue
        kind = _value_type(value)
        if kind:
            fields.setdefault(target.attr, kind)
    return fields


def _value_type(value) -> str:
    """What a value names about its own type: `Cls(...)` → Cls; `make(...)` → `make()`."""
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id[:1].isupper():
            return value.func.id
        return f"{value.func.id}()"
    if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name) and value.func.value.id in ("self", "cls")):
        return f"self.{value.func.attr}()"               # a factory method on this class
    return ""


def _typed_params(fn) -> dict[str, str]:
    out: dict[str, str] = {}
    args = fn.args
    for a in args.posonlyargs + args.args + args.kwonlyargs:
        kind = _annotation_name(a.annotation)
        if kind:
            out[a.arg] = kind
    return out


def _constructed_locals(fn) -> dict[str, str]:
    """Locals bound from a constructor call, once, in this function: `x = Cls(...)`.

    The one receiver type a parser can know without a type checker. A local assigned
    from a bare class call and never reassigned is that class, so `x.m()` is `Cls.m`
    and the resolver can place it. Anything assigned twice, or from anything other
    than a bare name being called, is left untyped — `x = make()` says nothing.
    """
    seen: dict[str, str | None] = {}
    for node in ast.walk(fn):
        targets: list = []
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            # `x: Foo = ...` — the annotation says the type, whatever the value is.
            kind = _annotation_name(node.annotation)
            seen[node.target.id] = None if node.target.id in seen else (kind or None)
            continue
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
            value = getattr(node, "value", None)
        elif isinstance(node, (ast.For, ast.With, ast.comprehension)):
            targets = [getattr(node, "target", None)] if hasattr(node, "target") else []
            value = None
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            cls = _value_type(value) or None
            seen[target.id] = None if target.id in seen else cls
    return {name: cls for name, cls in seen.items() if cls}


def _call_name(node) -> str | None:
    """The callee as written, keeping `self.` when it is there.

    Discarding the receiver threw away the single most useful fact about a call. In a
    real repository `run` is declared twenty-two times, so `run()` is genuinely
    ambiguous — but `self.run()` is not ambiguous at all, and the two used to be
    recorded identically.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        cursor = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            if cursor.id in ("self", "cls"):
                return "self." + ".".join(reversed(parts))
            parts.append(cursor.id)
            return ".".join(reversed(parts))
        # `OrderService().place()` / `make().save()`: a method on what a call returns.
        # Written `head().member`, which the resolver types from the class or from the
        # function's declared return type. It used to be `.place`, receiver lost.
        if isinstance(cursor, ast.Call) and len(parts) == 1:
            head = _call_name(cursor.func)
            if head and "()" not in head and not head.startswith("."):
                return f"{head}().{parts[0]}"
        # The receiver is a subscript, a literal or a longer chain — not a name to follow.
        return f".{node.attr}"
    return None


def _query(path: str, source: str, lang: str) -> FileResult:
    spec = QUERY_LANGUAGES[lang]
    out = FileResult(path=path, language=lang, tier="query")
    out.symbols.append(Symbol(path, "Module", path, 1, source.count("\n") + 1, "query"))
    for i, line in enumerate(source.splitlines(), 1):
        for pattern, kind in ((spec["class"], "Class"), (spec["func"], "Function")):
            m = re.match(pattern, line)
            if m:
                qn = f"{path}::{m.group(1)}"
                out.symbols.append(Symbol(qn, kind, path, i, 0, "query"))
                out.edges.append(Edge(path, "CONTAINS", qn))
                break
        m = re.match(spec["import"], line)
        if m:
            out.edges.append(Edge(path, "IMPORTS", m.group(1)))
    return out


_ANY_DECL = re.compile(r"^\s*(?:class|def|func|function|fn|type)\s+(\w+)")


def _heuristic(path: str, source: str, lang: str) -> FileResult:
    """Last resort. Everything here is marked a guess, because it is one."""
    out = FileResult(path=path, language=lang, tier="heuristic")
    out.symbols.append(Symbol(path, "Module", path, 1, source.count("\n") + 1, "heuristic"))
    for i, line in enumerate(source.splitlines(), 1):
        m = _ANY_DECL.match(line)
        if m:
            qn = f"{path}::{m.group(1)}"
            out.symbols.append(Symbol(qn, "Function", path, i, 0, "heuristic"))
            out.edges.append(Edge(path, "CONTAINS", qn))
    if out.degraded is None:
        out.degraded = f"no front end for {lang}; names found by pattern, not by parsing"
    return out
