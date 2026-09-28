import json, os, sqlite3, sys, tempfile, unittest
from pathlib import Path
REPO = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(REPO))
from skygraph import frontends, mcp, miniyaml, treesitter
from skygraph.schema import Symbol, Edge, KINDS, RELATIONS
from skygraph.store import Store
from skygraph.indexer import index

PY = "import os\nfrom pkg import thing\n\nclass Alpha:\n    def run(self):\n        os.getcwd()\n        helper()\n\ndef helper():\n    pass\n"
TS = 'import {a} from "./other";\nexport class Beta {}\nexport function go() {}\n'
GO = 'package main\nimport "fmt"\ntype Server struct{}\nfunc Start() {}\n'


class TheSchemaIsTheAuthority(unittest.TestCase):
    def test_an_undeclared_kind_is_refused(self):
        with self.assertRaises(ValueError):
            Symbol("x", "Wombat", "x.py")

    def test_an_undeclared_relation_is_refused(self):
        with self.assertRaises(ValueError):
            Edge("a", "SUMMONS", "b")

    def test_a_declared_one_is_accepted(self):
        self.assertIn(Symbol("x.py::f", "Function", "x.py").kind, KINDS)
        self.assertIn(Edge("a", "CALLS", "b").rel, RELATIONS)


class PythonParsesNatively(unittest.TestCase):
    def setUp(self):
        self.r = frontends.parse("m.py", PY)

    def test_it_is_tier_one(self):
        self.assertEqual(self.r.tier, "native")
        self.assertIsNone(self.r.degraded)

    def test_it_finds_the_class_and_both_functions(self):
        names = {s.name for s in self.r.symbols}
        self.assertIn("m.py::Alpha", names)
        self.assertIn("m.py::Alpha.run", names)
        self.assertIn("m.py::helper", names)

    def test_it_records_calls_and_imports(self):
        calls = {(e.src, e.dst) for e in self.r.edges if e.rel == "CALLS"}
        self.assertIn(("m.py::Alpha.run", "helper"), calls)
        imports = {e.dst for e in self.r.edges if e.rel == "IMPORTS"}
        self.assertEqual(imports, {"os", "pkg"})


class OtherLanguagesAreRead(unittest.TestCase):
    """The declarations must be found whichever tier finds them.

    These used to assert `tier == "query"`, which pinned an implementation detail
    rather than the contract: with tree-sitter installed the same files are parsed
    properly, and the tests failed for being right.
    """

    def test_typescript(self):
        r = frontends.parse("b.ts", TS)
        self.assertIn("b.ts::Beta", {s.name for s in r.symbols})
        self.assertEqual(r.tier, "native" if treesitter.claims("typescript") else "query")

    def test_go(self):
        r = frontends.parse("s.go", GO)
        self.assertIn("s.go::Server", {s.name for s in r.symbols})
        self.assertEqual(r.tier, "native" if treesitter.claims("go") else "query")

    def test_eleven_languages_are_claimed(self):
        self.assertEqual(1 + len(frontends.QUERY_LANGUAGES), 11)

    def test_the_pattern_tier_finds_declarations_and_no_calls(self):
        """The limit that makes tree-sitter worth an install."""
        r = frontends._query("b.ts", TS, "typescript")
        self.assertTrue({s.name for s in r.symbols})
        self.assertEqual([e for e in r.edges if e.rel == "CALLS"], [],
                         "a line pattern cannot see a call, and must not claim to")


TS_REAL = """import { Thing } from './thing';

export class Widget {
  render(): string {
    return this.format(Thing.name);
  }
  format(s: string): string { return s.trim(); }
}

export const build = (): Widget => {
  const w = new Widget();
  return w;
};

export function main() { build(); }
"""

JAVA_REAL = """package com.app;
import com.app.Repo;

public class Service {
    private Repo repo;
    public String fetch(String id) {
        return this.normalise(repo.findById(id));
    }
    private String normalise(String s) { return s.trim(); }
}
"""


class NothingIsLostSilently(unittest.TestCase):
    def test_unparseable_python_degrades_and_says_why(self):
        r = frontends.parse("broken.py", "def f(:\n")
        self.assertEqual(r.tier, "heuristic")
        self.assertIsNotNone(r.degraded)
        self.assertIn("fell to heuristic", r.degraded)

    def test_an_unknown_language_says_it_guessed(self):
        r = frontends.parse("x.zig", "fn main() void {}\n")
        self.assertEqual(r.tier, "heuristic")
        self.assertIn("not by parsing", r.degraded)


class ScopeIsOnTheRow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        s = Store(self.db)
        s.write(frontends.parse("m.py", PY), "alpha", "main")
        s.write(frontends.parse("m.py", PY), "beta", "main")

    def test_a_search_sees_only_its_own_repo(self):
        s = Store(self.db)
        self.assertTrue(s.search("Alpha", "alpha"))
        self.assertTrue(s.search("Alpha", "beta"))

    def test_an_unknown_repo_returns_nothing_rather_than_something_elses(self):
        self.assertEqual(Store(self.db).search("Alpha", "gamma"), [])

    def test_neighbours_are_scoped_too(self):
        self.assertEqual(Store(self.db).neighbours("m.py::Alpha.run", "gamma"), [])


class NeighboursGoBothWays(unittest.TestCase):
    def test_caller_and_callee(self):
        tmp = tempfile.mkdtemp(); db = os.path.join(tmp, "n.db")
        s = Store(db); s.write(frontends.parse("m.py", PY), "r", "main")
        got = s.neighbours("m.py::Alpha.run", "r")
        self.assertIn("helper", {g["other"] for g in got if g["dir"] == "out"})


class TheIndexerWalksARepository(unittest.TestCase):
    def test_it_counts_what_it_did(self):
        tmp = tempfile.mkdtemp()
        open(os.path.join(tmp, "a.py"), "w").write(PY)
        open(os.path.join(tmp, "b.ts"), "w").write(TS)
        open(os.path.join(tmp, "c.go"), "w").write(GO)
        os.makedirs(os.path.join(tmp, "node_modules"))
        open(os.path.join(tmp, "node_modules", "skip.js"), "w").write("function nope(){}")
        out = index(tmp, repo="demo", db=os.path.join(tmp, "i.db"))
        self.assertEqual(out["indexed"], 3)       # node_modules is skipped
        self.assertEqual(out["languages"], 3)


class ReIndexingReplacesRatherThanAccumulates(unittest.TestCase):
    """The three ways a stale index answers confidently about code that is not there.

    All three were real. Re-indexing unchanged code doubled every edge each run; a
    renamed symbol kept answering searches; a deleted file stayed in the graph. Each
    one looks exactly like a correct answer from the outside, which is why they get a
    test apiece rather than one combined one.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        self.db = os.path.join(self.tmp, "g.db")
        self._write("a.py", PY)

    def _write(self, name, text):
        with open(os.path.join(self.src, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def _index(self):
        return index(self.tmp, repo="t", db=self.db)

    def test_indexing_unchanged_code_twice_gives_the_same_graph(self):
        first = self._index()
        second = self._index()
        third = self._index()
        for key in ("files", "symbols", "edges"):
            self.assertEqual(first[key], second[key], f"{key} changed on the second run")
            self.assertEqual(second[key], third[key], f"{key} changed on the third run")
        self.assertGreater(first["edges"], 0, "the fixture should produce edges at all")

    def test_a_renamed_symbol_stops_answering_searches(self):
        self._index()
        self.assertTrue(Store(self.db).search("Alpha", "t"))
        self._write("a.py", PY.replace("class Alpha:", "class Gamma:"))
        self._index()
        store = Store(self.db)
        self.assertEqual(store.search("Alpha", "t"), [],
                         "the old name still resolves after the rename")
        self.assertTrue(store.search("Gamma", "t"), "the new name was not indexed")

    def test_a_deleted_file_leaves_the_graph_and_the_run_says_so(self):
        self._write("b.py", "def beta():\n    pass\n")
        self._index()
        self.assertTrue(Store(self.db).search("beta", "t"))
        os.remove(os.path.join(self.src, "b.py"))
        out = self._index()
        self.assertEqual(out["removed"], 1, "the run did not report the removal")
        self.assertEqual(Store(self.db).search("beta", "t"), [],
                         "a deleted file still answers searches")

    def test_pruning_one_repo_does_not_touch_another(self):
        """Scope is on the row, so a prune must respect it like every other write."""
        self._index()
        other = Store(self.db)
        other.write(frontends.parse("only.py", PY), "other-repo", "main")
        index(self.tmp, repo="t", db=self.db)
        self.assertTrue(Store(self.db).search("Alpha", "other-repo"),
                        "indexing one repo pruned another repo's rows")

    def test_an_index_from_an_older_schema_is_rebuilt_and_says_so(self):
        """An index is derived from source, so a schema change rebuilds it — loudly."""
        self._index()
        raw = sqlite3.connect(self.db)
        raw.execute("PRAGMA user_version = 0")
        raw.commit()
        raw.close()
        store = Store(self.db)
        self.assertTrue(store.rebuilt, "the stale index was discarded without saying so")
        self.assertEqual(store.search("Alpha", "t"), [])


class TheOntologiesAreTheContract(unittest.TestCase):
    def test_every_kind_belongs_to_exactly_one_ontology(self):
        from skygraph import ontology
        self.assertEqual(len(ontology.KIND_OWNER),
                         sum(len(o.kinds) for o in ontology.ONTOLOGIES.values()))

    def test_a_kind_no_ontology_declares_is_refused_at_construction(self):
        with self.assertRaises(ValueError) as caught:
            Symbol("x", "Wombat", "x.py")
        self.assertIn("undeclared kind", str(caught.exception))

    def test_a_symbol_knows_which_ontology_holds_it(self):
        self.assertEqual(Symbol("a::C", "Class", "a").ontology, "code_ontology")
        self.assertEqual(Symbol("a::E", "Entity", "a").ontology, "data_ontology")
        self.assertEqual(Symbol("a::P", "Endpoint", "a").ontology, "api_ontology")

    def test_link_declares_relations_but_no_kinds(self):
        """link joins nodes other ontologies own; a join that owned nodes would be one."""
        from skygraph.ontology import LINK
        self.assertEqual(LINK.kinds, ())
        self.assertTrue(LINK.relations)

    def test_a_model_made_fact_is_not_a_parsed_one(self):
        """The distinction the whole health report rests on."""
        self.assertTrue(Symbol("a::f", "Function", "a", tier="native").parsed)
        self.assertTrue(Symbol("a::f", "Function", "a", tier="query").parsed)
        self.assertFalse(Symbol("a::f", "Function", "a", tier="model").parsed)


class AnUnchangedFileIsNotReadAgain(unittest.TestCase):
    """The economic argument, tested rather than asserted in a README.

    An index that re-parses everything on every run has the same flaw as an agent that
    re-reads the folder every session, one layer down.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "g.db")
        self._write("a.py", PY)
        self._write("b.py", "def beta():\n    pass\n")

    def _write(self, name, text):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_a_second_run_over_untouched_code_reads_nothing(self):
        first = index(self.tmp, repo="r", db=self.db)
        self.assertEqual(first["indexed"], 2)
        self.assertEqual(first["unchanged"], 0)
        second = index(self.tmp, repo="r", db=self.db)
        self.assertEqual(second["indexed"], 0, "an unchanged file was read again")
        self.assertEqual(second["unchanged"], 2)

    def test_touching_one_file_costs_one_file(self):
        index(self.tmp, repo="r", db=self.db)
        self._write("b.py", "def beta():\n    return 2\n")
        out = index(self.tmp, repo="r", db=self.db)
        self.assertEqual(out["indexed"], 1)
        self.assertEqual(out["unchanged"], 1)

    def test_rewriting_a_file_with_the_same_bytes_is_still_unchanged(self):
        """The check is the content, not the timestamp."""
        index(self.tmp, repo="r", db=self.db)
        self._write("b.py", "def beta():\n    pass\n")          # identical text
        self.assertEqual(index(self.tmp, repo="r", db=self.db)["indexed"], 0)

    def test_full_forces_a_reread(self):
        index(self.tmp, repo="r", db=self.db)
        self.assertEqual(index(self.tmp, repo="r", db=self.db, full=True)["indexed"], 2)


