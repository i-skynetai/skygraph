# Reference

What skygraph can answer, what it reads, what its answers mean, and where it stops.

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
| Python | built-in `ast` | a 1,720-file Python service | 67 % |
| TypeScript, TSX | tree-sitter | a 10,089-file Angular and Java monorepo | 72 % |
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

## Limits

Stated plainly, so nothing here is a surprise:

- **Call resolution is partial.** Between 24 % (Ruby) and 74 % (Java) of in-repository
  calls resolve to one declaration, depending on the language — see the table above.
  The rest are marked `untyped` or `ambiguous`, never guessed, and the agent is told to
  read the file for those.
- **Refresh is automatic only at session start.** Edits made during a session, and
  `git checkout` or `pull`, are picked up at the next session or by `skygraph index`.
  Refreshing on every edit and git operation is the next release.
- **Not read yet:** Helm templates, Terraform, GraphQL and protobuf schemas, ORMs outside
  Python and Java, design diagrams, and Vue single-file components. Each is a roadmap
  item.
- **One machine, one user.** There is no cross-repository resolution and no shared
  server for a team.
- **The parsers download once,** about 22–26 MB from their GitHub release, the first
  time a language needs one.
- **Tested on macOS and Linux;** Windows is untested.
