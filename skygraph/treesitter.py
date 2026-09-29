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
CAPTURES = ("container", "callable", "bound", "call", "import", "binding", "reexport")
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


#: Nodes that carry a name, and nodes that carry a type, across the grammars. A binding
#: is read as "the first name-ish thing" and "the first type-ish thing under the type
#: field", which is enough for a field, a parameter or a typed local in every grammar
#: this file knows, and wrong for nothing worse than an untyped receiver.
NAME_NODES = {"identifier", "simple_identifier", "field_identifier", "property_identifier",
              "variable_name", "instance_variable", "constant"}
TYPE_NAME_NODES = {"type_identifier", "name", "simple_identifier", "predefined_type",
                   "identifier"}
TYPE_FIELDS = ("type", "return_type", "returns", "result")
#: Wrappers whose *argument* is the type that matters: `Optional<Foo>`, `List<Foo>`.
TYPE_WRAPPERS = {"Optional", "List", "list", "Set", "set", "Map", "dict", "Dict",
                 "Sequence", "Iterable", "Iterator", "Promise", "Observable", "Array",
                 "Vec", "Box", "Rc", "Arc", "Option", "Result", "Task", "Future",
                 "Mono", "Flux", "ReadonlyArray", "Nullable"}


def _first(node, types: set):
    """First descendant (depth-first) whose type is in `types`, or None."""
    stack = list(reversed(node.children))
    while stack:
        n = stack.pop()
        if n.type in types:
            return n
        stack.extend(reversed(n.children))
    return None


def _text(node) -> str:
    return node.text.decode("utf-8", "replace").strip() if node is not None else ""


def _type_name(node) -> str:
    """The bare class name a type node means, unwrapping `Optional<Foo>` and `*Foo`.

    A name that does not start with a capital — `string`, `int`, `error`, `i32` — is a
    primitive, not a class the graph could hold, and is reported as no type at all.
    """
    return _capitalised(_raw_type_name(node))


def _capitalised(text: str) -> str:
    return text if text[:1].isupper() else ""


def _raw_type_name(node) -> str:
    if node is None:
        return ""
    if node.type in TYPE_NAME_NODES:
        return _text(node)
    if node.type == "generic_type":
        base = _first(node, TYPE_NAME_NODES)
        if base is not None and _text(base) in TYPE_WRAPPERS:
            args = node.child_by_field_name("type_arguments") or _first(node, {"type_arguments"})
            inner = _first(args, TYPE_NAME_NODES) if args is not None else None
            if inner is not None:
                return _text(inner)
        return _text(base) if base is not None else ""
    found = _first(node, TYPE_NAME_NODES)
    if found is None:
        return ""
    text = _text(found)
    if text in TYPE_WRAPPERS:
        rest = [n for n in _descendants(node, TYPE_NAME_NODES) if _text(n) != text]
        return _text(rest[0]) if rest else ""
    return text


def _descendants(node, types: set) -> list:
    out, stack = [], list(reversed(node.children))
    while stack:
        n = stack.pop()
        if n.type in types:
            out.append(n)
        stack.extend(reversed(n.children))
    return out


def _constructed(value, language: str = "") -> str:
    """The type a value names by itself: `new Foo()`, `Foo()`, `Foo::new()`, `Foo.new`,
    `Foo{}` — or `make()` for a call to a plain function, which the resolver follows
    through that function's declared return type."""
    if value is None:
        return ""
    kind = value.type
    if kind == "new_expression":
        return _text(value.child_by_field_name("constructor"))
    if kind == "object_creation_expression":
        return _type_name(value.child_by_field_name("type")
                          or _first(value, {"type_identifier", "name", "identifier"}))
    if kind == "composite_literal":
        return _type_name(value.child_by_field_name("type"))
    if kind == "call":                                   # ruby
        receiver, method = value.child_by_field_name("receiver"), value.child_by_field_name("method")
        return _text(receiver) if receiver is not None and _text(method) == "new" else ""
    if kind in ("call_expression", "invocation_expression", "function_call_expression",
                "method_invocation"):
        fn = (value.child_by_field_name("function") or value.child_by_field_name("name")
              or (value.children[0] if value.children else None))
        if kind == "method_invocation" and value.child_by_field_name("object") is not None:
            return ""                                    # `a.make()`: not a plain factory
        text = _text(fn)
        if "::" in text:                                 # rust `Foo::new()`
            head = text.split("::")[0]
            return head if head[:1].isupper() else ""
        if language in CONSTRUCTOR_IS_A_CALL and text[:1].isupper() and "." not in text:
            return text                                  # kotlin, swift `Foo()`
        if text.isidentifier():                          # a factory: follow its return type
            return f"{text}()"
        if text.startswith(("this.", "self.", "$this->", "@")) and text.count(".") + text.count("->") == 1:
            return "self." + text.replace("->", ".").lstrip("$@").split(".")[-1] + "()"
        return ""
    return ""


