"""Ontology extractors — data_ontology and api_ontology.

`code_ontology` reads what the language declares. These read what the *framework*
declares, which is a different thing and usually the thing a question is actually about.
Nobody asks "which class inherits Base"; they ask which table the orders endpoint
writes to.

**One file can feed several ontologies.** A Python module holding SQLAlchemy models is
code_ontology *and* data_ontology: the class is a class, and it is also an entity with a
table name. So an extractor appends to the file's result rather than replacing it, and a
file's rows are still replaced as one unit.

**Framework detection is a guess about intent, and it is marked as one.** A class
inheriting something called `Base` is probably a SQLAlchemy model and might be anything
at all. Where the evidence is a real declaration — `__tablename__`, `CREATE TABLE`, an
OpenAPI document — the tier is `native`. Where it is a naming convention, the tier is
`query`, and `index_health` reports the split. The point is never to be certain;
it is to be honest about which one you are looking at.
"""
from __future__ import annotations
import ast
import json
import re

from .schema import Edge, Symbol

# ── data_ontology ──────────────────────────────────────────────────────────────

#: Base classes that mean "this is a persisted entity". Naming conventions, so anything
#: found this way is tier 2 — the class really might just be called Model.
ORM_BASES = {"Base", "Model", "models.Model", "DeclarativeBase", "SQLModel",
             "db.Model", "BaseModel"}

#: Calls that declare a field. `Column` and `Field` are SQLAlchemy and SQLModel;
#: `models.*Field` is Django.
FIELD_CALLS = re.compile(r"^(Column|Field|mapped_column|models\.\w*Field)$")

#: Calls that declare a reference to another entity.
REF_CALLS = re.compile(r"^(ForeignKey|models\.ForeignKey|models\.OneToOneField|"
                       r"models\.ManyToManyField|relationship)$")


def _call_path(node: ast.AST) -> str:
    """Dotted name of a call target: `models.CharField` from `models.CharField(...)`."""
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _reference_targets(node: ast.AST) -> list[str]:
    """Every entity a field declaration points at, however deeply it is nested."""
    found: list[str] = []
    for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
        if not REF_CALLS.match(_call_path(call)):
            continue
        for arg in call.args:
            target = _literal(arg) or _call_path(arg)
            if target:
                # `"orgs.id"` names a column; the entity is the part before the dot.
                found.append(target.split(".")[0])
                break
    return found


def _literal(node: ast.AST) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def data_ontology_from_python(path: str, tree: ast.AST) -> tuple[list[Symbol], list[Edge], bool]:
    """Entities and fields from SQLAlchemy, Django or SQLModel classes.

    Returns the third value True when at least one entity was found by a real
    declaration (`__tablename__`) rather than by a base-class name.
    """
    symbols: list[Symbol] = []
    edges: list[Edge] = []
    certain = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {_call_path(b) for b in node.bases}
        table = ""
        for stmt in node.body:
            if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "__tablename__"):
                table = _literal(stmt.value)

        if not table and not (bases & ORM_BASES):
            continue

        # A declared table name is evidence. A base class called Model is a guess.
        tier = "native" if table else "query"
        certain = certain or bool(table)
        entity = f"{path}::{node.name}"
        symbols.append(Symbol(entity, "Entity", path, node.lineno,
                              getattr(node, "end_lineno", 0) or 0, tier,
                              summary=f"table {table}" if table else
                                      f"inherits {', '.join(sorted(bases)) or 'nothing'}"))
        if table:
            edges.append(Edge(entity, "MAPS_TO", table, tier))

        for stmt in node.body:
            if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)):
                continue
            name = stmt.targets[0].id
            if name.startswith("__"):
                continue
            called = _call_path(stmt.value) if isinstance(stmt.value, ast.Call) else ""
            if not FIELD_CALLS.match(called) and not REF_CALLS.match(called):
                continue
            field = f"{entity}.{name}"
            symbols.append(Symbol(field, "Field", path, stmt.lineno,
                                  getattr(stmt, "end_lineno", 0) or 0, tier,
                                  summary=called))
            edges.append(Edge(entity, "HAS_FIELD", field, tier))

            # A foreign key is usually an argument to the column, not the column:
            # `Column(Integer, ForeignKey("orgs.id"))`. Django puts it at the top —
            # `models.ForeignKey(Org, ...)` — so both shapes are searched, and looking
            # only at the outer call missed every SQLAlchemy relation in the file.
            for target in _reference_targets(stmt.value):
                edges.append(Edge(entity, "REFERENCES", target, tier))
    return symbols, edges, certain