class CallTargetsAreResolvedAcrossFiles(unittest.TestCase):
    """The reason this is a graph and not a search box.

    A parser sees `helper()` and can honestly report only the word. Which declaration
    that is takes the whole repository, so it is resolved after every file is in.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "g.db")

    def _write(self, name, text):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_a_call_reaches_a_callee_in_another_file(self):
        self._write("caller.py", "from util import helper\n\ndef go():\n    return helper()\n")
        self._write("util.py", "def helper():\n    return 1\n")
        out = index(self.tmp, repo="r", db=self.db)
        self.assertEqual(out["calls"]["resolved"], 1)
        hops = Store(self.db).neighbours("util.py::helper", "r", rels=("CALLS",))
        self.assertIn("caller.py::go", [h["other"] for h in hops if h["dir"] == "in"],
                      "the caller in another file was not reachable from the callee")

    def test_an_ambiguous_name_is_left_bare_rather_than_guessed(self):
        """Two declarations share the name, so picking one would be wrong half the time.

        A missing edge makes an agent look. A wrong edge makes it confident.
        """
        self._write("one.py", "def run():\n    pass\n")
        self._write("two.py", "def run():\n    pass\n")
        self._write("caller.py", "def go():\n    return run()\n")
        out = index(self.tmp, repo="r", db=self.db)
        self.assertEqual(out["calls"]["ambiguous"], 1)
        self.assertEqual(out["calls"]["resolved"], 0)
        row = Store(self.db).db.execute(
            "SELECT dst, resolution FROM edges WHERE rel='CALLS' AND src=?",
            ("caller.py::go",)).fetchone()
        self.assertEqual(row["dst"], "run", "an ambiguous target was resolved anyway")
        self.assertEqual(row["resolution"], "ambiguous")

    def test_a_call_to_something_outside_the_repo_is_marked_external(self):
        self._write("a.py", "import json\n\ndef go():\n    return json.dumps({})\n")
        out = index(self.tmp, repo="r", db=self.db)
        self.assertGreaterEqual(out["calls"]["external"], 1)

    def test_the_health_report_shows_the_split(self):
        self._write("one.py", "def run():\n    pass\n")
        self._write("two.py", "def run():\n    pass\n")
        self._write("caller.py", "def go():\n    return run()\n")
        index(self.tmp, repo="r", db=self.db)
        report = Store(self.db).health("r")
        self.assertIn("ambiguous", report["call_edges"])
        self.assertIn("ambiguous", report["call_note"])


class GetSourceIsTheOnlyToolThatFetchesCode(unittest.TestCase):
    def setUp(self):
        from skygraph import tools as surface
        self.surface = surface
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "g.db")
        with open(os.path.join(self.tmp, "a.py"), "w", encoding="utf-8") as fh:
            fh.write(PY)
        index(self.tmp, repo="r", db=self.db)
        self.store = Store(self.db)

    def test_describe_symbol_never_returns_source(self):
        out = self.surface.describe_symbol(self.store, {"qualified_name": "a.py::Alpha"})
        self.assertNotIn("source", out)
        self.assertTrue(out["result"], "the symbol should have been found")

    def test_read_source_returns_the_exact_range_when_the_tier_knows_it(self):
        out = self.surface.read_source(self.store, {"qualified_name": "a.py::Alpha"})
        self.assertTrue(out["exact_range"])
        self.assertIn("class Alpha", out["source"])
        self.assertFalse(out["truncated"])

    def test_a_miss_offers_near_matches_rather_than_nothing(self):
        out = self.surface.describe_symbol(self.store, {"qualified_name": "zzz.py::Alpha"})
        self.assertEqual(out["result"], {})
        self.assertTrue(out["near_matches"], "a near miss returned no suggestion")

    def test_reading_an_index_older_than_the_tree_says_so(self):
        os.remove(os.path.join(self.tmp, "a.py"))
        out = self.surface.read_source(self.store, {"qualified_name": "a.py::Alpha"})
        self.assertIn("re-run", out.get("error", ""))


SQLALCHEMY = """from sqlalchemy import Column, Integer, String, ForeignKey
from db import Base

class Org(Base):
    __tablename__ = "orgs"
    id = Column(Integer, primary_key=True)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("orgs.id"))
"""

DJANGO = """from django.db import models

class Team(models.Model):
    name = models.CharField(max_length=50)

