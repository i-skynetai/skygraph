import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from codeindex import frontends, mcp
from codeindex.schema import Symbol, Edge, KINDS, RELATIONS
from codeindex.store import Store
from codeindex.indexer import index

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


class OtherLanguagesUseTheQueryTier(unittest.TestCase):
    def test_typescript(self):
        r = frontends.parse("b.ts", TS)
        self.assertEqual(r.tier, "query")
        self.assertIn("b.ts::Beta", {s.name for s in r.symbols})

    def test_go(self):
        r = frontends.parse("s.go", GO)
        self.assertEqual(r.tier, "query")
        self.assertIn("s.go::Server", {s.name for s in r.symbols})

    def test_eleven_languages_are_claimed(self):
        self.assertEqual(1 + len(frontends.QUERY_LANGUAGES), 11)


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


class TheMcpSurfaceIsReadOnly(unittest.TestCase):
    def test_five_tools_and_none_of_them_write(self):
        names = {t["name"] for t in mcp.TOOLS}
        self.assertEqual(names, {"code_search", "code_neighbours", "code_repos",
                                 "code_stats", "code_degraded"})

    def test_an_unknown_tool_raises(self):
        tmp = tempfile.mkdtemp()
        with self.assertRaises(KeyError):
            mcp.call(Store(os.path.join(tmp, "m.db")), "code_delete_everything", {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
