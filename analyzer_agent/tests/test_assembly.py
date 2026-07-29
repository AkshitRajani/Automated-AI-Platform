"""
Assembly pieces that must hold WITHOUT Strands or Bedrock:
  * the repo guard confines paths,
  * the tool registry is what we expect (and LSP is gated by config),
  * the injected tools (repo_map / parser_facts / emit_fact) work against a draft.
"""
import os
import tempfile
import unittest

from analyzer.models import Entity, QuadFile, Quad, Source
from analyzer_agent.agent import RepoGuard, domain_tools, task_prompt, AnalyzerTask
from analyzer_agent.store import FactStore
from analyzer_agent.tools import context, emit_fact, parser_facts, repo_map


def _draft():
    return QuadFile(
        app_id="APP",
        entities=[
            Entity(id="a.py::handler", type="Function", name="app.handler",
                   source=Source("a.py", 2, 4)),
            Entity(id="b.py::read", type="Function", name="b.read",
                   source=Source("b.py", 1, 3)),
        ],
        quads=[
            Quad(subject="Function:app.handler", predicate="CALLS",
                 object="read", resolved=False, file_path="a.py", line=3),
        ],
    )


class TestRepoGuard(unittest.TestCase):
    def test_inside_allowed_outside_refused(self):
        tmp = tempfile.mkdtemp()
        g = RepoGuard(tmp)
        self.assertTrue(g.allows(os.path.join(tmp, "x/y.py")))
        self.assertTrue(g.allows("x/y.py"))           # relative -> joined under root
        self.assertFalse(g.allows("/etc/passwd"))
        self.assertFalse(g.allows(""))


class TestToolRegistry(unittest.TestCase):
    def test_lsp_gated_by_config(self):
        # No ANALYZER_LSP_ENDPOINT in env -> the 4 core tools, no lsp.
        os.environ.pop("ANALYZER_LSP_ENDPOINT", None)
        names = {getattr(t, "__name__", repr(t)) for t in domain_tools()}
        self.assertEqual(names, {"repo_map", "parser_facts", "parse", "emit_fact"})

    def test_lsp_wired_when_configured(self):
        os.environ["ANALYZER_LSP_ENDPOINT"] = "mcp://pyright"
        try:
            names = {getattr(t, "__name__", repr(t)) for t in domain_tools()}
            self.assertIn("lsp_resolve", names)
        finally:
            os.environ.pop("ANALYZER_LSP_ENDPOINT", None)

    def test_task_prompt_mentions_repo_and_app(self):
        t = AnalyzerTask(repo_dir="/x/y", app_id="DEMO")
        msg = task_prompt(t)
        self.assertIn("DEMO", msg)
        self.assertIn("/x/y", msg)


class TestInjectedTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "a.py"), "w") as f:
            f.write("def handler():\n    return read()\n    # call into b\n")
        context.set_draft(_draft())
        context.set_store(FactStore(self.tmp, "APP"))

    def test_repo_map_lists_units(self):
        out = repo_map()
        self.assertIn("Function:app.handler", out)
        self.assertIn("a.py", out)

    def test_parser_facts_unresolved_filter(self):
        out = parser_facts(only_unresolved=True)
        self.assertIn("UNRESOLVED", out)
        self.assertIn("CALLS", out)

    def test_emit_fact_routes_through_gate(self):
        # 'read' is visible at a.py:2 -> the CALLS edge should be kept for the graph
        res = emit_fact(subject="Function:app.handler", predicate="CALLS",
                        object="Function:b.read", file="a.py", line=2)
        self.assertTrue(res.startswith("[graph]"), res)


if __name__ == "__main__":
    unittest.main()