class Member(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
"""

FASTAPI = """from fastapi import FastAPI
from models import User

app = FastAPI()

@app.get("/users/{user_id}")
def read_user(user_id: int):
    return User(id=user_id)

@app.post("/users")
def create_user(email: str):
    return User(email=email)
"""

DDL = """CREATE TABLE orgs (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  org_id INTEGER REFERENCES orgs(id)
);

CREATE INDEX ix_users_org ON users (org_id);
"""

SPEC_YAML = """openapi: 3.0.0
info:
  title: Billing API
paths:
  /invoices:
    get:
      summary: List invoices
    post:
      summary: Create one
"""


class _Indexed(unittest.TestCase):
    """Write files, index them, query the result."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "g.db")

    def write(self, name, text):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def build(self):
        self.out = index(self.tmp, repo="r", db=self.db)
        self.store = Store(self.db)
        return self.out

    def entities(self):
        return {r["name"]: r for r in self.store.search("", "r", ontology="data_ontology",
                                                        limit=200)
                if r["kind"] == "Entity"}

    def endpoints(self):
        return {r["summary"]: r for r in self.store.search("", "r", ontology="api_ontology",
                                                           limit=200)
                if r["kind"] == "Endpoint"}

    def rel(self, name):
        return [(r["src"], r["dst"]) for r in self.store.db.execute(
            "SELECT src, dst FROM edges WHERE rel=? ORDER BY src, dst", (name,))]


class TreeSitterIsTierOneWhenInstalled(_Indexed):
    """Optional, because a parser for thirty languages is not worth making everyone
    take a dependency — but it is the only tier that can see a call."""

    def setUp(self):
        super().setUp()
        if not treesitter.available():
            self.skipTest("tree-sitter is not installed")

    def test_typescript_methods_and_calls(self):
        self.write("widget.ts", TS_REAL)
        self.build()
        names = {r["name"] for r in self.store.search("", "r", limit=200)}
        self.assertIn("widget.ts::Widget.render", names, "methods were not found")
        self.assertIn("widget.ts::build", names, "an arrow function bound to a const")
        self.assertIn(("widget.ts::Widget.render", "widget.ts::Widget.format"),
                      self.rel("CALLS"), "`this.format()` did not reach the method")
        self.assertIn(("widget.ts::main", "widget.ts::build"), self.rel("CALLS"))

    def test_java_methods_and_calls(self):
        self.write("Service.java", JAVA_REAL)
        self.build()
        self.assertIn(("Service.java::Service.fetch",
                       "Service.java::Service.normalise"), self.rel("CALLS"))

    def test_a_receiver_it_cannot_follow_is_not_guessed(self):
        """Same rule as Python: an unknown receiver is never resolved."""
        self.write("widget.ts", TS_REAL)
        self.build()
        resolved = {s for s, _ in self.rel("CALLS")}
        rows = self.store.db.execute(
            "SELECT raw_dst, resolution FROM edges WHERE rel='CALLS' "
            "AND raw_dst = 's.trim'").fetchall()
        self.assertTrue(rows)
        self.assertNotEqual(rows[0]["resolution"], "resolved")

    def test_a_relative_import_keeps_its_module(self):
        self.write("widget.ts", TS_REAL)
        self.write("thing.ts", "export class Thing { static name = 'x'; }\n")
        self.build()
        rows = [(r["src"], r["raw_dst"], r["dst"], r["resolution"])
                for r in self.store.db.execute(
                    "SELECT src, raw_dst, dst, resolution FROM edges WHERE rel='IMPORTS'")]
        # `raw_dst` is the import as written; `dst` is the file it turned out to be.
        self.assertIn(("widget.ts", "./thing"), [(r[0], r[1]) for r in rows])
        self.assertIn(("widget.ts", "thing.ts", "resolved"),
                      [(r[0], r[2], r[3]) for r in rows])

    def test_the_language_is_reported_traversable(self):
        self.write("widget.ts", TS_REAL)
        self.build()
        coverage = {c["language"]: c for c in self.store.language_coverage("r")}
        self.assertTrue(coverage["typescript"]["traversable"])

    def test_a_file_tree_sitter_chokes_on_falls_to_the_pattern_tier(self):
        self.write("broken.ts", "export class {{{ !!! not typescript at all\n")
        self.build()
        self.assertTrue(self.store.search("", "r", limit=50),
                        "a broken file lost the whole index")


class EveryGrammarKeepsItsReceiver(_Indexed):
    """The 301-caller bug, reborn in a language that names its fields differently.

    `_callee` read `child_by_field_name("function")`, which is what TypeScript calls
    it. Java's `method_invocation` splits the same thing into `object` and `name`, so
    `TenantContext.getTenantId()` was recorded bare — and one method collected 735
    callers across six services, 732 of them wrong.
    """

    def setUp(self):
        super().setUp()
        if not treesitter.available():
            self.skipTest("tree-sitter is not installed")

    def test_java_keeps_the_object_it_was_called_on(self):
        self.write("A.java", "class A {\n"
                             "  String go() { return TenantContext.getTenantId(); }\n}\n")
        self.build()
        raw = [r["raw_dst"] for r in self.store.db.execute(
            "SELECT raw_dst FROM edges WHERE rel='CALLS'")]
        self.assertIn("TenantContext.getTenantId", raw)
        self.assertNotIn("getTenantId", raw, "the receiver was dropped")

    def test_a_java_call_with_no_receiver_stays_bare(self):
        self.write("A.java", "class A {\n  String go() { return helper(); }\n"
                             "  String helper() { return \"x\"; }\n}\n")
        self.build()
        raw = [r["raw_dst"] for r in self.store.db.execute(
            "SELECT raw_dst FROM edges WHERE rel='CALLS'")]
        self.assertIn("helper", raw)

    def test_a_constructor_names_the_class_without_the_keyword(self):
        self.write("w.ts", "export class W {}\nfunction b() { return new W(); }\n")
        self.build()
        self.assertIn(("w.ts::b", "w.ts::W"), self.rel("CALLS"))

    def test_type_arguments_are_not_part_of_the_callee(self):
        """`useApiQuery<string[]>('k')` calls `useApiQuery`. The `<string[]>` was kept,
        looked like a subscript, and made a function in the next file "external"."""
        self.write("h.ts", "export function useApiQuery<T>(k: string): T {\n"
                           "  return load<T>(k);\n}\nfunction load<T>(k: string): T {\n"
                           "  return JSON.parse(k) as T;\n}\n")
        self.write("p.ts", "import { useApiQuery } from './h';\n"
                           "export function page() { return useApiQuery<string[]>('x'); }\n")
        self.build()
        self.assertIn(("p.ts::page", "h.ts::useApiQuery"), self.rel("CALLS"))
        self.assertIn(("h.ts::useApiQuery", "h.ts::load"), self.rel("CALLS"))

    def test_typescript_is_unchanged_by_the_grammar_agnostic_read(self):
        self.write("w.ts", "export class W {\n  r() { return this.f(); }\n"
                           "  f() { return 1; }\n}\n")
        self.build()
        self.assertIn(("w.ts::W.r", "w.ts::W.f"), self.rel("CALLS"))


class ImportsAreResolvedToFilesNotNames(_Indexed):
    """81 of 1,265 module names on one codebase are shared — `__init__` 123 times.

    Two unrelated `models.py` reported the same 162 importers, each claiming the
    other's.
    """

    def setUp(self):
        super().setUp()
        for d in ("a", "b"):
            os.makedirs(os.path.join(self.tmp, d), exist_ok=True)
            with open(os.path.join(self.tmp, d, "models.py"), "w") as fh:
                fh.write(f"class {d.upper()}:\n    pass\n")
        self.write("uses.py", "from a.models import A\n\ndef go():\n    pass\n")
        self.build()

    def test_only_the_file_actually_imported_claims_the_importer(self):
        self.assertEqual(self.store.importers_of("a/models.py", "r"), ["uses.py"])
        self.assertEqual(self.store.importers_of("b/models.py", "r"), [])

    def test_the_run_reports_what_it_could_resolve(self):
        self.assertIn("imports", self.out)
        self.assertEqual(self.out["imports"]["resolved"], 1)

    def test_an_import_of_something_outside_the_repo_is_external(self):
        self.write("x.py", "import json\nimport os\n")
        out = self.build()
        self.assertGreaterEqual(out["imports"]["external"], 2)

    def test_the_import_is_still_readable_as_written(self):
        raw = [r["raw_dst"] for r in self.store.db.execute(
            "SELECT raw_dst FROM edges WHERE rel='IMPORTS'")]
        self.assertIn("a.models", raw)


class UnplacedIsNotTheSameAsElsewhere(_Indexed):
    """`external` is a claim. It was being made without grounds.

    Both real `store.write(...)` call sites were reported external — "not declared in
    this repository" — while `Store.write` sat in the next file. So "who calls this"
    answered a confident nothing, and a grep answered correctly in one call.
    """

    def test_a_call_we_could_not_type_says_untyped(self):
        self.write("store.py", "class Store:\n    def write(self, x):\n        pass\n")
        self.write("app.py", "from store import Store\n\n"
                             "def go(x):\n    s = make()\n    return s.write(x)\n")
        out = self.build()
        rows = {r["raw_dst"]: r["resolution"] for r in self.store.db.execute(
            "SELECT raw_dst, resolution FROM edges WHERE rel='CALLS'")}
        self.assertEqual(rows["s.write"], "untyped")
        self.assertIn("untyped", out["calls"])

    def test_a_genuinely_third_party_call_still_says_external(self):
        """The distinction is only worth anything if `external` still means something."""
        self.write("app.py", "import json\n\ndef go(x):\n    return json.dumps(x)\n")
        self.build()
        rows = {r["raw_dst"]: r["resolution"] for r in self.store.db.execute(
            "SELECT raw_dst, resolution FROM edges WHERE rel='CALLS'")}
        self.assertEqual(rows["json.dumps"], "external")

    def test_an_ambiguous_import_makes_its_calls_untyped_not_external(self):
        """Two files share a module name, so the import cannot be placed — and a call
        through it is unknown, not absent."""
        for d in ("a", "b"):
            os.makedirs(os.path.join(self.tmp, d), exist_ok=True)
            with open(os.path.join(self.tmp, d, "store.py"), "w") as fh:
                fh.write("class Store:\n    def write(self, x):\n        pass\n")
        self.write("app.py", "import store\n\ndef go(x):\n    return store.write(x)\n")
        self.build()
        rows = {r["raw_dst"]: r["resolution"] for r in self.store.db.execute(
            "SELECT raw_dst, resolution FROM edges WHERE rel='CALLS'")}
        self.assertEqual(rows["store.write"], "untyped")


class AnAnswerAgainstAChangedFileSaysSo(_Indexed):
    """The worst shape of wrong answer available: correct data, correct machinery, and
    a line range that points at the wrong function because the file moved on."""

    def setUp(self):
        super().setUp()
        self.write("a.py", "def first():\n    return 1\n\ndef second():\n    return 2\n")
        self.build()
        from skygraph import tools as surface
        self.surface = surface

    def test_an_unchanged_file_is_exact(self):
        out = self.surface.read_source(self.store, {"qualified_name": "a.py::second"})
        self.assertTrue(out["exact_range"])
        self.assertFalse(out["stale"])
        self.assertIn("def second", out["source"])

    def test_a_changed_file_stops_claiming_an_exact_range(self):
        self.write("a.py", "# added\n# added\n# added\n"
                           "def first():\n    return 1\n\ndef second():\n    return 2\n")
        out = self.surface.read_source(self.store, {"qualified_name": "a.py::second"})
        self.assertTrue(out["stale"])
        self.assertFalse(out["exact_range"])
        self.assertIn("changed since it was indexed", out["note"])

    def test_a_deleted_file_is_reported_rather_than_guessed_at(self):
        os.remove(os.path.join(self.tmp, "a.py"))
        out = self.surface.read_source(self.store, {"qualified_name": "a.py::second"})
        self.assertIn("re-run", out.get("error", "") + out.get("note", ""))


class TheServerNoticesAReplacedIndex(unittest.TestCase):
    """`skygraph index` replaces the file. A server holding the old handle keeps
    answering from a database that no longer exists — and looks like it is working."""

    def test_it_reopens_when_the_database_is_rebuilt(self):
        import subprocess
        launcher = REPO / "skygraph-mcp"
        if not launcher.is_file():
            self.skipTest("no launcher in this checkout")
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "g.db")
        with open(os.path.join(tmp, "one.py"), "w") as fh:
            fh.write("def only_in_first():\n    pass\n")
        index(tmp, repo="first", db=db)

        proc = subprocess.Popen([str(launcher), "--db", db], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True, bufsize=1)
        try:
            def ask(req):
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            ask({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            first = ask({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": "list_repos", "arguments": {}}})
            names = [r["repo"] for r in
                     json.loads(first["result"]["content"][0]["text"])["repos"]]
            self.assertEqual(names, ["first"])

            os.remove(db)
            with open(os.path.join(tmp, "two.py"), "w") as fh:
                fh.write("def only_in_second():\n    pass\n")
            index(tmp, repo="second", db=db)

            second = ask({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": "list_repos", "arguments": {}}})
            names = [r["repo"] for r in
                     json.loads(second["result"]["content"][0]["text"])["repos"]]
            self.assertIn("second", names, "the server served a deleted database")
        finally:
            proc.stdin.close()
            proc.wait(timeout=15)


class ANameIsNeverMatchedAcrossALanguage(_Indexed):
    """Found on a real 10,000-file repository, in a sample of ten.

    A Java test calling `put()` resolved to a TypeScript `ApiClient.put`, because the
    name was declared exactly once — in another language entirely. Roughly 4,400 edges
    were wrong the same way.
    """

    def setUp(self):
        super().setUp()
        if not treesitter.available():
            self.skipTest("needs a parser for the second language")

    def test_a_java_call_does_not_reach_a_typescript_method(self):
        self.write("Api.ts", "export class ApiClient {\n  put(x: string) { return x; }\n}\n")
        self.write("Test.java", "public class Test {\n"
                                "  public void go() { put(\"a\"); }\n}\n")
        self.build()
        for src, dst in self.rel("CALLS"):
            if src.startswith("Test.java"):
                self.assertFalse(dst.endswith(".ts") or ".ts::" in dst,
                                 f"a Java call resolved into TypeScript: {dst}")

    def test_the_same_name_in_its_own_language_still_resolves(self):
        self.write("a.ts", "export function helper() { return 1; }\n")
        self.write("b.ts", "export function go() { return helper(); }\n")
        self.build()
        self.assertIn(("b.ts::go", "a.ts::helper"), self.rel("CALLS"))


class TheDatamodelOntology(_Indexed):
    def test_a_declared_table_name_is_a_fact_and_a_base_class_is_a_guess(self):
        """The distinction the whole health report rests on, at the point it is made."""
        self.write("m.py", SQLALCHEMY)
        self.write("d.py", DJANGO)
        self.build()
        found = self.entities()
        self.assertEqual(found["m.py::User"]["tier"], "native",
                         "__tablename__ is a declaration, not an inference")
        self.assertEqual(found["d.py::Member"]["tier"], "query",
                         "a base class called models.Model is a naming convention")

    def test_a_model_class_is_both_a_class_and_an_entity(self):
        self.write("m.py", SQLALCHEMY)
        self.build()
        found = self.store.definition("m.py::User", "r")
        self.assertEqual(found["kind"], "Class")
        self.assertEqual([a["kind"] for a in found["also_in"]], ["Entity"])

    def test_fields_and_the_table_they_map_to(self):
        self.write("m.py", SQLALCHEMY)
        self.build()
        self.assertIn(("m.py::User", "users"), self.rel("MAPS_TO"))
        self.assertIn(("m.py::User", "m.py::User.org_id"), self.rel("HAS_FIELD"))

    def test_a_foreign_key_nested_inside_a_column_is_still_a_reference(self):
        """`Column(Integer, ForeignKey("orgs.id"))` — the key is an argument.

        Looking only at the outer call missed every SQLAlchemy relation there was.
        """
        self.write("m.py", SQLALCHEMY)
        self.build()
        self.assertIn(("m.py::User", "orgs"), self.rel("REFERENCES"))

    def test_a_django_foreign_key_at_the_top_level_works_too(self):
        self.write("d.py", DJANGO)
        self.build()
        self.assertIn(("d.py::Member", "Team"), self.rel("REFERENCES"))

    def test_ddl_gives_tables_columns_indexes_and_references(self):
        self.write("schema.sql", DDL)
        self.build()
        found = self.entities()
        self.assertIn("schema.sql::users", found)
        self.assertIn(("schema.sql::users", "users"), self.rel("MAPS_TO"))
        self.assertIn(("schema.sql::users", "orgs"), self.rel("REFERENCES"))
        self.assertIn(("schema.sql::users", "schema.sql::users.org_id"),
                      self.rel("HAS_FIELD"))
        self.assertTrue(any(src.endswith("ix_users_org") for src, _ in self.rel("INDEXES")))

    def test_an_ordinary_class_is_not_mistaken_for_an_entity(self):
        self.write("plain.py", "class Helper:\n    def go(self):\n        pass\n")
        self.build()
        self.assertEqual(self.entities(), {})


class TheOpenSpecOntology(_Indexed):
    def test_fastapi_decorators_become_endpoints(self):
        self.write("api.py", FASTAPI)
        self.build()
        self.assertEqual(set(self.endpoints()), {"GET /users/{user_id}", "POST /users"})

    def test_a_flask_route_declares_its_methods(self):
        self.write("api.py", 'from flask import Flask\napp = Flask(__name__)\n\n'
                             '@app.route("/health", methods=["GET", "POST"])\n'
                             'def health():\n    return "ok"\n')
        self.build()
        self.assertEqual(set(self.endpoints()), {"GET /health", "POST /health"})

    def test_a_bare_flask_route_is_a_get(self):
        self.write("api.py", 'from flask import Flask\napp = Flask(__name__)\n\n'
                             '@app.route("/ping")\ndef ping():\n    return "ok"\n')
        self.build()
        self.assertIn("GET /ping", self.endpoints())

    def test_an_openapi_document_in_yaml_is_read_at_the_query_tier(self):
        """There is no YAML parser in the standard library, and adding one for this
        would put a dependency in a project whose claim is that it has none."""
        self.write("openapi.yaml", SPEC_YAML)
        self.build()
        found = self.endpoints()
        self.assertEqual(set(found), {"List invoices", "Create one"})
        self.assertTrue(all(e["tier"] == "query" for e in found.values()))

    def test_an_openapi_document_in_json_is_read_at_the_native_tier(self):
        self.write("openapi.json", json.dumps({
            "openapi": "3.0.0", "info": {"title": "Billing"},
            "paths": {"/invoices": {"get": {"summary": "List", "operationId": "listInvoices",
                                            "parameters": [{"name": "page", "in": "query"}]}}}}))
        self.build()
        found = self.endpoints()
        self.assertIn("List", found)
        self.assertEqual(found["List"]["tier"], "native")
        self.assertTrue(self.rel("PARAMETER_OF"), "a declared parameter was dropped")
        self.assertTrue(self.rel("EXPOSES"))

    def test_an_ordinary_yaml_file_declares_nothing_rather_than_something_wrong(self):
        self.write("config.yaml", "logging:\n  level: debug\npaths:\n  /tmp: yes\n")
        self.build()
        self.assertEqual(self.endpoints(), {})

    def test_broken_json_does_not_stop_the_walk(self):
        self.write("bad.json", "{not json at all")
        self.write("api.py", FASTAPI)
        self.build()
        self.assertIn("POST /users", self.endpoints())


class ScopeBeatsNameWhenResolvingACall(_Indexed):
    """Name alone does not survive a real repository.

    On a 270-file codebase `run` is declared twenty-two times and `get` is called from
    1,354 places. Matching on the name left 91% of in-repo calls ambiguous, which made
    the cross-file traversal this project exists for mostly empty.
    """

    def test_self_resolves_to_the_calling_class_not_a_namesake(self):
        self.write("a.py", "class One:\n    def run(self):\n        return self.go()\n"
                           "    def go(self):\n        return 1\n\n"
                           "class Two:\n    def go(self):\n        return 2\n")
        self.build()
        calls = [d for s_, d in self.rel("CALLS") if s_ == "a.py::One.run"]
        self.assertIn("a.py::One.go", calls)
        self.assertNotIn("a.py::Two.go", calls)

    def test_a_local_call_prefers_the_same_file(self):
        self.write("here.py", "def helper():\n    return 1\n\n"
                              "def go():\n    return helper()\n")
        self.write("elsewhere.py", "def helper():\n    return 2\n")
        self.build()
        self.assertIn(("here.py::go", "here.py::helper"), self.rel("CALLS"))

    def test_an_imported_name_follows_the_import(self):
        self.write("util.py", "def helper():\n    return 1\n")
        self.write("other.py", "def helper():\n    return 2\n")
        self.write("app.py", "from util import helper\n\ndef go():\n    return helper()\n")
        self.build()
        self.assertIn(("app.py::go", "util.py::helper"), self.rel("CALLS"))

    def test_a_name_declared_once_anywhere_still_resolves(self):
        self.write("a.py", "def go():\n    return only_one()\n")
        self.write("b.py", "def only_one():\n    return 1\n")
        self.build()
        self.assertIn(("a.py::go", "b.py::only_one"), self.rel("CALLS"))

    def test_a_genuinely_ambiguous_call_is_still_left_bare(self):
        """Narrowing the search must not turn a guess into a claim."""
        self.write("one.py", "def run():\n    pass\n")
        self.write("two.py", "def run():\n    pass\n")
        self.write("caller.py", "def go():\n    return run()\n")
        out = self.build()
        self.assertEqual(out["calls"]["ambiguous"], 1)
        self.assertEqual(out["calls"]["resolved"], 0)

    def test_the_run_reports_how_each_one_was_found(self):
        self.write("a.py", "class One:\n    def run(self):\n        return self.go()\n"
                           "    def go(self):\n        return 1\n")
        out = self.build()
        self.assertIn("self", out["calls"]["how"])


class BinaryAndDocumentFilesAreNotCode(_Indexed):
    """Found on a real repository, where 22% of files had fallen to the heuristic tier.

    Word documents and PDFs were being read with errors="replace" and pattern-matched
    for declarations, which duly found some.
    """

    def test_a_null_byte_means_it_is_not_text_whatever_the_extension(self):
        with open(os.path.join(self.tmp, "report.xyz"), "wb") as fh:
            fh.write(b"PK\x03\x04\x00\x00fake docx bytes\x00def notreal():\n")
        out = self.build()
        self.assertEqual(out["files"], 0)
        self.assertEqual(out["skipped"], 1)

    def test_the_extension_check_ignores_case(self):
        from skygraph import frontends
        for name in ("paper.PDF", "Notes.MD", "Sheet.XLSX", "logo.PNG"):
            with self.subTest(name=name):
                self.assertFalse(frontends.unclaimed_source(name))

    def test_diagrams_and_data_are_not_source(self):
        from skygraph import frontends
        for name in ("flow.mmd", "events.jsonl", "style.css", "app.plist"):
            with self.subTest(name=name):
                self.assertFalse(frontends.unclaimed_source(name))

    def test_a_backup_copy_is_not_a_second_manifest(self):
        """`policy.yaml.backup-2026-09-12` keeps its real extension and adds a suffix,
        so the extension check never saw it."""
        from skygraph import frontends
        for name in ("policy.yaml.backup-2026-09-12", "conf.py.bak",
                     "main.tf.orig", "kb.json.pre-rename"):
            with self.subTest(name=name):
                self.assertFalse(frontends.unclaimed_source(name))


class TheLinkOntologyJoinsThem(_Indexed):
    """`code_ontology` alone is a better grep. These are the joins it cannot make."""

    def setUp(self):
        super().setUp()
        self.write("models.py", SQLALCHEMY)
        self.write("api.py", FASTAPI.replace("from models import User",
                                             "from models import User"))
        self.build()

    def test_an_endpoint_reaches_the_table_it_writes(self):
        chain = self.store.trace("api.py::POST /users", "r")["chain"]
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["handler"], "api.py::create_user")
        self.assertEqual(chain[0]["entity"], "models.py::User")
        self.assertEqual(chain[0]["tables"], ["users"])

    def test_the_handler_join_is_a_fact_and_the_persistence_join_is_a_lead(self):
        """A decorator sits on its function. A call to a model only suggests a write."""
        rows = {r["rel"]: r["tier"] for r in self.store.db.execute(
            "SELECT DISTINCT rel, tier FROM edges WHERE rel IN "
            "('HANDLED_BY','PERSISTS_TO','MAPS_TO')")}
        self.assertEqual(rows["HANDLED_BY"], "native")
        self.assertEqual(rows["MAPS_TO"], "native")
        self.assertEqual(rows["PERSISTS_TO"], "query",
                         "a derived edge must not claim to be a parsed one")

    def test_expand_symbol_returns_the_trace_without_a_second_call(self):
        from skygraph import tools as surface
        out = surface.expand_symbol(self.store, {"qualified_name": "api.py::POST /users"})
        self.assertEqual(out["trace"][0]["tables"], ["users"])

    def test_a_plain_function_gets_no_trace_key(self):
        from skygraph import tools as surface
        out = surface.expand_symbol(self.store, {"qualified_name": "api.py::create_user"})
        self.assertNotIn("trace", out)

    def test_link_is_reported_present_although_it_owns_no_nodes(self):
        report = self.store.health("r")
        self.assertNotIn("link", report["ontologies_absent"])
        self.assertGreater(report["links"]["PERSISTS_TO"], 0)

    def test_re_indexing_does_not_multiply_the_derived_edges(self):
        """PERSISTS_TO is rebuilt each run, so it must be cleared each run."""
        before = len(self.rel("PERSISTS_TO"))
        index(self.tmp, repo="r", db=self.db, full=True)
        self.assertEqual(len(Store(self.db).db.execute(
            "SELECT src, dst FROM edges WHERE rel='PERSISTS_TO'").fetchall()), before)


DOCKERFILE = """FROM python:3.12-slim AS builder
ARG BUILD_REV
RUN pip install poetry

FROM python:3.12-slim
ENV DATABASE_URL=postgres://localhost/app
ENV LOG_LEVEL debug
EXPOSE 8080
CMD ["uvicorn", "api:app"]
"""

COMPOSE = """version: "3"
services:
  api:
    image: myorg/api:1.2
    environment:
      - DATABASE_URL=postgres://db:5432/app
      - SENTRY_DSN=https://x@sentry.io/1
  worker:
    image: myorg/worker:1.2
    environment:
      QUEUE_URL: redis://cache:6379
"""

K8S = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: myorg/api:1.2
          env:
            - name: DATABASE_URL
              value: postgres://db/app
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-config
"""

WORKFLOW = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
  build:
    runs-on: ubuntu-latest
  deploy-production:
    runs-on: ubuntu-latest
"""


class TheMiniYamlReaderIsHonestAboutBeingSmall(unittest.TestCase):
    def test_a_colon_only_separates_a_key_when_a_space_follows(self):
        """`- DATABASE_URL=postgres://x` is a string, not a mapping.

        Without this rule it parsed as {"DATABASE_URL=postgres": "//x"}, which is the
        shape half of every compose file's environment list takes.
        """
        from skygraph import miniyaml
        got = miniyaml.load("env:\n  - DATABASE_URL=postgres://x:5432/db\n")
        self.assertEqual(got, {"env": ["DATABASE_URL=postgres://x:5432/db"]})

    def test_it_reads_both_environment_shapes(self):
        from skygraph import miniyaml
        got = miniyaml.load("a:\n  env:\n    K: 1\nb:\n  env:\n    - K=1\n")
        self.assertEqual(got["a"]["env"], {"K": 1})
        self.assertEqual(got["b"]["env"], ["K=1"])

    def test_several_documents(self):
        from skygraph import miniyaml
        self.assertEqual([d["kind"] for d in miniyaml.load_all(K8S)],
                         ["Deployment", "ConfigMap"])

    def test_it_refuses_yaml_it_does_not_implement_rather_than_half_reading(self):
        """A caller that gets an error knows to use a real parser. A caller that got a
        silently truncated document would not."""
        from skygraph import miniyaml
        for bad in ("base: &a\n  x: 1\n", "child:\n  <<: *a\n", "s: !!str 1\n",
                    "body: |\n  line\n"):
            with self.subTest(yaml=bad.strip()[:20]):
                with self.assertRaises(miniyaml.MiniYamlError):
                    miniyaml.load(bad)

    def test_comments_and_quoted_hashes(self):
        from skygraph import miniyaml
        got = miniyaml.load('a: 1  # trailing\nb: "has # inside"\n')
        self.assertEqual(got, {"a": 1, "b": "has # inside"})


class TheYamlReaderCannotBeMadeToHang(unittest.TestCase):
    """One 2 KB file stopped a 17,000-file index for over an hour.

    The key/value split was a regex: `((?:"[^"]*"|'[^']*'|[^:])+?):`. A quoted run can
    match either the quoted branch or one `[^:]` at a time, so a line with many quoted
    segments has exponentially many readings and the engine tries them all. A GitLab CI
    line with forty `_VAR="$VAR"` pairs was enough.

    The first test I wrote for this used a long line of `aaaa…` and passed instantly,
    because without quotes there is no ambiguity and nothing to backtrack. The shape
    matters more than the length.
    """

    def test_a_long_line_of_quoted_pairs_is_read_immediately(self):
        import time
        pairs = ",".join(f'_VAR{i}="$VALUE{i}"' for i in range(60))
        line = f"        --substitutions={pairs}"
        document = f"deploy:\n  script:\n    - |\n{line}\n"
        start = time.time()
        miniyaml.load_all(document)
        self.assertLess(time.time() - start, 1.0,
                        "the reader backtracked instead of scanning")

    def test_it_still_splits_on_a_colon_space_outside_quotes(self):
        self.assertEqual(miniyaml.load('key: value\n'), {"key": "value"})
        self.assertEqual(miniyaml.load('url: http://x:80/a\n'), {"url": "http://x:80/a"})

    def test_a_colon_inside_quotes_is_not_a_separator(self):
        self.assertEqual(miniyaml.load('cmd: "a: b"\n'), {"cmd": "a: b"})

    def test_a_colon_with_no_space_after_it_is_not_a_separator(self):
        self.assertEqual(miniyaml.load("env:\n  - A=postgres://h:5432/d\n"),
                         {"env": ["A=postgres://h:5432/d"]})

    def test_a_real_pipeline_file_parses(self):
        document = ('deploy:\n  script:\n    - |\n'
                    '      gcloud builds submit \\\n'
                    '        --substitutions=_A="$A",_B="$B",_C="$C"\n'
                    '  only:\n    - main\n')
        got = miniyaml.load(document)
        self.assertIn("deploy", got)


class TheDeployOntology(_Indexed):
    def test_a_dockerfile_gives_every_stage_not_just_the_last(self):
        """A multi-stage build produces a builder and a runtime; reporting only one
        loses the half that installs everything."""
        self.write("Dockerfile", DOCKERFILE)
        self.build()
        images = {r["name"] for r in self.store.search("", "r",
                                                       ontology="deploy_ontology",
                                                       limit=200)
                  if r["kind"] == "Image"}
        self.assertIn("Dockerfile::builder", images)
        self.assertIn("Dockerfile::stage-2", images)
        self.assertIn(("Dockerfile::builder", "Dockerfile::stage-2"), self.rel("BUILDS"))

    def test_expose_describes_the_image_rather_than_inventing_a_deployable(self):
        """It used to make a Deployable, producing a row saying the image ran itself."""
        self.write("Dockerfile", DOCKERFILE)
        self.build()
        rows = [r for r in self.store.search("", "r", ontology="deploy_ontology",
                                             limit=200) if r["kind"] == "Image"]
        self.assertTrue(any("port 8080" in r["summary"] for r in rows))
        self.assertFalse([s for s, d in self.rel("RUNS") if s == d],
                         "something runs itself")

    def test_env_and_arg_are_both_configuration(self):
        self.write("Dockerfile", DOCKERFILE)
        self.build()
        declared = {r["summary"] for r in self.store.search("", "r",
                                                            ontology="deploy_ontology",
                                                            limit=200)
                    if r["kind"] == "EnvVar"}
        self.assertEqual(declared, {"DATABASE_URL", "LOG_LEVEL", "BUILD_REV"})

    def test_compose_services_run_images_and_carry_configuration(self):
        self.write("docker-compose.yml", COMPOSE)
        self.build()
        runs = dict(self.rel("RUNS"))
        self.assertEqual(runs["docker-compose.yml::api"],
                         "docker-compose.yml::image:myorg/api:1.2")
        declared = {r["summary"] for r in self.store.search("", "r",
                                                            ontology="deploy_ontology",
                                                            limit=200)
                    if r["kind"] == "EnvVar"}
        self.assertEqual(declared, {"DATABASE_URL", "SENTRY_DSN", "QUEUE_URL"})

    def test_kubernetes_workloads_are_deployables_and_configmaps_are_not(self):
        """A ConfigMap configures and a Service routes; neither has a process in it."""
        self.write("k8s.yaml", K8S)
        self.build()
        names = {r["name"] for r in self.store.search("", "r",
                                                      ontology="deploy_ontology",
                                                      limit=200)
                 if r["kind"] == "Deployable"}
        self.assertEqual(names, {"k8s.yaml::api"})

    def test_a_workflow_becomes_a_pipeline_with_stages(self):
        self.write("ci.yml", WORKFLOW)
        self.build()
        stages = {src.split("::")[-1] for src, _ in self.rel("STAGE_OF")}
        self.assertEqual(stages, {"test", "build", "deploy-production"})

    def test_only_the_job_that_deploys_is_marked_as_deploying(self):
        """A job that merely mentions deploying is usually building what gets deployed."""
        self.write("ci.yml", WORKFLOW)
        self.build()
        deploying = {dst.split("::")[-1] for _, dst in self.rel("DEPLOYS")}
        self.assertEqual(deploying, {"deploy-production"})

    def test_an_ordinary_yaml_file_is_not_a_manifest(self):
        self.write("config.yaml", "logging:\n  level: debug\nretries: 3\n")
        self.build()
        self.assertEqual(self.out["by_ontology"].get("deploy_ontology", 0), 0)


class TheEnvironmentJoin(_Indexed):
    """The question no single file can answer: change this variable, what breaks?

    The manifest never names the code and the code never names the manifest.
    """

    def setUp(self):
        super().setUp()
        self.write("Dockerfile", DOCKERFILE)
        self.write("docker-compose.yml", COMPOSE)
        self.write("settings.py",
                   'import os\n\n'
                   'DATABASE_URL = os.environ["DATABASE_URL"]\n'
                   'LOG_LEVEL = os.getenv("LOG_LEVEL", "info")\n'
                   'SECRET_KEY = os.environ.get("SECRET_KEY")\n')
        self.build()

    def usage(self):
        return {e["name"]: e for e in self.store.env_usage("r")}

    def test_a_variable_read_in_code_reaches_the_manifest_that_sets_it(self):
        found = self.usage()["DATABASE_URL"]
        self.assertIn("settings.py", found["read_by"])
        self.assertIn("Dockerfile", found["declared_in"])
        self.assertIn("docker-compose.yml", found["declared_in"])

    def test_a_variable_read_but_never_declared_is_reported(self):
        """Set by the platform, a secret store, or nobody. Worth knowing which."""
        self.assertFalse(self.usage()["SECRET_KEY"]["declared"])
        self.assertIn("SECRET_KEY", self.store.health("r")["env_read_but_undeclared"])

    def test_reading_a_variable_is_not_declaring_one(self):
        declared = {r["summary"] for r in self.store.search("", "r",
                                                            ontology="deploy_ontology",
                                                            limit=200)
                    if r["kind"] == "EnvVar"}
        self.assertNotIn("SECRET_KEY", declared)

    def test_javascript_reads_are_found_too(self):
        self.write("app.js", "const url = process.env.DATABASE_URL;\n"
                             "const k = process.env['SENTRY_DSN'];\n")
        self.build()
        found = self.usage()
        self.assertIn("app.js", found["DATABASE_URL"]["read_by"])
        self.assertIn("SENTRY_DSN", found)


class TheDeployJoin(_Indexed):
    def test_an_image_command_reaches_the_module_it_starts(self):
        """`CMD ["uvicorn", "api:app"]` names `api`, and only the whole repository
        knows whether a module by that name exists."""
        self.write("Dockerfile", DOCKERFILE)
        self.write("api.py", "app = object()\n")
        self.build()
        self.assertIn(("api.py", "Dockerfile::stage-2"), self.rel("DEPLOYED_BY"))

    def test_a_command_naming_a_binary_is_not_invented_as_code(self):
        self.write("Dockerfile", 'FROM alpine\nCMD ["nginx", "-g", "daemon off;"]\n')
        self.build()
        self.assertEqual(self.rel("DEPLOYED_BY"), [])

    def test_the_join_is_rebuilt_not_appended_on_re_index(self):
        self.write("Dockerfile", DOCKERFILE)
        self.write("api.py", "app = object()\n")
        self.build()
        before = len(self.rel("DEPLOYED_BY"))
        index(self.tmp, repo="r", db=self.db, full=True)
        self.store = Store(self.db)
        self.assertEqual(len(self.rel("DEPLOYED_BY")), before)


class _StubModelServer:
    """A real HTTP server speaking the OpenAI shape, so the client path is exercised.

    Mocking the client would test the validator and nothing else. The parts that
    actually break in the field are the request, the response shape and the fence a
    model puts round its JSON, and those only get covered by really talking to a socket.
    """

    def __init__(self, reply=None, status=200, body=None):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        self.prompts = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                size = int(self.headers.get("Content-Length", 0))
                sent = json.loads(self.rfile.read(size)) if size else {}
                outer.prompts.append(sent["messages"][0]["content"])
                if status != 200:
                    self.send_response(status)
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                text = body if body is not None else (
                    "```json\n" + json.dumps(reply or {"symbols": []}) + "\n```")
                out = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions"

    def model(self, **kw):
        from skygraph.model import Model
        return Model("test-key", name="stub", provider="openai", url=self.url, **kw)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.shutdown()


HCL = 'resource "aws_lambda_function" "ingest" {\n  handler = "main.handler"\n}\n'
ERL = '-module(report).\n\nbuild(Rows) ->\n    lists:map(fun row/1, Rows).\n'


class WhatTierThreeIsEvenShown(_Indexed):
    """It is the last resort. Anything a parser handled must never reach it."""

    def test_a_file_no_front_end_claims_is_reachable_at_all(self):
        """This was broken for a long time and silently.

        The walk skipped every file no front end claimed, so a language without a
        pattern was not read badly — it was not read at all, and neither tier 3 nor the
        heuristic ever saw one.
        """
        from skygraph import frontends
        self.assertTrue(frontends.unclaimed_source("pipeline.hcl"))
        self.assertTrue(frontends.unclaimed_source("report.erl"))

    def test_documents_archives_and_dotfiles_are_not_source(self):
        from skygraph import frontends
        for name in ("README.md", "notes.txt", "logo.png", "app.min.js",
                     "package-lock.json", ".gitignore", "Makefile", "data.csv"):
            with self.subTest(name=name):
                self.assertFalse(frontends.unclaimed_source(name))

    def test_a_parsed_file_is_never_sent(self):
        self.write("parsed.py", PY)
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": [{"name": "ingest", "kind": "Function"}]}) as stub:
            self.out = index(self.tmp, repo="r", db=self.db, model=stub.model())
            sent = "\n".join(stub.prompts)
        self.assertIn("thing.hcl", sent)
        self.assertNotIn("parsed.py", sent, "a file the parser read was sent to a model")

    def test_without_a_key_there_is_no_tier_three_and_it_says_so(self):
        self.write("thing.hcl", HCL)
        out = index(self.tmp, repo="r", db=self.db, model=None)
        self.assertFalse(out["model"]["used"])
        self.assertEqual(out["model"]["candidates"], 1)
        self.assertIn("SKYGRAPH_MODEL_KEY", out["model"]["reason"])

    def test_a_missing_key_is_not_an_error(self):
        """Tier 3 is opt-in. No key means index without it, not stop."""
        from skygraph.model import Model
        import os
        before = os.environ.pop("SKYGRAPH_MODEL_KEY", None)
        try:
            self.assertIsNone(Model.from_environment())
        finally:
            if before is not None:
                os.environ["SKYGRAPH_MODEL_KEY"] = before

    def test_the_budget_caps_what_is_sent_and_the_rest_is_reported(self):
        for i in range(5):
            self.write(f"f{i}.hcl", HCL)
        with _StubModelServer({"symbols": [{"name": "x", "kind": "Function"}]}) as stub:
            out = index(self.tmp, repo="r", db=self.db, model=stub.model(budget=2))
            self.assertEqual(len(stub.prompts), 2)
        self.assertEqual(out["model"]["attempted"], 2)
        self.assertEqual(out["model"]["over_budget"], 3)

    def test_a_second_run_over_unchanged_files_asks_nothing(self):
        """The saving that matters: a model is the most expensive tier, and the
        content hash means it is paid for once."""
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": [{"name": "ingest", "kind": "Function"}]}) as stub:
            index(self.tmp, repo="r", db=self.db, model=stub.model())
            first = len(stub.prompts)
            index(self.tmp, repo="r", db=self.db, model=stub.model())
            self.assertEqual(first, 1)
            self.assertEqual(len(stub.prompts), 1, "an unchanged file was sent again")


class WhatTierThreeProduces(_Indexed):
    def test_its_rows_are_marked_as_its_own(self):
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": [
                {"name": "ingest", "kind": "Function", "line": 1, "summary": "ingests"}]}) as stub:
            index(self.tmp, repo="r", db=self.db, model=stub.model())
        self.store = Store(self.db)
        row = self.store.definition("thing.hcl::ingest", "r")
        self.assertEqual(row["tier"], "model")
        self.assertEqual(Symbol("x", "Function", "x", tier="model").parsed, False)

    def test_the_health_report_separates_read_from_inferred(self):
        self.write("parsed.py", PY)
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": [
                {"name": "a", "kind": "Function"}, {"name": "b", "kind": "Function"}]}) as stub:
            index(self.tmp, repo="r", db=self.db, model=stub.model())
        health = Store(self.db).health("r")
        self.assertEqual(health["inferred_symbols"], 2)
        self.assertGreater(health["parsed_symbols"], 0)
        self.assertLess(health["parsed_share"], 1.0)

    def test_the_gap_names_the_model_that_filled_it(self):
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": [{"name": "a", "kind": "Function"}]}) as stub:
            index(self.tmp, repo="r", db=self.db, model=stub.model())
        gaps = Store(self.db).degraded("r")
        self.assertEqual(len(gaps), 1)
        self.assertIn("a model read it", gaps[0]["degraded"])
        self.assertIn("stub", gaps[0]["degraded"])

    def test_an_undeclared_kind_is_dropped_not_admitted(self):
        """The ontology is the authority for a model exactly as for a parser."""
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": [
                {"name": "ok", "kind": "Function"},
                {"name": "bad", "kind": "Protocol"}]}) as stub:
            out = index(self.tmp, repo="r", db=self.db, model=stub.model())
        self.assertEqual(out["model"]["refused_rows"], 1)
        self.store = Store(self.db)
        self.assertIsNone(self.store.definition("thing.hcl::bad", "r"))
        self.assertIsNotNone(self.store.definition("thing.hcl::ok", "r"))

    def test_an_edge_from_something_it_did_not_declare_is_dropped(self):
        """A model describing code it was not shown."""
        from skygraph.model import to_rows
        _sym, edges, refused = to_rows("x.hcl", {
            "symbols": [{"name": "real", "kind": "Function"}],
            "edges": [{"src": "real", "rel": "CALLS", "dst": "open"},
                      {"src": "ghost", "rel": "CALLS", "dst": "open"}]})
        self.assertEqual(len(edges), 1)
        self.assertTrue(any("ghost" in r for r in refused))


