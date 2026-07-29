"""
Adversarial tests for A7 — the deployed-name confirmation checkpoint.

The disease: terraform states half a lambda name ("batch-csv-queries-tf"); the
deploy machinery completes it invisibly; the analyzer wrote the half-name with
full confidence, and tests/log-lookups downstream would use a name AWS has
never heard of.

The law under test: terraform-declared names are PROPOSALS. They are listed
for a human; corrections come back as ``lambda_name.<declared>: <deployed>``;
nothing computes journeys until ``confirm_lambda_names: yes``; every
correction travels in the quad's metadata. Manifest-declared names (whose
framework semantics make the entry name the deployed name) are never
questioned.
"""
import textwrap

from analyzer.emit import to_dict
from analyzer.extract import analyze


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


def _app(tmp_path):
    _write(tmp_path, "tfe/vars.tfvars", """
        lambda-list = {
          "ex0-batch" = { function_name = "batch-csv-queries-tf"
                          handler = "lambda_handler.main"
                          s3_key = "FORKLIFT/ex0-batch-x.zip" }
        }
    """)
    _write(tmp_path, "src/ex0-batch/lambda_handler.py", """
        def main(e, c):
            return e
    """)
    _write(tmp_path, "wf/machine.asl.json", """
    {
      "StartAt": "Run",
      "States": {
        "Run": { "Type": "Task", "Resource": "ex0-batch-csv-queries-tf", "End": true }
      }
    }
    """)


def _sheet(tmp_path, text):
    sheets = tmp_path / "sheets"
    sheets.mkdir(exist_ok=True)
    (sheets / "t_worksheet.yaml").write_text(textwrap.dedent(text),
                                             encoding="utf-8")
    return str(sheets)


class TestTheCheckpoint:
    def test_unconfirmed_names_halt_the_run(self, tmp_path):
        _app(tmp_path)
        qf = analyze(str(tmp_path), "t")
        assert "confirm_lambda_names" in qf.pending_names
        assert qf.lambda_names_declared == ["batch-csv-queries-tf"]
        assert not any(e.type == "Journey" for e in qf.entities)   # withheld

    def test_confirmed_names_complete_the_run(self, tmp_path):
        _app(tmp_path)
        qf = analyze(str(tmp_path), "t",
                     names_dir=_sheet(tmp_path, "confirm_lambda_names: yes\n"))
        assert "confirm_lambda_names" not in qf.pending_names
        assert qf.lambda_names_confirmed is True
        assert any(e.type == "Journey" for e in qf.entities)

    def test_correction_renames_the_lambda_everywhere(self, tmp_path):
        _app(tmp_path)
        qf = analyze(str(tmp_path), "t", names_dir=_sheet(tmp_path, """
            confirm_lambda_names: yes
            lambda_name.batch-csv-queries-tf: ex0-batch-csv-queries-tf
        """))
        names = {e.name for e in qf.entities if e.type == "LambdaFunction"}
        assert names == {"ex0-batch-csv-queries-tf"}          # renamed
        assert "batch-csv-queries-tf" not in {
            q.object for q in qf.quads} | {q.subject for q in qf.quads}
        # ... and the workflow's reference to the FULL name now lands on the
        # declared entity (the corrected name heals the split identity):
        invokes = [q for q in qf.quads if q.predicate == "INVOKES_LAMBDA"]
        assert any(q.object == "LambdaFunction:ex0-batch-csv-queries-tf"
                   for q in invokes)
        # the code link survives the rename (hints were re-keyed):
        handled = [q for q in qf.quads if q.predicate == "HANDLED_BY"]
        assert handled and handled[0].subject == "LambdaFunction:ex0-batch-csv-queries-tf"
        assert handled[0].object == "Function:src.ex0-batch.lambda_handler.main"

    def test_stale_correction_is_warned_never_applied(self, tmp_path):
        _app(tmp_path)
        qf = analyze(str(tmp_path), "t", names_dir=_sheet(tmp_path, """
            confirm_lambda_names: yes
            lambda_name.no-such-lambda-tf: whatever-tf
        """))
        assert any("no-such-lambda-tf" in w for w in qf.sheet_warnings)
        assert {e.name for e in qf.entities if e.type == "LambdaFunction"} \
            == {"batch-csv-queries-tf"}

    def test_manifest_lambdas_are_never_questioned(self, tmp_path):
        _write(tmp_path, "serverless.yml", """
            functions:
              data-pull:
                handler: lambdas/data_pull.handler
        """)
        _write(tmp_path, "lambdas/data_pull.py", """
            def handler(e, c):
                return e
        """)
        qf = analyze(str(tmp_path), "t")
        assert qf.lambda_names_declared == []
        assert "confirm_lambda_names" not in qf.pending_names

    def test_no_terraform_no_question(self, tmp_path):
        _write(tmp_path, "src/app.py", "def main():\n    return 1\n")
        qf = analyze(str(tmp_path), "t")
        assert "confirm_lambda_names" not in qf.pending_names


