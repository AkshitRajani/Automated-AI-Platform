"""Terraform pass: HCL subset reader, templatefile var maps, inline machines,
tfvars lambda-lists, Catch/Parallel wiring, and the front-door collapse."""
import os

import yaml

from analyzer.extract import analyze
from analyzer.terraform import extract_terraform, parse_hcl


# --- the reader --------------------------------------------------------------------
def test_hcl_reader_blocks_attrs_and_values():
    attrs, blocks = parse_hcl('''
# comment
role = "arn:aws:iam::1:role/x"
resource "aws_lambda_function" "pull" {
  function_name = "app-pull"
  handler       = "pull.handler"
  memory        = 256
  publish       = false
  layers        = ["a", "b"]
  environment {
    variables = { OUT = "bucket-1" }
  }
}
''')
    assert attrs["role"] == "arn:aws:iam::1:role/x"
    (btype, labels, b_attrs, b_blocks), = blocks
    assert (btype, labels) == ("resource", ["aws_lambda_function", "pull"])
    assert b_attrs["function_name"] == "app-pull"
    assert b_attrs["memory"] == 256 and b_attrs["publish"] is False
    assert b_attrs["layers"] == ["a", "b"]


def test_unparseable_expression_degrades_to_blank_not_crash():
    attrs, blocks = parse_hcl('''
resource "aws_lambda_function" "x" {
  function_name = var.prefix != "" ? "a" : "b"
  handler       = "x.handler"
}
''')
    (_, _, b_attrs, _), = blocks
    assert b_attrs["handler"] == "x.handler"          # the file keeps reading
    assert b_attrs["function_name"] == ("unparsed", None)   # the value is honest


def test_tfvars_lambda_list_sampleapp_shape(tmp_path):
    """The provider's own argument names (function_name/handler) mark lambda
    declarations inside a module's .tfvars value map — a real field layout."""
    (tmp_path / "workspace_vars.test.tfvars").write_text('''
lambda-list = {
  ex0-step-planner-data-pull = {
    function_name = "ex0-step-planner-data-pull-tf"
    handler       = "lambda_handler.main"
    environment_vars = {
      BucketF0N = "ex0-test-cmd1-us-east-1"
      DERIVED   = "${var.unknowable}"
    }
    unique_identifier = null
  }
}
''')
    ents, quads, bindings, _defs, _vmaps, _inline, _notes, _hints, _env = extract_terraform(str(tmp_path))
    assert [e.id for e in ents] == ["LambdaFunction:ex0-step-planner-data-pull-tf"]
    assert [(q.predicate, q.object) for q in quads] == \
        [("HANDLED_BY", "Function:lambda_handler.main")]
    assert bindings["BucketF0N"] == "ex0-test-cmd1-us-east-1"
    assert "DERIVED" not in bindings                   # ${} is never harvested


# --- end-to-end: the twin collapse --------------------------------------------------
def _twin(tmp_path):
    (tmp_path / "lambdas").mkdir()
    for name in ("pull", "load"):
        (tmp_path / "lambdas" / f"{name}.py").write_text(
            "import boto3\n"
            "def handler(event, context):\n"
            f"    boto3.client('s3').put_object(Bucket='b', Key='{name}.csv')\n")
    (tmp_path / "main.tf").write_text('''
resource "aws_lambda_function" "pull" {
  function_name = "app-pull"
  handler       = "pull.handler"
}
resource "aws_lambda_function" "load" {
  function_name = "app-load"
  handler       = "load.handler"
}
resource "aws_sfn_state_machine" "importer" {
  name       = "app-importer"
  definition = templatefile("${path.module}/import.asl.json", {
    pull_arn = aws_lambda_function.pull.arn
    load_arn = aws_lambda_function.load.arn
  })
}
''')
    (tmp_path / "import.asl.json").write_text(yaml.safe_dump({
        "StartAt": "Pull",
        "States": {
            "Pull": {"Type": "Task",
                     "Resource": "arn:aws:states:::lambda:invoke",
                     "Parameters": {"FunctionName": "${pull_arn}"},
                     "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "OnFail"}],
                     "Next": "Fan"},
            "Fan": {"Type": "Parallel",
                    "Branches": [{"StartAt": "Load",
                                  "States": {"Load": {
                                      "Type": "Task",
                                      "Resource": "arn:aws:states:::lambda:invoke",
                                      "Parameters": {"FunctionName": "${load_arn}"},
                                      "End": True}}}],
                    "End": True},
            "OnFail": {"Type": "Fail"},
        }}))