class WhenTheModelFails(_Indexed):
    """A failure is never fatal. The heuristic answer is already written."""

    def test_an_http_error_leaves_the_index_intact_and_says_why(self):
        self.write("parsed.py", PY)
        self.write("thing.hcl", HCL)
        with _StubModelServer(status=500) as stub:
            out = index(self.tmp, repo="r", db=self.db, model=stub.model())
        self.assertEqual(out["model"]["failed"], 1)
        self.assertEqual(out["model"]["accepted"], 0)
        self.assertTrue(any("500" in p for p in out["model"]["problems"]))
        self.assertIsNotNone(Store(self.db).definition("parsed.py::Alpha", "r"),
                             "a model failure lost a parsed file")

    def test_a_reply_that_is_not_json_is_a_failure_not_a_crash(self):
        self.write("thing.hcl", HCL)
        with _StubModelServer(body="I am afraid I cannot do that.") as stub:
            out = index(self.tmp, repo="r", db=self.db, model=stub.model())
        self.assertEqual(out["model"]["failed"], 1)

    def test_an_unreachable_endpoint_is_a_failure_not_a_crash(self):
        self.write("thing.hcl", HCL)
        from skygraph.model import Model
        dead = Model("k", provider="openai", name="stub",
                     url="http://127.0.0.1:1/v1/chat/completions")
        out = index(self.tmp, repo="r", db=self.db, model=dead)
        self.assertEqual(out["model"]["failed"], 1)
        self.assertTrue(out["model"]["problems"])

    def test_an_empty_answer_does_not_replace_the_heuristic_one(self):
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": []}) as stub:
            out = index(self.tmp, repo="r", db=self.db, model=stub.model())
        self.assertEqual(out["model"]["accepted"], 0)

    def test_the_key_is_never_written_into_the_report(self):
        self.write("thing.hcl", HCL)
        with _StubModelServer({"symbols": [{"name": "a", "kind": "Function"}]}) as stub:
            out = index(self.tmp, repo="r", db=self.db,
                        model=stub.model())
        self.assertNotIn("test-key", json.dumps(out))


