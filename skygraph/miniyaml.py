"""A small YAML reader: the YAML that configuration files are actually written in.

**Why this exists.** Compose files, Kubernetes manifests, CI workflows and OpenAPI
documents are all YAML, and there is no YAML parser in the standard library. The parsers
are skygraph's one dependency; a YAML library would be a second, for files that use a
small, regular part of the language.

**What it understands** — the shapes real CI and deployment files use:

    key: value          mapping entries, nested by indentation
    key:                a mapping or list underneath
    - item              list items, including lists of mappings
    [a, b]  {a: b}      flow style, one level deep
    run: |   run: >-    block scalars, literal and folded, with chomping indicators;
    - |                 their lines are read raw, so `#` and `: ` inside them are text
    &name  *name        anchors and aliases
    <<: *defaults       merge keys, one alias or a list of them; explicit keys win
    !reference [a, b]   tags — the tag is dropped and the value kept, which is what a
    !Ref Bucket         reader of structure wants from GitLab and CloudFormation tags
    # comment           dropped
    ---                 document separators, via `load_all`

**What it refuses, loudly** — complex keys (`? `), directives (`%YAML`), and a flow
collection that spans lines. A caller that gets a `MiniYamlError` knows the file needs a
real parser and can say so; a caller that got a silently truncated dictionary would not.
"""
from __future__ import annotations

import copy
import re

FLOW_SEQ = re.compile(r"^\[(.*)\]$")
FLOW_MAP = re.compile(r"^\{(.*)\}$")
#: The value part of a line that opens a block scalar: `|`, `>-`, `|2+` …
BLOCK = re.compile(r"^[|>](?:[1-9]?[-+]?|[-+][1-9]?)$")
ANCHOR = re.compile(r"^&([^\s\[\]{},]+)\s*")
ALIAS = re.compile(r"^\*([^\s\[\]{},]+)$")
TAG = re.compile(r"^!!?[A-Za-z0-9_./:-]*\s*")
BLOCK_MARK = "\x00block:"
DQ_ESCAPE = re.compile(r"\\(.)")
DQ_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r", "/": "/", "0": "\0"}


class MiniYamlError(Exception):
    """The document uses YAML this reader does not implement."""


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
            return _unquote(line[:i].strip()), line[i + 1:].strip()
    return None


