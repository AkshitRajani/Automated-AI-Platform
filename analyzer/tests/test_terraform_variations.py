"""Robustness battery: the SAME facts in different valid formats must produce the
SAME result, and anything outside the readable subset must degrade to a visible
blank — never a wrong answer, never a crash, never silence.

Two properties, enforced forever:
  EQUIVALENCE — one machine, four Terraform definition styles, identical journey.
  SAFETY      — exotic constructs (for-expressions, conditionals, functions,
                splats, dynamic blocks) cost only their own value; siblings
                survive and unresolved references surface as human questions.
"""
import os

import yaml

from analyzer.extract import analyze
from analyzer.terraform import parse_hcl


# --- format variations of the reader ------------------------------------------------
def test_format_variations_all_read_identically():
    """Layout freedom that must never change meaning: one-line blocks, commas,
    trailing commas, quoted keys, colon separators, CRLF, comments, unicode."""
    expect = {"function_name": "app-x", "handler": "x.main"}
    variants = [
        'resource "aws_lambda_function" "x" { function_name = "app-x" handler = "x.main" }',
        'resource "aws_lambda_function" "x" {\n  function_name = "app-x",\n  handler = "x.main",\n}',
        'resource "aws_lambda_function" "x" {\r\n  function_name = "app-x"\r\n  handler = "x.main"\r\n}',
        ('resource "aws_lambda_function" "x" {\n'
         '  # the name\n  function_name = "app-x" // inline\n'
         '  /* block */ handler = "x.main"\n}'),
    ]
    for text in variants:
        _attrs, blocks = parse_hcl(text)
        (_t, _l, b_attrs, _b), = blocks
        assert {k: b_attrs[k] for k in expect} == expect, text


def test_map_syntax_variations_equal():
    a1, _ = parse_hcl('m = {\n  a = "1"\n  b = "2"\n}')
    a2, _ = parse_hcl('m = { a = "1", b = "2" }')
    a3, _ = parse_hcl('m = {\n  a : "1"\n  b : "2"\n}')
    a4, _ = parse_hcl('m = {\n  "a" = "1"\n  "b" = "2"\n}')
    assert a1["m"] == a2["m"] == a3["m"] == a4["m"] == {"a": "1", "b": "2"}


def test_heredoc_variants():
    a1, _ = parse_hcl('d = <<EOF\n{"StartAt": "S"}\nEOF\n')
    a2, _ = parse_hcl('d = <<-EOF\n  {"StartAt": "S"}\n  EOF\n')
    assert '"StartAt"' in a1["d"] and '"StartAt"' in a2["d"]


def test_outside_subset_costs_only_its_own_value():
    """for-expressions, conditionals, function calls, splats, dynamic blocks:
    each unreadable VALUE becomes unparsed; every sibling fact still reads."""
    attrs, blocks = parse_hcl('''
m    = { for k, v in var.x : k => v }
name = var.p != "" ? "a" : "b"
v    = aws_lambda_function.x[*].arn
mix  = {
  good = "v"
  bad  = upper("x")
}
resource "aws_lambda_function" "x" {
  function_name = "app-x"
  dynamic "environment" {
    for_each = var.env
    content { }
  }
  handler = "x.main"
}
after = "ok"
''')
    assert attrs["mix"]["good"] == "v"
    assert attrs["after"] == "ok"                       # the file kept reading
    (_t, _l, b_attrs, _b), = blocks
    assert b_attrs["function_name"] == "app-x" and b_attrs["handler"] == "x.main"


# --- end-to-end equivalence: one machine, four definition styles --------------------
_ASL_BLANK = yaml.safe_dump({
    "StartAt": "Pull",
    "States": {"Pull": {"Type": "Task",
                        "Resource": "arn:aws:states:::lambda:invoke",
                        "Parameters": {"FunctionName": "${pull_arn}"},
                        "End": True}}})
_LAMBDA_TF = ('resource "aws_lambda_function" "pull" {\n'
              '  function_name = "app-pull"\n  handler = "pull.handler"\n}\n')
_PY = "def handler(event, context):\n    return 1\n"


def _outcome(tmp_path, files):
    for rel, content in files.items():
        (tmp_path / rel).write_text(content)
    sheets = tmp_path / "sheets"
    sheets.mkdir(exist_ok=True)
    (sheets / "t_worksheet.yaml").write_text("confirm_lambda_names: yes\n")
    qf = analyze(str(tmp_path), "T", names_dir=str(sheets))
    return (sorted(e.id for e in qf.entities if e.type == "Journey"),
            sorted({q.object for q in qf.quads if q.predicate == "INVOKES_LAMBDA"}),
            qf.pending_names)


