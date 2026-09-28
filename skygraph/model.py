"""Tier 3 — the optional model fallback, for files no parser could read.

**It is the last resort, not the first.** A file reaches this only after tier 1 refused
it and tier 2 had no pattern for it. Parsers are free, exact and repeatable; a model is
none of those. Using one where an AST would do would be spending tokens to get a worse
answer, in a project whose entire argument is about not spending tokens.

**Nothing it produces is called a fact.** Every row is tier `model`, which means
`Symbol.parsed` is False and `index_health` counts it separately. A caller can ask for
parsed rows only. This matters more than it sounds: a graph mixing read facts with a
model's reading of a file it could not parse, indistinguishably, is worse than one that
simply lacks the file — the gap is at least visible.

**It costs money, so it is capped and it reports.** A budget of files per run, a cap on
how much of any one file is sent, and counts of what was attempted, accepted and
refused. And because the index already skips files whose content hash has not moved, a
second run over an unchanged repository sends nothing at all.

No dependency: `urllib.request` from the standard library. Two provider shapes cover
everything in practice — Anthropic's, and the OpenAI-compatible one that OpenAI,
Ollama, vLLM and most hosted endpoints all speak.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .ontology import KIND_OWNER, RELATION_OWNER

#: How much of one file is sent. A file bigger than this is truncated, and the prompt
#: says so, because a model shown half a file and not told will invent the other half.
MAX_CHARS = 12_000

#: Files per run. Tier 3 only ever sees what no parser could read, so this is a ceiling
#: on a number that should already be small — and a repository where it is not is one
#: where the answer is a tier-2 pattern, not a bigger budget.
DEFAULT_BUDGET = 40

TIMEOUT = 60

PROMPT = """You are reading one source file to extract its structure for a code index.

Return ONLY a JSON object, no prose, no code fence:

{"symbols": [{"name": "...", "kind": "...", "line": 0, "summary": "..."}],
 "edges":   [{"src": "...", "rel": "...", "dst": "..."}]}

Rules:
- `kind` MUST be one of: %(kinds)s
- `rel` MUST be one of: %(relations)s
- `name` is the bare declared name, e.g. `parse_config`, not a path.
- `src` and `dst` use those same bare names. A `dst` naming something outside this
  file is fine — say the name as written.
- `line` is where the declaration starts, 1-based. Use 0 if you are unsure.
- `summary` is at most 12 words on what it does. Empty string if it is not clear.
- Extract only what the file actually declares. Do not infer, complete, or guess at
  code that is not shown. An empty list is a correct answer.

File: %(path)s
Language: %(language)s%(truncated)s