INSTANCE_PREFIXES = ("this.", "self.", "$this->", "@")
#: Expressions whose type a value states by itself, across the grammars.
VALUE_KINDS = ("call_expression", "new_expression", "object_creation_expression",
               "invocation_expression", "function_call_expression", "method_invocation",
               "call", "composite_literal")


def _binding(node, language: str = "") -> tuple[str, str, bool]:
    """(name, type, instance) for a declaration node; ("", "", False) when unreadable.

    `instance` is True for `this.x = new Foo()`, `@x = Foo.new` and the like: a
    binding made inside a method that belongs to the class, not the method.
    """
    inner = next((c for c in node.children if c.type == "variable_declaration"), None)
    if inner is not None and (inner.child_by_field_name("type") is not None
                              or any(c.type == "variable_declarator" for c in inner.children)):
        # C#: `int x = ...` keeps the type and the declarator one level down. Kotlin's
        # `variable_declaration` holds only the name, and is read in place below.
        name, kind, _ = _binding(inner, language)
        return name, kind, False
    instance = False
    left = node.child_by_field_name("left")
    if left is not None:
        text = _text(left)
        if text.startswith(INSTANCE_PREFIXES):
            instance = True
            base = text.replace("->", ".").lstrip("$@")
            name = base.split(".")[-1]
            value = node.child_by_field_name("right")
            kind = _constructed(value, language)
            return (name, kind, True) if name else ("", "", False)
    name = ""
    declarator = next((c for c in node.children if c.type == "variable_declarator"), None)
    if declarator is not None and declarator.child_by_field_name("name") is not None:
        name = _text(declarator.child_by_field_name("name"))
    for field in ("name", "pattern", "declarator", "left"):
        if name:
            break
        child = node.child_by_field_name(field)
        if child is None:
            continue
        target = child if child.type in NAME_NODES else _first(child, NAME_NODES)
        if target is not None:
            name = _text(target).lstrip("$@")
            break
    if not name:
        for child in node.children:
            if child.type in NAME_NODES:
                name = _text(child).lstrip("$@")
                break
            if child.type in ("variable_declaration", "pattern", "property_element",
                              "value_binding_pattern", "expression_list"):
                target = _first(child, NAME_NODES)
                if target is not None:
                    name = _text(target).lstrip("$@")
                    break
    if not name or name in ("this", "self"):
        return "", "", False
    typed = node.child_by_field_name("type")
    if typed is None:
        typed = next((c for c in node.children
                      if c.type in ("type_annotation", "user_type", "named_type")), None)
    kind = _type_name(typed) if typed is not None else ""
    if not kind:
        value = node.child_by_field_name("value") or node.child_by_field_name("right")
        if value is None:
            declarator = node.child_by_field_name("declarator") or next(
                (c for c in node.children if c.type == "variable_declarator"), None)
            if declarator is not None:
                value = declarator.child_by_field_name("value")
                if value is None:
                    # C#: the initializer is a plain child of the declarator, or sits
                    # inside an `equals_value_clause`, depending on the grammar version.
                    clause = next((c for c in declarator.children
                                   if c.type == "equals_value_clause"), None)
                    holder = clause if clause is not None else declarator
                    value = next((c for c in holder.children if c.type in VALUE_KINDS), None)
        if value is None:
            value = next((c for c in node.children if c.type in VALUE_KINDS), None)
        if value is not None and value.type == "expression_list":
            value = value.children[0] if value.children else None
        kind = _constructed(value, language)
    return name, kind, instance


def _receiver_of(node) -> tuple[str, str]:
    """Go: `func (a *A) M()` — the receiver's name and type, or ("", "")."""
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return "", ""
    param = _first(receiver, {"parameter_declaration"})
    if param is None:
        return "", ""
    return _text(param.child_by_field_name("name")), _type_name(param.child_by_field_name("type"))


def _pattern_names(node) -> list[str]:
    """Names bound by a destructuring pattern: `const { t, i18n } = useTranslation()`.
    Their types are unknown; what matters is that they are locals, so a bare `t()`
    is a call on a local and not a search of the repository for anything named `t`."""
    pattern = node.child_by_field_name("name") or node.child_by_field_name("pattern")
    if pattern is None or pattern.type not in ("object_pattern", "array_pattern",
                                               "tuple_pattern", "list_pattern"):
        return []
    return [_text(n) for n in _descendants(pattern, {"shorthand_property_identifier_pattern",
                                                      "identifier", "simple_identifier"})]


