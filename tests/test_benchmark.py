"""The golden-question benchmark: does the graph answer what a coder asks, and cheaply?

Two small repositories under `tests/fixtures/`, each written by hand so every expected
answer is known from the source and not derived from grep — the first version of this
benchmark used grep as its ground truth and called four correct answers wrong.

Every question asserts two things: the answer is right, and it fits a byte ceiling. The
ceilings are about 1.5× the size measured when the test was written, so a change that
doubles a response fails here before anyone reads it in a context window.

A question the graph cannot answer yet is kept as an expected failure rather than
dropped: it documents the gap, and it flips to a failure — loudly — the day the gap
closes, so the ceiling and the answer get re-checked then.
"""
import json, os, sys, tempfile, unittest
from pathlib import Path

REPO = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(REPO))
from skygraph import treesitter                                    # noqa: E402
from skygraph import tools as T                                    # noqa: E402
from skygraph.indexer import index                                 # noqa: E402
from skygraph.store import Store                                   # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"


def _size(payload) -> int:
    return len(json.dumps(payload, indent=2))


class _Bench(unittest.TestCase):
    fixture = ""

    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), "bench.db")
        cls.report = index(FIXTURES / cls.fixture, repo="bench", db=cls.db)
        cls.store = Store(cls.db)

    def ask(self, tool: str, ceiling: int, **args):
        args.setdefault("repo", "bench")
        out = T.TOOLS[tool][0](self.store, args)
        self.assertLessEqual(_size(out), ceiling,
                             f"{tool} answered in {_size(out)} bytes; ceiling {ceiling}")
        return out

    @staticmethod
    def callers(out) -> set:
        return {c["other"] for c in out.get("called_by", [])}

    @staticmethod
    def callees(out) -> set:
        return {c["other"] for c in out.get("calls", [])}


class GoldenQuestionsPython(_Bench):
    fixture = "bench_py"

    def test_where_is_a_symbol(self):
        out = self.ask("find_symbols", 450, query="create_user")
        self.assertEqual([r["name"] for r in out["results"]], ["app/api.py::create_user"])

    def test_what_is_in_a_file(self):
        out = self.ask("outline_file", 1_500, filepath="app/repo.py")
        self.assertEqual([r["name"].split("::")[-1] for r in out["signatures"]],
                         ["app/repo.py", "find_user", "get", "Registry",
                          "Registry.register", "Registry.get"])

    def test_which_table_an_endpoint_writes(self):
        out = self.ask("expand_symbol", 900, qualified_name="app/api.py::POST /users")
        self.assertEqual(out["trace"], [{
            "handler": "app/api.py::create_user", "entity": "app/models.py::User",
            "tables": ["users"], "confidence": "derived — the handler calls the model"}])

    def test_who_calls_a_function_across_files(self):
        out = self.ask("expand_symbol", 1_000, qualified_name="app/repo.py::find_user")
        self.assertEqual(self.callers(out),
                         {"app/api.py::read_user", "app/service.py::Worker.run"})
        self.assertEqual(self.callees(out), {"app/models.py::User"})

    def test_a_dict_get_is_not_a_caller_of_a_method_named_get(self):
        """`config.get("a")` on a parameter must not become a caller of `Registry.get`,
        nor of the top-level `get` — the receiver is untyped and stays that way."""
        out = self.ask("expand_symbol", 500, qualified_name="app/repo.py::Registry.get")
        self.assertEqual(self.callers(out), set())
        out = self.ask("expand_symbol", 500, qualified_name="app/repo.py::get")
        self.assertEqual(self.callers(out), set())
        rows = {r["resolution"] for r in self.store.db.execute(
            "SELECT resolution FROM edges WHERE rel='CALLS' AND raw_dst='config.get'")}
        self.assertEqual(rows, {"untyped"})

    def test_what_breaks_if_a_function_changes(self):
        out = self.ask("blast_radius", 600, symbol="app/repo.py::find_user",
                       direction="up", hops=2)
        self.assertEqual({c["symbol"] for c in out["callers"]},
                         {"app/api.py::read_user", "app/service.py::Worker.run"})
        self.assertFalse(out["callers_truncated"])

    def test_imports_are_files_not_names(self):
        out = self.ask("file_imports", 300, filepath="app/repo.py", direction="both")
        self.assertEqual(out["imports"], ["app/models.py"])
        self.assertEqual(out["imported_by"], ["app/api.py", "app/service.py"])

    def test_source_of_one_symbol_is_exact(self):
        out = self.ask("read_source", 500, qualified_name="app/repo.py::find_user")
        self.assertTrue(out["exact_range"])
        self.assertFalse(out["stale"])
        self.assertEqual(out["source"].splitlines()[0], "def find_user(user_id):")

    def test_health_says_what_it_could_not_type(self):
        out = self.ask("index_health", 6_000)
        self.assertGreaterEqual(out["call_edges"]["untyped"], 3)
        self.assertEqual(out["env_read_but_undeclared"], [],
                         "DATABASE_URL is declared in the Dockerfile")
        traversable = {l["language"] for l in out["languages"] if l["traversable"]}
        self.assertEqual(traversable, {"python"})

    def test_a_file_never_indexed_is_an_error(self):
        out = self.ask("outline_file", 400, filepath="app/nope.py")
        self.assertIn("error", out)

    @unittest.expectedFailure
    def test_a_module_imported_from_its_package_is_followed(self):
        """`from app import service` then `service.configure()`. The import records the
        package, so the alias `service` is unknown and the call is untyped. Phase 1."""
        out = self.ask("expand_symbol", 700, qualified_name="app/service.py::configure")
        self.assertEqual(self.callers(out), {"app/main.py::boot"})