class OneDatabaseDefault(unittest.TestCase):
    """It was defined twice, and the two did not match.

    The CLI wrote `~/.skygraph/index.db`; `index()` defaulted to `code-index.db` in the
    working directory. Anyone using the library rather than the command built a second
    index somewhere else and then found the first one empty — which is what happened
    here, on a real re-index.
    """

    def test_every_entry_point_agrees(self):
        import inspect
        from skygraph.indexer import index as index_fn
        from skygraph.mcp import serve
        from skygraph.store import DEFAULT_DB
        from skygraph.__main__ import DEFAULT_DB as cli
        defaults = {DEFAULT_DB, cli,
                    inspect.signature(index_fn).parameters["db"].default,
                    inspect.signature(serve).parameters["db"].default}
        self.assertEqual(len(defaults), 1, f"entry points disagree: {defaults}")

    def test_it_is_not_a_path_in_the_working_directory(self):
        """A default that is relative writes wherever the caller happened to stand."""
        from skygraph.store import DEFAULT_DB
        self.assertTrue(DEFAULT_DB.startswith("~"), DEFAULT_DB)


class TheLauncherStartsFromAnywhere(unittest.TestCase):
    """Found when a host reported "connection closed" and nothing else.

    `python3 -m skygraph serve` only resolves when the working directory is the
    repository. A host does not promise one, so the server started, failed to import
    itself, and died before writing a byte — and the host had nothing to report but a
    closed pipe.
    """

    def setUp(self):
        self.launcher = REPO / "skygraph-mcp"
        if not self.launcher.is_file():
            self.skipTest("no launcher in this checkout")

    def test_it_answers_from_an_unrelated_working_directory(self):
        import subprocess
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18",
                                         "capabilities": {}}})
        out = subprocess.run([str(self.launcher), "--db",
                              os.path.join(tempfile.mkdtemp(), "g.db")],
                             input=request + "\n", capture_output=True, text=True,
                             cwd=tempfile.gettempdir(), timeout=60,
                             env={"PATH": os.environ.get("PATH", ""),
                                  "HOME": os.environ.get("HOME", "")})
        self.assertEqual(out.returncode, 0, out.stderr)
        reply = json.loads(out.stdout.splitlines()[0])
        self.assertEqual(reply["result"]["serverInfo"]["name"], "skygraph")

    def test_it_is_executable(self):
        self.assertTrue(os.access(self.launcher, os.X_OK),
                        "a host runs it directly, so it needs the bit set")


