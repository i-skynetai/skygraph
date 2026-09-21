"""Language front ends. Three tiers, one shared output.

Adding a language means adding a front end here. Nothing downstream — the writer, the
store, the query layer — knows a language exists.

    tier 1  native     a real parse. Python today, via the standard library `ast`.
    tier 2  query      a declarative pattern set. Where new languages should land.
    tier 3  heuristic  a last resort that marks everything it produces as a guess.

A construct a tier cannot handle degrades to the tier below and records why. It never
disappears silently.
"""
from __future__ import annotations
import ast, re
from .schema import Symbol, Edge, FileResult

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


def language_of(path: str) -> str | None:
    if path.endswith(".py"):
        return "python"
    for lang, spec in QUERY_LANGUAGES.items():
        if path.endswith(spec["ext"]):
            return lang
    return None


def parse(path: str, source: str) -> FileResult:
    """Route one file to the highest tier that can handle it."""
    lang = language_of(path)
    if lang == "python":
        try:
            return _native_python(path, source)
        except SyntaxError as exc:
            # Degrade, loudly. A file we cannot parse is still a file that exists.
            r = _heuristic(path, source, "python")
            r.degraded = f"python AST failed ({exc.msg} line {exc.lineno}); fell to heuristic"
            return r
    if lang in QUERY_LANGUAGES:
        return _query(path, source, lang)
    return _heuristic(path, source, lang or "unknown")


def _native_python(path: str, source: str) -> FileResult:
    tree = ast.parse(source)
    out = FileResult(path=path, language="python", tier="native")
    out.symbols.append(Symbol(path, "Module", path, 1, "native"))

    def qualified(node, prefix: str) -> str:
        return f"{path}::{prefix}{node.name}" if prefix else f"{path}::{node.name}"

    def walk(node, prefix: str = "", owner: str | None = None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qn = qualified(child, prefix)
                out.symbols.append(Symbol(qn, "Class", path, child.lineno, "native"))
                out.edges.append(Edge(owner or path, "CONTAINS", qn))
                for base in child.bases:
                    if isinstance(base, ast.Name):
                        out.edges.append(Edge(qn, "INHERITS", base.id))
                walk(child, f"{child.name}.", qn)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = qualified(child, prefix)
                kind = "Method" if owner and "::" in owner and prefix else "Function"
                out.symbols.append(Symbol(qn, kind, path, child.lineno, "native"))
                out.edges.append(Edge(owner or path, "CONTAINS", qn))
                for call in ast.walk(child):
                    if isinstance(call, ast.Call):
                        target = _call_name(call.func)
                        if target:
                            out.edges.append(Edge(qn, "CALLS", target))
                walk(child, f"{prefix}{child.name}.", qn)
            elif isinstance(child, ast.Import):
                for a in child.names:
                    out.edges.append(Edge(path, "IMPORTS", a.name))
            elif isinstance(child, ast.ImportFrom):
                if child.module:
                    out.edges.append(Edge(path, "IMPORTS", child.module))
            else:
                walk(child, prefix, owner)

    walk(tree)
    return out


def _call_name(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _query(path: str, source: str, lang: str) -> FileResult:
    spec = QUERY_LANGUAGES[lang]
    out = FileResult(path=path, language=lang, tier="query")
    out.symbols.append(Symbol(path, "Module", path, 1, "query"))
    for i, line in enumerate(source.splitlines(), 1):
        for pattern, kind in ((spec["class"], "Class"), (spec["func"], "Function")):
            m = re.match(pattern, line)
            if m:
                qn = f"{path}::{m.group(1)}"
                out.symbols.append(Symbol(qn, kind, path, i, "query"))
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
    out.symbols.append(Symbol(path, "Module", path, 1, "heuristic"))
    for i, line in enumerate(source.splitlines(), 1):
        m = _ANY_DECL.match(line)
        if m:
            qn = f"{path}::{m.group(1)}"
            out.symbols.append(Symbol(qn, "Function", path, i, "heuristic"))
            out.edges.append(Edge(path, "CONTAINS", qn))
    if out.degraded is None:
        out.degraded = f"no front end for {lang}; names found by pattern, not by parsing"
    return out