#: `CREATE TABLE [IF NOT EXISTS] [schema.]name (`  — the name, however it is quoted.
SQL_TABLE = re.compile(
    r"""CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"""
    r"""[`"\[]?(?:\w+[`"\]]?\.[`"\[]?)?(\w+)""", re.I)
SQL_INDEX = re.compile(
    r"""CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?(\w+)[`"\]]?"""
    r"""\s+ON\s+[`"\[]?(\w+)""", re.I)
SQL_COLUMN = re.compile(r"""^\s*[`"\[]?(\w+)[`"\]]?\s+"""
                        r"""(INTEGER|INT|BIGINT|SMALLINT|SERIAL|TEXT|VARCHAR|CHAR|"""
                        r"""BOOLEAN|BOOL|DATE|TIMESTAMP|DATETIME|NUMERIC|DECIMAL|"""
                        r"""REAL|FLOAT|DOUBLE|JSON|JSONB|UUID|BLOB|BYTEA)""", re.I)
SQL_REFS = re.compile(r"""REFERENCES\s+[`"\[]?(\w+)""", re.I)


def data_ontology_from_sql(path: str, source: str) -> tuple[list[Symbol], list[Edge]]:
    """Tables, columns and indexes from DDL. A `CREATE TABLE` is not a guess."""
    symbols: list[Symbol] = []
    edges: list[Edge] = []
    lines = source.splitlines()
    current = ""

    for i, line in enumerate(lines, 1):
        table = SQL_TABLE.search(line)
        if table:
            current = f"{path}::{table.group(1)}"
            symbols.append(Symbol(current, "Entity", path, i, 0, "native",
                                  summary=f"table {table.group(1)}"))
            edges.append(Edge(current, "MAPS_TO", table.group(1), "native"))
            continue

        index = SQL_INDEX.search(line)
        if index:
            name = f"{path}::{index.group(1)}"
            symbols.append(Symbol(name, "Index", path, i, 0, "native",
                                  summary=f"on {index.group(2)}"))
            edges.append(Edge(name, "INDEXES", f"{path}::{index.group(2)}", "native"))
            continue

        if not current:
            continue
        if line.strip().startswith(")"):
            current = ""
            continue
        column = SQL_COLUMN.match(line)
        if column:
            field = f"{current}.{column.group(1)}"
            symbols.append(Symbol(field, "Field", path, i, 0, "native",
                                  summary=column.group(2).lower()))
            edges.append(Edge(current, "HAS_FIELD", field, "native"))
            ref = SQL_REFS.search(line)
            if ref:
                edges.append(Edge(current, "REFERENCES", ref.group(1), "native"))
    return symbols, edges


PRISMA_MODEL = re.compile(r"^\s*model\s+(\w+)\s*\{")
PRISMA_FIELD = re.compile(r"^\s*(\w+)\s+(\w+)(\[\])?(\?)?")
PRISMA_MAP = re.compile(r"""@@map\(\s*["'](\w+)["']\s*\)""")


