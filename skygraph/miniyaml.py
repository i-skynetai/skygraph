"""A deliberately small YAML reader. Mappings, lists, scalars — and nothing else.

**Why this exists.** Compose files, Kubernetes manifests, CI workflows and OpenAPI
documents are all YAML, and there is no YAML parser in the standard library. Taking a
dependency for them would put one in a project whose entire claim is that it has none,
and every consumer would inherit it.

**Why it is safe to be small.** The files this reads are machine-written or written to a
template. They do not use anchors, merge keys, tags, or block scalars — and when one
does, this raises rather than returning a half-read document. Everything built on it is
tier `query` for exactly that reason: it is a reader, not a parser, and the difference
is that a parser is complete.

What it understands:

    key: value          mapping entries, nested by indentation
    key:                a mapping or list underneath
    - item              list items, including lists of mappings
    [a, b]  {a: b}      flow style, one level deep
    # comment           dropped
    ---                 document separators, via `load_all`

What it refuses, loudly: anchors (`&x`, `*x`), merge keys (`<<:`), tags (`!!str`), and
block scalars (`|`, `>`). A caller that gets a `MiniYamlError` knows the file needs a
real parser; a caller that got a silently truncated dictionary would not.
"""
from __future__ import annotations

import re

REFUSED = re.compile(r"(^|\s)(?:[&*]\w|<<\s*:|!!?\w)|:\s*[|>][-+0-9]*\s*$")
FLOW_SEQ = re.compile(r"^\[(.*)\]$")
FLOW_MAP = re.compile(r"^\{(.*)\}$")


#: A colon only separates a key from a value when a space or a line end follows it.
#: Without that rule `- DATABASE_URL=postgres://x` reads as a mapping from
#: "DATABASE_URL=postgres" to "//x", which is the shape half of every compose file's
#: environment list takes.
#:
#: This was a regular expression — `^((?:"[^"]*"|\'[^\']*\'|[^:])+?):(?:\s+(.*)|$)` —
#: and it was catastrophic. A quoted run can match either the quoted branch or one
#: `[^:]` at a time, so a line with many quoted segments has exponentially many ways to
#: be read and the engine tries them all. A 1,784-character GitLab CI line took longer
#: than an hour; the whole index stopped on one 2 KB file. A scan is linear and there
#: is nothing to backtrack.


def _split_key(line: str) -> tuple[str, str] | None:
    """(key, rest) when this line opens a mapping entry, else None."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(line) or line[i + 1] in " \t"):
            return line[:i].strip().strip("\"'"), line[i + 1:].strip()
    return None


class MiniYamlError(Exception):
    """The document uses YAML this reader does not implement."""


def _scalar(raw: str):
    text = raw.strip()
    if not text:
        return None
    seq = FLOW_SEQ.match(text)
    if seq:
        inner = seq.group(1).strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    flow = FLOW_MAP.match(text)
    if flow:
        out = {}
        for pair in flow.group(1).split(","):
            if ":" in pair:
                k, _, v = pair.partition(":")
                out[k.strip().strip("\"'")] = _scalar(v)
        return out
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _strip_comment(line: str) -> str:
    out, quote = [], ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (not out or out[-1] in (" ", "\t")):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _rows(text: str) -> list[tuple[int, str]]:
    rows = []
    for raw in text.splitlines():
        if REFUSED.search(raw):
            raise MiniYamlError(f"unsupported YAML: {raw.strip()[:60]}")
        line = _strip_comment(raw)
        if not line.strip():
            continue
        rows.append((len(line) - len(line.lstrip()), line.strip()))
    return rows


def _parse(rows: list[tuple[int, str]], start: int, indent: int):
    """Everything at `indent` or deeper, starting at `start`. Returns (value, next)."""
    if start >= len(rows):
        return None, start
    if rows[start][1].startswith("- "):
        return _parse_list(rows, start, rows[start][0])
    return _parse_map(rows, start, indent)


def _parse_list(rows, i, indent):
    items = []
    while i < len(rows):
        depth, line = rows[i]
        if depth < indent or not line.startswith(("- ", "-")):
            break
        if depth > indent:
            break
        body = line[1:].lstrip()
        i += 1
        if not body:                                    # "-" then a nested block
            value, i = _parse(rows, i, indent + 1)
            items.append(value)
            continue
        pair = _split_key(body)
        if pair:
            # "- key: value" — a mapping whose first key shares the dash's line
            key, rest = pair
            entry = {}
            if rest.strip():
                entry[key] = _scalar(rest)
            else:
                nested, i = _parse(rows, i, depth + 2)
                entry[key] = nested
            deeper, i = _parse_map(rows, i, depth + 2, into=entry)
            items.append(deeper)
        else:
            items.append(_scalar(body))
    return items, i


def _parse_map(rows, i, indent, into=None):
    out = {} if into is None else into
    while i < len(rows):
        depth, line = rows[i]
        if depth < indent:
            break
        if line.startswith("- "):
            break
        pair = _split_key(line)
        if not pair:
            i += 1
            continue
        key, rest = pair
        i += 1
        if rest.strip():
            out[key] = _scalar(rest)
        elif i < len(rows) and rows[i][0] > depth:
            out[key], i = _parse(rows, i, rows[i][0])
        elif i < len(rows) and rows[i][1].startswith("- ") and rows[i][0] == depth:
            out[key], i = _parse_list(rows, i, depth)
        else:
            out[key] = None
    return out, i


def load_all(text: str) -> list:
    """Every document in the file. Kubernetes manifests routinely hold several."""
    docs, buffer = [], []
    for line in text.splitlines():
        if line.rstrip() == "---":
            docs.append("\n".join(buffer))
            buffer = []
        else:
            buffer.append(line)
    docs.append("\n".join(buffer))

    out = []
    for doc in docs:
        rows = _rows(doc)
        if not rows:
            continue
        value, _ = _parse(rows, 0, rows[0][0])
        if value:
            out.append(value)
    return out


def load(text: str):
    """The first document, or None."""
    docs = load_all(text)
    return docs[0] if docs else None
