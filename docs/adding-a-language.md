# Adding a language

Tier 2 takes about twenty lines and no change to anything downstream.

## The entry

`skygraph/frontends.py`, in `QUERY_LANGUAGES`:

```python
"elixir": {
    "ext":    (".ex", ".exs"),
    "class":  r"^\s*defmodule\s+([\w.]+)",
    "func":   r"^\s*def\s+(\w+)",
    "import": r"^\s*(?:import|alias|require)\s+([\w.]+)",
},
```

Four keys. `ext` is how the router claims a file; the other three are anchored regular
expressions whose first group is the name.

That is the whole change. The writer, the store, the scoping and the MCP tools already
work — they never knew what a language was.

## A test

```python
def test_elixir(self):
    r = frontends.parse("m.ex", "defmodule Alpha do\n  def run do\n  end\nend\n")
    self.assertEqual(r.tier, "query")
    self.assertIn("m.ex::Alpha", {s.name for s in r.symbols})
```

## When tier 2 is not enough

Go to tier 1 — a real parser — only when the language earns it: when patterns produce
wrong answers rather than merely incomplete ones, or when you need types, positions or
nested ownership that a line-oriented match cannot see.

Tier 1 is a `_native_<language>` function returning the same `FileResult`. Everything
downstream is unchanged, again.

## What not to do

**Do not widen the schema to fit a language.** If a construct has no home in the shared
vocabulary, that is a decision about the vocabulary, made once and deliberately — not a
new kind smuggled in by one front end. `schema.py` raises precisely to make that
conversation happen.

**Do not let a pattern guess quietly.** If your front end cannot handle something, fall
to the tier below and set `degraded`. An incomplete graph that says so is useful; one
that does not is dangerous.