def _return_type(node) -> str:
    """The declared return type of a callable, as a bare class name."""
    for field in ("return_type", "returns", "result"):
        child = node.child_by_field_name(field)
        if child is not None:
            return _type_name(child)
    if node.type == "method_declaration":                # java: the `type` field
        return _type_name(node.child_by_field_name("type"))
    for child in node.children:                          # kotlin, swift: a bare user_type child
        if child.type == "user_type":
            return _type_name(child)
    return ""


def _retype(target: str, locals_: dict, fields: dict) -> str:
    """`svc.find` on a typed name becomes `FooService.find`; the resolver does the rest."""
    parts = target.split(".")
    if parts[0] in locals_ and locals_[parts[0]] == "self":
        parts[0] = "self"
    if parts[0] == "self" and len(parts) == 3 and fields.get(parts[1]):
        return f"{fields[parts[1]]}.{parts[2]}"
    if parts[0] == "self" and len(parts) == 2:
        return "self." + parts[1]
    if len(parts) == 1 and locals_.get(target, None) == "":
        # `t()` where `t` came from `const { t } = useTranslation()`: a call on a
        # local, not a search of the repository for anything named `t`.
        return f"(local).{target}"
    if len(parts) == 2 and not target.startswith("("):
        if locals_.get(parts[0]):
            return f"{locals_[parts[0]]}.{parts[1]}"
        if fields.get(parts[0]):
            return f"{fields[parts[0]]}.{parts[1]}"
    return target


#: Languages where `Foo()` with no keyword constructs a Foo. Elsewhere a capitalised
#: call is an ordinary method — C# names every method that way.
CONSTRUCTOR_IS_A_CALL = {"kotlin", "swift", "scala"}


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
    # PHP writes `$this->svc->find`, Ruby `@svc.find`; both mean what `self.x.m` means.
    text = text.replace("->", ".").replace("::", ".").lstrip("$")
    if text.startswith("@"):
        text = "self." + text[1:]
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


def _import_names(node) -> list[str]:
    """The local names an import binds: `import D, { a, b as c } from 'x'` → D, a, c.

    An import edge that names only the module cannot type anything — `Foo.m()` needs
    to know that `Foo` came from that module. So each bound name is recorded as
    `module::name`, the way the Python front end records `pkg.name`.
    """
    names: list[str] = []
    clause = next((c for c in node.children if c.type == "import_clause"), None)
    if clause is None:
        return names
    for child in clause.children:
        if child.type == "identifier":                          # default import
            names.append(_text(child))
        elif child.type == "namespace_import":                 # `* as ns`
            ident = _first(child, {"identifier"})
            if ident is not None:
                names.append(_text(ident))
        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type == "import_specifier":
                    name = spec.child_by_field_name("name")
                    alias = spec.child_by_field_name("alias")
                    if name is not None and alias is not None:
                        names.append(f"{_text(name)} as {_text(alias)}")   # `Foo as F`
                    elif name is not None:
                        names.append(_text(name))
    return names