class AReceiverIsNotDiscarded(_Indexed):
    """The bug that made the graph claim things that were not true.

    `sys.stdout.write(...)` and `store.write(...)` were both recorded as `write`, so a
    file importing a module that happened to declare a `write` had its JSON output
    pointed at the database writer. On a real repository one method showed 301 callers
    where nine existed. A wrong edge makes an agent confident, which is worse than the
    missing one it replaced.
    """

    def test_a_method_on_a_standard_library_object_is_external(self):
        self.write("store.py", "class Store:\n    def write(self, x):\n        pass\n")
        self.write("out.py", "import sys\nimport store\n\n"
                             "def emit(line):\n    sys.stdout.write(line)\n")
        self.build()
        self.assertEqual([d for s_, d in self.rel("CALLS") if s_ == "out.py::emit"
                          and "Store" in d], [],
                         "a write to stdout was resolved to a database writer")

    def test_a_module_receiver_reaches_the_module_not_a_class_in_it(self):
        """This test used to assert the opposite, and was wrong.

        `store` here is a module. `store.save(...)` calls the module's `save`, not the
        `save` method of a class that happens to live in the same file — those are
        different functions, and picking the method is the same guess by another route.
        """
        self.write("store.py", "class Store:\n    def save(self, x):\n        pass\n\n"
                               "def save(x):\n    pass\n")
        self.write("app.py", "import store\n\ndef go(s):\n    return store.save(s)\n")
        self.build()
        calls = dict(self.rel("CALLS"))
        self.assertEqual(calls["app.py::go"], "store.py::save")

    def test_a_module_receiver_with_no_such_function_is_external(self):
        self.write("store.py", "class Store:\n    def save(self, x):\n        pass\n")
        self.write("app.py", "import store\n\ndef go(s):\n    return store.save(s)\n")
        self.build()
        self.assertEqual([d for s_, d in self.rel("CALLS") if s_ == "app.py::go"
                          and "Store" in d], [])

    def test_a_class_imported_by_name_does_reach_its_method(self):
        """`from store import Store` then `Store.save(...)` — that one is knowable."""
        self.write("store.py", "class Store:\n    def save(self, x):\n        pass\n")
        self.write("app.py", "from store import Store\n\n"
                             "def go(x):\n    return Store.save(x)\n")
        self.build()
        self.assertIn(("app.py::go", "store.py::Store.save"), self.rel("CALLS"))

    def test_a_bare_call_never_reaches_a_method(self):
        """`set(...)` is a builtin. It resolved to `RuntimeConfig.set`."""
        self.write("conf.py", "class RuntimeConfig:\n    def set(self, k):\n        pass\n")
        self.write("main.py", "def lifespan():\n    return set([1, 2])\n")
        self.build()
        self.assertEqual([d for s_, d in self.rel("CALLS") if s_ == "main.py::lifespan"
                          and "RuntimeConfig" in d], [])

    def test_a_dict_get_is_not_a_call_to_a_class_method(self):
        self.write("registry.py", "class Registry:\n    def get(self, k):\n        pass\n")
        self.write("user.py", "import registry\n\n"
                              "def pick(config):\n    return config.get('a')\n")
        self.build()
        resolved = [d for s_, d in self.rel("CALLS") if s_ == "user.py::pick"]
        self.assertNotIn("registry.py::Registry.get", resolved)


