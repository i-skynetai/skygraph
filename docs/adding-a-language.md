# Adding a language

A language is a query file and a grammar name. No Python.

## Tier 1 — a real parse (tree-sitter)

`skygraph/queries/<language>.scm` names the node types of that grammar that play each
of five roles. One interpreter in `treesitter.py` reads every file the same way:

| Capture | Meaning | Becomes |
|---|---|---|
| `@container` | a named thing with members — class, interface, struct, enum, trait, impl, module | `Class` |
| `@callable` | a function or method | `Function`, or `Method` when inside a container |
| `@bound` | a name bound to a function value: `const handler = () => {}` | `Function` / `Method` |
| `@call` | a call site; the callee text, receiver included, is read by the interpreter | a `CALLS` edge |
| `@import` | an import; the module text is read by the interpreter | an `IMPORTS` edge |

The whole Elixir entry would be:

```scheme
; skygraph/queries/elixir.scm
(call) @call
```

plus, in `treesitter.py`, one line in `GRAMMAR` naming the grammar the language pack
provides. That is the whole change. The resolver, the store, the scoping and the MCP
tools never learn a language exists.

A node type the grammar does not have fails when the file is compiled — at the first
index, loudly — rather than matching nothing. `tests/test_skygraph.py` compiles every
query file for every claimed grammar and parses a small snippet in each language,
expecting a class, a callable and a call.

Nesting, qualified names (`path::Class.method`), `this`/`self` normalisation and
receiver handling are the interpreter's job, not the query's. Keep the query to node
types; if a language needs more than that, the interpreter is the place to discuss it.

## Tier 2 — the pattern floor

Without tree-sitter installed, `frontends.py::QUERY_LANGUAGES` holds one entry per
language: an extension list and anchored regular expressions for a class, a function
and an import. It finds declarations and cannot find calls, and `index_health` says
so per language. Add an entry there too, so the language is read at all when the
parsers are absent.

## What not to do

**Do not widen the schema to fit a language.** Five captures map onto the declared
kinds; a construct with no home is a decision about the vocabulary, made once — not a
sixth capture smuggled in by one file.

**Do not let a pattern guess quietly.** A tier-2 entry that cannot read something must
fall to the tier below and set `degraded`.