def data_ontology_from_prisma(path: str, source: str) -> tuple[list[Symbol], list[Edge]]:
    """A Prisma schema says outright what it is, so all of this is tier 1."""
    symbols: list[Symbol] = []
    edges: list[Edge] = []
    current = ""
    for i, line in enumerate(source.splitlines(), 1):
        model = PRISMA_MODEL.match(line)
        if model:
            current = f"{path}::{model.group(1)}"
            symbols.append(Symbol(current, "Entity", path, i, 0, "native",
                                  summary=f"model {model.group(1)}"))
            edges.append(Edge(current, "MAPS_TO", model.group(1), "native"))
            continue
        if not current:
            continue
        if line.strip() == "}":
            current = ""
            continue
        mapped = PRISMA_MAP.search(line)
        if mapped:
            edges.append(Edge(current, "MAPS_TO", mapped.group(1), "native"))
            continue
        field = PRISMA_FIELD.match(line)
        if field and not line.lstrip().startswith(("//", "@@")):
            name, kind = field.group(1), field.group(2)
            full = f"{current}.{name}"
            symbols.append(Symbol(full, "Field", path, i, 0, "native", summary=kind))
            edges.append(Edge(current, "HAS_FIELD", full, "native"))
            if kind[:1].isupper():          # a relation to another model
                edges.append(Edge(current, "REFERENCES", kind, "native"))
    return symbols, edges


# ── api_ontology ──────────────────────────────────────────────────────────────

METHODS = ("get", "post", "put", "patch", "delete", "head", "options")

#: Decorators that route: `@app.get("/x")`, `@router.post(...)`, `@app.route("/x")`,
#: `@blueprint.route(...)`. The attribute is the method; `route` takes it as a keyword.
ROUTE_ATTRS = set(METHODS) | {"route"}


def api_ontology_from_python(path: str, tree: ast.AST) -> tuple[list[Symbol], list[Edge]]:
    """Endpoints from FastAPI and Flask decorators, joined to the function beneath.

    This is where `link` costs nothing: the decorator is attached to the function in the
    tree, so the endpoint and its handler arrive already connected. Everywhere else the
    join has to be inferred; here it is a fact.
    """
    symbols: list[Symbol] = []
    edges: list[Edge] = []

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                handler = f"{owner}.{child.name}" if owner != path else f"{path}::{child.name}"
                for dec in child.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    attr = _call_path(dec).rsplit(".", 1)[-1]
                    if attr not in ROUTE_ATTRS:
                        continue
                    route = next((_literal(a) for a in dec.args if _literal(a)), "")
                    if not route:
                        continue
                    verbs = [attr.upper()] if attr in METHODS else []
                    if attr == "route":
                        for kw in dec.keywords:
                            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                                verbs = [_literal(e).upper() for e in kw.value.elts if _literal(e)]
                        verbs = verbs or ["GET"]
                    for verb in verbs:
                        endpoint = f"{path}::{verb} {route}"
                        symbols.append(Symbol(endpoint, "Endpoint", path, dec.lineno,
                                              0, "native", summary=f"{verb} {route}"))
                        edges.append(Edge(endpoint, "HANDLED_BY", handler, "native"))
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{path}::{child.name}")
                continue
            visit(child, owner)

    visit(tree, path)
    return symbols, edges


#: `app.get('/users', handler)` / `router.post("/x", ...)` in Express and friends.
JS_ROUTE = re.compile(
    r"""\b(?:app|router|server)\.(get|post|put|patch|delete|head|options)\s*\(\s*"""
    r"""['"`]([^'"`]+)['"`]""", re.I)

#: Spring: `@GetMapping("/users")`, `@RequestMapping(value = "/x", ...)`.
JAVA_ROUTE = re.compile(
    r"""@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?"""
    r"""["']([^"']+)["']""")


