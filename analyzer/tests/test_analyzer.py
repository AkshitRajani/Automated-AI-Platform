"""Analyzer tests — exact assertions on a controlled fixture + the ingestion contract."""
import os
import sys

from analyzer import analyze, to_yaml
from analyzer.emit import to_dict

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample_app")


def _quads(qf):
    return [(q.subject, q.predicate, q.object, q.resolved) for q in qf.quads]


def _objs(qf, predicate):
    return {q.object for q in qf.quads if q.predicate == predicate}


# --- entities ---------------------------------------------------------------
def test_entities_cover_every_function_and_module():
    qf = analyze(_FIX, "APP")
    types = {}
    for e in qf.entities:
        types[e.type] = types.get(e.type, 0) + 1
    assert types["Module"] == 2                      # service.py, helpers.py
    assert types["Function"] == 6                    # 4 in service + 2 in helpers
    # every SOURCE entity carries a file:line (derived journey entities have no file)
    assert all(e.source and e.source.file_path
               for e in qf.entities if e.language != "journey")


# --- the typed facts (canonical Type:name URNs) ---------------------
def test_endpoints():
    qf = analyze(_FIX, "APP")
    assert _objs(qf, "EXPOSES_ENDPOINT") == {"APIEndpoint:GET /items", "APIEndpoint:POST /items"}


def test_s3_literal_is_resolved_variable_is_symbolic():
    qf = analyze(_FIX, "APP")
    s3 = {(q.object, q.resolved) for q in qf.quads if q.predicate == "READS_FROM_S3"}
    assert ("S3Object:my-bucket/items.json", True) in s3   # literal → resolved
    assert ("S3Object:bucket/key", False) in s3            # variables → symbolic, honest


def test_lambda_invoke():
    qf = analyze(_FIX, "APP")
    assert _objs(qf, "INVOKES_LAMBDA") == {"LambdaFunction:worker-fn"}


def test_module_level_env_read():
    qf = analyze(_FIX, "APP")
    assert "Parameter:API_KEY" in _objs(qf, "READS_ENV_VAR")   # read at import time


def test_internal_calls_resolve_to_canonical_ids():
    qf = analyze(_FIX, "APP")
    calls = [(q.subject, q.object) for q in qf.quads if q.predicate == "CALLS"]
    # canonical: Function:service.list_items CALLS Function:service.get_client — the
    # callee object IS the definition's node id (so the edge connects in Neptune).
    assert any(s.endswith(".list_items") and o.endswith(".get_client") for s, o in calls)
    assert any(s.endswith(".create_item") and o.endswith(".log_event") for s, o in calls)
    # and a resolved call's object must be a real entity id (Type:qualname), not a bare name
    ids = {e.id for e in qf.entities}
    resolved = [o for s, o in calls if o in ids]
    assert resolved, "at least one CALLS edge resolves to a real entity node"


# --- determinism ------------------------------------------------------------
def test_deterministic():
    assert to_yaml(analyze(_FIX, "APP")) == to_yaml(analyze(_FIX, "APP"))


# --- the headline contract: output must feed ingestion with zero quarantine -
def test_ingestion_contract_zero_quarantine(tmp_path):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from ingestion.parsers.quad_parser import parse_quad_file
    out = tmp_path / "quad.yaml"
    out.write_text(to_yaml(analyze(_FIX, "APP")))
    result = parse_quad_file(str(out))
    assert result.quarantine_count == 0
    assert result.entity_count == len(analyze(_FIX, "APP").entities)
    assert result.quad_count == len(analyze(_FIX, "APP").quads)
