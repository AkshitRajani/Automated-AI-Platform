"""Workflow (etl_workflow YAML) extraction — exact assertions on a controlled fixture."""
import os

from analyzer import analyze, to_yaml
from analyzer import workflow as wf

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "wf_app")


def _objs(qf, predicate):
    return {q.object for q in qf.quads if q.predicate == predicate}


def test_detects_workflow_by_shape_not_filename():
    import yaml
    doc = yaml.safe_load(open(os.path.join(_FIX, "pipeline.yaml")))
    assert wf.is_workflow(doc) is True
    assert wf.is_workflow({"document": {"content": "code"}}) is False   # wrapped-code look-alike
    assert wf.is_workflow({"services": {}}) is False                    # docker-compose


def test_workflow_entities():
    qf = analyze(_FIX, "APP")
    types = {}
    for e in qf.entities:
        types[e.type] = types.get(e.type, 0) + 1
    assert types["WorkflowFile"] == 1
    assert types["Step"] == 4


def test_reads_writes_calls():
    qf = analyze(_FIX, "APP")
    assert "Table:LOAN_SPST" in _objs(qf, "QUERIES_DATABASE")        # dataBackbone read → typed URN
    assert "Table:RESULT_SPST" in _objs(qf, "WRITES_DATABASE")        # LOAD target → typed URN
    assert any(o.startswith("S3Object:s3://") for o in _objs(qf, "WRITES_TO_S3"))
    assert "Symbol:compute_risk" in _objs(qf, "CALLS")               # EXECUTE customFunction


def test_feeds_lineage_links_real_producers():
    qf = analyze(_FIX, "APP")
    feeds = [(q.subject, q.object) for q in qf.quads if q.predicate == "FEEDS"]
    # enrich_loans reads dataframe `loans` produced by read_loans → that lineage edge exists
    assert any(s.endswith("::read_loans") and o.endswith("::enrich_loans") for s, o in feeds)


def test_templated_value_is_symbolic():
    qf = analyze(_FIX, "APP")
    # the glue table in the SQL is ${...} → recorded but resolved=False
    syms = [q for q in qf.quads if q.predicate == "QUERIES_DATABASE" and "${" in q.object]
    assert all(q.resolved is False for q in syms)


def test_workflow_output_feeds_ingestion(tmp_path):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from ingestion.parsers.quad_parser import parse_quad_file
    out = tmp_path / "q.yaml"
    out.write_text(to_yaml(analyze(_FIX, "APP")))
    assert parse_quad_file(str(out)).quarantine_count == 0
