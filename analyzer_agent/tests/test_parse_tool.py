"""
The live ``parse(path)`` tool — Level 2 of the two-level design.

The load-bearing property: a single-file re-parse must produce the SAME canonical
ids as the full draft (computed relative to the repo root), so the agent can emit
edges against them and they connect. This test parses a nested file two ways —
whole-repo vs. only-this-file — and asserts the ids are identical.
"""
import os
import tempfile
import unittest

from analyzer import analyze
from analyzer_agent.store import FactStore
from analyzer_agent.tools import context, parse


class TestParseTool(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        # a nested package so the qualname depends on the repo root
        pkg = os.path.join(self.repo, "app", "svc")
        os.makedirs(pkg)
        open(os.path.join(self.repo, "app", "__init__.py"), "w").close()
        open(os.path.join(pkg, "__init__.py"), "w").close()
        with open(os.path.join(pkg, "core.py"), "w") as f:
            f.write("import os\n"
                    "def handler():\n"
                    "    return os.environ['BUCKET']\n")
        context.set_root(self.repo)
        context.set_store(FactStore(self.repo, "APP"))

    def test_single_file_ids_match_full_draft(self):
        rel = "app/svc/core.py"
        full = analyze(self.repo, app_id="APP")
        one = analyze(self.repo, app_id="APP", only=[rel])
        # the canonical id of handler must be identical whether parsed alone or in full
        full_ids = {e.id for e in full.entities if e.source and e.source.file_path == rel}
        one_ids = {e.id for e in one.entities}
        self.assertIn("Function:app.svc.core.handler", full_ids)
        self.assertEqual(one_ids, full_ids)

    def test_only_filter_restricts_to_the_file(self):
        one = analyze(self.repo, app_id="APP", only=["app/svc/core.py"])
        files = {e.source.file_path for e in one.entities if e.source}
        self.assertEqual(files, {"app/svc/core.py"})

    def test_parse_tool_returns_canonical_facts(self):
        out = parse("app/svc/core.py")
        self.assertIn("Function:app.svc.core.handler", out)
        self.assertIn("READS_ENV_VAR", out)        # the env read is reported
        self.assertIn("BUCKET", out)

    def test_parse_missing_file_is_honest(self):
        out = parse("app/svc/nope.py")
        self.assertIn("found nothing", out)


if __name__ == "__main__":
    unittest.main()
