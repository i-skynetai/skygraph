# Changelog

## Unreleased

- Typed receivers: a field, parameter or local with a declared type (or built by a
  constructor) types the calls on it, in every language that declares types; a local
  built by a factory follows the factory's declared return type. Java's resolved share
  of in-repository calls on a real monorepo: 17 % → 47 %; Python 53 % → 59 %.
  Symbols carry `returns`; the index schema is version 7 and rebuilds.
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
- Go, Rust, C#, Kotlin, Swift, PHP and Ruby each have a three-file fixture and the same
  golden questions as Python and TypeScript, run in CI. Go methods are `Struct.Method`;
  Ruby `require_relative` is an import; PHP namespaces and PSR-4 root folders resolve;
  a Go package is a scope like a Java package.

## 0.2.0 — 2026-09-27

The trust release: the graph stops answering confidently over a gap.

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
