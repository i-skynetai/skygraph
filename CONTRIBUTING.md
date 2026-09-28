# Contributing

## Running the tests

```bash
python3 -m unittest discover -s tests -t .                 # the default install
.venv/bin/python -m unittest discover -s tests -t .        # and with the parsers
```

Run it **both ways**. The parser tier only executes when tree-sitter is installed, and
a skipped test is not evidence — CI runs the suite twice for the same reason.

166 cases; the core is standard library only — no install step, nothing to pin. That is the same
command CI runs, so a green run here is the run that matters.

## What a change needs

- **A test that fails without it.** A pass needs a positive observation, not the absence
  of an error.
- **A recorded reason for anything the change makes impossible.** A rule without a
  reason gets relaxed by the next person who finds it inconvenient.
- **No new dependency.** The parser tiers are standard library. A tier that needs a
  third-party grammar belongs behind the same `Symbol`/`Edge` boundary as everything
  else, not in the core.

## Adding a language

Most languages are a tier-2 front end and about twenty lines — see
[docs/adding-a-language.md](docs/adding-a-language.md). Add the front end; do not touch
the writer, the store or the query layer. If a change to the core seems necessary to
support one language, that is the thing to discuss first, because it is usually a sign
the capture vocabulary is wrong rather than too small.

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
