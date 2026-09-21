# skynet-code-index

**Code intelligence for coding agents.** Parses a repository into a graph of files and
symbols carrying `CALLS`, `IMPORTS`, `CONTAINS` and `INHERITS` edges, and serves symbol
search and one-hop neighbour expansion to an agent over MCP.

Sourcegraph and Graphify solve this for humans reading code. This solves it for an agent
assembling context: when a search surfaces a caller, the agent needs the callee that
lives in a *different file*, and that is a graph query, not a text search.

```
  repository ──► front end ──► capture vocabulary ──► graph ──► MCP
                  (3 tiers)      (one schema)        (SQLite)   (5 read-only tools)
```

## The design

**One capture vocabulary, three interchangeable front ends.** Every front end emits the
same `Symbol` and `Edge` types. Everything downstream — the writer, the store, the query
layer, the scoping — knows nothing about languages. Adding a language means adding a
front end, not touching the core.

| Tier | How | Today |
|---|---|---|
| **1 · native** | a real parse, full fidelity | Python, via the standard library `ast` |
| **2 · query** | declarative patterns per language | TypeScript, JavaScript, Go, Java, Ruby, Rust, C#, PHP, Kotlin, Swift |
| **3 · heuristic** | last resort, marks everything a guess | anything else |

**Nothing is ever lost silently.** A construct a tier cannot handle degrades to the tier
below and records *why*, on the file row. `codeindex degraded` lists every one.

A graph that is quietly incomplete produces confident wrong answers. That is worse than
a graph that says loudly it could not read a file, so the engine refuses to be quiet.

**The schema is the authority.** `codeindex/schema.py` declares the kinds and relations
that may exist. A front end emitting anything else raises at construction — the process
stops rather than writing a node nobody declared.

**Scope lives on the row, not on the query.** Every symbol and edge carries its repo and
branch. A query that forgets to filter returns nothing rather than another repository's
code: the failure mode is empty, not wrong.

## Use

```bash
git clone https://github.com/arupmmi07/skynet-code-index.git
cd skynet-code-index

python3 -m codeindex index /path/to/a/repo --repo myrepo
python3 -m codeindex search Alpha --repo myrepo
python3 -m codeindex neighbours 'src/a.py::Alpha.run' --repo myrepo
python3 -m codeindex degraded --repo myrepo
```

Indexing itself:

```json
{ "files": 7, "symbols": 32, "edges": 266, "languages": 1,
  "tiers": { "native": 7 }, "degraded": 0 }
```

## As an MCP server

```bash
python3 -m codeindex serve --db code-index.db
```

Five tools, all read-only: `code_search`, `code_neighbours`, `code_repos`,
`code_stats`, `code_degraded`. There is no write tool — indexing is a separate,
deliberate act.

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"code_neighbours",
           "arguments":{"repo":"myrepo","symbol":"src/a.py::Alpha.run"}}}
```

## Documentation

| | |
|---|---|
| [Architecture](docs/architecture.md) | The pipeline, and where a language plugs in |
| [Adding a language](docs/adding-a-language.md) | Tier 2 in about twenty lines |

## Status

Python 3.11+, standard library only. **18 tests.** Line numbers are recorded for
declarations; end-of-range is not yet persisted.

## Licence

Apache 2.0.
