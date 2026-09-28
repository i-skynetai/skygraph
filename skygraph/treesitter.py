"""Tier 1 for languages other than Python — a real parse, when tree-sitter is present.

**Why this is optional and not a dependency.** Everything else in skygraph is the
standard library, and a consumer that installs it inherits whatever it depends on. A
parser for thirty languages is worth an install; it is not worth making everyone take
one. So: if `tree_sitter` and `tree_sitter_language_pack` import, this tier runs. If
they do not, the file falls to the pattern tier exactly as before, and `index_health`
reports which languages are read by a pattern rather than a parser.

**What it buys is calls.** The pattern tier can see a declaration and cannot see a call,
because a call is not a line — so a repository of TypeScript used to index as a list of
classes with nothing to traverse. `blast_radius`, `related_symbols` and `called_by` were
empty and correct, which is the worst combination: an agent cannot tell a thin graph
from a complete one by querying it.

**One interpreter, one query file per language.** `queries/<language>.scm` names the
node types that are containers, callables, bound functions, calls and imports — five
captures — and this module never mentions a grammar's vocabulary. Adding a language is
a query file and a grammar name; a wrong node type fails when the file is compiled,
loudly, rather than matching nothing.

**The receiver is kept, exactly as in Python.** `this.format()` becomes `self.format`
and `sys.stdout.write()` stays `sys.stdout.write`, so the resolver treats every language
by the same rules and a method on an unknown object is never guessed at.
"""
from __future__ import annotations

import re
from pathlib import Path

from .schema import Edge, FileResult, Symbol

#: Set once, on the first attempt. None means "not tried yet"; False means tree-sitter
#: is not installed and we should stop asking.
_AVAILABLE: bool | None = None
_PARSERS: dict[str, object] = {}

#: `tree_sitter_language_pack` names some grammars differently from our language names.
GRAMMAR = {"javascript": "javascript", "typescript": "typescript", "tsx": "tsx",
           "java": "java", "go": "go", "rust": "rust", "csharp": "csharp",
           "ruby": "ruby", "php": "php", "kotlin": "kotlin", "swift": "swift"}

#: Where the per-language query files live. One file, five captures — see the module
#: docstring. `tsx` reads the TypeScript file: the grammar differs, the vocabulary does not.
QUERY_DIR = Path(__file__).parent / "queries"
CAPTURES = ("container", "callable", "bound", "call", "import")
_QUERIES: dict[str, object] = {}


def query_file(language: str) -> Path:
    return QUERY_DIR / f"{'typescript' if language == 'tsx' else language}.scm"


def _query(language: str):
    """The compiled query for a language. Compiled once; a bad node type raises here."""
    if language not in _QUERIES:
        from tree_sitter import Query
        from tree_sitter_language_pack import get_language
        _QUERIES[language] = Query(get_language(GRAMMAR[language]),
                                   query_file(language).read_text(encoding="utf-8"))
    return _QUERIES[language]


#: `this` and `self` mean the enclosing class in every language here, and the resolver
#: already knows what `self.` means. Normalising at the edge keeps one rule.
RECEIVER_SELF = re.compile(r"^(?:this|self)\.")
#: A receiver that is itself a call or an index — `get_thing().run()`, `items[0].run()`.
UNKNOWABLE = re.compile(r"[()\[\]]")


