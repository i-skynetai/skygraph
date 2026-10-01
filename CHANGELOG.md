# Changelog

## 0.2.0 — 2026-09-29

The first public release — the trust release: the graph stops answering confidently
over a gap, and says what it cannot see.

- Ready to install from GitHub: `pipx install "git+https://github.com/arupmmi07/skygraph.git@v0.2.0"`.
  The README now leads with install, a quick start, the fourteen tools, the languages
  with their measured call resolution, privacy and network use, troubleshooting and
  uninstall. A code of conduct joins the contributor guide.
- Call resolution is the same on every run (SG-002). A barrel was walked only 64 files
  deep, in set order, so a shared library re-exporting more than that resolved
  differently with each Python hash seed: 38,728 to 38,779 calls on one unchanged
  monorepo. Walked completely and in path order, it is 38,909 every time.
- CI and deployment YAML is read, not dropped (SG-001). Block scalars (`run: |`),
  anchors, aliases, merge keys, nested flow collections, wrapped quoted strings and
  tags are understood; on 141 real files the reader returns what PyYAML returns. It
  used to refuse them — skygraph could not read its own workflows — and the refused
  file was recorded as parsed and empty; what it still refuses is now marked
  degraded with the reason. Seven open-source projects: 12 pipelines found, was 7.
  A pipeline is named by its file, so one named like its job no longer vanishes, and
  GitLab's hidden `.template` jobs are not stages.
- Refreshes that overlap are safe (SG-003). One index takes one writer at a time: a
  second run waits for the first and then reads only what is still out of date —
  two overlapping runs used to re-read the same files and interleave their writes.
  The store uses SQLite's write-ahead log, so a server keeps answering while an
  index is written; its sidecar files are never indexed, and ones left behind by a
  deleted index are cleared instead of failing the next open.
- `skygraph --version` and `skygraph-mcp --version`.
- `skygraph init` writes every command by absolute path, taken from the environment
  that ran it, and quotes paths in the session hook: a host started from a dock has
  no shell PATH, and a project under "My Projects" was split in two.
- JavaScript has its own three-file benchmark fixture; all eleven languages now answer
  the same golden questions in CI.
- Pushing a `v*` tag builds the wheel and source archive and opens a draft GitHub
  release with this changelog's section as notes. CI covers Python 3.11 to 3.14, and
  the source archive carries the tests and fixtures. Licence metadata is SPDX.
- Typed receivers: a field, parameter or local with a declared type (or built by a
  constructor) types the calls on it, in every language that declares types; a local
  built by a factory follows the factory's declared return type. Java's resolved share
  of in-repository calls on a real monorepo: 17 % → 47 %; Python 53 % → 59 %.
  Symbols carry `returns`; the index schema is version 7 and rebuilds.
- The tree-sitter parsers are a dependency, not the `[parsers]` extra (kept as an alias):
  an install that lacked them indexed every language but Python without calls. The pack
  downloads its grammars once, on first use. A grammar that will not load is tried once
  per language, not once per file, and each file's row says why it fell to the pattern
  tier.
- A missing tool argument is named once, not wrapped in itself.
- An index written by a newer skygraph is refused, not rebuilt. A server still running
  older code keeps the handshake and the tool list, answers every tool call with the two
  schema numbers and "restart", and leaves the file alone. Found when a refreshed index
  came back empty: the old server had "rebuilt" it to nothing.
- Barrels are followed: `export … from` in TypeScript and the imports of a Python
  `__init__.py` are `RE_EXPORTS` edges, and a name imported through one is bound to the
  file that declares it. A call on a destructured or untyped local is `untyped`, not
  `ambiguous`.
- Java frameworks: JAX-RS (`@Path`, `@GET`) and Spring (`@GetMapping`, `@RequestMapping`)
  endpoints joined to their handlers, with constant-built routes kept as placeholders;
  JPA `@Entity` classes with tables, fields and references. Endpoint → handler → entity
  traces now exist for Java.
- Manifests are knowledge: `package.json`, `pom.xml`, `build.gradle`, `requirements*.txt`,
  `pyproject.toml`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json` yield `Dependency`
  symbols and `DEPENDS_ON` edges in the deploy ontology instead of "unknown" noise.
- Modules and Python endpoints carry an end line, so `read_source` on either is exact.
- `skygraph forget --repo X` drops a repository from the index.
- `find_symbols` answers an exact name with that row alone unless `limit` is passed:
  a unique-name lookup fell from 2.8 KB to under 0.5 KB.
- The interface walk: `extends` and `implements` are `INHERITS` and `IMPLEMENTS` edges in
  every grammar (Rust `impl Trait for Type` included), resolved to classes. Callers of
  `FooService.find` are reported as callers of `FooServiceImpl.find`, marked `via` the
  interface; `expand_symbol` shows `overrides` and `implemented_by`; `blast_radius`
  follows dispatch. On the Java monorepo, 28 implementation methods that had no
  caller now have theirs, 6 of 6 sampled confirmed by the declarations.
- A call with no enclosing callable — a `describe(() => …)` at the top of a test file,
  `app.include_router(...)` at the top of a module — belongs to the module, not to
  nothing. A Go import binds its package name, and `svc.NewService()` reaches the
  package's function and, through its return type, the struct's methods. Python
  `import x as y` and `from x import A as B` are followed.
- One call edge per (caller, callee, file): `expect(...)` fifty times in one callback
  was fifty rows. The monorepo's call edges fell from 494k to 190k, its index from
  498 MB to 286 MB, and `expand_symbol` no longer lists the same callee three times.
- Swift `extension T` and Rust `impl T` blocks add members to a type declared elsewhere
  instead of declaring a second `T`; a library's `Session`, "declared five times", is
  one type again. Templates (`.erb`, `.haml`, `.vue`, …) and IDE project files are not
  source and no longer count as degraded.
- Go, Rust, C#, Kotlin, Swift, PHP and Ruby each have a three-file fixture and the same
  golden questions as Python and TypeScript, run in CI. Go methods are `Struct.Method`;
  Ruby `require_relative` is an import; PHP namespaces and PSR-4 root folders resolve;
  a Go package is a scope like a Java package.

### Earlier in 0.2.0

- `read_source` compares the file's digest with the indexed one and never claims an
  exact range for a changed file; the server reopens its database when the file is
  replaced underneath it.
- A call on a receiver the parser cannot type is `untyped`, not `external`; a bare call
  never resolves to a method; TypeScript generic calls keep their callee; every
  tree-sitter grammar keeps the receiver.
- Imports resolve as paths — relative specifiers, `tsconfig` aliases, dotted names with
  the closest file winning a tie — so same-named files no longer share importers.
- A Java package is one scope across `src/main` and `src/test`; a bare call inside a
  Java class is `this`; `.tsx` is parsed with the tsx grammar.
- A language is a query file: `queries/<language>.scm`, five captures, one interpreter.
- `find_symbols` ranks the exact name first and returns ten rows; list rows carry no
  repeated fields; Python declarations carry their docstring's first line.
- `context_for`, the fourteenth tool: one call to start on a symbol, under a byte budget.
- `skygraph init` wires a project to Claude Code and Codex and installs a session-start
  hook that keeps the index no older than the session.
- A golden-question benchmark with hand-verified answers and byte ceilings runs in CI.
- `pyproject.toml`; `skygraph` and `skygraph-mcp` console scripts; query files as
  package data.

## 0.1.0

Five ontologies, Python via `ast`, pattern tier for ten languages, optional model tier,
thirteen read-only MCP tools over stdio, delta re-index.