class EveryToolAnswersAboutTheWholeFile(_Indexed):
    """All three of these paged a name search and filtered the page.

    On the busiest file in a real repository that returned 8 rows of 31, presented as
    the file's outline — an answer that looks complete and is not.
    """

    def setUp(self):
        super().setUp()
        body = "".join(f"def f{i}():\n    pass\n\n" for i in range(40))
        self.write("big.py", body)
        self.write("small.py", "def one():\n    pass\n")
        self.build()
        from skygraph import tools as surface
        self.surface = surface

    def test_outline_file_returns_every_declaration(self):
        got = self.surface.outline_file(self.store, {"repo": "r", "filepath": "big.py"})
        self.assertEqual(len(got["signatures"]), 41)      # 40 functions and the module

    def test_outline_file_accepts_a_path_suffix(self):
        got = self.surface.outline_file(self.store, {"repo": "r", "filepath": "big.py"})
        self.assertTrue(got["signatures"])

    def test_siblings_are_the_whole_file(self):
        got = self.surface.related_symbols(self.store, {"qualified_name": "big.py::f0"})
        self.assertEqual(len(got["siblings"]), 40)

    def test_a_limit_is_capped_and_says_so(self):
        got = self.surface.find_symbols(self.store, {"query": "f", "repo": "r",
                                                     "limit": 100000})
        self.assertLessEqual(len(got["results"]), self.surface.MAX_ROWS)
        self.assertIn("capped", got.get("note", ""))