def available() -> bool:
    """Whether a real parse is possible. Asked once; the answer does not change."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import tree_sitter                                    # noqa: F401
            import tree_sitter_language_pack                      # noqa: F401
            _AVAILABLE = True
        except Exception:                                         # noqa: BLE001
            _AVAILABLE = False
    return _AVAILABLE


def claims(language: str) -> bool:
    return available() and language in GRAMMAR and query_file(language).is_file()


def _parser(language: str):
    if language not in _PARSERS:
        from tree_sitter_language_pack import get_parser
        _PARSERS[language] = get_parser(GRAMMAR[language])
    return _PARSERS[language]


def _name_of(node) -> str:
    field = node.child_by_field_name("name")
    if field is not None:
        return field.text.decode("utf-8", "replace").strip()
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "constant",
                          "property_identifier", "simple_identifier", "name"):
            return child.text.decode("utf-8", "replace").strip()
    return ""


#: The child that holds a call's arguments, whatever the grammar calls it. Taking the
#: text before it gives the callee exactly as written, in every language, without
#: needing to know which field name each grammar uses for the receiver.
#: Where the callee ends. Type arguments are listed too: `useApiQuery<string[]>(k)` is a
#: call to `useApiQuery`, and reading up to the arguments alone kept the `<string[]>`,
#: which then looked like a subscript and made an in-repository function "external".
ARGUMENT_NODES = ("arguments", "argument_list", "value_arguments", "call_arguments",
                  "call_suffix", "parenthesized_expression", "type_arguments")


def _callee(node) -> str:
    """The callee as written, receiver and all — the same shapes Python produces.

    This used to read `child_by_field_name("function")`, which is what TypeScript calls
    it. Java's `method_invocation` splits the same thing into `object` and `name`, so
    `TenantContext.getTenantId()` was recorded as a bare `getTenantId` — and one method
    then collected 735 callers across six services, 732 of them wrong. Exactly the bug
    the Python front end had, reborn in a language that names its fields differently.

    Reading the source text up to the arguments needs no field names at all, so a
    grammar this file has never been tested against behaves the same way.
    """
    cut = None
    for child in node.children:
        if child.type in ARGUMENT_NODES:
            cut = child.start_byte
            break
    if cut is not None:
        text = node.text[:cut - node.start_byte].decode("utf-8", "replace")
    else:
        target = (node.child_by_field_name("function")
                  or node.child_by_field_name("constructor")
                  or node.child_by_field_name("name"))
        if target is None:
            return ""
        text = target.text.decode("utf-8", "replace")

    text = text.strip()
    for prefix in ("new ", "new\t", "await ", "return "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if not text or "\n" in text:
        return ""
    if RECEIVER_SELF.match(text):
        return "self." + text.split(".", 1)[1]
    if UNKNOWABLE.search(text):
        # The receiver is a call or a subscript, so it names nothing we can follow.
        return "." + text.rsplit(".", 1)[-1].strip("()[]! ")
    return text


def _module(node) -> str:
    for child in node.children:
        if "string" in child.type or child.type in ("interpreted_string_literal",
                                                    "raw_string_literal"):
            return child.text.decode("utf-8", "replace").strip("\"'`")
    text = node.text.decode("utf-8", "replace")
    text = re.sub(r"^\s*(import|using|use|from)\s+", "", text).strip().rstrip(";")
    return text.split()[0].strip("\"'`") if text else ""


def parse(path: str, source: str, language: str) -> FileResult:
    """One file, really parsed. Raises nothing the caller has to catch."""
    from tree_sitter import QueryCursor
    # JSX is not TypeScript: the plain grammar marks a component body as an error
    # and the calls inside it vanish. Ninety-three of a hook's 109 callers were found
    # until a `.tsx` file was parsed as `.ts`; the rest were in components.
    grammar = "tsx" if path.endswith(".tsx") and "tsx" in GRAMMAR else language
    out = FileResult(path=path, language=language, tier="native")
    out.symbols.append(Symbol(path, "Module", path, 1, 0, "native"))

    tree = _parser(grammar).parse(source.encode("utf-8", "replace"))
    # Which capture each node is in, by node id. One query run per file; the walk
    # below then asks "what is this node" without knowing any grammar's vocabulary.
    role: dict[int, str] = {}
    for capture, nodes in QueryCursor(_query(grammar)).captures(tree.root_node).items():
        for node in nodes:
            role[node.id] = capture
    seen: set[str] = set()

    def declare(name: str, kind: str, node) -> str:
        qualified = f"{path}::{name}"
        if qualified in seen:
            return qualified
        seen.add(qualified)
        out.symbols.append(Symbol(qualified, kind, path, node.start_point[0] + 1,
                                  node.end_point[0] + 1, "native"))
        return qualified

    def walk(node, owner: str, enclosing: str) -> None:
        what = role.get(node.id)
        if what == "container":
            name = _name_of(node)
            if name:
                qualified = declare(name, "Class", node)
                out.edges.append(Edge(owner or path, "CONTAINS", qualified, "native"))
                for child in node.children:
                    walk(child, qualified, enclosing)
                return

        elif what == "callable":
            name = _name_of(node)
            if name:
                inside = owner and owner != path
                full = f"{owner.split('::', 1)[-1]}.{name}" if inside else name
                qualified = declare(full, "Method" if inside else "Function", node)
                out.edges.append(Edge(owner or path, "CONTAINS", qualified, "native"))
                for child in node.children:
                    walk(child, owner, qualified)
                return

        elif what == "bound":
            # `const handler = () => {...}` — the name is on the binding, not the
            # function, and modern TypeScript declares most of its code this way.
            value = node.child_by_field_name("value")
            if value is not None and value.type in ("arrow_function", "function",
                                                    "function_expression"):
                name = _name_of(node)
                if name:
                    inside = owner and owner != path
                    full = f"{owner.split('::', 1)[-1]}.{name}" if inside else name
                    qualified = declare(full, "Method" if inside else "Function", node)
                    out.edges.append(Edge(owner or path, "CONTAINS", qualified, "native"))
                    for child in node.children:
                        walk(child, owner, qualified)
                    return

        elif what == "call" and enclosing:
            target = _callee(node)
            if target:
                out.edges.append(Edge(enclosing, "CALLS", target, "native"))

        elif what == "import":
            module = _module(node)
            if module:
                out.edges.append(Edge(path, "IMPORTS", module, "native"))

        for child in node.children:
            walk(child, owner, enclosing)

    walk(tree.root_node, path, "")
    return out
