# Getting started

Everything about installing skygraph, connecting it to your coding agent, keeping the
index current, and removing it. The [README](../README.md) has the short version.

## Install and connect

You need Python 3.11 or newer and a git client.

**1. Install.** [pipx](https://pipx.pypa.io) keeps skygraph in its own environment and
puts the two commands on your PATH:

```bash
pipx install "git+https://github.com/i-skynetai/skygraph.git@v0.2.0"
```

Or with pip, inside a virtual environment:

```bash
pip install "git+https://github.com/i-skynetai/skygraph.git@v0.2.0"
```

**2. See it work.** No project or agent needed:

```bash
skygraph demo
```

It indexes a small sample shop — a Python API, an order service, two tables, a
TypeScript client, a Dockerfile and a CI file — into a temporary folder, and asks it the
questions a coding agent asks: where is this declared, what does this endpoint write to,
who calls this, what breaks if it changes, can the index be trusted. Each answer is
shown with its size, the way the agent receives it. Nothing is left behind.

**3. Wire your project.** From anywhere:

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

Running `init` again is safe: everything is merged or replaced, never duplicated.

When skygraph is on PATH, as it is after a pipx install, `.mcp.json` and
`.claude/settings.json` name its commands with no path from your machine, so you can
commit them. A teammate who installs skygraph gets the same setup, and on their first
session the hook asks them to run `skygraph init .` once. If skygraph is reachable only
by its path, `init` says so, and those two files then belong to your machine only.

**4. Restart the agent in the project** and ask it something only the graph answers
cheaply:

> Use skygraph: where is `PaymentService` declared, and who calls its `refund` method?

In Claude Code the tools appear as `mcp__skygraph__find_symbols` and so on. Run `/mcp`
to confirm the server is connected.

**Codex.** Run `skygraph init /path/to/your/project --codex`, or paste the printed block
into `~/.codex/config.toml`, then restart Codex.

**Any other MCP host.** `skygraph-mcp --repo <name>` is a stdio MCP server; point the
host at it by absolute path (`command -v skygraph-mcp` prints it). [Connecting
it](connecting.md) has the details.

## Commands

| Command | Does |
|---|---|
| `skygraph demo` | index a sample project and answer an agent's questions about it — the quickest way to see what it does |
| `skygraph init <path>` | wire a project to Claude Code (and Codex with `--codex`), then index it |
| `skygraph index <path> --repo <name>` | build or refresh the index; leave out `<path>` to refresh the folder the repository was indexed from; `--full` re-reads everything, `--summary` prints one line |
| `skygraph forget --repo <name>` | drop one repository from the index |
| `skygraph degraded --repo <name>` | files that were not parsed at their best tier, and why |
| `skygraph search <text> --repo <name>` | find symbols by name from the terminal |
| `skygraph neighbours <symbol> --repo <name>` | one hop of calls and imports |
| `skygraph ontologies` | the five ontologies as JSON |
| `skygraph-mcp --repo <name>` | the MCP server a host starts |

Every command that reads or writes an index takes `--db <file>` to use one other than
`~/.skygraph/index.db`.

## Keeping it current

- **Every session.** The hook `init` installs runs a delta index when the agent starts:
  only files whose content hash changed are read again. On this repository a cold index
  takes 0.6 s and the next run reads nothing.
- **By hand.** `skygraph index /path/to/project --repo name` does the same; `--full`
  re-reads everything.
- **Not yet automatic:** edits the agent makes during a session, and `git checkout` or
  `pull`, are picked up at the next session start or by hand. Refreshing on every edit
  and git operation is next — see [Keeping the index fresh](design/index-refresh.md).
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
     machine. See [the model tier](connecting.md#optionally-let-a-model-read-what-the-parsers-could-not).
- **What the server can do.** Answer questions. There is no write tool; indexing is a
  separate command. It speaks MCP over stdio only.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The host shows no skygraph tools, or says "connection closed" | Run the server by hand with the command from `.mcp.json` and read its error: `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \| "$(command -v skygraph-mcp)"` |
| `list_repos` comes back empty | The server reads a different index. Pass the same `--db` to `init` and the server, or re-run `init`. |
| A tool answers "written by skygraph schema N … restart" | A server from before an upgrade is still running. Restart the agent. |
| `index_health` lists a language as not traversable | Its parser did not load — usually the first index ran offline. Run `skygraph index <path> --repo <name> --full` once online. |
| The session hook says "is not indexed on this machine yet", or "is not a folder" | The project was never indexed here, or it moved. Run `skygraph init .` in the project. The index is left as it was until you do. |
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