class AFileTheIndexHasNotSeenIsAnErrorNotAnEmptyAnswer(_Indexed):
    """`signatures: []` also means "indexed, declares nothing" — a SQL file, a
    template. An agent shown an empty list for a path that was never indexed reads it
    as "nothing here" and moves on, which is the confident wrong answer this project
    refuses everywhere else."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.tmp, "a", "b"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp, "c"), exist_ok=True)
        self.write("a/b/models.py", "def one():\n    pass\n")
        self.write("c/models.py", "def two():\n    pass\n")
        self.write("empty.sql", "-- nothing declared\n")
        self.build()
        from skygraph import tools as surface
        self.surface = surface

    def test_outline_of_an_unindexed_file_is_an_error(self):
        out = self.surface.outline_file(self.store, {"repo": "r", "filepath": "zzz.py"})
        self.assertIn("error", out)
        self.assertNotIn("signatures", out)

    def test_imports_of_an_unindexed_file_is_an_error(self):
        out = self.surface.file_imports(self.store, {"repo": "r", "filepath": "zzz.py",
                                                     "direction": "both"})
        self.assertIn("error", out)

    def test_an_indexed_file_that_declares_nothing_is_still_an_empty_list(self):
        out = self.surface.outline_file(self.store, {"repo": "r", "filepath": "empty.sql"})
        self.assertNotIn("error", out)
        self.assertEqual(out["signatures"], [])

    def test_a_unique_suffix_is_accepted(self):
        out = self.surface.outline_file(self.store, {"repo": "r", "filepath": "b/models.py"})
        self.assertEqual(out["filepath"], "a/b/models.py")

    def test_an_ambiguous_suffix_is_refused_rather_than_guessed(self):
        out = self.surface.outline_file(self.store, {"repo": "r", "filepath": "models.py"})
        self.assertIn("error", out)
        self.assertIn("more than one", out["error"])


class ImportDirectionIsMatchedOnTheModule(_Indexed):
    def test_a_file_does_not_import_itself(self):
        """`LIKE '%' || dst || '%'` made build-pptx.py import itself, via `pptx`."""
        self.write("pptx.py", "def build():\n    pass\n")
        self.write("build-pptx.py", "import pptx\n\ndef go():\n    pass\n")
        self.build()
        from skygraph import tools as surface
        got = surface.file_imports(self.store, {"repo": "r", "filepath": "build-pptx.py",
                                                "direction": "imported_by"})
        self.assertNotIn("build-pptx.py", got["imported_by"])

    def test_the_real_importer_is_found(self):
        self.write("util.py", "def helper():\n    pass\n")
        self.write("app.py", "from util import helper\n")
        self.build()
        from skygraph import tools as surface
        got = surface.file_imports(self.store, {"repo": "r", "filepath": "util.py",
                                                "direction": "imported_by"})
        self.assertEqual(got["imported_by"], ["app.py"])


class TheIndexSaysWhichLanguagesItCanTraverse(_Indexed):
    """An agent cannot tell a thin graph from a complete one by querying it."""

    def test_a_pattern_read_language_is_reported_as_untraversable(self):
        self.write("a.py", PY)
        self.write("b.ts", TS)
        self.build()
        coverage = {c["language"]: c for c in self.store.language_coverage("r")}
        self.assertTrue(coverage["python"]["traversable"])
        self.assertFalse(coverage["typescript"]["traversable"],
                         "tier 2 emits no calls, and the report must say so")

    def test_the_health_report_carries_it(self):
        self.write("b.ts", TS)
        self.build()
        health = self.store.health("r")
        self.assertIn("languages", health)
        self.assertIn("blast_radius", health["language_note"])


class GeneratedOutputIsNotIndexed(_Indexed):
    def test_build_and_report_directories_are_skipped(self):
        for d in ("coverage", ".nx", "node_modules", "htmlcov"):
            os.makedirs(os.path.join(self.tmp, d), exist_ok=True)
            with open(os.path.join(self.tmp, d, "x.py"), "w") as fh:
                fh.write("def generated():\n    pass\n")
        self.write("real.py", "def kept():\n    pass\n")
        out = self.build()
        self.assertEqual(out["files"], 1)

    def test_html_is_not_source(self):
        from skygraph import frontends
        self.assertFalse(frontends.unclaimed_source("coverage/index.html"))


class TheMcpProtocolIsHonoured(unittest.TestCase):
    """A host drops a server that answers a question nobody asked.

    Every host sends `notifications/initialized` straight after the handshake. This
    server used to reply to it with an error carrying a made-up `"id": null` — a
    response to a message that, having no id, was not waiting for one.
    """

    def setUp(self):
        self.store = Store(os.path.join(tempfile.mkdtemp(), "g.db"))

    def _ask(self, req):
        return mcp.handle(self.store, req)

    def test_a_notification_is_never_answered(self):
        for method in ("notifications/initialized", "notifications/cancelled",
                       "notifications/anything_at_all"):
            with self.subTest(method=method):
                self.assertIsNone(self._ask({"jsonrpc": "2.0", "method": method}),
                                  "a message with no id was answered")

    def test_an_unknown_notification_is_silent_rather_than_an_error(self):
        """Even an unsupported method must not produce a reply when it has no id."""
        self.assertIsNone(self._ask({"jsonrpc": "2.0", "method": "no/such/thing"}))

    def test_the_clients_protocol_version_is_echoed_when_we_speak_it(self):
        for asked in mcp.PROTOCOL_VERSIONS:
            with self.subTest(asked=asked):
                out = self._ask({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": asked}})
                self.assertEqual(out["protocolVersion"], asked)

    def test_an_unknown_version_gets_ours_rather_than_silence(self):
        out = self._ask({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(out["protocolVersion"], mcp.PROTOCOL_VERSIONS[0])

    def test_errors_carry_a_protocol_code_not_a_python_class_name(self):
        cases = [
            ({"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
             mcp.METHOD_NOT_FOUND),
            ({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "nope", "arguments": {}}}, mcp.INVALID_PARAMS),
            ({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "find_symbols", "arguments": {}}},
             mcp.INVALID_PARAMS),
        ]
        for req, code in cases:
            with self.subTest(method=req.get("method")):
                with self.assertRaises(mcp.ProtocolError) as caught:
                    self._ask(req)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("KeyError", str(caught.exception))

    def test_a_missing_argument_says_which_one(self):
        with self.assertRaises(mcp.ProtocolError) as caught:
            self._ask({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "find_symbols", "arguments": {}}})
        self.assertIn("query", str(caught.exception))
        self.assertIn("find_symbols", str(caught.exception))

    def test_ping_is_answered(self):
        self.assertEqual(self._ask({"jsonrpc": "2.0", "id": 1, "method": "ping"}), {})


class TheMcpSurfaceIsReadOnly(unittest.TestCase):
    def test_thirteen_tools_and_none_of_them_write(self):
        names = {t["name"] for t in mcp.TOOLS}
        self.assertEqual(names, {
            "list_repos", "find_symbols", "list_files", "map_coverage",
            "describe_symbol", "expand_symbol", "outline_file", "read_source",
            "related_symbols", "file_imports", "blast_radius",
            "repo_summary", "index_health"})

    def test_no_tool_changes_a_single_row(self):
        """Indexing is a separate, deliberate act. There is no write path from here.

        Checked by behaviour rather than by name: `list_repos` has "index" in
        its name and writes nothing, so a substring rule would be both wrong and
        reassuring. Every tool is called and the row counts must not move.
        """
        from skygraph import tools as surface
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "a.py")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(PY)
        db = os.path.join(tmp, "g.db")
        index(tmp, repo="r", db=db)
        store = Store(db)

        def counts():
            return tuple(store.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                         for t in ("symbols", "edges", "files"))

        before = counts()
        sample = {"repo": "r", "branch": "main", "query": "Alpha",
                  "qualified_name": "a.py::Alpha", "filepath": "a.py",
                  "symbol": "a.py::Alpha"}
        for name, (handler, _desc, required) in surface.TOOLS.items():
            with self.subTest(tool=name):
                handler(store, {k: sample[k] for k in
                                set(required) | {"repo", "branch"} & set(sample)})
                self.assertEqual(counts(), before, f"{name} changed the database")

    def test_only_one_tool_returns_source(self):
        """The saving comes from looking before fetching, so exactly one tool fetches."""
        returns_code = [t["name"] for t in mcp.TOOLS
                        if "source" in t["description"].lower()
                        and "returns code" in t["description"].lower()]
        self.assertEqual(returns_code, ["read_source"])

    def test_every_tool_declares_its_required_arguments(self):
        for tool in mcp.TOOLS:
            with self.subTest(tool=tool["name"]):
                schema = tool["inputSchema"]
                for name in schema["required"]:
                    self.assertIn(name, schema["properties"],
                                  "a required argument with no declared shape")

    def test_an_unknown_tool_raises(self):
        tmp = tempfile.mkdtemp()
        with self.assertRaises(KeyError):
            mcp.call(Store(os.path.join(tmp, "m.db")), "code_delete_everything", {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