def api_ontology_from_pattern(path: str, source: str, lang: str) -> tuple[list[Symbol], list[Edge]]:
    """Routes a pattern can see. Tier 2: the handler is not reliably adjacent."""
    pattern = JS_ROUTE if lang in ("javascript", "typescript") else JAVA_ROUTE
    symbols: list[Symbol] = []
    for i, line in enumerate(source.splitlines(), 1):
        for m in pattern.finditer(line):
            verb = m.group(1).upper()
            verb = "ANY" if verb == "REQUEST" else verb
            route = m.group(2)
            symbols.append(Symbol(f"{path}::{verb} {route}", "Endpoint", path, i, 0,
                                  "query", summary=f"{verb} {route}"))
    return symbols, []


def _spec_symbols(path: str, doc: dict, tier: str) -> tuple[list[Symbol], list[Edge]]:
    """Shared by the JSON and YAML readers once a `paths` mapping is in hand."""
    symbols: list[Symbol] = []
    edges: list[Edge] = []
    title = (doc.get("info") or {}).get("title") or path
    service = f"{path}::{title}"
    symbols.append(Symbol(service, "Service", path, 1, 0, tier, summary=title))

    for route, operations in (doc.get("paths") or {}).items():
        if not isinstance(operations, dict):
            continue
        for verb, body in operations.items():
            if verb.lower() not in METHODS:
                continue
            endpoint = f"{path}::{verb.upper()} {route}"
            summary = (body or {}).get("summary", "") if isinstance(body, dict) else ""
            symbols.append(Symbol(endpoint, "Endpoint", path, 1, 0, tier,
                                  summary=summary or f"{verb.upper()} {route}"))
            edges.append(Edge(service, "EXPOSES", endpoint, tier))

            operation_id = (body or {}).get("operationId") if isinstance(body, dict) else ""
            if operation_id:
                op = f"{path}::{operation_id}"
                symbols.append(Symbol(op, "Operation", path, 1, 0, tier,
                                      summary=operation_id))
                edges.append(Edge(endpoint, "HANDLED_BY", op, tier))

            for param in (body or {}).get("parameters", []) if isinstance(body, dict) else []:
                if not isinstance(param, dict) or not param.get("name"):
                    continue
                name = f"{endpoint}({param['name']})"
                symbols.append(Symbol(name, "Parameter", path, 1, 0, tier,
                                      summary=param.get("in", "")))
                edges.append(Edge(name, "PARAMETER_OF", endpoint, tier))
    return symbols, edges


def api_ontology_from_json(path: str, source: str) -> tuple[list[Symbol], list[Edge]] | None:
    """An OpenAPI document in JSON. Parsed properly, so tier 1."""
    try:
        doc = json.loads(source)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or not (doc.get("openapi") or doc.get("swagger")):
        return None
    return _spec_symbols(path, doc, "native")


#: Indentation-aware, and deliberately small. There is no YAML parser in the standard
#: library, and pulling one in for this would put a dependency in a project whose whole
#: claim is that it has none. So the reader understands exactly the shape an OpenAPI
#: document has — `paths:`, a route, a verb — and everything it reads is tier 2 and
#: says so. A spec it cannot follow produces nothing rather than something wrong.
YAML_KEY = re.compile(r"^(\s*)([^\s#][^:]*):\s*(.*)$")


def api_ontology_from_yaml(path: str, source: str) -> tuple[list[Symbol], list[Edge]] | None:
    lines = source.splitlines()
    if not any(re.match(r"^(openapi|swagger)\s*:", ln) for ln in lines[:40]):
        return None

    title, paths, in_paths, base = "", {}, False, 0
    route = verb = None
    for line in lines:
        match = YAML_KEY.match(line)
        if not match:
            continue
        indent, key, value = len(match.group(1)), match.group(2).strip(), match.group(3).strip()
        if key == "title" and not title:
            title = value.strip("'\"")
        if key == "paths" and not value:
            in_paths, base, route, verb = True, indent, None, None
            continue
        if not in_paths:
            continue
        if indent <= base and key != "paths":
            in_paths = False
            continue
        if key.startswith("/"):
            route, verb = key, None
            paths[route] = {}
        elif route and key.lower() in METHODS:
            verb = key.lower()
            paths[route][verb] = {"summary": ""}
        elif verb and key == "summary":
            # The one line worth carrying. An endpoint's summary is what lets an agent
            # decide it has the wrong one without fetching anything at all.
            paths[route][verb]["summary"] = value.strip("'\"")
        elif verb and indent <= base + 4:
            verb = None                     # left the operation block
    if not paths:
        return None
    return _spec_symbols(path, {"info": {"title": title}, "paths": paths}, "query")


