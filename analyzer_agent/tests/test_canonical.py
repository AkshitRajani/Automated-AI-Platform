"""
The canonical-id contract — the precondition that makes the agent's edges connect.

Locks ``canonical`` to the *exact* id scheme ingestion writes, so the two cannot
silently drift (the 0%-connect bug from the build session). If someone changes
``neptune_writer``'s f-string, this test should be what fails.
"""
import unittest

from analyzer_agent import canonical


class TestCanonical(unittest.TestCase):
    def test_node_and_edge_endpoint_agree(self):
        # An edge endpoint built from a canonical subject must equal the node id
        # ingestion writes for that same unit — otherwise the edge orphans.
        app, type_, qual = "SBX", "Function", "web.app.topology.build_topology"
        node = canonical.node_id(app, type_, qual)                       # ingestion node
        endpoint = canonical.edge_endpoint(app, canonical.canonical_id(type_, qual))
        self.assertEqual(node, endpoint)
        self.assertEqual(node, "SBX:Function:web.app.topology.build_topology")

    def test_matches_ingestion_fstrings(self):
        # Mirror ingestion/graph/neptune_writer exactly:
        #   node:  f"{app_id}:{entity.type}:{entity.name}"
        #   edge:  f"{app_id}:{quad.subject}"
        app, type_, name = "DEMO", "Method", "Service.run"
        self.assertEqual(canonical.node_id(app, type_, name), f"{app}:{type_}:{name}")
        subject = canonical.canonical_id(type_, name)
        self.assertEqual(canonical.edge_endpoint(app, subject), f"{app}:{subject}")

    def test_unknown_type_degrades_to_symbol(self):
        self.assertEqual(canonical.canonical_id("Gizmo", "x.y"), "Symbol:x.y")

    def test_split_roundtrip(self):
        cid = canonical.canonical_id("Table", "orders")
        self.assertEqual(canonical.split(cid), ("Table", "orders"))
        self.assertEqual(canonical.split("orders"), ("Symbol", "orders"))

    def test_is_canonical(self):
        self.assertTrue(canonical.is_canonical("Function:a.b"))
        self.assertFalse(canonical.is_canonical("a.b"))
        self.assertFalse(canonical.is_canonical("s3://bucket/key"))


if __name__ == "__main__":
    unittest.main()