def test_terraform_twin_collapses_to_one_front_door(tmp_path):
    """The 456 mechanism, killed: templatefile blanks resolve from the repo, the
    Catch target and the Parallel branch connect, handlers suffix-join into code
    — ONE machine journey, zero fake journeys, zero blanks left to ask."""
    _twin(tmp_path)
    sheets = tmp_path / "sheets"
    sheets.mkdir(exist_ok=True)
    (sheets / "t_worksheet.yaml").write_text("confirm_lambda_names: yes\n")
    qf = analyze(str(tmp_path), "T", names_dir=str(sheets))
    assert qf.pending_names == []
    journeys = [e.id for e in qf.entities if e.type == "Journey"]
    assert journeys == ["Journey:StateMachine:app-importer"]
    assert qf.unwired == []
    members = {q.object for q in qf.quads
               if q.subject == "Journey:StateMachine:app-importer"
               and q.predicate == "HAS_MEMBER"}
    # blanks landed on the real lambdas, which landed on the real code
    assert "LambdaFunction:app-pull" in members
    assert "LambdaFunction:app-load" in members            # via the Parallel branch
    assert "State:app-importer::OnFail" in members         # via the Catch edge
    assert "Function:lambdas.pull.handler" in members      # handler suffix join


def test_inline_jsonencode_machine(tmp_path):
    (tmp_path / "r.py").write_text(
        "def handler(event, context):\n    return 1\n")
    (tmp_path / "main.tf").write_text('''
resource "aws_lambda_function" "report" {
  function_name = "app-report"
  handler       = "r.handler"
}
resource "aws_sfn_state_machine" "reporter" {
  name = "app-reporter"
  definition = jsonencode({
    StartAt = "Build"
    States = {
      Build = {
        Type     = "Task"
        Resource = aws_lambda_function.report.arn
        End      = true
      }
    }
  })
}
''')
    sheets = tmp_path / "sheets"
    sheets.mkdir(exist_ok=True)
    (sheets / "t_worksheet.yaml").write_text("confirm_lambda_names: yes\n")
    qf = analyze(str(tmp_path), "T", names_dir=str(sheets))
    journeys = [e.id for e in qf.entities if e.type == "Journey"]
    assert journeys == ["Journey:StateMachine:app-reporter"]
    assert any(q.predicate == "INVOKES_LAMBDA"
               and q.object == "LambdaFunction:app-report" for q in qf.quads)


def test_nested_var_walk_is_generic_not_app_shaped(tmp_path):
    """var.X["k"].field is a pure data walk into whatever map the repo declares —
    proven here on a domain that has nothing to do with lambdas or any client
    layout. And a missing hop resolves to nothing (a visible blank), never a
    guess."""
    (tmp_path / "vars.tfvars").write_text('''
queue-config = {
  orders = {
    queue_name = "orders-inbound-q"
    dlq_name   = "orders-dead-letter-q"
  }
}
''')
    (tmp_path / "main.tf").write_text('''
resource "aws_sfn_state_machine" "poller" {
  name       = "poller"
  definition = templatefile("${path.module}/poll.asl.json", {
    queue    = var.queue-config["orders"].queue_name
    missing  = var.queue-config["payments"].queue_name
  })
}
''')
    (tmp_path / "poll.asl.json").write_text(yaml.safe_dump({
        "StartAt": "S", "States": {"S": {"Type": "Succeed"}}}))
    _e, _q, _b, _d, vmaps, _i, _n, _h, _env = extract_terraform(str(tmp_path))
    vmap = vmaps["poll.asl.json"]
    assert vmap["queue"] == "orders-inbound-q"     # literal at the end → copied
    assert "missing" not in vmap                    # missing hop → stays a blank


def test_unresolvable_templatefile_value_stays_a_visible_blank(tmp_path):
    """A var-map value only Terraform state knows (module output) is NOT guessed:
    the blank survives into the graph and the gate holds journeys until a human
    answers — the unskippable checkpoint, end to end."""
    (tmp_path / "main.tf").write_text('''
resource "aws_sfn_state_machine" "m" {
  name       = "app-m"
  definition = templatefile("${path.module}/m.asl.json", {
    pull_arn = module.lambdas["pull"].arn
  })
}
''')
    (tmp_path / "m.asl.json").write_text(yaml.safe_dump({
        "StartAt": "Pull",
        "States": {"Pull": {"Type": "Task",
                            "Resource": "arn:aws:states:::lambda:invoke",
                            "Parameters": {"FunctionName": "${pull_arn}"},
                            "End": True}}}))
    sheets = tmp_path / "sheets"
    sheets.mkdir(exist_ok=True)
    (sheets / "t_worksheet.yaml").write_text("confirm_lambda_names: yes\n")
    qf = analyze(str(tmp_path), "T", names_dir=str(sheets))
    assert qf.pending_names == ["pull_arn"]
    assert not [e for e in qf.entities if e.type == "Journey"]