# ── deploy_ontology ────────────────────────────────────────────────────────

#: Manifest kinds that actually run something. A ConfigMap configures and a Service
#: routes; neither is a thing with a process in it, and calling them Deployables would
#: make "what runs this" return objects that do not run.
K8S_RUNNERS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob",
               "ReplicaSet", "Pod", "Rollout"}

DOCKER_FROM = re.compile(r"^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?", re.I)
DOCKER_ENV = re.compile(r"^\s*ENV\s+(.*)$", re.I)
DOCKER_ARG = re.compile(r"^\s*ARG\s+(\w+)", re.I)
DOCKER_EXPOSE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.I)
#: `CMD ["uvicorn", "api:app"]`, `ENTRYPOINT python -m worker`, `CMD node server.js`.
DOCKER_RUN = re.compile(r"^\s*(?:CMD|ENTRYPOINT)\s+(.*)$", re.I)
#: A token that looks like it names code in this repository rather than a binary.
CODE_REF = re.compile(r"^([\w./-]+?)(?::[\w.]+)?$")
NOT_CODE = {"python", "python3", "node", "npm", "yarn", "sh", "bash", "-m", "-c",
            "uvicorn", "gunicorn", "celery", "flask", "django-admin", "manage.py",
            "exec", "/bin/sh", "/bin/bash", "serve", "start", "run"}


def deploy_from_dockerfile(path: str, source: str) -> tuple[list[Symbol], list[Edge]]:
    """Images a Dockerfile builds, and the variables it bakes in.

    A `FROM ... AS name` stage is an image in its own right: a multi-stage build is the
    usual way a repository produces both a builder and a runtime, and reporting only the
    last one loses the half that installs everything.
    """
    symbols: list[Symbol] = []
    edges: list[Edge] = []
    stages: list[str] = []

    for i, line in enumerate(source.splitlines(), 1):
        base = DOCKER_FROM.match(line)
        if base:
            # An unnamed stage is numbered, not named after the file: `Dockerfile::
            # Dockerfile` read like a mistake, and a multi-stage build has several.
            named = base.group(2) or f"stage-{len(stages) + 1}"
            image = f"{path}::{named}"
            symbols.append(Symbol(image, "Image", path, i, 0, "native",
                                  summary=f"from {base.group(1)}"))
            if stages:
                edges.append(Edge(stages[-1], "BUILDS", image, "native"))
            stages.append(image)
            continue
        if not stages:
            continue

        env = DOCKER_ENV.match(line)
        arg = DOCKER_ARG.match(line)
        names: list[str] = []
        if env:
            body = env.group(1)
            names = ([body.split("=", 1)[0].strip()] if "=" in body
                     else body.split()[:1])
        elif arg:
            names = [arg.group(1)]
        for name in [n for n in names if n]:
            var = f"{path}::{name}"
            symbols.append(Symbol(var, "EnvVar", path, i, 0, "native", summary=name))
            edges.append(Edge(stages[-1], "CONFIGURES", var, "native"))

        # An EXPOSE declares a port on the image, not a second thing to deploy. It
        # used to become a Deployable, which produced a row saying the image ran
        # itself — true, useless, and in the way of every real answer.
        port = DOCKER_EXPOSE.match(line)
        if port:
            for sym in symbols:
                if sym.name == stages[-1]:
                    symbols[symbols.index(sym)] = Symbol(
                        sym.name, sym.kind, sym.path, sym.line, sym.end_line, sym.tier,
                        summary=f"{sym.summary}, port {port.group(1)}")
                    break

        run = DOCKER_RUN.match(line)
        if run:
            for token in _command_tokens(run.group(1)):
                if token.lower() in NOT_CODE or not CODE_REF.match(token):
                    continue
                # A bare name here — `api` from `api:app`. The link pass decides
                # whether this repository actually declares a module by that name.
                edges.append(Edge(stages[-1], "DEPLOYS",
                                  token.split(":")[0], "query"))
    return symbols, edges


