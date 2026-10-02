"""`skygraph init`: wire a project to Claude Code and Codex in one command.

An agent reaches for the graph only when two things are true: the host can start the
server, and the agent has been told to use it before reading files. Both are
configuration, both are easy to get slightly wrong, and neither has anything to do with
indexing. So this writes them — `.mcp.json` for Claude Code, a block for Codex, the
paragraph for `CLAUDE.md` and `AGENTS.md`, and the session-start hook that keeps the
index no older than the session — then indexes once and prints what the agent will see.

Everything written is idempotent: markers around the paragraph, a merge into existing
JSON, a named server entry replaced rather than duplicated. Running it twice is safe.

`.mcp.json` and `.claude/settings.json` are written to be committed: commands by name,
and no path from this machine, whenever skygraph is on PATH (see `on_path`).
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from .indexer import index
from .store import DEFAULT_DB, Store

MARK_START = "<!-- skygraph:start -->"
MARK_END = "<!-- skygraph:end -->"

#: The paragraph that makes the difference between an agent that uses the graph and
#: one that greps out of habit — with the fallback contract, so it is a habit and not
#: a hope: when the graph says it is unsure, read the file.
INSTRUCTION = """## Skygraph

This project is indexed in skygraph. Before reading files to build context, use its
tools: `find_symbols` to locate, `context_for` or `expand_symbol` to understand a
symbol and its surroundings, `outline_file` for a file's shape, and `read_source` only
when you need the actual code. Run `index_health` if an answer depends on the index
being complete.

If a skygraph answer is empty, marked `stale`, `untyped` or `ambiguous`, or
`index_health` shows the file's language is not traversable, read the file directly.
Skygraph narrows what to read; it does not replace reading when it says it is unsure.
"""


def launcher() -> Path | None:
    """The checkout's `skygraph-mcp`, when this is a checkout rather than an install."""
    candidate = Path(__file__).resolve().parent.parent / "skygraph-mcp"
    return candidate if candidate.is_file() else None