```
%(source)s
```"""


class ModelError(Exception):
    """The provider could not be reached, or did not return usable JSON."""


class Model:
    """One configured provider. Holds the key and never writes it anywhere."""

    def __init__(self, key: str, name: str = "", url: str = "",
                 provider: str = "", budget: int = DEFAULT_BUDGET) -> None:
        if not key:
            raise ValueError("a model needs a key")
        self._key = key
        self.provider = provider or ("anthropic" if key.startswith("sk-ant-")
                                     else "openai")
        self.name = name or ("claude-haiku-4-5-20251001"
                             if self.provider == "anthropic" else "gpt-4o-mini")
        self.url = url or ("https://api.anthropic.com/v1/messages"
                           if self.provider == "anthropic"
                           else "https://api.openai.com/v1/chat/completions")
        self.budget = budget
        self.attempted = self.accepted = self.refused = 0
        self.problems: list[str] = []

    # ── configuration ──────────────────────────────────────────────────────

    @classmethod
    def from_environment(cls, key: str = "", budget: int = 0) -> "Model | None":
        """A model if one is configured, and None if not — never an error.

        Tier 3 is opt-in. A missing key is the ordinary case and means "index without
        it", not "stop".
        """
        key = key or os.environ.get("SKYGRAPH_MODEL_KEY", "")
        if not key:
            return None
        return cls(key,
                   name=os.environ.get("SKYGRAPH_MODEL", ""),
                   url=os.environ.get("SKYGRAPH_MODEL_URL", ""),
                   provider=os.environ.get("SKYGRAPH_MODEL_PROVIDER", ""),
                   budget=budget or int(os.environ.get("SKYGRAPH_MODEL_BUDGET",
                                                       DEFAULT_BUDGET)))

    def describe(self) -> dict:
        """What was used, for the run report. The key is not part of that."""
        return {"provider": self.provider, "model": self.name, "budget": self.budget}

    # ── the call ───────────────────────────────────────────────────────────

    def _request(self, prompt: str) -> str:
        if self.provider == "anthropic":
            body = {"model": self.name, "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}]}
            headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01",
                       "content-type": "application/json"}
        else:
            body = {"model": self.name, "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}]}
            headers = {"Authorization": f"Bearer {self._key}",
                       "content-type": "application/json"}

        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            # The body often says which limit was hit; the key is never in it.
            detail = exc.read().decode("utf-8", "replace")[:200] if exc.fp else ""
            raise ModelError(f"HTTP {exc.code} from {self.provider}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelError(f"cannot reach {self.provider}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ModelError(f"{self.provider} did not return JSON: {exc}") from exc

        try:
            if self.provider == "anthropic":
                return "".join(block.get("text", "")
                               for block in payload["content"])
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"unexpected response shape from {self.provider}") from exc

    def read(self, path: str, source: str, language: str) -> dict:
        """Ask for one file's structure. Raises ModelError; never returns junk."""
        self.attempted += 1
        clipped = source[:MAX_CHARS]
        prompt = PROMPT % {
            "kinds": ", ".join(sorted(KIND_OWNER)),
            "relations": ", ".join(sorted(RELATION_OWNER)),
            "path": path, "language": language or "unknown",
            "truncated": (f"\nNOTE: truncated to the first {MAX_CHARS} characters; "
                          "do not describe what is not shown."
                          if len(source) > MAX_CHARS else ""),
            "source": clipped,
        }
        return _as_json(self._request(prompt))


def _as_json(text: str) -> dict:
    """The model was told not to use a fence. Models use fences anyway."""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1] if "\n" in body else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise ModelError(f"no JSON object in the reply: {text[:120]!r}")
    try:
        found = json.loads(body[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ModelError(f"the reply was not valid JSON: {exc}") from exc
    if not isinstance(found, dict):
        raise ModelError("the reply was JSON but not an object")
    return found


def to_rows(path: str, reply: dict, tier: str = "model"):
    """Turn a reply into symbols and edges, dropping anything undeclared.

    The ontologies are the authority here exactly as they are for a parser. A model
    asked for `Function` will sometimes answer `Interface`, and the right response is to
    drop that row and say so — not to widen the schema, and not to let one through
    because a model is confident.

    Returns (symbols, edges, refused) where `refused` explains each drop.
    """
    from .schema import Edge, Symbol            # local: keeps model.py importable alone

    symbols, edges, refused = [], [], []
    declared: set[str] = set()

    for item in reply.get("symbols") or []:
        if not isinstance(item, dict):
            refused.append("a symbol that was not an object")
            continue
        name = str(item.get("name") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not name:
            refused.append("a symbol with no name")
            continue
        try:
            line = int(item.get("line") or 0)
        except (TypeError, ValueError):
            line = 0
        try:
            # The model gives a bare name; the path is ours to attach, so the naming
            # is identical to a parsed file's and nothing downstream can tell which
            # tier wrote a row except by reading the tier.
            symbols.append(Symbol(f"{path}::{name}", kind, path, max(0, line), 0, tier,
                                  summary=str(item.get("summary") or "")[:120]))
            declared.add(name)
        except ValueError as exc:
            refused.append(str(exc).split(".")[0])

    for item in reply.get("edges") or []:
        if not isinstance(item, dict):
            refused.append("an edge that was not an object")
            continue
        src = str(item.get("src") or "").strip()
        rel = str(item.get("rel") or "").strip()
        dst = str(item.get("dst") or "").strip()
        if not (src and dst):
            refused.append("an edge missing an end")
            continue
        if src not in declared:
            # An edge from something the same reply did not declare is a model
            # describing code it was not shown.
            refused.append(f"an edge from undeclared {src!r}")
            continue
        try:
            edges.append(Edge(f"{path}::{src}", rel, dst, tier))
        except ValueError as exc:
            refused.append(str(exc).split(".")[0])

    return symbols, edges, refused