def _unquote(text: str) -> str:
    """One pair of matching quotes off, never more: `"a 'b'"` keeps its inner quote."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
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


def _open_quote(text: str) -> bool:
    """Whether `text` starts a quoted scalar that this line does not close."""
    if text[:1] == "'":
        return text.replace("''", "").count("'") % 2 == 1
    if text[:1] == '"':
        return re.sub(r"\\.", "", text).count('"') % 2 == 1
    return False


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _value_part(line: str) -> str:
    """What follows the key, or the dash, on a comment-free line."""
    body = line.strip()
    while body.startswith("- ") or body == "-":
        body = body[1:].lstrip()
    pair = _split_key(body)
    return pair[1] if pair else body


def _block_text(lines: list[str], header: str) -> str:
    """The value of a block scalar from its raw lines and its `|`/`>` header."""
    trailing_blank = bool(lines) and not lines[-1].strip()
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    content = [ln for ln in lines if ln.strip()]
    width = min((_indent(ln) for ln in content), default=0)
    body = [ln[width:] if ln.strip() else "" for ln in lines]
    if header.startswith(">"):
        # Folded: a break between two text lines is a space; each empty line is one
        # break; a more-indented line keeps the breaks around it.
        joined, prev = "", ""
        for ln in body:
            if not ln:
                joined += "\n"
                prev = "blank"
            elif ln.startswith((" ", "\t")):
                joined += ("\n" if prev in ("text", "more") else "") + ln
                prev = "more"
            else:
                joined += " " if prev == "text" else "\n" if prev == "more" else ""
                joined += ln
                prev = "text"
    else:
        joined = "\n".join(body)
    if "-" in header:
        return joined
    if "+" in header and trailing_blank:
        return joined + "\n\n"
    return joined + "\n" if joined else ""


class _Reader:
    """One document: its rows, its block scalars and its anchors."""

    def __init__(self, lines: list[str]) -> None:
        self.blocks: list[str] = []
        self.anchors: dict[str, object] = {}
        self.rows = self._rows(lines)

    # ── lines → rows ──────────────────────────────────────────────────────────

    def _rows(self, raw_lines: list[str]) -> list[tuple[int, str]]:
        rows: list[tuple[int, str]] = []
        i = 0
        while i < len(raw_lines):
            raw = raw_lines[i]
            i += 1
            stripped = raw.strip()
            if stripped.startswith("? ") or stripped == "?":
                raise MiniYamlError(f"unsupported YAML (complex key): {stripped[:60]}")
            if stripped.startswith("%"):
                raise MiniYamlError(f"unsupported YAML (directive): {stripped[:60]}")
            line = _strip_comment(raw)
            if not line.strip():
                continue
            value = _value_part(line)
            header = TAG.sub("", ANCHOR.sub("", value))
            if BLOCK.match(header):
                # Gather the raw lines below, more indented than the key that owns the
                # block, as text. Under `- script: |` that key is `script`, not the dash:
                # a sibling `displayName:` at the key's column ends the block.
                column, owner = _indent(line), _indent(line)
                body = line.strip()
                while body.startswith("- ") or body == "-":
                    owner = column                       # the dash is the owner …
                    rest_of_line = body[1:].lstrip()
                    column += len(body) - len(rest_of_line)
                    body = rest_of_line
                parent = column if _split_key(body) else owner   # … unless a key follows it
                block: list[str] = []
                while i < len(raw_lines) and (not raw_lines[i].strip()
                                              or _indent(raw_lines[i]) > parent):
                    block.append(raw_lines[i])
                    i += 1
                self.blocks.append(_block_text(block, header))
                marker = f"{BLOCK_MARK}{len(self.blocks) - 1}"
                line = line[: len(line) - len(header)].rstrip() + " " + marker
            elif header.startswith(("[", "{")) and (header.count("[") > header.count("]")
                                                     or header.count("{") > header.count("}")):
                raise MiniYamlError(f"unsupported YAML (multi-line flow): {line.strip()[:60]}")
            rows.append((_indent(line), line.strip()))
        return rows

    # ── values ────────────────────────────────────────────────────────────────

    def _alias(self, name: str):
        if name not in self.anchors:
            raise MiniYamlError(f"unsupported YAML (alias before its anchor): *{name}")
        return copy.deepcopy(self.anchors[name])

    def scalar(self, raw: str):
        text = raw.strip()
        anchor = ANCHOR.match(text)
        if anchor:
            text = text[anchor.end():]
        text = TAG.sub("", text)
        value = self._plain(text)
        if anchor:
            self.anchors[anchor.group(1)] = value
        return value

    def _plain(self, text: str):
        if not text:
            return None
        if text.startswith(BLOCK_MARK):
            return self.blocks[int(text[len(BLOCK_MARK):])]
        alias = ALIAS.match(text)
        if alias:
            return self._alias(alias.group(1))
        if (FLOW_SEQ.match(text) or FLOW_MAP.match(text)):
            value, end = self._flow(text, 0)
            if text[end:].strip():
                raise MiniYamlError(f"unsupported YAML (flow): {text[:60]}")
            return value
        if len(text) >= 2 and text[0] == text[-1] == "'":
            return text[1:-1].replace("''", "'")          # '' is an escaped quote
        if len(text) >= 2 and text[0] == text[-1] == '"':
            return DQ_ESCAPE.sub(lambda m: DQ_ESCAPES.get(m.group(1), m.group(0)), text[1:-1])
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

    def _flow(self, s: str, i: int):
        """A flow collection or a flow scalar at `s[i]`, nested to any depth and aware of
        quotes. Returns (value, index after it)."""
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] in "[{":
            closing, items, mapping = ("]" if s[i] == "[" else "}"), [], {}
            is_map = s[i] == "{"
            i += 1
            while True:
                while i < len(s) and s[i] in " \t,":
                    i += 1
                if i >= len(s):
                    raise MiniYamlError(f"unsupported YAML (unclosed flow): {s[:60]}")
                if s[i] == closing:
                    return (mapping if is_map else items), i + 1
                if is_map:
                    key, i = self._flow_token(s, i, ":")
                    if i < len(s) and s[i] == ":":
                        value, i = self._flow(s, i + 1)
                    else:
                        value = None
                    mapping[_unquote(key.strip())] = value
                else:
                    value, i = self._flow(s, i)
                    items.append(value)
        token, i = self._flow_token(s, i, "")
        return self.scalar(token), i

    def _flow_token(self, s: str, i: int, stop: str) -> tuple[str, int]:
        """Text up to the next `,` `]` `}` (or `stop`) outside quotes."""
        start, quote = i, ""
        while i < len(s):
            ch = s[i]
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch in ",]}" or (stop and ch == stop and (i + 1 == len(s) or s[i + 1] in " \t,]}")):
                break
            i += 1
        return s[start:i].strip(), i

    def _continuation(self, i: int, key_col: int, first: str = "") -> tuple[list[str], int]:
        """Lines that continue a plain or quoted scalar: deeper than its key, not a list
        item, and not themselves a `key: value`. YAML folds them into one line. A quote
        left open on the first line runs to its closing quote, colons and all."""
        more = []
        while _open_quote(" ".join([first, *more])) and i < len(self.rows):
            more.append(self.rows[i][1])
            i += 1
        if more:
            return more, i
        while i < len(self.rows):
            depth, line = self.rows[i]
            if depth <= key_col or line.startswith("- ") or line == "-" or _split_key(line):
                break
            more.append(line)
            i += 1
        return more, i

    def _opens_nested(self, rest: str) -> tuple[bool, str | None]:
        """Whether `rest` is empty but for an anchor or a tag — a value that continues
        on the lines below — and the anchor's name if there is one."""
        anchor = ANCHOR.match(rest)
        name = anchor.group(1) if anchor else None
        remainder = TAG.sub("", rest[anchor.end():] if anchor else rest).strip()
        return not remainder, name

    def _nested(self, i: int, indent: int, anchor: str | None):
        value, i = self.parse(i, indent)
        if anchor:
            self.anchors[anchor] = copy.deepcopy(value)
        return value, i

    def _merge(self, out: dict, value) -> None:
        """`<<:` — copy in what the alias holds, without replacing what is already set."""
        for source in (value if isinstance(value, list) else [value]):
            if isinstance(source, dict):
                for k, v in source.items():
                    out.setdefault(k, v)

    # ── structure ─────────────────────────────────────────────────────────────

    def parse(self, start: int, indent: int):
        """Everything at `indent` or deeper, starting at `start`. Returns (value, next)."""
        if start >= len(self.rows):
            return None, start
        if self.rows[start][1].startswith("- ") or self.rows[start][1] == "-":
            return self.parse_list(start, self.rows[start][0])
        return self.parse_map(start, indent)

    def parse_list(self, i: int, indent: int):
        items = []
        while i < len(self.rows):
            depth, line = self.rows[i]
            if depth != indent or not (line.startswith("- ") or line == "-"):
                break
            body = line[1:].lstrip()
            key_col = depth + len(line) - len(body)
            i += 1
            empty, anchor = self._opens_nested(body)
            if empty:                                   # "-" then a nested block
                value, i = self._nested(i, indent + 1, anchor)
                items.append(value)
                continue
            # `- &name key: value` anchors the mapping that starts on this line.
            lead = ANCHOR.match(body)
            keyed = body[lead.end():] if lead else body
            pair = _split_key(keyed)
            if pair and not keyed.startswith(("*", "!", "[", "{", BLOCK_MARK)):
                # "- key: value" — a mapping whose first key shares the dash's line
                key, rest = pair
                entry: dict = {}
                i = self._entry(entry, key, rest, i, key_col)
                deeper, i = self.parse_map(i, key_col, into=entry)
                if lead:
                    self.anchors[lead.group(1)] = copy.deepcopy(deeper)
                items.append(deeper)
            else:
                more, i = ([], i) if body.startswith(("[", "{", "*", BLOCK_MARK)) \
                    else self._continuation(i, depth, body)
                items.append(self.scalar(" ".join([body, *more])))
        return items, i

    def _entry(self, out: dict, key: str, rest: str, i: int, key_col: int) -> int:
        """Read one `key: rest` entry at column `key_col`; its children, if any, start
        at row `i` and sit deeper than the key. Returns the next row."""
        empty, anchor = self._opens_nested(rest)
        if not empty:
            more, i = ([], i) if rest.startswith(("[", "{", "*", BLOCK_MARK)) \
                else self._continuation(i, key_col, rest)
            value = self.scalar(" ".join([rest, *more]))
        elif i < len(self.rows) and self.rows[i][0] > key_col \
                and not self.rows[i][1].startswith(("- ", BLOCK_MARK)) and self.rows[i][1] != "-" \
                and not _split_key(self.rows[i][1]):
            more, i = self._continuation(i, key_col)      # the value starts on the next line
            value = self.scalar(" ".join(more))
            if anchor:
                self.anchors[anchor] = copy.deepcopy(value)
        elif i < len(self.rows) and self.rows[i][0] > key_col:
            value, i = self._nested(i, self.rows[i][0], anchor)
        elif i < len(self.rows) and self.rows[i][0] == key_col \
                and (self.rows[i][1].startswith("- ") or self.rows[i][1] == "-"):
            value, i = self.parse_list(i, key_col)      # a list at the key's own column
            if anchor:
                self.anchors[anchor] = copy.deepcopy(value)
        else:
            value = None
        if key == "<<":
            self._merge(out, value)
        else:
            out[key] = value
        return i

    def parse_map(self, i: int, indent: int, into: dict | None = None):
        out = {} if into is None else into
        while i < len(self.rows):
            depth, line = self.rows[i]
            if depth < indent or line.startswith("- ") or line == "-":
                break
            pair = _split_key(line)
            i += 1
            if not pair:
                continue
            key, rest = pair
            i = self._entry(out, key, rest, i, depth)
        return out, i


def load_all(text: str) -> list:
    """Every document in the file. Kubernetes manifests routinely hold several."""
    docs, buffer = [], []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()                                # the newline that ends the file
    for line in lines:
        line = line.rstrip("\r")
        if line.rstrip() == "---" or line.startswith("--- "):
            docs.append(buffer)
            buffer = [line[4:]] if line.startswith("--- ") else []
        elif line.rstrip() == "...":
            continue
        else:
            buffer.append(line)
    docs.append(buffer)

    out = []
    for doc in docs:
        reader = _Reader(doc)
        if not reader.rows:
            continue
        value, _ = reader.parse(0, reader.rows[0][0])
        if value:
            out.append(value)
    return out


def load(text: str):
    """The first document, or None."""
    docs = load_all(text)
    return docs[0] if docs else None