def installed(script: str) -> str | None:
    """A console script by absolute path: first from the environment running this
    command, so `init` never wires a project to some other install of skygraph that
    happens to be earlier on PATH; then from PATH.

    Absolute, so the command does not depend on the PATH the host was started with:
    when a bare name is not found, a host reports only "connection closed". Shared
    files use the bare name instead when that is safe (`on_path`).
    """
    beside = Path(sys.executable).parent / script
    for candidate in (beside, beside.with_suffix(".exe")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    found = shutil.which(script)
    return os.path.abspath(found) if found else None


def on_path(script: str) -> bool:
    """Whether a host will start this same install by the script's bare name.

    `.mcp.json` and `.claude/settings.json` are meant to be committed, so they should
    name a command, not a place on one person's disk. A bare name is safe when PATH
    finds this install by it — through pipx's or uv's shared bin folder, or a plain
    user or system install. It is not safe when PATH reaches it only because a virtual
    environment is activated in this shell: the host, started later from another shell,
    would not find it.
    """
    found = shutil.which(script)
    if not found:
        return False
    here = installed(script)
    if here and not os.path.samefile(found, here):
        return False                       # PATH would start some other install
    folder = os.path.dirname(os.path.abspath(found))
    activated = (sys.prefix != sys.base_prefix
                 and folder == os.path.dirname(os.path.abspath(sys.executable)))
    return not activated


def shared_files_are_portable() -> bool:
    """Whether `.mcp.json` and the hook can name skygraph's commands without a path."""
    return on_path("skygraph-mcp") and on_path("skygraph")


def server_command(repo: str, db: str, shared: bool = True) -> list[str]:
    """How a host starts the server.

    For a shared file (`shared=True`, `.mcp.json`), the bare `skygraph-mcp` when PATH
    finds this install by it. Otherwise, and always for a file only this user reads
    (the Codex config), the installed console script or the checkout's launcher by
    absolute path, which works from any working directory.
    """
    args = ["--repo", repo] + (["--db", db] if db != DEFAULT_DB else [])
    if shared and shared_files_are_portable():
        return ["skygraph-mcp"] + args
    if installed("skygraph-mcp"):
        return [installed("skygraph-mcp")] + args
    if launcher():
        return [str(launcher())] + args
    raise RuntimeError("neither `skygraph-mcp` on PATH nor a checkout launcher was found; "
                       "install with `pip install .` or run from the checkout")


def index_command(repo: str, db: str) -> str:
    """The session-start hook: a delta index, one line of stdout for the agent.

    It names no project folder. The index records the folder each repository was
    indexed from, and a run with no folder refreshes that one — or refuses, if it is
    gone, rather than emptying the index.
    """
    # A shell runs this, so every path is quoted: a launcher under "My Projects" would
    # otherwise run "My" and fail.
    q = shlex.quote
    tail = f"--repo {q(repo)}" + (f" --db {q(db)}" if db != DEFAULT_DB else "")
    if shared_files_are_portable():
        return f"skygraph index {tail} --summary"
    if installed("skygraph"):
        return f"{q(installed('skygraph'))} index {tail} --summary"
    if launcher():
        return f"{q(str(launcher()))} --index {tail}"
    return f"{q(sys.executable)} -m skygraph index {tail} --summary"


def _merge_json(path: Path, update) -> None:
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise RuntimeError(f"{path} is not valid JSON; fix or remove it first")
    update(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_mcp_json(project: Path, repo: str, db: str) -> Path:
    command = server_command(repo, db)
    target = project / ".mcp.json"

    def update(data: dict) -> None:
        servers = data.setdefault("mcpServers", {})
        servers["skygraph"] = {"type": "stdio", "command": command[0],
                               "args": command[1:]}
    _merge_json(target, update)
    return target


def write_hook(project: Path, repo: str, db: str) -> Path:
    """A SessionStart hook in the project's `.claude/settings.json`. Its stdout is
    added to the agent's context, so the one line the index prints — what changed,
    what is untyped — is the first thing the agent reads."""
    command = index_command(repo, db)
    target = project / ".claude" / "settings.json"

    def update(data: dict) -> None:
        entries = data.setdefault("hooks", {}).setdefault("SessionStart", [])
        entries[:] = [e for e in entries if not any(
            "skygraph" in str(h.get("command", "")) for h in e.get("hooks", []))]
        entries.append({"matcher": "startup|resume",
                        "hooks": [{"type": "command", "command": command, "timeout": 120}]})
    _merge_json(target, update)
    return target


def write_instruction(path: Path) -> Path:
    block = f"{MARK_START}\n{INSTRUCTION}{MARK_END}\n"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if MARK_START in text and MARK_END in text:
        head = text[:text.index(MARK_START)]
        tail = text[text.index(MARK_END) + len(MARK_END):].lstrip("\n")
        text = head + block + tail
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    path.write_text(text, encoding="utf-8")
    return path


def codex_block(repo: str, db: str) -> str:
    # `~/.codex/config.toml` is this user's own file, never shared, so the absolute
    # path, which does not depend on the PATH Codex was started with.
    command = server_command(repo, db, shared=False)
    args = ", ".join(json.dumps(a) for a in command[1:])
    return (f"# skygraph:start\n[mcp_servers.skygraph]\ncommand = {json.dumps(command[0])}\n"
            f"args = [{args}]\n# skygraph:end\n")


def write_codex(repo: str, db: str, config: Path | None = None) -> Path:
    config = config or Path("~/.codex/config.toml").expanduser()
    block = codex_block(repo, db)
    text = config.read_text(encoding="utf-8") if config.is_file() else ""
    if "# skygraph:start" in text and "# skygraph:end" in text:
        head = text[:text.index("# skygraph:start")]
        tail = text[text.index("# skygraph:end") + len("# skygraph:end"):].lstrip("\n")
        text = head + block + tail
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text, encoding="utf-8")
    return config


def summary_line(report: dict) -> str:
    """One line for a hook's stdout and for `index --summary`."""
    calls = report.get("calls", {})
    total = sum(v for k, v in calls.items() if k != "how") or 1
    return (f"skygraph: {report['repo']} — {report['files']} files "
            f"({report['indexed']} re-read, {report['removed']} removed), "
            f"{report['symbols']} symbols; calls resolved {calls.get('resolved', 0)}, "
            f"untyped {round(100 * calls.get('untyped', 0) / total)}%; "
            f"{report['degraded']} degraded. Use find_symbols / context_for before reading files.")


def init(project: str | os.PathLike, repo: str | None = None, db: str = DEFAULT_DB,
         hook: bool = True, codex: bool = False, run_index: bool = True,
         codex_config: Path | None = None, out=None) -> dict:
    """Wire a project. Returns what was written, for the caller to print or test."""
    out = out or sys.stdout
    project = Path(project).expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError(f"{project} is not a directory")
    repo = repo or project.name
    written: dict = {"repo": repo, "project": str(project),
                     "portable": shared_files_are_portable()}

    written["mcp_json"] = str(write_mcp_json(project, repo, db))
    written["claude_md"] = str(write_instruction(project / "CLAUDE.md"))
    if codex or (project / "AGENTS.md").is_file():
        written["agents_md"] = str(write_instruction(project / "AGENTS.md"))
    if hook:
        written["hook"] = str(write_hook(project, repo, db))
    if codex:
        written["codex_config"] = str(write_codex(repo, db, codex_config))
    else:
        written["codex_block"] = codex_block(repo, db)

    if run_index:
        report = index(project, repo, "main", db)
        written["index"] = summary_line(report)
        health = Store(db).health(repo)
        written["languages"] = [(l["language"], l["traversable"]) for l in health["languages"]]

    print(f"wrote {written['mcp_json']}", file=out)
    print(f"wrote {written['claude_md']}" + (f" and {written['agents_md']}" if "agents_md" in written else ""), file=out)
    if hook:
        print(f"wrote {written['hook']} (SessionStart: delta index, one line into context)", file=out)
    if not written["portable"]:
        print("note: skygraph is not on PATH outside this shell, so .mcp.json"
              + (" and .claude/settings.json name it" if hook else " names it")
              + " by its path on this machine. That works here, but do not commit"
              + (" them" if hook else " it") + "; install with pipx and run `skygraph init`"
              " again to make them shareable", file=out)
    if codex:
        print(f"wrote {written['codex_config']}", file=out)
    else:
        print("Codex: add this to ~/.codex/config.toml (or re-run with --codex):\n"
              + written["codex_block"], file=out)
    if run_index:
        print(written["index"], file=out)
        # Only code languages: JSON, YAML and a Dockerfile never have calls, and telling
        # someone to install parsers for them is advice that cannot be followed.
        from .frontends import QUERY_LANGUAGES
        thin = [lang for lang, ok in written["languages"]
                if not ok and lang in QUERY_LANGUAGES]
        if thin:
            print(f"read by pattern, no call edges: {', '.join(thin)} — declarations only; "
                  "the tree-sitter parsers did not load. They come with `pip install "
                  "skygraph` (the grammars download once, on first use); a checkout run "
                  "without installing lacks them", file=out)
    print("next: restart Claude Code in this project and ask it to run list_repos", file=out)
    return written
