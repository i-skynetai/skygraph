# Connecting skygraph to Claude Code or Codex

Two steps, and the second is a config file: index a project, then tell the host where
the server is. `skygraph init` does both; this page is for when you want to do them by
hand, run from a checkout, or connect a host `init` does not know.

## The short way

```bash
pipx install "git+https://github.com/i-skynetai/skygraph.git@v0.2.0"
skygraph init /path/to/your/project
```

`init` writes four things and indexes once:

| Written | What it does |
|---|---|
| `.mcp.json` in the project | tells Claude Code how to start the server, scoped to this repository (`--repo`) |
| `CLAUDE.md` (and `AGENTS.md` if present, or with `--codex`) | the paragraph that makes the agent reach for the graph before reading files, and the fallback rule for when the graph says it is unsure |
| `.claude/settings.json` | a `SessionStart` hook: a delta index in seconds, and one line into the agent's context saying what changed and what is untyped (`--no-hook` to skip) |
| Codex block | printed; `--codex` writes it into `~/.codex/config.toml` |

When skygraph is on PATH, the two project files name its commands with no path from your
machine, so they can be committed; the hook refreshes the folder the index recorded for
the repository. Otherwise they use absolute paths from the environment that ran `init`,
and `init` says the files are for this machine only. The Codex block always uses the
absolute path: it lives in your own config, so it need not depend on PATH.

Then restart Claude Code in the project and ask it to run `list_repos`. Running `init`
again is safe: everything it writes is merged or replaced, never duplicated.

The rest of this page is the long way.

## 1. Index the project

```bash
skygraph index /path/to/your/project --repo myproject
```

The index lands in `~/.skygraph/index.db` by default — one store, so `list_repos` has
something to list. Index as many projects as you like into it; `--db` picks another
file.

Re-run the same command whenever you want it current. A second run reads only the files
whose contents changed, so it costs seconds, not minutes. With `--summary` it prints the
one line the session hook shows the agent:

```
skygraph: skygraph — 58 files (7 re-read, 0 removed), 756 symbols; calls resolved 897, untyped 11%; 0 degraded.
```

There is no watcher and no daemon. Indexing is a deliberate act — or the session hook —
and a background process quietly rewriting what the next question sees is not something
to add lightly.

### The parsers

`pip install skygraph` brings them. The first index that needs one downloads the parser
bundle for your platform from the pack's GitHub release — about 22–26 MB, about 50 MB
on disk once unpacked — into the user cache folder, once per pack version. Offline,
each file of that language falls to the pattern tier and its row says why; run
`skygraph index … --full` once you are online.

### Running from a checkout

```bash
git clone https://github.com/i-skynetai/skygraph.git
cd skygraph
python3 -m venv .venv
.venv/bin/pip install "tree-sitter>=0.23" "tree-sitter-language-pack>=1.20,<2"
./skygraph-mcp --version
```

**Put the virtual environment beside `skygraph-mcp`, not in your system Python.** The
launcher looks for `./.venv` next to itself and re-executes with that interpreter, so
the host does not need to know which Python to run and nothing is installed globally.
Delete `.venv` to undo it. Without the parsers a checkout still works: Python is parsed,
and every other language is read by pattern — declarations only, no calls.

From the checkout, `python3 -m skygraph <command>` runs the same commands as `skygraph`,
and `./skygraph-mcp --index /path/to/project --repo myproject` runs a delta index.

### Optionally, let a model read what the parsers could not

Skygraph indexes without this. It only matters if your repository holds languages the
parsers have no pattern for — Terraform, Erlang, GraphQL schemas and the like.

```bash
export SKYGRAPH_MODEL_KEY=...     # Anthropic, or any OpenAI-compatible endpoint
skygraph index /path/to/your/project --repo myproject
```

Only files no parser could read are sent, never more than the budget
(`--model-budget`), and the key is never written into the index or the report. The run
says what it cost and what it refused. Everything a model produced is tier `model`, so
`index_health` counts it apart from what was actually read — ask for that before
trusting an answer that depends on one of those files.

A local endpoint keeps the files on your machine and makes the tier free:

```bash
export SKYGRAPH_MODEL_KEY=unused
export SKYGRAPH_MODEL_URL=http://localhost:11434/v1/chat/completions
export SKYGRAPH_MODEL=qwen2.5-coder
```

## 2. Point the host at it

`command -v skygraph-mcp` prints the server's absolute path for an install; for a
checkout it is `/path/to/skygraph/skygraph-mcp`.

