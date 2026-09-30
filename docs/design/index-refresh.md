# Keeping the index fresh

Design for roadmap features SG-003 and SG-010 to SG-016. Status lives in
[ROADMAP.md](../../ROADMAP.md); this page is the shape they share.

## The problem

An index is only useful while it matches the files on disk. Files change in four ways,
and today skygraph notices one of them:

| What changes the files | Noticed today? |
|---|---|
| A new session starts after work elsewhere | **yes** — the session-start hook `init` installs runs a delta index |
| The agent edits a file during the session | no — the next session sees it |
| `git checkout`, `pull`, `merge` or `rebase` changes many files at once | no — the next session sees it |
| An editor or another tool saves a file | no — the next session sees it |

Between those moments `read_source` notices a changed file and marks its answer
`stale`, but every other tool answers from the old rows.

## The design

![Five triggers feed one refresh command, which writes the index one run at a time; the
server reopens it and marks stale rows, and the agent's next question sees the
change](../images/index-refresh.svg)

**Every trigger runs the same command,** `skygraph index`, told which files changed when
the trigger knows (`--paths`) or which commit to compare with (`--changed-since`). There
is one refresh path to make fast and correct, not five.

**One writer at a time (SG-003).** A session hook, an edit hook and a git hook can fire
together. The store moves to SQLite's write-ahead log so the server keeps reading while
an index is written, and a second refresh waits for the running one and then covers
whatever changed meanwhile, instead of failing or racing it.

**Only what changed (SG-012).** A refresh today walks and hashes every file and
re-resolves every call, even when nothing changed. On a 10,000-file repository that is
5.6 s, most of it re-resolving calls; on a 1,720-file one, 0.8 s. Named files are
re-read directly, and only calls that can have changed — those in the changed files,
and those that resolved into them — are resolved again. Target: under a second on
10,000 files.

**Never in the way.** A hook must not make an edit or a `git checkout` feel slower. A
refresh that cannot finish quickly runs detached, in the background.

## The triggers

| Trigger | Mechanism | Runs | Feature |
|---|---|---|---|
| Session starts | Claude Code `SessionStart` hook, installed by `init` | a delta index; its one line reaches the agent | works today |
| Claude Code edits a file | `PostToolUse` hook, matcher `Edit\|Write\|MultiEdit\|NotebookEdit`; the path is `tool_input.file_path` (`notebook_path` for notebooks) | `--paths <file>` | SG-010 |
| Codex edits a file | Codex's hooks, where the installed version supports them | `--paths <file>` | SG-015 |
| `git checkout` / `switch` | `post-checkout` | a branch checkout: `--changed-since <old HEAD>`; a file checkout, which names no commits: a plain delta index | SG-011 |
| `git pull` / `merge` | `post-merge` | `--changed-since ORIG_HEAD` | SG-011 |
| `git rebase` / `commit --amend` | `post-rewrite` | the rewritten files | SG-011 |
| Anything else | `skygraph watch`, opt-in; or the next session | changed files | SG-016 |

**GitHub, GitLab or any other remote behaves the same.** A pull or a checkout is a
local git operation, so local git hooks see it wherever the code came from. Hooks are
added beside what is already there — existing hooks, `core.hooksPath` and husky are
preserved, never overwritten.

**Operations with no git hook** — `git stash pop`, `git reset --hard`, a bulk
search-and-replace — are caught by the next edit hook, the next session, or `watch`.
`index_health` says how many files changed since the last index (SG-014), so a stale
index is visible rather than trusted.

## Branches (SG-013, needs a decision)

Every row already carries a branch, but the indexer never asks git — everything is
filed under `main`. Two models:

- **One index that mirrors the working tree** (recommended). A checkout re-reads only
  the files that differ between the two commits, and the index records the branch and
  commit it reflects. It costs nothing extra, and the agent works on what is checked
  out.
- **One copy per branch.** Switching back is instant, but every branch costs a full
  index — 286 MB for the 10,000-file repository above.

## What the agent sees

- `index_health` reports the branch, the commit and when the index was last refreshed,
  and how many files have changed since (SG-013, SG-014).
- A row from a file changed since indexing carries `stale: true` in any tool (SG-014).
- The server already reopens the database when a refresh replaces it, and refuses an
  index written by newer code with a message to restart.

## Open questions

- Whether a Claude Code hook's detached child keeps the hook open, which decides
  between running the targeted refresh in the foreground and detaching it.
- Which Codex versions run hooks from a project's configuration. Codex has an
  experimental hooks feature; one reported issue has hooks in a repository's own
  configuration not firing in interactive sessions. SG-015 decides per version, with
  git hooks and `watch` as the fallback.
- Whether the server should ever refresh the index itself. Today it is strictly
  read-only, and that is deliberate: an agent that could re-index could change what the
  next question sees. The hooks keep that line.

## Appendix — diagram source

The diagram is hand-written SVG: [`docs/images/index-refresh.svg`](../images/index-refresh.svg),
with a PNG render beside it (`index-refresh.png`) for viewers that do not show SVG.
