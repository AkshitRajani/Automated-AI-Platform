"""
Orchestration wiring without Bedrock/AWS:
  * onboarding runs parser → merged quad YAML, traces the stages, degrades cleanly
    when Bedrock + Postgres are absent (parser-only),
  * the diff parser extracts the changed file + added lines for gate 5,
  * the exec-env selector honours config and falls back safely.
"""
import os
import tempfile
import unittest

from core.config import CoreConfig
from core.execenv import make_exec_env
from core.generate import _parse_diff
from core.onboarding import onboard
from core.score import score_generated
from core.trace import TraceEmitter
from eval.execution import InProcessEnv


def _cfg(**over):
    base = dict(shared={"postgres": {"host": "", "password": ""},
                        "neptune": {"endpoint": ""},
                        "bedrock": {"model_arn": "", "region": "us-east-1"}},
               eval_env="inprocess", sandbox_dir="", quad_dir="",
               aws_region="us-east-1", max_repairs=2, stability_runs=3, mutation_max=8,
               golden_bdd_root="", score_output_dir="", scoring_threshold=0.45)
    base.update(over)
    return CoreConfig(**base)


class TestOnboardingParserOnly(unittest.TestCase):
    def test_parser_only_onboard_writes_quadfile_and_traces(self):
        repo = tempfile.mkdtemp()
        with open(os.path.join(repo, "svc.py"), "w") as f:
            f.write("import os\n"
                    "def handler():\n"
                    "    return os.environ['BUCKET']\n")
        events = []
        tr = TraceEmitter(); tr.add_listener(events.append)
        cfg = _cfg(quad_dir=tempfile.mkdtemp())

        res = onboard(repo, "APP", cfg, tr)

        self.assertGreater(res.parser_entities, 0)
        self.assertFalse(res.ingested)              # no Postgres → skipped, not faked
        self.assertEqual(res.agent_graph_facts, 0)  # no Bedrock → agent skipped
        self.assertTrue(os.path.isfile(res.quad_file))
        names = [e.name for e in events if e.kind == "span.start"]
        self.assertIn("onboard", names)
        self.assertIn("analyzer.parse", names)


class TestDiffParse(unittest.TestCase):
    def test_extracts_changed_file_and_added_lines(self):
        diff = (
            "--- a/svc.py\n"
            "+++ b/svc.py\n"
            "@@ -1,2 +1,4 @@\n"
            " import os\n"
            "+def added():\n"
            "+    return 1\n"
            " def handler():\n"
        )
        primary, changed = _parse_diff(diff)
        self.assertEqual(primary, "svc.py")
        self.assertIn(2, changed["svc.py"])     # 'def added()' is new line 2
        self.assertIn(3, changed["svc.py"])

    def test_empty_diff(self):
        primary, changed = _parse_diff("")
        self.assertIsNone(primary)
        self.assertEqual(changed, {})


class TestExecEnvSelector(unittest.TestCase):
    def test_default_is_inprocess(self):
        self.assertIsInstance(make_exec_env(_cfg()), InProcessEnv)

    def test_sandbox_missing_falls_back(self):
        env = make_exec_env(_cfg(eval_env="sandbox", sandbox_dir="/no/such/dir"))
        self.assertIsInstance(env, InProcessEnv)   # graceful fallback, not a crash


class TestScoreWiring(unittest.TestCase):
    def test_score_writes_json_and_html(self):
        golden = tempfile.mkdtemp()
        generated = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        feature = (
            "Feature: Login\n"
            "  Scenario: User signs in with valid credentials\n"
            "    When the user submits valid credentials\n"
            "    Then the user is logged in\n"
        )
        with open(os.path.join(golden, "login.feature"), "w", encoding="utf-8") as f:
            f.write(feature)
        with open(os.path.join(generated, "login.feature"), "w", encoding="utf-8") as f:
            f.write(feature)

        tr = TraceEmitter()
        cfg = _cfg(score_output_dir=out)
        res = score_generated("APP", generated, cfg, tr, golden_dir=golden, output_dir=out)

        self.assertTrue(os.path.isfile(res.report_json))
        self.assertTrue(os.path.isfile(res.report_html))
        self.assertGreaterEqual(res.overall_score, 50.0)
        self.assertEqual(res.matched_behaviors, 1)


if __name__ == "__main__":
    unittest.main()
