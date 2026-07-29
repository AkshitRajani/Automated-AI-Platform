"""P0 worksheet-handling fixes (study S14) + P1 provenance stamping (study S1-S5).

The contract under test:
  - a malformed sheet is a clean, named halt — never a traceback;
  - the worksheet is merged on every write — operator answers are NEVER destroyed;
  - stale tokens and value-vs-decision conflicts are warned about, loudly;
  - a human-supplied name is stamped extraction_method="human" forever;
  - answers, decisions (kind+reason) and warnings travel INSIDE the quad;
  - a still-blank ${token} is resolved:false everywhere it appears — wiring
    edges and journey membership included.
"""
import pytest
import yaml

from analyzer.emit import to_dict
from analyzer.extract import analyze
from analyzer.journeys import extract_journeys
from analyzer.models import Entity, Quad, QuadFile, Source
from analyzer.wiring import extract_state_machine


def _app(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "h.py").write_text(
        "import os, boto3\n"
        "s3 = boto3.client('s3')\n"
        "def handler(event, context):\n"
        "    bucket = os.environ['MYSTERY_BUCKET']\n"
        "    s3.put_object(Bucket=bucket, Key='a/b.csv')\n")
    (app / "serverless.yml").write_text(
        "functions:\n  f:\n    handler: h.handler\n"
        "    events:\n      - httpApi:\n          method: post\n          path: /go\n")
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    return app, sheets


# --- P0.2: malformed sheet = clean halt --------------------------------------------
def test_malformed_worksheet_is_a_named_error_not_a_crash(tmp_path):
    app, sheets = _app(tmp_path)
    (sheets / "t_worksheet.yaml").write_text('MYSTERY_BUCKET: "unclosed\n')
    with pytest.raises(ValueError, match="not valid YAML"):
        analyze(str(app), "T", names_dir=str(sheets))


def test_malformed_decisions_is_a_named_error_not_a_crash(tmp_path):
    app, sheets = _app(tmp_path)
    (sheets / "t_decisions.yaml").write_text('MYSTERY_BUCKET: {broken: "x\n')
    with pytest.raises(ValueError, match="not valid YAML"):
        analyze(str(app), "T", names_dir=str(sheets))


# --- P0.1: worksheet merge never deletes answers ------------------------------------
def test_worksheet_merge_preserves_existing_answers(tmp_path):
    from analyzer.__main__ import _load_sheet, _write_template
    ws = tmp_path / "t_worksheet.yaml"
    ws.write_text("A_TOKEN: kept-value\nHALF_DONE: \n")
    _write_template({"B_TOKEN": [("Subj", "PRED", "S3Object:${B_TOKEN}/x")],
                     "HALF_DONE": [("S", "P", "O")]}, str(ws))
    data = _load_sheet(str(ws))
    assert data["A_TOKEN"] == "kept-value"        # the answer SURVIVED the rewrite
    assert "B_TOKEN" in data and data["B_TOKEN"] is None   # new blank appended
    assert "HALF_DONE" in data                    # still listed, still blank
    text = ws.read_text()
    assert "used by Subj --PRED-->" in text       # usage comments for new blanks


# --- P0.3 + P0.4: stale + conflict warnings ----------------------------------------
def test_stale_answer_and_value_vs_decision_conflict_are_warned(tmp_path):
    app, sheets = _app(tmp_path)
    (sheets / "t_worksheet.yaml").write_text(
        "MYSTERY_BUCKET: real-bucket\nGHOST_TOKEN: whatever\n")
    (sheets / "t_decisions.yaml").write_text(
        "MYSTERY_BUCKET:\n  decision: skipped\n  reason: owner unavailable\n")
    qf = analyze(str(app), "T", names_dir=str(sheets))
    assert any("GHOST_TOKEN" in w and "stale or misspelled" in w
               for w in qf.sheet_warnings)
    assert any("MYSTERY_BUCKET" in w and "the value wins" in w
               for w in qf.sheet_warnings)
    # and the value DID win — loudly, not silently
    writes = [q for q in qf.quads if q.predicate == "WRITES_TO_S3"]
    assert writes[0].object == "S3Object:real-bucket/a/b.csv"


