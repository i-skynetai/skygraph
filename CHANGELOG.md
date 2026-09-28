# Changelog

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
