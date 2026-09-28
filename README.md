# Skygraph

[![tests](https://github.com/arupmmi07/skygraph/actions/workflows/tests.yml/badge.svg)](https://github.com/arupmmi07/skygraph/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![licence](https://img.shields.io/badge/licence-Apache%202.0-blue)](LICENSE)


*A graph of your code, for the agent reading it.*

**Code intelligence for coding agents.** It indexes a repository once into a graph, and
serves that graph to Claude Code, Codex or any MCP host through fourteen read-only
tools — so the agent stops rebuilding context out of your folder on every session.

That is the whole argument. An agent with no index pays for rediscovery every time you
open it: read the tree, open likely files, guess at the rest. Skygraph does the reading
once, refreshes only what changed, and answers questions the agent would otherwise
answer by opening files — *where is this declared, what calls it, what breaks if it
changes* — in a few hundred tokens instead of a few thousand.

Sourcegraph and Graphify solve this for humans reading code. This solves it for an agent
assembling context: when a search surfaces a caller, the agent needs the callee that
lives in a *different file*, and that is a graph query, not a text search.

## Where it sits

![Skygraph between the agent and the repository: fourteen read-only tools over MCP, five
ontologies, three extraction tiers, and an index refreshed by delta](docs/images/architecture.svg)

## The fourteen tools

Shaped by one question: does this let the agent take one fewer turn, or carry less text,
than reading the folder would?

| | |
|---|---|
| **Find** | `find_symbols` · `list_repos` · `list_files` · `map_coverage` |
| **Understand** | `describe_symbol` · `expand_symbol` · `outline_file` · `read_source` · `context_for` |
| **Traverse** | `related_symbols` · `file_imports` · `blast_radius` |
| **Trust** | `repo_summary` · `index_health` |

Three rules fall out of that question, and they are what make this different from a
search box.

**Look before you fetch.** Only `read_source` returns code. Everything else returns
structure — names, kinds, line ranges, relations. An agent can locate a symbol, see its
shape, check its callers and decide it is the wrong one, for a few hundred tokens rather
than a file.

**Answer the whole question in one call.** `context_for`, `expand_symbol` and `related_symbols`
bundle what would otherwise be four or five round trips. A round trip re-sends the whole
conversation, so a bundled answer is cheaper than the sum of its parts by a wide margin.

**Say what you do not know.** `index_health` exists because an agent that cannot
see the gaps in an index will answer over them. An index nine tenths inferred by a
language model is a different object from one nine tenths parsed, and nothing in the
rows themselves says which you have.

## Five ontologies

An ontology declares what may exist in the graph. A front end that emits anything else
raises rather than writing a row nobody agreed to.

| | | Read from |
|---|---|---|
| `code_ontology` | what is declared, what calls what, what imports what | Python AST; ten more languages parsed with `[parsers]`, pattern-matched without |
| `data_ontology` | entities, fields, keys | SQLAlchemy, Django, SQLModel, SQL DDL, Prisma |
| `api_ontology` | endpoints, operations, parameters | FastAPI, Flask, Express, Spring, OpenAPI in JSON or YAML |
| `deploy_ontology` | images, deployables, config, pipelines | Dockerfile, Compose, Kubernetes, GitHub Actions, GitLab CI |
| `link` | the joins between the layers | derived after indexing |

**A file can feed several at once.** A module of SQLAlchemy models is `code_ontology`
and `data_ontology` both: the class really is a class, and it really is an entity with a
table. Asking about it returns both, because being told "it's a class" and never
learning it has a table is usually half the answer you wanted.

```json
{"name": "models.py::User", "kind": "Class", "ontology": "code_ontology",
 "also_in": [{"ontology": "data_ontology", "kind": "Entity", "summary": "table users"}]}
```

## What the join buys you

`code_ontology` alone is a better grep. The joins are what a text search cannot fake,
because they are written down nowhere — nothing in a route handler names a table.

```
POST /users  ──HANDLED_BY──►  create_user  ──PERSISTS_TO──►  User  ──MAPS_TO──►  users
   api_ontology                  code_ontology                 data_ontology            table
```

`expand_symbol` on an endpoint returns that whole chain in one call, because an agent
that has just found an endpoint is about to ask what it writes to.

**Two of those joins are facts and one is a lead, and they are not allowed to look
alike.** A route decorator sits on its function in the syntax tree, and
`__tablename__` states a name outright — those are `native`. That a handler *persists*
to a model is inferred from a resolved call, so it is `query`, and the trace says
`derived — the handler calls the model`. An agent that wants only facts can filter;
one that wants a lead can follow it. What it must not do is confuse them.

## Declaration or convention — the tier says which

The same distinction runs through the extractors:

```
m.py::User      table users              tier=native   __tablename__ says so
d.py::Member    inherits models.Model    tier=query    a base class name is a guess
```

A class inheriting something called `Model` is probably a Django model and might be
anything at all. `index_health` reports the split, so an index built mostly from
conventions is visibly a different object from one built from declarations.

## Built once, refreshed by delta

Every file carries a content hash. A second run reads only what changed. On a real
271-file repository, cold:

```
files 271 · symbols 3,470 · edges 25,000+ · 1.8 seconds
```

and then:

```
run 2   indexed 0 · unchanged 271
```

Re-indexing after a day's work costs the few files you touched. An index that re-parsed
everything on every run would have the same flaw as the agent it is meant to fix, one
layer down.

## Calls are resolved by scope, then by name

A parser sees `helper()` and can honestly report only the word. Which declaration that
is takes the whole repository, so resolution happens once, after every file is in.

**Name alone does not survive a real codebase.** On a 271-file repository `run` is
declared twenty-two times and `get` is called from 1,354 places. Matching on the name
left 91% of in-repo calls ambiguous. So the search runs narrowest first:

| | Found by |
|---|---|
| `self.x()` inside a class | that class, then any class in the same file |
| `receiver.x()` where the receiver is an imported module | that module |
| `receiver.x()` where the receiver is anything else | **nothing — left ambiguous** |
| a bare `x()` | the same file, then an imported module, then a unique declaration |

```
resolved 3,612 · ambiguous 3,576 · external 13,404
how: same-file 2,553 · imported 396 · self 303 · receiver 194 · self-in-file 164
```

**An unknown receiver is never resolved.** `config.get("a")` is a dictionary in almost
every file that contains one, and it is not a call to the one class that happens to
declare a `get`. Resolving it on the name being unique is the same guess this refuses
everywhere else — and on a real repository it produced a method with 301 callers where
nine existed.

**An unresolved call says *why*, and the reasons are not interchangeable.**

| | |
|---|---|
| `resolved` | the callee is known |
| `untyped` | the receiver is a local, a parameter or a return value, so which declaration it means is unknown — **not** that the callee is absent |
| `ambiguous` | several same-named functions could be meant |
| `external` | genuinely not declared in this repository |

That distinction is the difference between a useful answer and a wrong one. `external`
is a claim, and it was being made without grounds: both real `store.write(...)` call
sites in this project were reported *not declared in this repository* while
`Store.write` sat in the next file. So "who calls this" answered a confident nothing.

**Read `untyped` before trusting a caller list.** A large count means callers are
missing, not that there are none — which is exactly when a `grep` is the better tool,
and the index should say so rather than let you assume otherwise.

**What is still ambiguous is left bare.** Narrowing the search must not turn a guess
into a claim. A missing edge makes an agent look; a wrong edge makes it confident.

## The optional parser tier

A line pattern can see a declaration and cannot see a call. Without a real parser, a
TypeScript repository indexes as a list of classes with nothing to traverse — and
`blast_radius`, `related_symbols` and `called_by` come back empty, correctly and
uselessly.

```bash
pip install 'skygraph[parsers]'
```

Measured on a real 10,089-file Angular and Java repository, same files both ways:

| | patterns only | with parsers |
|---|---|---|
| symbols | 15,418 | **38,007** |
| edges | 41,415 | **264,442** |
| resolved calls | 16 | **35,232** |
| cold index | 19 s | 39 s |

It is optional because a consumer inherits whatever this depends on, and a parser for
thirty grammars is worth an install without being worth forcing on everyone. Without
it nothing breaks; the graph is thinner and says which languages are thin.

Everything it produces is tier `native` — it is a real parse — and it keeps the
receiver exactly as the Python front end does, so `this.format()` becomes `self.format`
and one set of resolution rules covers every language.

## The optional model tier

Only for files the parsers could not read, only with a key you supply, and never for
anything a parser handled.

```bash
export SKYGRAPH_MODEL_KEY=...         # Anthropic or any OpenAI-compatible endpoint
python3 -m skygraph index /path/to/repo --repo myrepo
```

```json
{"model": {"provider": "openai", "model": "gpt-4o-mini", "used": true,
           "candidates": 2, "attempted": 2, "accepted": 2,
           "failed": 0, "refused_rows": 2, "over_budget": 0}}
```

**Nothing it produces is called a fact.** Every row is tier `model`, so `parsed` is
false and `index_health` counts it apart:

```
parsed 2 · inferred 3 · share 0.4
gap: report.erl — no parser could read this; a model read it (gpt-4o-mini);
                  2 row(s) refused as undeclared
```

Three things hold it in place.

**The ontology is the authority for a model exactly as for a parser.** A reply naming a
kind no ontology declares has that row dropped and counted — not the schema widened,
and not the row admitted because a model sounded sure. An edge from something the same
reply did not declare is a model describing code it was not shown, and goes the same
way.

**It is capped and it reports.** A budget of files per run, a cap on how much of one
file is sent, and counts of attempted, accepted and refused. A failure is never fatal:
the heuristic answer for that file is already written, so an unreachable endpoint costs
you a better answer, not the index.

**A second run asks nothing.** The content hash already decides what gets re-read, so
the most expensive tier is paid for once per version of a file.

It talks to Anthropic or to anything speaking the OpenAI shape — including a local
Ollama or vLLM, which makes the whole tier free:

```bash
export SKYGRAPH_MODEL_KEY=unused
export SKYGRAPH_MODEL_URL=http://localhost:11434/v1/chat/completions
export SKYGRAPH_MODEL=qwen2.5-coder
```

## The parsing tiers

![The pipeline, the three tiers, and what the core guarantees regardless of
language](docs/images/pipeline.svg)

## The design

**One capture vocabulary, three interchangeable front ends.** Every front end emits the
same `Symbol` and `Edge` types. Everything downstream — the writer, the store, the query
layer, the scoping — knows nothing about languages. Adding a language means adding a
front end, not touching the core.

| Tier | How | Today |
|---|---|---|
| **1 · native** | a real parse, full fidelity | Python via `ast`; everything else via tree-sitter, when installed |
| **2 · query** | line patterns — declarations only, never calls | the same languages, when tree-sitter is not installed |
| **3 · model** | optional, needs a key | anything the first two could not read |
| **4 · heuristic** | the floor, marks everything a guess | when there is no key |

**Nothing is ever lost silently.** A construct a tier cannot handle degrades to the tier
below and records *why*, on the file row. `skygraph degraded` lists every one.

A graph that is quietly incomplete produces confident wrong answers. That is worse than
a graph that says loudly it could not read a file, so the engine refuses to be quiet.

**The schema is the authority.** `skygraph/schema.py` declares the kinds and relations
that may exist. A front end emitting anything else raises at construction — the process
stops rather than writing a node nobody declared.

**Scope lives on the row, not on the query.** Every symbol and edge carries its repo and
branch. A query that forgets to filter returns nothing rather than another repository's
code: the failure mode is empty, not wrong.

## Use

```bash
pip install /path/to/skygraph           # or `pip install 'skygraph[parsers]'` for every language
skygraph init /path/to/your/project     # .mcp.json, CLAUDE.md, a session-start hook, first index
```

Then restart Claude Code in the project. That is the whole install; [Connecting
it](docs/connecting.md) has the long way and the Codex block.

From a checkout, without installing:

```bash
git clone https://github.com/arupmmi07/skygraph.git
cd skygraph

python3 -m skygraph index /path/to/a/repo --repo myrepo
python3 -m skygraph search Alpha --repo myrepo
python3 -m skygraph neighbours 'src/a.py::Alpha.run' --repo myrepo
python3 -m skygraph degraded --repo myrepo
```

Indexing itself:

```json
{ "files": 8, "symbols": 61, "edges": 383, "languages": 1,
  "tiers": { "native": 8 }, "degraded": 0 }
```

## As an MCP server

```bash
./skygraph-mcp
```

Fourteen tools, all read-only. There is no write tool of any kind — indexing is a
separate, deliberate act, and an agent that could re-index could also quietly change
what the next question sees.

It negotiates the protocol version rather than asserting one, answers `ping`, and
**never replies to a notification** — a JSON-RPC message with no `id` is not waiting for
an answer, and a host is entitled to drop a server that sends one anyway.

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"expand_symbol",
           "arguments":{"qualified_name":"src/a.py::Alpha.run"}}}
```

## Documentation

| | |
|---|---|
| [Connecting it](docs/connecting.md) | Wiring it into Claude Code, Codex or any MCP host |
| [Architecture](docs/architecture.md) | The pipeline, and where a language plugs in |
| [Adding a language](docs/adding-a-language.md) | Tier 2 in about twenty lines |
| [Contributing](CONTRIBUTING.md) | Running the tests, and what a change needs |


## Status

Python 3.11+, standard library only. **229 tests**, run by CI on 3.11, 3.12 and 3.13.

All five ontologies have extractors, and the optional model tier is wired in.

`index_health` reports per language whether it produces call edges at all, so a thin
graph is visible rather than merely quiet.

YAML is read by a deliberately small reader rather than a dependency: it understands the
shapes manifests take, marks everything it produces tier 2, and raises rather than
half-reading a document that uses anchors, merge keys, tags or block scalars.

## Licence

Apache 2.0.
