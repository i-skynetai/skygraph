# Connecting skygraph to Claude Code or Codex

Two steps, and the second is a config file. Index a project, then tell the host where
the server is.

## The short way

```bash
pip install skygraph            # or: pip install /path/to/checkout
skygraph init /path/to/your/project
```

`init` writes four things and indexes once:

| Written | What it does |
|---|---|
| `.mcp.json` in the project | tells Claude Code how to start the server, scoped to this repository (`--repo`) |
| `CLAUDE.md` (and `AGENTS.md` if present) | the paragraph that makes the agent reach for the graph before reading files, and the fallback rule for when the graph says it is unsure |
| `.claude/settings.json` | a `SessionStart` hook: a delta index in seconds, and one line into the agent's context saying what changed and what is untyped (`--no-hook` to skip) |
| Codex block | printed; `--codex` writes it into `~/.codex/config.toml` |

Then restart Claude Code in the project and ask it to run `list_repos`. Running `init`
again is safe: everything it writes is merged or replaced, never duplicated.

The rest of this page is the long way, for hosts and setups `init` does not cover.

## 1. Index the project

```bash
python3 -m skygraph index /path/to/your/project --repo myproject
```

The index lands in `~/.skygraph/index.db` by default — one store, so
`list_repos` has something to list. Index as many projects as you like into it.

Re-run the same command whenever you want it current. A second run reads only the files
whose contents changed, so it costs seconds, not minutes:

```
indexed 3 · unchanged 1,847 · removed 1
```

There is no watcher and no daemon. Indexing is a deliberate act, and a background
process quietly rewriting what the next question sees is not something to add lightly.

### Optionally, install the parsers

Without them only Python produces call edges, so `blast_radius`, `related_symbols` and
`called_by` are empty for every other language. With them, every language is really
parsed.

```bash
cd /path/to/skygraph
python3 -m venv .venv
.venv/bin/pip install tree-sitter tree-sitter-language-pack
```

**Put the virtual environment beside `skygraph-mcp`, not in your system Python.** The
launcher looks for `./.venv` next to itself and re-executes with that interpreter, so
the host does not need to know which Python to run and nothing is installed globally.
About 18 MB. Delete `.venv` to undo it.

Re-index after installing them: the parsers see things the patterns could not, and a
file whose content hash has not moved is not re-read, so use `--full` once.

### Optionally, let a model read what the parsers could not

Skygraph indexes without this. It only matters if your repository holds languages the
parsers have no pattern for — Terraform, Erlang, GraphQL schemas and the like.

```bash
export SKYGRAPH_MODEL_KEY=...     # Anthropic, or any OpenAI-compatible endpoint
python3 -m skygraph index /path/to/your/project --repo myproject
```

The run says what it cost and what it refused. Everything a model produced is tier
`model`, so `index_health` counts it apart from what was actually read — ask for that
before trusting an answer that depends on one of those files.

A local endpoint works and makes the tier free:

```bash
export SKYGRAPH_MODEL_KEY=unused
export SKYGRAPH_MODEL_URL=http://localhost:11434/v1/chat/completions
export SKYGRAPH_MODEL=qwen2.5-coder
```

## 2. Point the host at it

### Claude Code

Point it at `skygraph-mcp`, by absolute path:

```json
{
  "mcpServers": {
    "skygraph": {
      "type": "stdio",
      "command": "/absolute/path/to/skygraph/skygraph-mcp",
      "args": []
    }
  }
}
```

in `~/.claude.json`. Or:

```bash
claude mcp add skygraph -- /absolute/path/to/skygraph/skygraph-mcp
```

The tools then appear as `mcp__skygraph__find_symbols` and so on.

**Use `skygraph-mcp`, not `python3 -m skygraph serve`.** A host does not promise a
server any particular working directory, so the module form starts, fails to import
itself and dies before writing a byte. The host reports that as *connection closed*,
with nothing in it to say the real reason was an import. The launcher puts its own
directory on `sys.path`, so it needs no `cwd`, no `PYTHONPATH` and nothing on `PATH`.

**Include `"type": "stdio"`.** Claude Code distinguishes stdio servers from HTTP ones by
that field.

### Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.skygraph]
command = "/absolute/path/to/skygraph/skygraph-mcp"
args = []
```

### Anything else that speaks MCP

`skygraph-mcp` is a stdio MCP server. It negotiates the protocol version, answers
`ping`, and never replies to a notification. Any compliant host will do.

## Re-index after the tree changes

The index records a content hash per file, and `read_source` compares it. A file that
has moved on since it was indexed is reported as `stale: true` and the line range stops
claiming to be exact — so an answer against a changed file says so instead of pointing
confidently at the wrong function.

The server also notices when `skygraph index` replaces the database underneath it and
reopens. Without that it would keep answering from the deleted file, with yesterday's
line numbers, and look like it was working.

Neither is a substitute for re-indexing. Both exist so that not doing so is visible.

## 3. Check the host can see it

Ask the agent to run `list_repos`. It should come back with what you indexed. If
it comes back empty, the server is running but the store is elsewhere — pass
`["--db", "/path/to/index.db"]` as `args`.

If the host reports **connection closed**, run the command yourself. The launcher prints
any import or startup error to stderr, which the host swallows:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | /path/to/skygraph-mcp
```

## What to tell the agent

The tools are discoverable, but one instruction earns its place in a `CLAUDE.md` or
`AGENTS.md`, because it is the habit that saves the tokens:

```markdown
This project is indexed in skygraph. Before reading files to build context, use the
skygraph tools: `find_symbols` to locate, `expand_symbol` or `related_symbols`
to understand the surroundings, and `read_source` only when you need the actual code.
Run `index_health` if an answer depends on the index being complete.
```

Without that, a host will often reach for its own file-reading tools out of habit, which
is the behaviour this exists to replace.

## Hosting it for other people

The same server behind HTTP serves a team from one index, which is worth doing when the
repository is large enough that everyone indexing it separately is wasteful. Two things
change and neither is optional:

- **Scope becomes a boundary, not a filter.** Locally, `repo` keeps one project's
  answers out of another's. Shared, it is the difference between two people's code, and
  it needs to be enforced by who is asking rather than by what they passed.
- **The index is a copy of source.** Structure, not text — `read_source` reads from disk
  — but symbol names leak design, and a shared index is a shared disclosure.

Neither is built. The server is stdio and local, and saying it hosts a team today would
be the kind of claim this project is otherwise careful not to make.