# --- P1: provenance stamping --------------------------------------------------------
def test_human_answer_is_stamped_human(tmp_path):
    app, sheets = _app(tmp_path)
    (sheets / "t_worksheet.yaml").write_text("MYSTERY_BUCKET: real-bucket\n")
    qf = analyze(str(app), "T", names_dir=str(sheets))
    w = [q for q in qf.quads if q.predicate == "WRITES_TO_S3"][0]
    assert w.extraction_method == "human"         # a person said this — forever visible
    assert w.resolved and w.confidence == 1.0
    assert qf.human_answers == {"MYSTERY_BUCKET": "real-bucket"}


def test_repo_answer_stays_machine_provenance(tmp_path):
    app, sheets = _app(tmp_path)
    (app / "serverless.yml").write_text(         # repo itself declares the value
        "functions:\n  f:\n    handler: h.handler\n"
        "    environment:\n      MYSTERY_BUCKET: repo-bucket\n")
    qf = analyze(str(app), "T", names_dir=str(sheets))
    w = [q for q in qf.quads if q.predicate == "WRITES_TO_S3"][0]
    assert w.object == "S3Object:repo-bucket/a/b.csv"
    assert w.extraction_method == "ast"           # repo-derived stays machine-stamped


def test_decisions_travel_inside_the_quad(tmp_path):
    app, sheets = _app(tmp_path)
    (sheets / "t_decisions.yaml").write_text(
        "MYSTERY_BUCKET:\n  decision: runtime-data\n  reason: bucket chosen per run\n")
    qf = analyze(str(app), "T", names_dir=str(sheets))
    assert qf.pending_names == []                 # decided → unblocked
    assert qf.decisions == {"MYSTERY_BUCKET": {"decision": "runtime-data",
                                               "reason": "bucket chosen per run"}}
    md = to_dict(qf)["metadata"]
    assert md["decisions"]["MYSTERY_BUCKET"]["decision"] == "runtime-data"
    # the fact honestly keeps the blank, low confidence
    w = [q for q in qf.quads if q.predicate == "WRITES_TO_S3"][0]
    assert "${MYSTERY_BUCKET}" in w.object and not w.resolved


# --- P1: the blank is resolved:false EVERYWHERE it appears --------------------------
def test_token_bearing_invoke_edge_is_unresolved(tmp_path):
    doc = {"StartAt": "A",
           "States": {"A": {"Type": "Task",
                            "Resource": "arn:aws:states:::lambda:invoke",
                            "Parameters": {"FunctionName": "${x_arn}"},
                            "End": True}}}
    _ents, quads = extract_state_machine(doc, "m.asl.json", "named-machine")
    inv = [q for q in quads if q.predicate == "INVOKES_LAMBDA"][0]
    assert not inv.resolved and inv.confidence == 0.5


def test_journey_membership_of_symbolic_node_carries_the_doubt():
    ents = [Entity(id="StateMachine:m", type="StateMachine", name="m",
                   source=Source("f", 1, None))]
    quads = [Quad("StateMachine:m", "FEEDS", "State:m::A", True, 1.0, "f", 1),
             Quad("State:m::A", "INVOKES_LAMBDA", "LambdaFunction:${x}",
                  False, 0.5, "f", 2)]
    _e, j_quads, _u = extract_journeys(QuadFile(app_id="T", entities=ents, quads=quads))
    sym = [q for q in j_quads if q.predicate == "HAS_MEMBER"
           and "${" in q.object]
    assert sym and all(not q.resolved and q.confidence == 0.5 for q in sym)
    solid = [q for q in j_quads if q.predicate == "HAS_MEMBER"
             and "${" not in q.object]
    assert solid and all(q.resolved and q.confidence == 1.0 for q in solid)
