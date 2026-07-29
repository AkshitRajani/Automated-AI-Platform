"""Unit tests for the Neptune graph backend — no live Neptune."""
from __future__ import annotations

from coding_agent.kb.graph import GraphClient, build_gremlin


class FakeExecutor:
    """Maps a node -> its outgoing edges, ignoring the gremlin string."""
    def __init__(self, edges_by_node: dict):
        self.edges_by_node = edges_by_node
        self.calls = []

    def one_hop(self, node, relations, direction, app_id, limit):
        self.calls.append((node, tuple(relations), direction, app_id, limit))
        return self.edges_by_node.get(node, [])


def test_degrades_when_neptune_absent():
    client = GraphClient(executor=None, available=False)
    res = client.walk("late_fee_handler", app_id="DEMO")
    assert res.edges == []
    assert "not configured" in res.note


def test_missing_app_id_refuses():
    client = GraphClient(executor=FakeExecutor({}), available=True)
    res = client.walk("x", app_id="")
    assert "app_id is required" in res.note


def test_single_hop_edges():
    ex = FakeExecutor({
        "late_fee_handler": [
            {"src": "late_fee_handler", "relation": "QUERIES_DATABASE",
             "dst": "APP_PMT", "dst_kind": "Table"},
        ],
    })
    res = GraphClient(ex, True).walk("late_fee_handler", app_id="DEMO")
    assert len(res.edges) == 1
    assert res.edges[0].relation == "QUERIES_DATABASE"
    assert res.edges[0].dst == "APP_PMT"


def test_two_hops_expand_frontier():
    ex = FakeExecutor({
        "A": [{"src": "A", "relation": "CALLS_HTTP_API", "dst": "B", "dst_kind": "Endpoint"}],
        "B": [{"src": "B", "relation": "QUERIES_DATABASE", "dst": "C", "dst_kind": "Table"}],
    })
    res = GraphClient(ex, True).walk("A", hops=2, app_id="DEMO")
    dsts = {e.dst for e in res.edges}
    assert dsts == {"B", "C"}


def test_limit_bounds_results():
    ex = FakeExecutor({
        "A": [{"src": "A", "relation": "R", "dst": f"n{i}", "dst_kind": "X"} for i in range(50)],
    })
    res = GraphClient(ex, True).walk("A", hops=1, app_id="DEMO", limit=5)
    assert len(res.edges) == 5


def test_cycle_does_not_loop_forever():
    ex = FakeExecutor({
        "A": [{"src": "A", "relation": "R", "dst": "B", "dst_kind": "X"}],
        "B": [{"src": "B", "relation": "R", "dst": "A", "dst_kind": "X"}],
    })
    res = GraphClient(ex, True).walk("A", hops=5, app_id="DEMO")
    # A->B and B->A, then A already visited — terminates.
    assert {(e.src, e.dst) for e in res.edges} == {("A", "B"), ("B", "A")}


def test_empty_result_has_actionable_note():
    res = GraphClient(FakeExecutor({}), True).walk("ghost", app_id="DEMO")
    assert res.edges == []
    assert "no edges" in res.note


def test_gremlin_builder_shape():
    q = build_gremlin("late_fee_handler", ["QUERIES_DATABASE"], "out", "DEMO", 25)
    assert "has('app_id','DEMO')" in q
    assert "has('name','late_fee_handler')" in q
    assert "outE('QUERIES_DATABASE')" in q
    assert ".limit(25)" in q


def test_gremlin_direction_in():
    q = build_gremlin("APP_PMT", [], "in", "DEMO", 10)
    assert "inE()" in q and "outV()" in q
