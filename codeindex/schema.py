"""The capture vocabulary — the one thing every language front end must agree on.

The schema is the authority. A front end may only emit kinds and relations declared
here, and the writer refuses anything it does not recognise. That refusal is the point:
a graph that is quietly incomplete produces confident wrong answers, which is worse
than a graph that is loudly missing a language.
"""
from __future__ import annotations
from dataclasses import dataclass, field

#: Node kinds a front end may emit.
KINDS = ("Module", "Class", "Function", "Method", "Variable")

#: Edge kinds a front end may emit.
RELATIONS = ("CONTAINS", "CALLS", "IMPORTS", "INHERITS")

#: How a file was parsed. Tier 1 is a real AST; tier 3 is a guess that says so.
TIERS = ("native", "query", "heuristic")


@dataclass(frozen=True)
class Symbol:
    """One named thing in a file. `name` is `<path>` or `<path>::<symbol>`."""
    name: str
    kind: str
    path: str
    line: int = 0
    tier: str = "native"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"undeclared kind {self.kind!r}; schema allows {KINDS}")
        if self.tier not in TIERS:
            raise ValueError(f"undeclared tier {self.tier!r}; schema allows {TIERS}")


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str

    def __post_init__(self) -> None:
        if self.rel not in RELATIONS:
            raise ValueError(f"undeclared relation {self.rel!r}; schema allows {RELATIONS}")


@dataclass
class FileResult:
    """What one front end returns for one file."""
    path: str
    language: str
    tier: str
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    degraded: str | None = None      #: set when the file fell to a lower tier, and why
