# Roadmap

Every planned feature has an ID, a status and, once someone takes it, an owner. **This
file is the source of truth for what is being worked on.** Pick from here, and update
the row when you start and when you finish — see [Picking a feature](#picking-a-feature).

## Status

| Status | Means | Who moves it on |
|---|---|---|
| **Proposed** | an idea; the scope is not agreed yet | a maintainer, to Ready or Needs decision |
| **Needs decision** | a design choice must be made first — usually an ontology change | a maintainer, after discussion on the issue |
| **Ready** | scope and acceptance agreed; anyone may pick it | you, when you claim it |
| **In progress** | claimed — the row names the owner and the date | the owner, when the pull request opens |
| **In review** | a pull request is open | a maintainer, when it merges |
| **Done** | merged; the row names the version | — |

Priority: **P0** a correctness bug, fix first · **P1** the next release · **P2** planned ·
**P3** an idea. Size: **S** about a day · **M** a few days · **L** a week or more, and
worth splitting.

## Picking a feature

1. **Choose a `Ready` row.** New here? Take one marked *good first issue*.
2. **Claim it.** Open an issue with the *Claim a feature* template naming the ID, or
   comment on the feature's issue if one exists. A maintainer confirms within a few days.
3. **Mark it `In progress`** in this file — your handle and the date in the Owner
   column — in your first pull request, or in a one-line pull request of its own.
4. **For an L-sized feature, write a design note first**, from
   [the template](docs/features/TEMPLATE.md), and get it agreed on the issue before the
   code.
5. **Open the pull request.** Set the row to `In review`, and meet the acceptance
   criteria below — each one is a test. [Contributing](CONTRIBUTING.md) has what every
   change needs.
6. **On merge,** the row becomes `Done` with the version.

One feature per person at a time. A claim with no visible progress for 21 days goes back
to `Ready`, so nothing stays blocked by a claim nobody is working on. To propose
something new, open an issue with the *Propose a feature*; it gets an ID when accepted.

## Features

### 0.2.0 — first public release: what must ship

The release bar: a fresh clone reaches a working demo with one command, the tests pass
with one command, and nothing the README claims is broken. These rows block the release.

| ID | Feature | Area | P | Size | Status | Owner |
|---|---|---|---|---|---|---|
| SG-001 | [YAML with block scalars and anchors](#sg-001) | deploy | P0 | M | Done — 0.2.0 | @arupmmi07 |
| SG-002 | [Deterministic call resolution](#sg-002) | resolver | P0 | S | Done — 0.2.0 | @arupmmi07 |
| SG-003 | [Safe concurrent indexing](#sg-003) | store | P0 | S | Done — 0.2.0 | @arupmmi07 |
| SG-004 | [`skygraph demo`: see it work in one command](#sg-004) | experience | P0 | S | Done — 0.2.0 | @arupmmi07 |

### 0.3.0 — always fresh

| ID | Feature | Area | P | Size | Status | Owner |
|---|---|---|---|---|---|---|
| SG-010 | [Refresh after the agent edits a file](#sg-010) | freshness | P1 | S | Ready | |
| SG-011 | [Refresh after git checkout, pull, merge and rebase](#sg-011) | freshness | P1 | M | Ready | |
| SG-012 | [Targeted refresh of named files](#sg-012) | freshness | P1 | L | Ready | |
| SG-013 | [Branch-aware index](#sg-013) | freshness | P1 | M | Ready | |
| SG-014 | [Freshness shown in every answer](#sg-014) | freshness | P1 | M | Ready | |
| SG-015 | [Refresh for Codex and other hosts](#sg-015) | freshness | P1 | M | Needs decision | |
| SG-016 | [`skygraph watch`](#sg-016) | freshness | P2 | M | Proposed | |

### 0.4.0 — data models and API contracts

| ID | Feature | Area | P | Size | Status | Owner |
|---|---|---|---|---|---|---|
| SG-020 | [OpenAPI schemas, `$ref` and multi-file specs](#sg-020) | api | P1 | M | Ready | |
| SG-021 | [Join an OpenAPI operation to its handler](#sg-021) | api | P1 | M | Ready | |
| SG-022 | [SQL constraints, ALTER TABLE and views](#sg-022) | data | P1 | M | Ready | |
| SG-023 | [Migrations as schema history](#sg-023) | data | P2 | L | Proposed | |
| SG-024 | [Prisma enums, `@map`, `@relation`, datasource](#sg-024) — *good first issue* | data | P1 | S | Ready | |
| SG-025 | [Which database a service uses](#sg-025) | data | P2 | M | Needs decision | |
| SG-026 | [TypeScript and JavaScript ORMs](#sg-026) | data | P1 | M | Ready | |
| SG-027 | [ORMs in the other languages](#sg-027) | data | P2 | L | Ready | |
| SG-028 | [GraphQL schemas](#sg-028) | api | P2 | M | Ready | |
| SG-029 | [gRPC and protobuf](#sg-029) | api | P2 | M | Ready | |
| SG-030 | [Python routers and URL confs](#sg-030) | api | P1 | M | Ready | |
| SG-031 | [TypeScript and JavaScript endpoints, parsed](#sg-031) | api | P1 | L | Ready | |
| SG-032 | [Endpoints in the other languages](#sg-032) | api | P2 | L | Ready | |

### 0.5.0 — design and documentation

| ID | Feature | Area | P | Size | Status | Owner |
|---|---|---|---|---|---|---|
| SG-040 | [Design diagrams as knowledge](#sg-040) | design | P2 | L | Needs decision | |
| SG-041 | [`diagram_for`: diagrams drawn from the graph](#sg-041) | tools | P2 | M | Ready | |
| SG-042 | [Documentation index](#sg-042) | design | P2 | M | Needs decision | |

### 0.6.0 — reach

| ID | Feature | Area | P | Size | Status | Owner |
|---|---|---|---|---|---|---|
| SG-050 | [Vue, Svelte and Astro components](#sg-050) | languages | P1 | M | Ready | |
| SG-051 | [Angular components, injection and routes](#sg-051) | languages | P2 | M | Proposed | |
| SG-052 | [C and C++](#sg-052) | languages | P2 | L | Ready | |
| SG-053 | [Scala, Dart, Elixir, Lua and shell](#sg-053) | languages | P3 | M | Proposed | |
| SG-054 | [Better resolution where it is thinnest](#sg-054) | resolver | P2 | L | Ready | |
| SG-055 | [Jupyter notebooks](#sg-055) — *good first issue* | languages | P3 | S | Proposed | |
| SG-056 | [Terraform, Helm, Kustomize, CloudFormation](#sg-056) | deploy | P2 | L | Ready | |
| SG-057 | [Jenkins, Azure Pipelines, CircleCI, Bitbucket](#sg-057) — *good first issue* | deploy | P2 | M | Ready | |
| SG-058 | [Application config as declarations](#sg-058) | deploy | P2 | M | Ready | |

### Tools, trust and distribution

| ID | Feature | Area | P | Size | Status | Owner |
|---|---|---|---|---|---|---|
| SG-060 | [`changes_impact`: what a diff affects](#sg-060) | tools | P1 | M | Ready | |
| SG-061 | [Which tests exercise a symbol](#sg-061) | tools | P1 | M | Needs decision | |
| SG-062 | [A public token benchmark](#sg-062) | trust | P1 | M | Ready | |
| SG-063 | [Search by description](#sg-063) | tools | P3 | L | Proposed | |
| SG-064 | [Cross-repository resolution](#sg-064) | resolver | P3 | L | Proposed | |
| SG-070 | [Publish to PyPI](#sg-070) | distribution | P1 | S | Needs decision | |
| SG-071 | [CI on macOS and Windows](#sg-071) | distribution | P2 | M | Ready | |
| SG-072 | [A Claude Code plugin](#sg-072) | distribution | P2 | M | Proposed | |
| SG-073 | [100,000-file repositories](#sg-073) | store | P2 | L | Proposed | |
| SG-074 | [Serving one index to a team](#sg-074) | distribution | P3 | L | Proposed | |

## Details

Each entry says what is wrong or missing today, what done looks like, and where in the
code it starts. Every acceptance line is a test.

### Correctness

<a id="sg-001"></a>**SG-001 — YAML with block scalars and anchors.** The built-in YAML
reader refuses block scalars (`run: |`) and anchors (`&x`, `<<: *x`), which almost every
GitHub Actions, GitLab CI and Kubernetes file uses — skygraph cannot read its own
workflows. Worse, a refused file is recorded as parsed with nothing in it, not as
degraded. *Done when:* `.github/workflows/*.yml` in this repository yields a `Pipeline`
and its `Stage`s; a GitLab file using `<<: *defaults` yields its jobs; a file the reader
still refuses is marked `degraded` with the reason. *Starts in:* `skygraph/miniyaml.py`,
`frontends._deploy_yaml`.

<a id="sg-002"></a>**SG-002 — Deterministic call resolution.** The same unchanged
10,000-file repository resolves between 38,728 and 38,779 calls depending on Python's
hash seed, so a refresh that changed nothing can change answers. *Done when:* two runs
with different `PYTHONHASHSEED` values produce identical edges, checked by a test.
*Starts in:* `Store.resolve_calls` — iteration over sets where the first match wins.

<a id="sg-003"></a>**SG-003 — Safe concurrent indexing.** Once hooks refresh the index,
a session hook, an edit hook and a git hook can run at the same moment. The database
uses no write-ahead log and indexing takes no lock. *Done when:* the store opens in WAL
mode; a second `skygraph index` on the same repository waits for, or merges into, the
running one instead of failing; a server keeps answering while an index is written.
*Starts in:* `Store.__init__`, `indexer.index`.

<a id="sg-004"></a>**SG-004 — `skygraph demo`: see it work in one command.** Today, seeing
skygraph answer anything needs your own project and an agent wired to it. Someone
evaluating it should not need either. *Done when:* `skygraph demo` indexes a small
sample project shipped inside the package — Python and TypeScript, with an endpoint, an
entity and a call across files — into a throwaway index, asks the questions an agent
asks (where is it, what calls it, what breaks, which table an endpoint writes), and
prints each answer beside what reading the files would have cost; it needs no network
beyond the one-time parser download, and it leaves nothing behind.

### Always fresh

See [Keeping the index fresh](docs/design/index-refresh.md) for the design these share.

<a id="sg-010"></a>**SG-010 — Refresh after the agent edits a file.** Today the index is
refreshed when a session starts, or by hand. *Done when:* `skygraph init` also installs
a Claude Code `PostToolUse` hook for the file-editing tools that refreshes the edited
file in the background, and the next tool call sees the change. *Depends on:* SG-003,
SG-012.

<a id="sg-011"></a>**SG-011 — Refresh after git checkout, pull, merge and rebase.** A
branch switch or a pull changes many files at once, outside any agent. *Done when:*
`skygraph init --git-hooks` installs `post-checkout`, `post-merge` and `post-rewrite`
hooks that run a delta index in the background without slowing git; existing hooks,
`core.hooksPath` and husky are preserved, not overwritten; it works the same with GitHub,
GitLab or any remote, because the hooks are local. *Depends on:* SG-003.

<a id="sg-012"></a>**SG-012 — Targeted refresh of named files.** A refresh with nothing
changed still walks and hashes every file and re-resolves every call: 5.6 s on a
10,000-file repository, most of it resolution. *Done when:* `skygraph index --paths a.ts
b.ts` and `--changed-since <git ref>` re-read only those files and re-resolve only the
calls that can have changed, in under a second on that repository.

<a id="sg-013"></a>**SG-013 — Branch-aware index.** Every index row carries a branch, but
the indexer never asks git — everything is filed under `main`. *Decided (2026-09-30):*
one index mirrors the working tree — a checkout re-reads only the files that differ —
and records the branch and commit it reflects; no copy per branch. *Done when:*
`index_health` reports the branch and commit the index reflects; after `git checkout`
of another branch and a refresh, answers match that branch's files and the reported
branch changes; a repository that is not a git checkout still indexes, with no branch.

<a id="sg-014"></a>**SG-014 — Freshness shown in every answer.** Only `read_source`
notices that a file changed since it was indexed. *Done when:* any tool's row from a
changed file carries `stale: true`, and `index_health` reports how many files changed
since the last index.

<a id="sg-015"></a>**SG-015 — Refresh for Codex and other hosts.** Hosts differ in what
hooks they offer. *Decision needed:* which host mechanisms to use, and whether a host
with none relies on git hooks (SG-011) and `skygraph watch` (SG-016).

<a id="sg-016"></a>**SG-016 — `skygraph watch`.** An opt-in watcher, standard library
only, that refreshes changed files as they are saved — for editors and hosts with no
hooks.

### Data models and API contracts

<a id="sg-020"></a>**SG-020 — OpenAPI schemas, `$ref` and multi-file specs.** A spec
yields its service, endpoints, operation IDs and parameters, but not request or response
bodies: the `Payload` kind and the `ACCEPTS` and `RETURNS` relations are declared and
never produced. *Done when:* `components/schemas` become `Payload`s joined to the
operations that accept and return them; `$ref` across files resolves; OpenAPI 3.1 works.

<a id="sg-021"></a>**SG-021 — Join an OpenAPI operation to its handler.** An operation
ID links only to a symbol inside the spec file. *Done when:* an operation joins the
code endpoint with the same method and path, or the function named by its operation ID,
as a lead (`query` tier); `expand_symbol` on the operation reaches the handler.

<a id="sg-022"></a>**SG-022 — SQL constraints, ALTER TABLE and views.** DDL yields
tables, typed columns, indexes and inline `REFERENCES`. *Done when:* table-level
`FOREIGN KEY … REFERENCES`, `ALTER TABLE … ADD COLUMN / ADD CONSTRAINT`, `CREATE VIEW`
and the common PostgreSQL, MySQL and SQL Server types are read.

<a id="sg-023"></a>**SG-023 — Migrations as schema history.** Flyway and plain SQL
migrations are read one file at a time; Liquibase, Alembic, Django, Rails and Prisma
migrations are not read as schema at all. *Done when:* the schema a migration folder
produces, applied in order, is the `data_ontology` for that database.

<a id="sg-024"></a>**SG-024 — Prisma enums, `@map`, `@relation`, datasource.** Models,
fields, relations by type and `@@map` are read. *Done when:* `enum` blocks become
`Enum`s, field-level `@map` renames the column, `@relation(fields, references)` gives
the key, and the datasource provider is recorded.

<a id="sg-025"></a>**SG-025 — Which database a service uses.** Nothing says "this
service talks to PostgreSQL". *Decision needed:* a `Datastore` kind and a link to it,
fed by Prisma datasources, Compose images, connection-string variables and Spring
datasource settings.

<a id="sg-026"></a>**SG-026 — TypeScript and JavaScript ORMs.** TypeORM, Sequelize,
Mongoose, Drizzle and MikroORM models are read as code only. *Done when:* each yields
`Entity` and `Field` rows and the table they map to, with a fixture per ORM.

<a id="sg-027"></a>**SG-027 — ORMs in the other languages.** Entity Framework Core,
GORM, ActiveRecord (`schema.rb`), Eloquent, Exposed and Room, Diesel. Split per ORM when
claimed; each is an S or M.

<a id="sg-028"></a>**SG-028 — GraphQL schemas.** `.graphql` files are not read. *Done
when:* types, queries, mutations and subscriptions become API rows, and resolvers join
them where a framework makes that explicit.

<a id="sg-029"></a>**SG-029 — gRPC and protobuf.** `.proto` files are not read. *Done
when:* services, RPCs and messages become API rows, with request and response messages
as `Payload`s.

<a id="sg-030"></a>**SG-030 — Python routers and URL confs.** FastAPI and Flask route
decorators are read, but an `APIRouter(prefix=…)` or `include_router`, a Blueprint's
`url_prefix`, and Django `urls.py` and REST framework routers are not. *Done when:* the
full path of each route is right, with a fixture per framework.

<a id="sg-031"></a>**SG-031 — TypeScript and JavaScript endpoints, parsed.** Express
routes are found by a line pattern; NestJS, Next.js, Fastify and Hono are not found.
*Done when:* routes come from the tree-sitter parse, with their handlers joined.

<a id="sg-032"></a>**SG-032 — Endpoints in the other languages.** ASP.NET, Go
(`net/http`, Gin, Echo, chi), Rails routes, Laravel, Ktor, Micronaut and Quarkus, Axum
and Actix, Vapor. Split per framework when claimed.

### Design and documentation

<a id="sg-040"></a>**SG-040 — Design diagrams as knowledge.** Markdown, Mermaid and
PlantUML files are skipped as not source, and draw.io files fall to the heuristic floor,
so the architecture a team drew is invisible to the agent. *Decision needed:* a design
ontology (`Component`, `Relationship`) read from Mermaid (in `.mmd` files and Markdown
fences), PlantUML, draw.io and Structurizr, joined to code modules by name as a lead.

<a id="sg-041"></a>**SG-041 — `diagram_for`.** A read-only tool that returns Mermaid for
a symbol's callers and callees, a module's dependencies, or an endpoint's chain through
handler and entity to table — drawn from the graph, so it is always current.

<a id="sg-042"></a>**SG-042 — Documentation index.** READMEs and decision records are
not indexed. *Decision needed:* a documentation ontology — headings, and which symbols
each document names — so an agent can find the decision record about the code it is
changing.

### Reach

<a id="sg-050"></a>**SG-050 — Vue, Svelte and Astro components.** `.vue` files are
skipped as not source, so a Vue project's components are invisible; `.svelte` and
`.astro` fall to the heuristic floor. *Done when:* the script block of each is parsed as
TypeScript or JavaScript, with a fixture.

<a id="sg-051"></a>**SG-051 — Angular components, injection and routes.** Angular
classes are parsed as TypeScript; their roles are not. Components, injectables and
what they inject, and the route table.

<a id="sg-052"></a>**SG-052 — C and C++.** The largest language family not supported.
A query file, the extension entry and a benchmark fixture; headers resolve by include
path.

<a id="sg-053"></a>**SG-053 — Scala, Dart, Elixir, Lua and shell.** One per claim; see
[Adding a language](docs/adding-a-language.md).

<a id="sg-054"></a>**SG-054 — Better resolution where it is thinnest.** Of in-repository
calls, Rust resolves 29 %, Ruby 24 %, and Swift's remaining ambiguity is overloads.
Traits and generic impls, `Foo.new` in Ruby, overloads by argument count, and declared
return types across imports in TypeScript and Python. Split per language.

<a id="sg-055"></a>**SG-055 — Jupyter notebooks.** Code cells of `.ipynb` files, parsed
as Python, with the cell as the line reference.

<a id="sg-056"></a>**SG-056 — Terraform, Helm, Kustomize, CloudFormation.** None are
read. Resources and modules; Helm charts and values (the templates are not YAML);
Kustomize overlays; CloudFormation and SAM. Split per tool.

<a id="sg-057"></a>**SG-057 — Jenkins, Azure Pipelines, CircleCI, Bitbucket.** Only
GitHub Actions and GitLab CI are read. Each pipeline and its stages, one fixture each.

<a id="sg-058"></a>**SG-058 — Application config as declarations.** Environment
variables are found where code reads them, but `.env.example`, Spring
`application.yml` and `application.properties`, and Django settings do not count as
declaring them, so they are reported as read but undeclared.

### Tools, trust and distribution

<a id="sg-060"></a>**SG-060 — `changes_impact`.** Given a git diff or a list of files:
the symbols it changes, their callers, the endpoints above them and the tests that reach
them — the review question, in one call.

<a id="sg-061"></a>**SG-061 — Which tests exercise a symbol.** *Decision needed:* a
`TESTED_BY` link derived from calls out of test files, and a `tests_for` tool.

<a id="sg-062"></a>**SG-062 — A public token benchmark.** A reproducible measurement, on
pinned open-source repositories, of the bytes an agent reads with and without the
graph for the same questions, run in CI, so the saving is a number anyone can check.

<a id="sg-063"></a>**SG-063 — Search by description.** Find a symbol by what it does,
using local embeddings or the optional model tier.

<a id="sg-064"></a>**SG-064 — Cross-repository resolution.** An import that names a
symbol in another indexed repository resolves to it.

<a id="sg-070"></a>**SG-070 — Publish to PyPI.** `pip install skygraph`, released by
trusted publishing from the release workflow. A maintainer decision.

<a id="sg-071"></a>**SG-071 — CI on macOS and Windows.** CI runs on Linux only; the
paths, the launcher and `init` have not been run on Windows.

<a id="sg-072"></a>**SG-072 — A Claude Code plugin.** The server, the hooks and the
instruction in one install.

<a id="sg-073"></a>**SG-073 — 100,000-file repositories.** Measure and bound index time,
size and memory; tune SQLite.

<a id="sg-074"></a>**SG-074 — Serving one index to a team.** HTTP, authentication, and
scope enforced by who is asking — see [Hosting it for other
people](docs/connecting.md#hosting-it-for-other-people).
