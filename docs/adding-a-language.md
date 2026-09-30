# Adding a language

A language is three small pieces: a query file, a grammar name, and an entry that says
which file extensions belong to it. The resolver, the store and the tools never learn a
language exists.

## Tier 1 — a real parse (tree-sitter)

`skygraph/queries/<language>.scm` names the node types of that grammar that play each
of seven roles. One interpreter in `treesitter.py` reads every file the same way. The
first five are what every language needs; the last two are optional and make calls
resolve better:

| Capture | Meaning | Becomes |
|---|---|---|
| `@container` | a named thing with members — class, interface, struct, enum, trait, impl, module | `Class` |
| `@callable` | a function or method | `Function`, or `Method` when inside a container |
| `@bound` | a name bound to a function value: `const handler = () => {}` | `Function` / `Method` |
| `@call` | a call site; the callee text, receiver included, is read by the interpreter | a `CALLS` edge |
| `@import` | an import; the module text is read by the interpreter | an `IMPORTS` edge |
| `@binding` | a field, parameter or local with a declared type, or assigned from a constructor | types the receiver: `repo.save()` on a `Repo` field resolves to `Repo.save` |
| `@reexport` | a re-export in a barrel file, such as `export { x } from "./x"` | a `RE_EXPORTS` edge, followed to the file that declares the name |

The whole Elixir entry would be:

```scheme
; skygraph/queries/elixir.scm
(call) @call
```

plus, in `treesitter.py`, one line in `GRAMMAR` naming the grammar the language pack
provides, and the tier-2 entry below, which is also where the file extensions are
declared.

A node type the grammar does not have fails when the file is compiled — at the first
index, loudly — rather than matching nothing. `tests/test_skygraph.py` compiles every
query file for every claimed grammar and parses a small snippet in each language,
expecting a class, a callable and a call.

Nesting, qualified names (`path::Class.method`), `this`/`self` normalisation and
receiver handling are the interpreter's job, not the query's. Keep the query to node
types; if a language needs more than that, the interpreter is the place to discuss it.

## Tier 2 — the pattern floor

`frontends.py::QUERY_LANGUAGES` holds one entry per language: its file extensions, and
anchored regular expressions for a class, a function and an import. The extensions are
how a file is recognised as that language at all. The patterns are the floor when a
parser cannot load: they find declarations and cannot find calls, and `index_health`
says so per language.

## What not to do

**Do not widen the schema to fit a language.** Seven captures map onto the declared
kinds and relations; a construct with no home is a decision about the vocabulary, made
once — not an eighth capture smuggled in by one file.

**Add the language to the benchmark.** `tests/test_benchmark.py::OTHER_LANGUAGES` takes
a three-file fixture under `tests/fixtures/` — a repository class, a service holding it
in a typed field, an entry point — and asks every language the same questions with
answers written by hand. A language without one is a claim, not a feature.

**Do not let a pattern guess quietly.** A tier-2 entry that cannot read something must
fall to the tier below and set `degraded`.
