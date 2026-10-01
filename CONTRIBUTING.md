# Contributing

## Picking a feature

[ROADMAP.md](ROADMAP.md) lists every planned feature with an ID, a status and an owner,
and it is the source of truth for who is working on what. Take a `Ready` row — *good
first issue* ones are small and self-contained — claim it with the *Claim a feature*
issue template, and set the row to `In progress` with your handle and the date. Your
pull request moves it to `In review`; the merge makes it `Done`. The full rules, and the
[design-note template](docs/features/TEMPLATE.md) for large features, are in the
roadmap.

## Setting up

```bash
git clone https://github.com/arupmmi07/skygraph.git
cd skygraph
python3 -m venv .venv
.venv/bin/pip install -e .
```

Python 3.11 or newer. The editable install brings the tree-sitter parsers, the one
dependency.

## Running the tests

```bash
.venv/bin/python -m unittest discover -s tests -t .        # as installed, parsers live
python3 -m unittest discover -s tests -t .                 # bare: the fallback
```

Run it **both ways**. The parser tier only executes when tree-sitter is present, and a
skipped test is not evidence; the bare run is what a machine gets when the parsers
cannot load. CI runs both, on Python 3.11 to 3.14, plus the lint below.

```bash
ruff check --select E9,F skygraph tests
```

The suite is the golden-question benchmark plus the unit cases, and it needs nothing
but the standard library to run. A green run of those commands is the run that matters.

## The benchmark

`tests/test_benchmark.py` indexes small repositories under `tests/fixtures/` — one per
language — and asks
the questions a coder asks — where is X, what is in this file, who calls X, which table
does this endpoint write — with answers known from the source, not derived from grep.
Each answer must be right and must fit a byte ceiling. A gap the graph cannot answer yet
is an `expectedFailure`: it stays in the suite and flips the day it is fixed, so the
ceiling and the answer get re-checked then. Add a question here before adding a tool.

## What a change needs

- **A test that fails without it.** A pass needs a positive observation, not the absence
  of an error.
- **A recorded reason for anything the change makes impossible.** A rule without a
  reason gets relaxed by the next person who finds it inconvenient.
- **No new dependency.** The tree-sitter parsers are the one there is, because without
  them nothing but Python has calls. Anything else is standard library, and a tier that
  needs a third-party grammar belongs behind the same `Symbol`/`Edge` boundary as
  everything else, not in the core.

## Adding a language

A language is a query file — `skygraph/queries/<language>.scm`, seven captures — a
grammar name, its file extensions and a benchmark fixture; see
[docs/adding-a-language.md](docs/adding-a-language.md). Do not touch the interpreter,
the writer, the store or the query layer. If a
change to the core seems necessary to support one language, that is the thing to
discuss first, because it is usually a sign the capture vocabulary is wrong rather than
too small.

## What will be refused

- **A front end that fails quietly.** A construct it cannot read must degrade to the
  tier below and record the reason on the file row. A graph that is silently incomplete
  produces confident wrong answers, which is worse than one that admits a gap.
- **A node or edge kind that `schema.py` does not declare.** The schema is the
  authority; widen it deliberately or not at all.
- **A query that can reach outside its repo and branch.** Scope lives on the row. The
  failure mode must be empty, never another repository's code.
- **A write tool on the MCP surface.** Indexing is a separate, deliberate act.

## Style

Match the file you are editing. The code explains its own reasoning in docstrings; keep
that habit — the *why* is the part that survives.

## Documentation

The README follows one order — what it is, a picture, the problem, the words you need,
see it work in sixty seconds, numbered steps, what happens on a run, what you get, what
it is not, status, read more, licence — and stays under 900 words; detail belongs in
`docs/`. Pictures are drawn as SVG, kept in `docs/images/`, and embedded as the PNG
rendered from them, because many previewers cannot show SVG; look at the PNG before
committing it. Every number on a page is current and every claim is tested or a roadmap
row. No private, employer or client names anywhere.

## Releasing

1. Set the version in `pyproject.toml` and `skygraph/__init__.py`, and give it a
   section in `CHANGELOG.md` headed `## X.Y.Z — YYYY-MM-DD`.
2. Commit, tag and push:

   ```bash
   git tag -a vX.Y.Z -m "X.Y.Z"
   git push origin main vX.Y.Z
   ```

3. The release workflow runs the suite, checks the tag matches the package version,
   builds the wheel and source archive, and opens a **draft** GitHub release with them
   and the changelog section as notes. Read it, then publish it.
