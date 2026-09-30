# Skygraph

[![tests](https://github.com/arupmmi07/skygraph/actions/workflows/tests.yml/badge.svg)](https://github.com/arupmmi07/skygraph/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/arupmmi07/skygraph?include_prereleases)](https://github.com/arupmmi07/skygraph/releases)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![licence](https://img.shields.io/badge/licence-Apache%202.0-blue)](LICENSE)

*A graph of your code, for the agent reading it.*

**Code intelligence for coding agents.** Skygraph indexes a repository once into a local
graph and serves it to Claude Code, Codex or any MCP host through fourteen read-only
tools — so the agent stops rebuilding context out of your folder on every session.

An agent with no index pays for rediscovery every time you open it: read the tree, open
likely files, guess at the rest. Skygraph does the reading once, refreshes only what
changed, and answers the questions the agent would otherwise answer by opening files —
*where is this declared, what calls it, what breaks if it changes* — in a few hundred
tokens instead of a few thousand. When it is not sure, it says so, and the agent reads
the file.

- **Local.** One SQLite file in `~/.skygraph/`. No service, no account, no telemetry.
- **Eleven languages, really parsed.** Python, TypeScript/TSX, JavaScript, Java, Go,
  Rust, C#, Kotlin, Swift, PHP and Ruby — plus the frameworks, schemas and deploy files
  around them.
- **Honest.** Every unresolved call says *why* — `untyped`, `ambiguous` or `external` —
  and `index_health` shows what was parsed and what was guessed.

![Skygraph between the agent and the repository: fourteen read-only tools over MCP, five
ontologies, three extraction tiers, and an index refreshed by delta](docs/images/architecture.svg)

## Quick start

You need Python 3.11 or newer and a git client.

**1. Install.** [pipx](https://pipx.pypa.io) keeps skygraph in its own environment and
puts the two commands on your PATH:

```bash
pipx install "git+https://github.com/arupmmi07/skygraph.git@v0.2.0"
```

Or with pip, inside a virtual environment:

```bash
pip install "git+https://github.com/arupmmi07/skygraph.git@v0.2.0"
```

Check it:

```bash
skygraph --version
```

**2. Wire a project.** From anywhere:

```bash
skygraph init /path/to/your/project
```

That writes the configuration below and indexes the project once. The first index that
needs a parser downloads the parser bundle once (see [Privacy and
network](#privacy-and-network)).

| Written | What it does |
|---|---|
| `.mcp.json` in the project | tells Claude Code how to start the server, scoped to this repository |
| `CLAUDE.md`, and `AGENTS.md` if the project has one | a short paragraph telling the agent to use the graph before reading files, and to read the file when the graph says it is unsure |
| `.claude/settings.json` | a session-start hook that re-indexes only changed files and prints one line into the agent's context (`--no-hook` to skip) |
| Codex block | printed; `--codex` writes it into `~/.codex/config.toml` |

Running `init` again is safe: everything is merged or replaced, never duplicated. The
paths it writes are absolute and belong to your machine; a teammate runs `init` on
theirs.

**3. Restart the agent in the project** and ask it something only the graph answers
cheaply:

> Use skygraph: where is `PaymentService` declared, and who calls its `refund` method?

In Claude Code the tools appear as `mcp__skygraph__find_symbols` and so on. Run `/mcp`
to confirm the server is connected.

**Codex.** Run `skygraph init /path/to/your/project --codex`, or paste the printed block
into `~/.codex/config.toml`, then restart Codex.

**Any other MCP host.** `skygraph-mcp --repo <name>` is a stdio MCP server; point the
host at it by absolute path (`command -v skygraph-mcp` prints it). [Connecting
it](docs/connecting.md) has the details.

## The fourteen tools

All read-only. Only `read_source` returns code; everything else returns structure —
names, kinds, line ranges, relations — so the agent can check it has the right symbol
before paying for its text.

| | Tool | Answers |
|---|---|---|
| **Find** | `list_repos` | what is indexed, and how big — start here |
| | `find_symbols` | where a name is declared; an exact name comes back as one row |
| | `list_files` | the indexed files, optionally under a folder |
| | `map_coverage` | files and definitions per folder — is this module indexed, and how well |
| **Understand** | `context_for` | one call to start on a symbol: definition, file outline, imports, callers, callees — under a byte budget |
| | `describe_symbol` | one symbol's kind, file, line range and tier, without its source |
| | `expand_symbol` | a symbol with what it contains, calls and is called by; for an endpoint, the trace to its table |
| | `outline_file` | every declaration in a file with its line range |
| | `read_source` | the source of one symbol, read live from disk, marked `stale` if the file changed |
| **Traverse** | `related_symbols` | siblings in the file, callees, callers, importers |
| | `file_imports` | what a file imports, and what imports it |
| | `blast_radius` | transitive callers or callees, deepest first |
| **Trust** | `repo_summary` | counts and root for one repository |
| | `index_health` | parsed versus inferred, degraded files, which languages have call edges |

## Languages and frameworks

Every language below is parsed, not pattern-matched, and has a three-file fixture with
the same golden questions in CI. The last column is the share of in-repository calls
resolved to one declaration on a real codebase; the rest are marked `untyped` or
`ambiguous` rather than guessed.

| Language | Parser | Measured on | Calls resolved |
|---|---|---|---|
| Python | built-in `ast` | a 1,720-file Python service | 65 % |
| TypeScript, TSX | tree-sitter | a 10,089-file Angular and Java monorepo | 71 % |
| JavaScript | tree-sitter | the same monorepo's JavaScript files | 42 % |
| Java | tree-sitter | the same monorepo · square/moshi | 54 % · 74 % |
| C# | tree-sitter | serilog | 64 % |
| PHP | tree-sitter | slimphp/Slim | 49 % |
| Kotlin | tree-sitter | square/moshi | 42 % |
| Go | tree-sitter | gorilla/mux | 40 % |
| Swift | tree-sitter | Alamofire | 40 % |
| Rust | tree-sitter | tokio-rs/bytes | 29 % |
| Ruby | tree-sitter | sinatra | 24 % |

Rust traits and generics, Ruby's missing types and Swift overloads resolve least. There,
"who calls this" is a lead, not a list, and the answer says so.

Beyond code, five ontologies declare what else the graph may hold:

| Ontology | What | Read from |
|---|---|---|
| `code_ontology` | declarations, calls, imports, inheritance | the eleven languages above |
| `data_ontology` | entities, fields, keys | SQLAlchemy, Django, SQLModel, JPA, SQL DDL, Prisma |
| `api_ontology` | endpoints, operations, parameters | FastAPI, Flask, Express, Spring, JAX-RS, OpenAPI in JSON or YAML |
| `deploy_ontology` | images, deployables, config, pipelines, dependencies | Dockerfile, Compose, Kubernetes, GitHub Actions, GitLab CI, `package.json`, `pom.xml`, `build.gradle`, `requirements`, `pyproject`, `go.mod`, `Cargo.toml` |
| `link` | the joins between the layers | derived after indexing |

The joins are what a text search cannot fake, because they are written down nowhere —
nothing in a route handler names a table:

```
POST /users  ──HANDLED_BY──►  create_user  ──PERSISTS_TO──►  User  ──MAPS_TO──►  users
   api_ontology                  code_ontology                 data_ontology            table
```

`expand_symbol` on an endpoint returns that chain in one call.

## When the agent should read the file instead

The graph narrows what to read; it does not replace reading when it is unsure. Every
unresolved call carries its reason:

| | |
|---|---|
| `resolved` | the callee is known |
| `untyped` | the receiver is a local, parameter or return value whose type is unknown — the callee exists, which one is unknown |
| `ambiguous` | several same-named declarations could be meant |
| `external` | not declared in this repository |

The paragraph `init` writes into `CLAUDE.md` turns that into a rule: if an answer is
empty, marked `stale`, `untyped` or `ambiguous`, or `index_health` says the file's
language is not traversable, read the file directly.

## Keeping it current

- **Every session.** The hook `init` installs runs a delta index when the agent starts:
  only files whose content hash changed are read again. On this repository a cold index
  takes 0.6 s and the next run reads nothing.
- **By hand.** `skygraph index /path/to/project --repo name` does the same; `--full`
  re-reads everything.
- **Not yet automatic:** edits the agent makes during a session, and `git checkout` or
  `pull`, are picked up at the next session start or by hand. Refreshing on every edit
  and git operation is next — see [Keeping the index fresh](docs/design/index-refresh.md).
- **Changed since indexing.** `read_source` compares the file on disk with the indexed
  one and marks the answer `stale` rather than pointing at the wrong lines.
- **After upgrading skygraph,** restart the agent so it starts a server from the new
  code. An old server that finds a newer index refuses it and says "restart" rather than
  answering from it.

## Privacy and network

- **What the index holds.** Structure, not text: names, kinds, line ranges, relations
  and a content hash per file, in `~/.skygraph/index.db`. `read_source` reads source
  from disk when asked.
- **What goes over the network.** Two things, and nothing else:
  1. The parser pack downloads its compiled grammars the first time one is needed —
     one bundle for your platform, about 22–26 MB, once per pack version, from the
     pack's own GitHub release — and caches it. Offline, those files fall back to pattern matching and
     say so.
  2. The optional model tier, only if you set `SKYGRAPH_MODEL_KEY`, sends files no
     parser could read to the endpoint you choose. A local endpoint keeps it on your
     machine. See [the model tier](docs/connecting.md#optionally-let-a-model-read-what-the-parsers-could-not).
- **What the server can do.** Answer questions. There is no write tool; indexing is a
  separate command. It speaks MCP over stdio only.

## Commands

| Command | Does |
|---|---|
| `skygraph init <path>` | wire a project to Claude Code (and Codex with `--codex`), then index it |
| `skygraph index <path> --repo <name>` | build or refresh the index; `--full` re-reads everything, `--summary` prints one line |
| `skygraph forget --repo <name>` | drop one repository from the index |
| `skygraph degraded --repo <name>` | files that were not parsed at their best tier, and why |
| `skygraph search <text> --repo <name>` | find symbols by name from the terminal |
| `skygraph neighbours <symbol> --repo <name>` | one hop of calls and imports |
| `skygraph ontologies` | the five ontologies as JSON |
| `skygraph-mcp --repo <name>` | the MCP server a host starts |

Every command that reads or writes an index takes `--db <file>` to use one other than
`~/.skygraph/index.db`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The host shows no skygraph tools, or says "connection closed" | Run the server by hand with the command from `.mcp.json` and read its error: `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \| "$(command -v skygraph-mcp)"` |
| `list_repos` comes back empty | The server reads a different index. Pass the same `--db` to `init` and the server, or re-run `init`. |
| A tool answers "written by skygraph schema N … restart" | A server from before an upgrade is still running. Restart the agent. |
| `index_health` lists a language as not traversable | Its parser did not load — usually the first index ran offline. Run `skygraph index <path> --repo <name> --full` once online. |
| Answers point at old line numbers | Re-index, or reopen the session so the hook does. `read_source` already marks those answers `stale`. |

## Uninstall

```bash
pipx uninstall skygraph
rm -rf ~/.skygraph
```

In each project, delete the `skygraph` entry from `.mcp.json`, the block between
`<!-- skygraph:start -->` and `<!-- skygraph:end -->` in `CLAUDE.md` and `AGENTS.md`,
and the skygraph hook in `.claude/settings.json`; in `~/.codex/config.toml`, the block
between `# skygraph:start` and `# skygraph:end`. The parser cache lives where this
prints, before you uninstall:

```bash
python -c "import tree_sitter_language_pack as p; print(p.cache_dir())"
```

## How it works

![The pipeline, the three tiers, and what the core guarantees regardless of
language](docs/images/pipeline.svg)

**One capture vocabulary, interchangeable front ends.** Every front end emits the same
`Symbol` and `Edge` types; the store, the resolver and the tools know nothing about
languages. A language is a query file — see [Adding a language](docs/adding-a-language.md).

| Tier | How | Used for |
|---|---|---|
| **native** | a real parse | Python via `ast`; the other ten via tree-sitter |
| **query** | line patterns — declarations only, never calls | a language whose parser could not load |
| **model** | optional, needs a key | files no parser could read |
| **heuristic** | the floor, every row a guess | the rest |

**Nothing is lost silently.** A file a tier cannot handle falls to the tier below and
records why on its row; `skygraph degraded` lists them. A graph that is quietly
incomplete gives confident wrong answers.

**Calls are resolved by scope, then by name.** On the Python service above, `get` is
declared 57 times, so a name alone decides nothing. The resolver works narrowest first:

| Call | Found by |
|---|---|
| `self.x()` inside a class | that class, then another class in the same file |
| `svc.find()` on a field, parameter or local with a declared type, or built by a constructor or a typed factory | that type, in every language that declares types |
| a name imported through a barrel (`index.ts`, `__init__.py`) | the file that actually declares it |
| a call on an interface or base class | the interface; `expand_symbol` on an implementation lists those callers too, marked `via` |
| `module.x()` on an imported module or Go package | that module |
| a bare `x()` | `this` in a Java-family class that declares it, then the same file, an import, then the one declaration of that name in the language |
| `receiver.x()` on anything else | **nothing — left `untyped`** |

An unknown receiver is never resolved on the name being unique: `config.get("a")` is a
dictionary, not a call to the one class that happens to declare `get`.

**The parsers are what give calls.** The same 10,089-file monorepo, indexed both ways
on a laptop:

| | patterns only | with parsers |
|---|---|---|
| symbols | 16,076 | **38,700** |
| edges | 41,524 | **284,728** |
| resolved calls | 14 | **38,773** |
| cold index | 22 s | 54 s |

**The schema is the authority.** `skygraph/schema.py` and the five ontologies declare the
kinds and relations that may exist; a front end — or a model — emitting anything else is
refused, not admitted. **Scope lives on the row:** every symbol and edge carries its
repository and branch, so a query that forgets to filter returns nothing rather than
another project's code.

[Architecture](docs/architecture.md) has the full design and the reasons behind it.

## Documentation

| | |
|---|---|
| [Connecting it](docs/connecting.md) | Claude Code, Codex or any MCP host, by hand; running from a checkout; the model tier |
| [Architecture](docs/architecture.md) | The pipeline, the resolver, and why each rule exists |
| [Adding a language](docs/adding-a-language.md) | A query file, a grammar name and its file extensions |
| [Roadmap](ROADMAP.md) | Every planned feature, its status and owner — and how to pick one |
| [Keeping the index fresh](docs/design/index-refresh.md) | The design for refreshing after edits and git operations |
| [Contributing](CONTRIBUTING.md) | Running the tests, and what a change needs |
| [Changelog](CHANGELOG.md) | What changed in each release |
| [Security](SECURITY.md) | What the index holds, and how to report a vulnerability |

## Status

Version 0.2.0, beta. **267 tests**, including a golden-question benchmark with
hand-checked answers and byte ceilings, run by CI on Python 3.11 to 3.14 — once without
the parsers, for the fallback, and once as installed. Developed on macOS; CI runs on
Linux.

What comes next — refreshing on every edit and git operation, deeper OpenAPI, SQL and
ORM support, design diagrams, more languages — is in the [roadmap](ROADMAP.md), with a
status and an owner per feature. Contributions welcome: pick a `Ready` one.

## Licence

[Apache 2.0](LICENSE).
