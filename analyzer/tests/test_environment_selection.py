"""
Adversarial tests for A15 — one map, ONE environment.

The disease: seven `workspace_vars.*.tfvars` files, one per environment, all
read together — devl bucket values silently landing in a test map.

The law under test: files that declare the same setting with different values
COMPETE; nothing from a competing file is used until a human (or a flag) names
the one that grounds the map; the choice and the exclusions are recorded.
"""
import textwrap

from analyzer.emit import to_dict
from analyzer.extract import analyze


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


TEST_TFVARS = """
    APP_BUCKET = "ex0-test-cmd1-us-east-1"
    lambda-list = {
      "ex0-pull" = { function_name = "pull-tf"
                     handler = "lambda_handler.main"
                     s3_key = "FORKLIFT/ex0-pull-x.zip" }
    }
"""
DEVL_TFVARS = """
    APP_BUCKET = "ex0-devl-cmd1-us-east-1"
    lambda-list = {
      "ex0-pull" = { function_name = "pull-devl-tf"
                     handler = "lambda_handler.main"
                     s3_key = "FORKLIFT/ex0-pull-x.zip" }
    }
"""


def _two_envs(tmp_path):
    _write(tmp_path, "tfe/workspace_vars.test.tfvars", TEST_TFVARS)
    _write(tmp_path, "tfe/workspace_vars.devl.tfvars", DEVL_TFVARS)
    _write(tmp_path, "src/ex0-pull/lambda_handler.py", """
        import os, boto3
        def main(e, c):
            boto3.client('s3').put_object(Bucket=os.environ['APP_BUCKET'], Key='k')
    """)


class TestCompetitionDetection:
    def test_undecided_run_halts_and_mixes_nothing(self, tmp_path):
        _two_envs(tmp_path)
        qf = analyze(str(tmp_path), "t")
        assert qf.pending_names[0] == "environment_file"
        assert len(qf.env_candidates) == 2
        # NOTHING from either competing file was used:
        assert "APP_BUCKET" not in qf.bindings
        assert not any(e.type == "LambdaFunction" for e in qf.entities)
        assert not any(e.type == "Journey" for e in qf.entities)  # halted
        assert any("no environment chosen" in n for n in qf.analyzer_notes)

    def test_single_tfvars_never_questioned(self, tmp_path):
        _write(tmp_path, "tfe/workspace_vars.test.tfvars", TEST_TFVARS)
        qf = analyze(str(tmp_path), "t")
        assert qf.env_candidates == []
        assert "environment_file" not in qf.pending_names

    def test_disjoint_tfvars_never_compete(self, tmp_path):
        # Two tfvars with no overlapping keys are parts of ONE configuration,
        # not two environments — no question.
        _write(tmp_path, "tfe/buckets.tfvars", 'BUCKET_A = "one"\n')
        _write(tmp_path, "tfe/topics.tfvars", 'TOPIC_B = "two"\n')
        qf = analyze(str(tmp_path), "t")
        assert qf.env_candidates == []
        assert qf.bindings.get("BUCKET_A") == "one"
        assert qf.bindings.get("TOPIC_B") == "two"

    def test_identical_values_never_compete(self, tmp_path):
        # The same key with the SAME value states one fact twice — no conflict.
        _write(tmp_path, "tfe/a.tfvars", 'REGION = "us-east-1"\n')
        _write(tmp_path, "tfe/b.tfvars", 'REGION = "us-east-1"\nEXTRA = "x"\n')
        qf = analyze(str(tmp_path), "t")
        assert qf.env_candidates == []


class TestSelection:
    def test_env_file_param_selects_and_excludes(self, tmp_path):
        _two_envs(tmp_path)
        qf = analyze(str(tmp_path), "t", env_file="workspace_vars.test.tfvars")
        assert qf.environment_file.endswith("workspace_vars.test.tfvars")
        assert qf.bindings["APP_BUCKET"] == "ex0-test-cmd1-us-east-1"
        lams = {e.name for e in qf.entities if e.type == "LambdaFunction"}
        assert lams == {"pull-tf"}                      # devl's lambda excluded
        # ... and the code fact resolved with the TEST bucket, end to end:
        assert any(q.object == "S3Object:ex0-test-cmd1-us-east-1/k"
                   for q in qf.quads if q.predicate == "WRITES_TO_S3")
        assert any("NOT used" in n for n in qf.analyzer_notes)

    def test_worksheet_answer_selects(self, tmp_path):
        _two_envs(tmp_path)
        sheets = tmp_path / "sheets"
        sheets.mkdir()
        (sheets / "t_worksheet.yaml").write_text(
            "environment_file: workspace_vars.devl.tfvars\n", encoding="utf-8")
        qf = analyze(str(tmp_path), "t", names_dir=str(sheets))
        assert qf.bindings["APP_BUCKET"] == "ex0-devl-cmd1-us-east-1"
        assert {e.name for e in qf.entities
                if e.type == "LambdaFunction"} == {"pull-devl-tf"}

    def test_param_beats_worksheet(self, tmp_path):
        _two_envs(tmp_path)
        sheets = tmp_path / "sheets"
        sheets.mkdir()
        (sheets / "t_worksheet.yaml").write_text(
            "environment_file: workspace_vars.devl.tfvars\n", encoding="utf-8")
        qf = analyze(str(tmp_path), "t", names_dir=str(sheets),
                     env_file="workspace_vars.test.tfvars")
        assert qf.bindings["APP_BUCKET"] == "ex0-test-cmd1-us-east-1"

    def test_wrong_answer_stays_pending(self, tmp_path):
        _two_envs(tmp_path)
        qf = analyze(str(tmp_path), "t", env_file="workspace_vars.prod.tfvars")
        assert "environment_file" in qf.pending_names
        assert "APP_BUCKET" not in qf.bindings

    def test_env_answer_never_becomes_a_token_answer(self, tmp_path):
        # The reserved key must not leak into token substitution or warnings.
        _two_envs(tmp_path)
        sheets = tmp_path / "sheets"
        sheets.mkdir()
        (sheets / "t_worksheet.yaml").write_text(
            "environment_file: workspace_vars.test.tfvars\n", encoding="utf-8")
        qf = analyze(str(tmp_path), "t", names_dir=str(sheets))
        assert "environment_file" not in qf.human_answers
        assert not any("environment_file" in w for w in qf.sheet_warnings)


class TestMetadata:
    def test_choice_and_candidates_travel_in_the_quad(self, tmp_path):
        _two_envs(tmp_path)
        qf = analyze(str(tmp_path), "t", env_file="workspace_vars.test.tfvars")
        meta = to_dict(qf)["metadata"]
        assert meta["environment_file"].endswith("workspace_vars.test.tfvars")
        assert len(meta["environment_candidates"]) == 2
