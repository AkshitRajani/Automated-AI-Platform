"""The journey pass: roots, subsumption, classification, grouping — pure, no fixtures."""
from analyzer.journeys import extract_journeys
from analyzer.models import Entity, Quad, QuadFile, Source


def _q(s, p, o):
    return Quad(s, p, o, True, 1.0, "f.py", 1)


def _e(eid, etype):
    return Entity(id=eid, type=etype, name=eid.split(":", 1)[1],
                  source=Source("f.py", 1, None))


def _qf(entities, quads):
    return QuadFile(app_id="T", entities=entities, quads=quads)


def test_journey_found_name_equals_id_and_members_ordered():
    """endpoint -> fn -> state machine chain is a journey; the entity's name IS its
    id (the join key for KB inventory / spec lookup — issue C1), and HAS_MEMBER
    carries hop order."""
    ents = [_e("Function:app.run", "Function")]
    quads = [
        _q("Function:app.run", "EXPOSES_ENDPOINT", "APIEndpoint:POST /run"),
        _q("Function:app.run", "INVOKES_STEP_FUNCTION", "StateMachine:m"),
        _q("StateMachine:m", "FEEDS", "State:m::A"),
        _q("State:m::A", "INVOKES_LAMBDA", "LambdaFunction:l"),
    ]
    j_ents, j_quads, _unwired = extract_journeys(_qf(ents, quads))
    journeys = [e for e in j_ents if e.type == "Journey"]
    assert [e.id for e in journeys] == ["Journey:APIEndpoint:POST /run"]
    assert journeys[0].name == journeys[0].id
    members = {q.object: q.line for q in j_quads
               if q.subject == journeys[0].id and q.predicate == "HAS_MEMBER"}
    assert members["Function:app.run"] == 1
    assert members["StateMachine:m"] == 2
    assert members["LambdaFunction:l"] == 4


def test_small_read_is_grouped_not_a_journey():
    """A 2-hop endpoint read is a behavior, bundled into its owner's family."""
    ents = [_e("Function:api.get_thing", "Function")]
    quads = [
        _q("Function:api.get_thing", "EXPOSES_ENDPOINT", "APIEndpoint:GET /thing"),
        _q("Function:api.get_thing", "QUERIES_DATABASE", "Table:things"),
    ]
    j_ents, j_quads, _unwired = extract_journeys(_qf(ents, quads))
    assert not [e for e in j_ents if e.type == "Journey"]
    groups = [e for e in j_ents if e.type == "BehaviorGroup"]
    assert [g.id for g in groups] == ["BehaviorGroup:api"]
    assert groups[0].name == groups[0].id


def test_passive_store_never_roots_a_journey():
    """A table only ever read must not spawn its own journey — its walk is a
    sub-walk of the intake that reaches it (subsumption + acting/button rule)."""
    ents = [_e("Function:app.enter", "Function"), _e("Function:app.deep", "Function"),
            _e("Function:app.deeper", "Function"), _e("Function:app.deepest", "Function")]
    quads = [
        _q("Function:app.enter", "EXPOSES_ENDPOINT", "APIEndpoint:POST /go"),
        _q("Function:app.enter", "QUERIES_DATABASE", "Table:ref_data"),
        _q("Function:app.enter", "CALLS", "Function:app.deep"),
        _q("Function:app.deep", "CALLS", "Function:app.deeper"),
        _q("Function:app.deeper", "CALLS", "Function:app.deepest"),
        _q("Function:app.deepest", "WRITES_DATABASE", "Table:out"),
    ]
    j_ents, _, _unwired = extract_journeys(_qf(ents, quads))
    journeys = [e.id for e in j_ents if e.type == "Journey"]
    assert journeys == ["Journey:APIEndpoint:POST /go"]      # depth>=4 => journey
    assert not any("ref_data" in j for j in journeys)


def test_frontdoor_rule_orphan_fragment_is_a_gap_not_a_journey():
    """A journey-shaped walk rooted at a plain function (no button, no declared
    orchestrator) is a fragment whose incoming arrow we failed to read — it must
    land on the unwired list, never be promoted to a Journey. This is the exact
    mechanism that turned a handful of real journeys into hundreds."""
    ents = [_e(f"Function:app.f{i}", "Function") for i in range(5)]
    quads = [_q(f"Function:app.f{i}", "CALLS", f"Function:app.f{i+1}")
             for i in range(4)]                       # depth 4 => journey-shaped
    j_ents, _, unwired = extract_journeys(_qf(ents, quads))
    assert not [e for e in j_ents if e.type == "Journey"]
    assert unwired == ["Function:app.f0"]


def test_frontdoor_rule_small_orphan_still_groups():
    """Small standalone behaviors keep working exactly as before — the front-door
    rule only blocks JOURNEY promotion, it does not delete behavior docs."""
    ents = [_e("Function:util.tidy", "Function")]
    quads = [_q("Function:util.tidy", "WRITES_TO_S3", "S3Object:b/tidy.csv")]
    j_ents, _, unwired = extract_journeys(_qf(ents, quads))
    assert [e.id for e in j_ents if e.type == "BehaviorGroup"] == ["BehaviorGroup:util"]
    assert unwired == []


def test_determinism():
    ents = [_e("Function:a.f", "Function")]
    quads = [_q("Function:a.f", "EXPOSES_ENDPOINT", "APIEndpoint:GET /x"),
             _q("Function:a.f", "WRITES_TO_S3", "S3Object:b/k")]
    one = extract_journeys(_qf(ents, quads))
    two = extract_journeys(_qf(ents, quads))
    assert [(e.id, e.name) for e in one[0]] == [(e.id, e.name) for e in two[0]]
    assert [(q.subject, q.predicate, q.object, q.line) for q in one[1]] == \
           [(q.subject, q.predicate, q.object, q.line) for q in two[1]]