### Claude Code

In the project's `.mcp.json`:

```json
{
  "mcpServers": {
    "skygraph": {
      "type": "stdio",
      "command": "/absolute/path/to/skygraph-mcp",
      "args": ["--repo", "myproject"]
    }
  }
}
```

Or:

```bash
claude mcp add skygraph -- /absolute/path/to/skygraph-mcp --repo myproject
```

The tools then appear as `mcp__skygraph__find_symbols` and so on. `--repo` makes a
bare `find_symbols` search this project rather than every repository in the index.

**Use `skygraph-mcp`, not `python3 -m skygraph serve`.** A host does not promise a
server any particular working directory, so the module form can start, fail to import
itself and die before writing a byte. The host reports that as *connection closed*,
with nothing in it to say the real reason was an import. The launcher needs no `cwd`,
no `PYTHONPATH` and nothing on `PATH`.

**Include `"type": "stdio"`.** Claude Code distinguishes stdio servers from HTTP ones by
that field.

### Codex

`~/.codex/config.toml`, or `.codex/config.toml` in the project:

```toml
[mcp_servers.skygraph]
command = "/absolute/path/to/skygraph-mcp"
args = ["--repo", "myproject"]
```

### Anything else that speaks MCP

`skygraph-mcp` is a stdio MCP server. It negotiates the protocol version, answers
`ping`, and never replies to a notification. Any compliant host will do.

## 3. Check the host can see it

Ask the agent to run `list_repos`. It should come back with what you indexed. If it
comes back empty, the server is running but reading another index — pass the same
`--db` to the server as to `skygraph index`.

If the host reports **connection closed**, run the command yourself. The server prints
any import or startup error to stderr, which the host swallows:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | /absolute/path/to/skygraph-mcp
```

## What to tell the agent

The tools are discoverable, but one instruction earns its place in a `CLAUDE.md` or
`AGENTS.md`, because it is the habit that saves the tokens. `init` writes this one:

```markdown
## Skygraph

This project is indexed in skygraph. Before reading files to build context, use its
tools: `find_symbols` to locate, `context_for` or `expand_symbol` to understand a
symbol and its surroundings, `outline_file` for a file's shape, and `read_source` only
when you need the actual code. Run `index_health` if an answer depends on the index
being complete.

If a skygraph answer is empty, marked `stale`, `untyped` or `ambiguous`, or
`index_health` shows the file's language is not traversable, read the file directly.
Skygraph narrows what to read; it does not replace reading when it says it is unsure.
```

Without it, a host will often reach for its own file-reading tools out of habit, which
is the behaviour this exists to replace.

## Removing a repository

```bash
skygraph forget --repo myproject
```

drops it from the index; the others are untouched.

## Re-index after the tree changes

The index records a content hash per file, and `read_source` compares it. A file that
has moved on since it was indexed is reported as `stale: true` and the line range stops
claiming to be exact — so an answer against a changed file says so instead of pointing
confidently at the wrong function.

The server also notices when `skygraph index` replaces the database underneath it and
reopens. Without that it would keep answering from the deleted file, with yesterday's
line numbers, and look like it was working.

Neither is a substitute for re-indexing. Both exist so that not doing so is visible.

## After upgrading skygraph

```bash
pipx install --force "git+https://github.com/i-skynetai/skygraph.git@<new tag>"
```

An install pinned to a tag stays on that tag, so name the new one.

Then restart the host, or reopen the session, so it starts a server from the new code.
A server started before the upgrade keeps the old code in memory; when the index is
rebuilt under it by the new code, it refuses to serve it and says so on every tool
call — the two schema numbers and the word "restart" — rather than answering from an
index it cannot read, and rather than rebuilding it. An index built by an older version
is rebuilt on the next `skygraph index`, and the report says `rebuilt`.

## Hosting it for other people

The same server behind HTTP could serve a team from one index, which is worth doing when
the repository is large enough that everyone indexing it separately is wasteful. Two
things change and neither is optional:

- **Scope becomes a boundary, not a filter.** Locally, `repo` keeps one project's
  answers out of another's. Shared, it is the difference between two people's code, and
  it needs to be enforced by who is asking rather than by what they passed.
- **The index is a copy of source.** Structure, not text — `read_source` reads from disk
  — but symbol names leak design, and a shared index is a shared disclosure.

Neither is built. The server is stdio and local, and saying it hosts a team today would
be the kind of claim this project is otherwise careful not to make.
