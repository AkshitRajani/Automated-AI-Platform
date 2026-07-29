"""
Adversarial tests for the A12 silent-miss trio (registry: B1 / B2 / B3).

Each was a way for real information to disappear without a trace. The tests
assert BOTH directions: the information now survives, and nothing false is
invented in its place.
"""
import textwrap

from analyzer.extract import analyze


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


def _objs(qf, pred):
    return [q.object for q in qf.quads if q.predicate == pred]


# --------------------------------------------------------------------------
# B1 — a lambda declared in TWO homes must yield ONE entity but ALL settings
# --------------------------------------------------------------------------
class TestB1DualHomeEnv:
    def test_second_home_env_values_survive(self, tmp_path):
        _write(tmp_path, "tfe/variables.tf", """
            variable "lambda-list" {
              default = {
                "data-pull" = { handler = "lambda_handler.main" }
              }
            }
        """)
        _write(tmp_path, "tfe/workspace_vars.tfvars", """
            lambda-list = {
              "data-pull" = {
                function_name = "data-pull"
                handler = "lambda_handler.main"
                environment_vars = { BUCKET = "real-bucket", JSON_KEY = "cfg/key.json" }
              }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        lams = [e for e in qf.entities if e.type == "LambdaFunction"]
        assert len(lams) == 1                       # dedup still holds
        assert qf.bindings.get("BUCKET") == "real-bucket"       # B1: settings from
        assert qf.bindings.get("JSON_KEY") == "cfg/key.json"    # the second home

    def test_first_home_env_also_survives_when_second_is_skeleton(self, tmp_path):
        _write(tmp_path, "tfe/main.tfvars", """
            lambda-list = {
              "data-pull" = {
                function_name = "data-pull"
                environment_vars = { BUCKET = "real-bucket" }
              }
            }
        """)
        _write(tmp_path, "tfe/extra.tf", """
            locals {
              shadow = { "data-pull" = { handler = "lambda_handler.main" } }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        assert qf.bindings.get("BUCKET") == "real-bucket"


# --------------------------------------------------------------------------
# B2 — templatefile targets are read whatever their extension
# --------------------------------------------------------------------------
MACHINE_JSON = """
{
  "StartAt": "Load",
  "States": {
    "Load":   { "Type": "Task", "Resource": "${loader_arn}", "Next": "Done" },
    "Done":   { "Type": "Succeed" }
  }
}
"""

STEP_FN_TF = """
    resource "aws_sfn_state_machine" "m" {
      name = "real-machine-tf"
      definition = templatefile("%s", { loader_arn = "real-loader-tf" })
    }
"""


class TestB2TemplatefileTargets:
    def test_tpl_extension_is_parsed(self, tmp_path):
        _write(tmp_path, "tfe/step_function_definition.tpl", MACHINE_JSON)
        _write(tmp_path, "tfe/main.tf",
               STEP_FN_TF % "${path.module}/step_function_definition.tpl")
        qf = analyze(str(tmp_path), "t")
        assert any(e.id == "StateMachine:real-machine-tf" for e in qf.entities)
        # the machine's states exist AND the varmap answered the blank
        assert "LambdaFunction:real-loader-tf" in _objs(qf, "INVOKES_LAMBDA")
        # nothing pending: the checkpoint is satisfied for REAL, not vacuously
        assert qf.pending_names == []

    def test_json_extension_unchanged(self, tmp_path):
        _write(tmp_path, "tfe/machine.asl.json", MACHINE_JSON)
        _write(tmp_path, "tfe/main.tf", STEP_FN_TF % "${path.module}/machine.asl.json")
        qf = analyze(str(tmp_path), "t")
        assert any(e.id == "StateMachine:real-machine-tf" for e in qf.entities)
        states = [e for e in qf.entities if e.type == "State"
                  and "real-machine-tf" in e.id]
        assert len(states) == 2                    # parsed once, not twice

    def test_missing_target_is_noted_never_silent(self, tmp_path):
        _write(tmp_path, "tfe/main.tf", STEP_FN_TF % "${path.module}/not_there.tpl")
        qf = analyze(str(tmp_path), "t")
        assert any("not in the upload" in n for n in qf.analyzer_notes)

    def test_non_machine_target_is_noted(self, tmp_path):
        _write(tmp_path, "tfe/notes.tpl", "just some text, not a machine")
        _write(tmp_path, "tfe/main.tf", STEP_FN_TF % "${path.module}/notes.tpl")
        qf = analyze(str(tmp_path), "t")
        assert any("does not parse as a state machine" in n
                   for n in qf.analyzer_notes)


# --------------------------------------------------------------------------
# B3 — a still-blank ${x} Resource becomes a QUESTION, never nothing
# --------------------------------------------------------------------------
class TestB3BareTokenResource:
    def test_bare_token_surfaces_as_pending(self, tmp_path):
        _write(tmp_path, "wf/machine.asl.json", """
        {
          "StartAt": "Notify",
          "States": {
            "Notify": { "Type": "Task", "Resource": "${notify_arn}", "End": true }
          }
        }
        """)
        qf = analyze(str(tmp_path), "t")
        assert "LambdaFunction:${notify_arn}" in _objs(qf, "INVOKES_LAMBDA")
        assert "notify_arn" in qf.pending_names            # asked, not dropped
        assert not any(e.type == "Journey" for e in qf.entities)   # journeys withheld

    def test_answered_token_resolves_to_real_lambda(self, tmp_path):
        _write(tmp_path, "wf/machine.asl.json", """
        {
          "StartAt": "Notify",
          "States": {
            "Notify": { "Type": "Task", "Resource": "${notify_arn}", "End": true }
          }
        }
        """)
        sheets = tmp_path / "sheets"
        sheets.mkdir()
        (sheets / "t_worksheet.yaml").write_text("notify_arn: real-notify-tf\n",
                                                 encoding="utf-8")
        qf = analyze(str(tmp_path), "t", names_dir=str(sheets))
        assert "LambdaFunction:real-notify-tf" in _objs(qf, "INVOKES_LAMBDA")
        assert qf.pending_names == []

    def test_arn_forms_still_work(self, tmp_path):
        _write(tmp_path, "wf/machine.asl.json", """
        {
          "StartAt": "A",
          "States": {
            "A": { "Type": "Task",
                   "Resource": "arn:aws:lambda:us-east-1:1:function:real-a-tf",
                   "Next": "B" },
            "B": { "Type": "Task",
                   "Resource": "arn:aws:states:::lambda:invoke",
                   "Parameters": { "FunctionName": "real-b-tf" },
                   "End": true }
          }
        }
        """)
        qf = analyze(str(tmp_path), "t")
        objs = _objs(qf, "INVOKES_LAMBDA")
        assert "LambdaFunction:real-a-tf" in objs
        assert "LambdaFunction:real-b-tf" in objs

    def test_non_lambda_integrations_still_ignored(self, tmp_path):
        # An SQS/other service integration ARN must NOT be read as a lambda.
        _write(tmp_path, "wf/machine.asl.json", """
        {
          "StartAt": "Q",
          "States": {
            "Q": { "Type": "Task",
                   "Resource": "arn:aws:states:::sqs:sendMessage",
                   "End": true }
          }
        }
        """)
        qf = analyze(str(tmp_path), "t")
        assert _objs(qf, "INVOKES_LAMBDA") == []