def _command_tokens(raw: str) -> list[str]:
    """Words from either form a CMD takes: a JSON array, or a bare shell line."""
    body = raw.strip()
    if body.startswith("["):
        try:
            parsed = json.loads(body)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return body.split()


def _env_pairs(block) -> list[str]:
    """Variable names from either shape an environment block takes.

    Compose and Kubernetes each allow two, and a file usually mixes them:
        environment: [A=1, B=2]      environment: {A: 1}
        env: [{name: A, value: 1}]
    """
    names: list[str] = []
    if isinstance(block, dict):
        names += [str(k) for k in block]
    elif isinstance(block, list):
        for item in block:
            if isinstance(item, dict):
                if item.get("name"):
                    names.append(str(item["name"]))
                else:
                    names += [str(k) for k in item]
            elif isinstance(item, str) and "=" in item:
                names.append(item.split("=", 1)[0].strip())
            elif isinstance(item, str):
                names.append(item.strip())
    return [n for n in names if n]


def deploy_from_compose(path: str, doc: dict) -> tuple[list[Symbol], list[Edge]]:
    services = doc.get("services")
    if not isinstance(services, dict):
        return [], []
    symbols: list[Symbol] = []
    edges: list[Edge] = []
    for name, spec in services.items():
        if not isinstance(spec, dict):
            continue
        service = f"{path}::{name}"
        symbols.append(Symbol(service, "Deployable", path, 1, 0, "query", summary=name))
        image = spec.get("image")
        if isinstance(image, str):
            ref = f"{path}::image:{image}"
            symbols.append(Symbol(ref, "Image", path, 1, 0, "query", summary=image))
            edges.append(Edge(service, "RUNS", ref, "query"))
        for var in _env_pairs(spec.get("environment")):
            ref = f"{path}::{var}"
            symbols.append(Symbol(ref, "EnvVar", path, 1, 0, "query", summary=var))
            edges.append(Edge(service, "CONFIGURES", ref, "query"))
    return symbols, edges


def deploy_from_k8s(path: str, doc: dict) -> tuple[list[Symbol], list[Edge]]:
    kind = doc.get("kind")
    if kind not in K8S_RUNNERS:
        return [], []
    name = ((doc.get("metadata") or {}).get("name")
            if isinstance(doc.get("metadata"), dict) else None) or kind
    workload = f"{path}::{name}"
    symbols = [Symbol(workload, "Deployable", path, 1, 0, "query",
                      summary=f"{kind} {name}")]
    edges: list[Edge] = []

    def containers(node):
        """Containers sit at different depths in different kinds, so walk for them."""
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("containers", "initContainers") and isinstance(value, list):
                    yield from (c for c in value if isinstance(c, dict))
                else:
                    yield from containers(value)
        elif isinstance(node, list):
            for item in node:
                yield from containers(item)

    for container in containers(doc):
        image = container.get("image")
        if isinstance(image, str):
            ref = f"{path}::image:{image}"
            symbols.append(Symbol(ref, "Image", path, 1, 0, "query", summary=image))
            edges.append(Edge(workload, "RUNS", ref, "query"))
        for var in _env_pairs(container.get("env")):
            ref = f"{path}::{var}"
            symbols.append(Symbol(ref, "EnvVar", path, 1, 0, "query", summary=var))
            edges.append(Edge(workload, "CONFIGURES", ref, "query"))
    return symbols, edges


