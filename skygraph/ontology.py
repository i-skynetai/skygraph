"""The five ontologies — what may exist in the graph, declared before anything is read.

An ontology is a small contract: these node kinds, these relations, and nothing else.
A front end that emits something undeclared raises at construction rather than writing a
row nobody agreed to. That refusal is the point. A graph is only worth querying if the
shape of it is known in advance; one that grows whatever a parser happened to find is a
pile of rows with a query language attached.

**Why five and not one.** A coding agent asks questions that cross layers. *Which
endpoint writes this table? What deploys the service that owns it? If I change this
column, whose handler breaks?* Each layer has its own vocabulary — an endpoint is not a
function and a table is not a class — so each gets its own ontology, and `link` carries
the joins between them.

`link` is the one that earns the project. `code_ontology` alone is a better `grep`.
The joins are what a text search cannot fake, because they are not written down anywhere
in the source: nothing in a route handler says which table it ends up touching.
"""
from __future__ import annotations
from dataclasses import dataclass

#: How a fact was obtained. Every node and edge records one, and they never mix
#: silently: `native` is a parse, `model` is a guess a language model made, and a caller
#: is entitled to ask for one and not the other.
TIERS = ("native", "query", "model", "heuristic")

#: The tiers that read the code rather than infer it. `index_health` reports the
#: split, because an index that is 90% inferred is a different object from one that is
#: 90% parsed, and an agent cannot tell from the rows.
PARSED_TIERS = ("native", "query")


@dataclass(frozen=True)
class Ontology:
    name: str
    purpose: str
    kinds: tuple[str, ...]
    relations: tuple[str, ...]
    #: What a reader should understand the absence of this ontology to mean.
    absent_means: str


CODE_ONTOLOGY = Ontology(
    name="code_ontology",
    purpose="the code as written: what is declared, what calls what, what imports what",
    kinds=("Module", "Class", "Function", "Method", "Variable"),
    # RE_EXPORTS: a barrel — `export * from './x'`, or a Python `__init__` — passes a
    # module's names on. Not an import: the barrel uses nothing, it forwards.
    relations=("CONTAINS", "CALLS", "IMPORTS", "INHERITS", "RE_EXPORTS"),
    absent_means="no source file in this repository was readable by any tier",
)

DATA_ONTOLOGY = Ontology(
    name="data_ontology",
    purpose="the shapes data is stored in: entities, their fields, and how they relate",
    kinds=("Entity", "Field", "Index", "Enum"),
    relations=("HAS_FIELD", "REFERENCES", "INDEXES", "EXTENDS"),
    absent_means="no ORM model, migration or schema file was found — not that the "
                 "project has no database",
)

API_ONTOLOGY = Ontology(
    name="api_ontology",
    purpose="the contract the outside world sees: endpoints, operations and payloads",
    kinds=("Service", "Endpoint", "Operation", "Payload", "Parameter"),
    relations=("EXPOSES", "ACCEPTS", "RETURNS", "PARAMETER_OF"),
    absent_means="no OpenAPI document or routed handler was found",
)

DEPLOY_ONTOLOGY = Ontology(
    name="deploy_ontology",
    purpose="how it runs: images, services, configuration and the pipelines that ship it",
    kinds=("Image", "Deployable", "EnvVar", "Pipeline", "Stage"),
    relations=("BUILDS", "RUNS", "CONFIGURES", "DEPLOYS", "STAGE_OF"),
    absent_means="no Dockerfile, compose file, manifest or pipeline definition was found",
)

LINK = Ontology(
    name="link",
    purpose="the joins between the layers — the part no single file states",
    kinds=(),                       # link declares no nodes; it only connects them
    relations=("HANDLED_BY",        # Endpoint  → Function/Method
               "PERSISTS_TO",       # Function  → Entity
               "MAPS_TO",           # Entity    → a table or collection name
               "DEPLOYED_BY",       # Service   → Deployable
               "CONFIGURED_BY"),    # Deployable→ EnvVar
    absent_means="the layers were indexed but nothing joined them — usually because "
                 "only one ontology found anything",
)

ONTOLOGIES: dict[str, Ontology] = {
    o.name: o for o in (CODE_ONTOLOGY, DATA_ONTOLOGY, API_ONTOLOGY, DEPLOY_ONTOLOGY, LINK)
}

#: Every kind, and the one ontology that declares it. Two ontologies may not declare the
#: same kind: a row must know which contract it is held to, and a name that means two
#: things is how a graph starts answering the wrong question.
KIND_OWNER: dict[str, str] = {}
RELATION_OWNER: dict[str, str] = {}
for _o in ONTOLOGIES.values():
    for _k in _o.kinds:
        if _k in KIND_OWNER:
            raise RuntimeError(f"kind {_k!r} is declared by two ontologies")
        KIND_OWNER[_k] = _o.name
    for _r in _o.relations:
        if _r in RELATION_OWNER:
            raise RuntimeError(f"relation {_r!r} is declared by two ontologies")
        RELATION_OWNER[_r] = _o.name


def ontology_of_kind(kind: str) -> str:
    try:
        return KIND_OWNER[kind]
    except KeyError:
        raise ValueError(
            f"undeclared kind {kind!r}. No ontology allows it; declared kinds are "
            + ", ".join(sorted(KIND_OWNER))) from None


def ontology_of_relation(relation: str) -> str:
    try:
        return RELATION_OWNER[relation]
    except KeyError:
        raise ValueError(
            f"undeclared relation {relation!r}. No ontology allows it; declared "
            "relations are " + ", ".join(sorted(RELATION_OWNER))) from None


def describe() -> list[dict]:
    """What an agent gets when it asks what this index can even be asked about."""
    return [{"ontology": o.name, "purpose": o.purpose,
             "kinds": list(o.kinds), "relations": list(o.relations),
             "absent_means": o.absent_means} for o in ONTOLOGIES.values()]