class GoldenQuestionsTypeScriptAndJava(_Bench):
    fixture = "bench_ts"

    @classmethod
    def setUpClass(cls):
        if not treesitter.available():
            raise unittest.SkipTest("tree-sitter is not installed")
        super().setUpClass()

    def test_a_generic_call_still_reaches_its_function(self):
        out = self.ask("expand_symbol", 900,
                       qualified_name="src/hooks/useApiQuery.ts::useApiQuery")
        self.assertEqual(self.callers(out),
                         {"src/pages/list.ts::ListPage.load", "src/pages/detail.ts::detail"})
        self.assertEqual(self.callees(out), {"src/hooks/useApiQuery.ts::load"})

    def test_what_is_in_a_typescript_file(self):
        out = self.ask("outline_file", 1_100, filepath="src/pages/list.ts")
        self.assertEqual([r["name"].split("::")[-1] for r in out["signatures"]],
                         ["src/pages/list.ts", "ListPage", "ListPage.load",
                          "ListPage.refresh"])

    def test_this_reaches_the_method_on_the_same_class(self):
        out = self.ask("expand_symbol", 750,
                       qualified_name="src/pages/list.ts::ListPage.refresh")
        self.assertEqual(self.callees(out), {"src/pages/list.ts::ListPage.load"})

    def test_a_private_java_method_does_not_collect_other_classes_callers(self):
        """The 735-caller bug: `TenantContext.getTenantId()` elsewhere must never be
        attributed to `Publisher.getTenantId`."""
        out = self.ask("expand_symbol", 600,
                       qualified_name="svc/Publisher.java::Publisher.getTenantId")
        self.assertNotIn("svc/Listener.java::Listener.on", self.callers(out))
        self.assertNotIn("svc/Publisher.java::Publisher.publish", {
            c for c in self.callers(out) if "TenantContext" in c})

    def test_health_reports_both_languages_traversable(self):
        out = self.ask("index_health", 6_000)
        traversable = {l["language"] for l in out["languages"] if l["traversable"]}
        self.assertEqual(traversable, {"typescript", "java"})

    @unittest.expectedFailure
    def test_a_same_package_java_class_is_a_known_receiver(self):
        """`TenantContext.getTenantId()` from a class in the same package, with no
        import. The receiver is untyped today. Phase 1: Java package resolution."""
        out = self.ask("expand_symbol", 700,
                       qualified_name="svc/TenantContext.java::TenantContext.getTenantId")
        self.assertEqual(self.callers(out), {"svc/Publisher.java::Publisher.publish",
                                             "svc/Listener.java::Listener.on"})

    @unittest.expectedFailure
    def test_a_bare_call_inside_a_java_class_is_an_implicit_this(self):
        """`getTenantId()` inside `Publisher` means `this.getTenantId()`. Phase 1."""
        out = self.ask("expand_symbol", 600,
                       qualified_name="svc/Publisher.java::Publisher.getTenantId")
        self.assertEqual(self.callers(out), {"svc/Publisher.java::Publisher.publish"})


if __name__ == "__main__":
    unittest.main()