#: A job whose name or script suggests it puts something somewhere.
DEPLOYING = re.compile(r"deploy|release|ship|rollout|publish|promote", re.I)


def deploy_from_pipeline(path: str, doc: dict) -> tuple[list[Symbol], list[Edge]]:
    """GitHub Actions and GitLab CI. Both are "a pipeline with named stages"."""
    jobs = doc.get("jobs")
    gitlab = False
    if not isinstance(jobs, dict):
        # GitLab has no `jobs:` key — every top-level mapping that is not a reserved
        # word is a job. `stages:` is the giveaway that this is one at all.
        if not isinstance(doc.get("stages"), list):
            return [], []
        reserved = {"stages", "variables", "default", "include", "workflow",
                    "image", "services", "before_script", "after_script", "cache"}
        jobs = {k: v for k, v in doc.items()
                if k not in reserved and isinstance(v, dict)}
        gitlab = True
    if not jobs:
        return [], []

    name = doc.get("name") if isinstance(doc.get("name"), str) else path.rsplit("/", 1)[-1]
    pipeline = f"{path}::{name}"
    symbols = [Symbol(pipeline, "Pipeline", path, 1, 0, "query", summary=name)]
    edges: list[Edge] = []

    for job, spec in jobs.items():
        stage = f"{path}::{job}"
        summary = job
        if isinstance(spec, dict) and isinstance(spec.get("stage"), str):
            summary = f"{job} ({spec['stage']})"
        symbols.append(Symbol(stage, "Stage", path, 1, 0, "query", summary=summary))
        edges.append(Edge(stage, "STAGE_OF", pipeline, "query"))

        body = str(spec) if isinstance(spec, (dict, list)) else ""
        if DEPLOYING.search(job) or (gitlab and DEPLOYING.search(body[:600])):
            # Named, not inferred from the whole script: a job that merely *mentions*
            # deploying is usually building the thing that will be deployed later.
            edges.append(Edge(pipeline, "DEPLOYS", stage, "query"))

        for var in _env_pairs(spec.get("env") if isinstance(spec, dict) else None):
            ref = f"{path}::{var}"
            symbols.append(Symbol(ref, "EnvVar", path, 1, 0, "query", summary=var))
            edges.append(Edge(stage, "CONFIGURES", ref, "query"))
    return symbols, edges


#: `os.environ["X"]`, `os.environ.get("X")`, `os.getenv("X")`, `process.env.X`,
#: `process.env["X"]`, `System.getenv("X")`, `ENV["X"]`.
ENV_READ_PY = re.compile(r"""os\.environ(?:\.get)?\s*[\[(]\s*["'](\w+)["']|"""
                         r"""os\.getenv\s*\(\s*["'](\w+)["']""")
ENV_READ_ANY = re.compile(r"""process\.env(?:\.(\w+)|\[\s*["'](\w+)["']\s*\])|"""
                          r"""System\.getenv\s*\(\s*["'](\w+)["']|"""
                          r"""ENV\s*\[\s*["'](\w+)["']""")


def env_reads(path: str, source: str, lang: str | None) -> list[tuple[int, str]]:
    """Every environment variable this file reads, with its line.

    Not a symbol of its own — a read is not a declaration. These become `CONFIGURED_BY`
    edges in the link pass, joining the code that reads a variable to the manifest that
    sets it. That join answers the question nobody can answer by reading one file:
    *if I change this variable, what breaks?*
    """
    pattern = ENV_READ_PY if lang == "python" else ENV_READ_ANY
    found = []
    for i, line in enumerate(source.splitlines(), 1):
        for match in pattern.finditer(line):
            name = next((g for g in match.groups() if g), "")
            if name:
                found.append((i, name))
    return found