def parse(path: str, source: str, language: str) -> FileResult:
    """One file, really parsed. Raises nothing the caller has to catch."""
    from tree_sitter import QueryCursor
    # JSX is not TypeScript: the plain grammar marks a component body as an error
    # and the calls inside it vanish. Ninety-three of a hook's 109 callers were found
    # until a `.tsx` file was parsed as `.ts`; the rest were in components.
    grammar = "tsx" if path.endswith(".tsx") and "tsx" in GRAMMAR else language
    out = FileResult(path=path, language=language, tier="native")
    out.symbols.append(Symbol(path, "Module", path, 1, source.count("\n") + 1, "native"))

    tree = _parser(grammar).parse(source.encode("utf-8", "replace"))
    # Which capture each node is in, by node id. One query run per file; the walk
    # below then asks "what is this node" without knowing any grammar's vocabulary.
    role: dict[int, str] = {}
    for capture, nodes in QueryCursor(_query(grammar)).captures(tree.root_node).items():
        for node in nodes:
            role[node.id] = capture
    seen: set[str] = set()

    def declare(name: str, kind: str, node, returns: str = "") -> str:
        qualified = f"{path}::{name}"
        if qualified in seen:
            return qualified
        seen.add(qualified)
        out.symbols.append(Symbol(qualified, kind, path, node.start_point[0] + 1,
                                  node.end_point[0] + 1, "native", returns=returns))
        return qualified

    def is_function_value(node) -> bool:
        value = node.child_by_field_name("value")
        return value is not None and value.type in ("arrow_function", "function",
                                                    "function_expression")

    #: Fields by the type that declares them. Go and Rust keep a struct's fields in one
    #: node and its methods in others (`func (a *A)`, `impl A`), so a method finds its
    #: fields by the type's name rather than by nesting.
    struct_fields: dict[str, dict[str, str]] = {}

    def bindings_under(node, container: bool) -> dict[str, str]:
        """Every typed name declared inside `node` but not inside a nested callable or
        container — a class's fields, or a callable's parameters and locals. Scanned up
        front, so a field declared below its first use still types it. For a container
        the scan also enters its methods, but keeps only instance bindings there:
        `this.svc = new Foo()` in a constructor is a field."""
        found: dict[str, str] = {}
        stack = [(c, False) for c in reversed(node.children)]
        while stack:
            n, in_callable = stack.pop()
            what = role.get(n.id)
            if what == "container":
                continue
            if what == "callable" or (what == "bound" and is_function_value(n)):
                if not container:
                    continue
                stack.extend((c, True) for c in reversed(n.children))
                continue
            if what in ("binding", "bound"):
                name, kind, instance = _binding(n, language)
                if name and name not in found and (instance or not in_callable):
                    found[name] = kind                   # "" means: a local of unknown type
                if not container:
                    for local in _pattern_names(n):
                        found.setdefault(local, "")
            stack.extend((c, in_callable) for c in reversed(n.children))
        return found

    def walk(node, owner: str, enclosing: str, fields: dict, locals_: dict) -> None:
        what = role.get(node.id)
        if what == "container":
            name = _name_of(node)
            if name:
                qualified = declare(name, "Class", node)
                out.edges.append(Edge(owner or path, "CONTAINS", qualified, "native"))
                own = bindings_under(node, container=True)
                # `impl A` in Rust owns no fields; `struct A` does. Share by name.
                struct_fields.setdefault(name, {}).update(own)
                own = struct_fields[name]
                for child in node.children:
                    walk(child, qualified, enclosing, own, locals_)
                return

        elif what == "callable" or (what == "bound" and is_function_value(node)):
            # `const handler = () => {...}` — the name is on the binding, not the
            # function, and modern TypeScript declares most of its code this way.
            name = _name_of(node)
            if name:
                inside = owner and owner != path
                receiver, rtype = _receiver_of(node)
                if rtype and not inside:
                    # Go: `func (s *Service) Handle()` is `Service.Handle`, a method of
                    # a struct declared elsewhere in the file — or in another one.
                    full, kind, holder = f"{rtype}.{name}", "Method", f"{path}::{rtype}"
                else:
                    full = f"{owner.split('::', 1)[-1]}.{name}" if inside else name
                    kind, holder = ("Method" if inside else "Function"), (owner or path)
                qualified = declare(full, kind, node, returns=_return_type(node))
                out.edges.append(Edge(holder, "CONTAINS", qualified, "native"))
                own = bindings_under(node, container=False)
                seen_fields = fields
                if receiver and rtype:
                    # `s` is this method's `self`.
                    own[receiver] = "self"
                    seen_fields = struct_fields.get(rtype, fields)
                for child in node.children:
                    walk(child, owner, qualified, seen_fields, own)
                return

        elif what == "call" and language == "ruby" and _callee(node) in ("require", "require_relative"):
            # Ruby imports are calls. Record the file, not a call to `require`.
            arg = _first(node, {"string_content"})
            if arg is not None:
                out.edges.append(Edge(path, "IMPORTS", "./" + _text(arg) if _callee(node) == "require_relative" else _text(arg), "native"))

        elif what == "call" and enclosing:
            target = _callee(node)
            if target:
                out.edges.append(Edge(enclosing, "CALLS",
                                      _retype(target, locals_, fields), "native"))

        elif what == "import":
            module = _module(node)
            if module:
                names = _import_names(node) if node.type == "import_statement" else []
                for name in names or [""]:
                    out.edges.append(Edge(path, "IMPORTS",
                                          f"{module}::{name}" if name else module, "native"))

        elif what == "reexport" and node.child_by_field_name("source") is not None:
            # A barrel. Its names come from elsewhere, and a file importing the barrel
            # is really importing that elsewhere — the resolver follows this edge.
            module = _text(node.child_by_field_name("source")).strip("\"'`")
            if module:
                out.edges.append(Edge(path, "RE_EXPORTS", module, "native"))

        for child in node.children:
            walk(child, owner, enclosing, fields, locals_)

    walk(tree.root_node, path, "", {}, {})
    return out
