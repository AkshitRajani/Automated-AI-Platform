"""Journey review checkpoint — the pure core, no terminal."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from review_journeys import journeys_from, real_nodes, sheet_path, _load_yaml, _save

DOC = {
    "metadata": {"app_id": "T"},
    "entities": [
        {"id": "Journey:APIEndpoint:POST /go", "type": "Journey", "name": "Journey:APIEndpoint:POST /go"},
        {"id": "Function:app.f", "type": "Function", "name": "app.f"},
    ],
    "quads": [
        {"subject": "Journey:APIEndpoint:POST /go", "predicate": "STARTS_AT",
         "object": "APIEndpoint:POST /go"},
        {"subject": "Journey:APIEndpoint:POST /go", "predicate": "HAS_MEMBER",
         "object": "Function:app.f", "context": {"line_start": 1}},
        {"subject": "Journey:APIEndpoint:POST /go", "predicate": "HAS_MEMBER",
         "object": "Table:out", "context": {"line_start": 2}},
        {"subject": "Function:app.f", "predicate": "WRITES_DATABASE", "object": "Table:out"},
    ],
}


def test_journeys_read_from_analyzer_facts():
    js = journeys_from(DOC)
    j = js["Journey:APIEndpoint:POST /go"]
    assert j["entry"] == "APIEndpoint:POST /go"
    assert [n for _h, n in j["members"]] == ["Function:app.f", "Table:out"]


def test_grounding_set_covers_entities_and_quad_nodes():
    nodes = real_nodes(DOC)
    assert "APIEndpoint:POST /go" in nodes and "Table:out" in nodes
    assert "InventedThing:x" not in nodes


def test_verdicts_persist_and_pending_shrinks(tmp_path):
    path = sheet_path(str(tmp_path), "t")
    _save(path, {"Journey:APIEndpoint:POST /go": {"status": "confirmed", "name": "go journey"}})
    verdicts = _load_yaml(path)
    assert verdicts["Journey:APIEndpoint:POST /go"]["status"] == "confirmed"
    pending = {j for j in journeys_from(DOC)
               if verdicts.get(j, {}).get("status") in (None, "", "deferred")}
    assert pending == set()                       # verdict recorded -> nothing pending