class TestAuditTrail:
    def test_metadata_carries_declared_confirmed_and_corrections(self, tmp_path):
        _app(tmp_path)
        qf = analyze(str(tmp_path), "t", names_dir=_sheet(tmp_path, """
            confirm_lambda_names: yes
            lambda_name.batch-csv-queries-tf: ex0-batch-csv-queries-tf
        """))
        meta = to_dict(qf)["metadata"]
        assert meta["lambda_names_confirmed"] is True
        assert meta["lambda_name_corrections"] == {
            "batch-csv-queries-tf": "ex0-batch-csv-queries-tf"}
        assert meta["lambda_names_declared"] == ["batch-csv-queries-tf"]

    def test_reserved_keys_never_leak_into_token_answers(self, tmp_path):
        _app(tmp_path)
        qf = analyze(str(tmp_path), "t", names_dir=_sheet(tmp_path, """
            confirm_lambda_names: yes
            lambda_name.batch-csv-queries-tf: ex0-batch-csv-queries-tf
        """))
        assert "confirm_lambda_names" not in qf.human_answers
        assert not any(k.startswith("lambda_name.") for k in qf.human_answers)
        assert not any("confirm_lambda_names" in w for w in qf.sheet_warnings)

    def test_rerun_with_same_sheet_is_idempotent(self, tmp_path):
        _app(tmp_path)
        sheets = _sheet(tmp_path, """
            confirm_lambda_names: yes
            lambda_name.batch-csv-queries-tf: ex0-batch-csv-queries-tf
        """)
        one = to_dict(analyze(str(tmp_path), "t", names_dir=sheets))
        two = to_dict(analyze(str(tmp_path), "t", names_dir=sheets))
        assert one == two


class TestOrderingWithEnvironment:
    def test_environment_question_comes_before_names(self, tmp_path):
        # Two competing env files, each declaring lambdas: the environment must
        # be chosen FIRST (its answer changes which lambda list even exists),
        # and while it is unchosen there is no name list to confirm.
        _write(tmp_path, "tfe/workspace_vars.test.tfvars", """
            B = "test-bucket"
            lambda-list = {
              "x" = { function_name = "x-tf"
                      handler = "h.main" }
            }
        """)
        _write(tmp_path, "tfe/workspace_vars.devl.tfvars", """
            B = "devl-bucket"
            lambda-list = {
              "x" = { function_name = "x-devl-tf"
                      handler = "h.main" }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        assert qf.pending_names[0] == "environment_file"
        assert "confirm_lambda_names" not in qf.pending_names
        # choose the environment -> NOW the names ask for confirmation
        qf2 = analyze(str(tmp_path), "t", env_file="workspace_vars.test.tfvars")
        assert qf2.pending_names[0] == "confirm_lambda_names"
        assert qf2.lambda_names_declared == ["x-tf"]