_STYLES = {
    "templatefile+resource_ref": {
        "pull.py": _PY, "sm.asl.json": _ASL_BLANK,
        "main.tf": _LAMBDA_TF +
            'resource "aws_sfn_state_machine" "m" {\n  name = "app-m"\n'
            '  definition = templatefile("${path.module}/sm.asl.json", '
            '{ pull_arn = aws_lambda_function.pull.arn })\n}\n'},
    "heredoc+interpolation": {
        "pull.py": _PY,
        "main.tf": _LAMBDA_TF +
            'resource "aws_sfn_state_machine" "m" {\n  name = "app-m"\n'
            '  definition = <<EOF\n'
            '{"StartAt": "Pull", "States": {"Pull": {"Type": "Task",\n'
            '  "Resource": "arn:aws:states:::lambda:invoke",\n'
            '  "Parameters": {"FunctionName": "${aws_lambda_function.pull.arn}"},\n'
            '  "End": true}}}\n'
            'EOF\n}\n'},
    "file()_no_placeholders": {
        "pull.py": _PY,
        "sm.asl.json": _ASL_BLANK.replace("${pull_arn}", "app-pull"),
        "main.tf": _LAMBDA_TF +
            'resource "aws_sfn_state_machine" "m" {\n  name = "app-m"\n'
            '  definition = file("${path.module}/sm.asl.json")\n}\n'},
    "tfvars_map+var_walk": {
        "pull.py": _PY, "sm.asl.json": _ASL_BLANK,
        "vars.tfvars": ('lambdas = {\n  pull = {\n    function_name = "app-pull"\n'
                        '    handler = "pull.handler"\n  }\n}\n'),
        "main.tf":
            'resource "aws_sfn_state_machine" "m" {\n  name = "app-m"\n'
            '  definition = templatefile("${path.module}/sm.asl.json", '
            '{ pull_arn = var.lambdas["pull"].function_name })\n}\n'},
}


def test_four_definition_styles_one_identical_outcome(tmp_path):
    outcomes = {}
    for style, files in _STYLES.items():
        d = tmp_path / style.replace("+", "_").replace("(", "").replace(")", "")
        d.mkdir()
        outcomes[style] = _outcome(d, files)
    expected = (["Journey:StateMachine:app-m"], ["LambdaFunction:app-pull"], [])
    for style, got in outcomes.items():
        assert got == expected, f"{style} diverged: {got}"


# --- the zero-lambda incident: files present, nothing found, nothing said -----------
_LAMBDA_MAP = '''
lambda-list = {
  app-worker = {
    function_name = "app-worker-tf"
    handler       = "worker.main"
  }
}
'''


def _count_lambdas(tmp_path):
    from analyzer.terraform import extract_terraform
    ents, _q, _b, _d, _v, _i, notes, _h, _env = extract_terraform(str(tmp_path))
    return len([e for e in ents if e.type == "LambdaFunction"]), notes


def test_utf16_tfvars_still_parses(tmp_path):
    """A Windows editor re-saving the file as UTF-16 must not silently erase
    every lambda (the zero-lambda incident, hypothesis 1)."""
    (tmp_path / "vars.tfvars").write_bytes(_LAMBDA_MAP.encode("utf-16"))
    n, _ = _count_lambdas(tmp_path)
    assert n == 1


def test_unterminated_string_costs_one_line_not_the_file(tmp_path):
    """One typo'd quote must never swallow the rest of the file (hypothesis 2)."""
    (tmp_path / "vars.tfvars").write_text(
        'broken = "oops no closing quote\n' + _LAMBDA_MAP)
    n, _ = _count_lambdas(tmp_path)
    assert n == 1


def test_lambda_map_in_locals_block(tmp_path):
    """The shape scan finds lambda declarations wherever the layout put them —
    a locals block, not only .tfvars (hypothesis 3)."""
    (tmp_path / "main.tf").write_text("locals {\n" + _LAMBDA_MAP + "\n}\n")
    n, _ = _count_lambdas(tmp_path)
    assert n == 1


def test_lambda_map_in_variable_default(tmp_path):
    (tmp_path / "main.tf").write_text(
        'variable "lambda-list" {\n  type = any\n  default = {\n'
        '    app-worker = {\n      function_name = "app-worker-tf"\n'
        '      handler = "worker.main"\n    }\n  }\n}\n')
    n, _ = _count_lambdas(tmp_path)
    assert n == 1


def test_lambda_map_inline_in_module_call(tmp_path):
    (tmp_path / "main.tf").write_text(
        'module "lambdas" {\n  source = "registry.example.com/org/lambda/aws"\n'
        + _LAMBDA_MAP + "\n}\n")
    n, _ = _count_lambdas(tmp_path)
    assert n == 1


def test_same_map_in_two_homes_emits_once(tmp_path):
    (tmp_path / "vars.tfvars").write_text(_LAMBDA_MAP)
    (tmp_path / "main.tf").write_text("locals {\n" + _LAMBDA_MAP + "\n}\n")
    n, _ = _count_lambdas(tmp_path)
    assert n == 1                                     # deduped by canonical id


def test_notes_report_what_was_read(tmp_path):
    """Observability: the pass reports its own coverage — a silent miss can
    never happen again."""
    (tmp_path / "vars.tfvars").write_text(_LAMBDA_MAP)
    _n, notes = _count_lambdas(tmp_path)
    assert any("1 file(s) read" in x and "1 lambda declaration(s)" in x
               for x in notes)
