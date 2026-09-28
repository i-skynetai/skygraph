"""The capture vocabulary — the one thing every language front end must agree on.

The kinds and relations themselves are declared in `ontology.py`; this module is the
shape a front end returns and the gate that checks it. A front end may only emit what an
ontology allows, and the writer refuses anything else. That refusal is the point: a
graph that is quietly incomplete produces confident wrong answers, which is worse than a
graph that is loudly missing a language.

Every node and edge records the ontology it belongs to and the tier that produced it.
Those two are what let a caller ask for parsed facts and not a model's guesses, and what
let `index_health` say how much of an index is actually read rather than inferred.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .ontology import (KIND_OWNER, PARSED_TIERS, RELATION_OWNER, TIERS,
                       ontology_of_kind, ontology_of_relation)

#: Every declared kind and relation, flattened across the ontologies. Callers that only
#: want to know "may this exist at all" read these; callers that care which contract a
#: row is held to ask the ontology.
KINDS = tuple(sorted(KIND_OWNER))
RELATIONS = tuple(sorted(RELATION_OWNER))


@dataclass(frozen=True)
class Symbol:
    """One named thing. `name` is `<path>` or `<path>::<symbol>`."""
    name: str
    kind: str
    path: str
    line: int = 0
    #: Last line of the declaration. 0 means the front end could not say — `read_source`
    #: then falls back to a window rather than guessing a range and cutting it wrong.
    end_line: int = 0
    tier: str = "native"
    #: Free-form, one line. What `describe_symbol` returns instead of source text.
    summary: str = ""

    def __post_init__(self) -> None:
        ontology_of_kind(self.kind)             # raises if undeclared
        if self.tier not in TIERS:
            raise ValueError(f"undeclared tier {self.tier!r}; schema allows {TIERS}")

    @property
    def ontology(self) -> str:
        return ontology_of_kind(self.kind)

    @property
    def parsed(self) -> bool:
        """False when a language model produced this rather than a parser."""
        return self.tier in PARSED_TIERS


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str
    tier: str = "native"

    def __post_init__(self) -> None:
        ontology_of_relation(self.rel)          # raises if undeclared
        if self.tier not in TIERS:
            raise ValueError(f"undeclared tier {self.tier!r}; schema allows {TIERS}")

    @property
    def ontology(self) -> str:
        return ontology_of_relation(self.rel)


@dataclass
class FileResult:
    """What one front end returns for one file."""
    path: str
    language: str
    tier: str
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    degraded: str | None = None      #: set when the file fell to a lower tier, and why
    #: Content hash of the source this was built from. The indexer skips a file whose
    #: hash has not moved, which is what makes a second run cost the delta.
    digest: str = ""
