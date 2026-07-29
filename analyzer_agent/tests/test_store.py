"""
The store + grounding gate routing, on a tiny real file (no Bedrock, no Strands).

Proves the load-bearing behaviour: a fact visible at its line is kept for the
graph; a hallucinated one is rejected; a behavioural note bypasses to pgvector;
and verified facts serialize to an ingestion-ready QuadFile.
"""
import os
import tempfile
import unittest

from analyzer_agent.store import EmittedFact, FactStore


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # a real source file the gate can re-open and check
        self.src = "svc.py"
        with open(os.path.join(self.tmp, self.src), "w") as f:
            f.write(
                "import os\n"
                "def handler():\n"
                "    bucket = os.environ['DATA_BUCKET']\n"
                "    return read(bucket)\n"
            )
        self.store = FactStore(self.tmp, "APP")

    def test_grounded_env_read_goes_to_graph(self):
        dest, _ = self.store.emit(EmittedFact(
            subject="Function:svc.handler", predicate="READS_ENV_VAR",
            object="DATA_BUCKET", file=self.src, line=3))
        self.assertEqual(dest, "graph")
        self.assertEqual(len(self.store.verified), 1)

    def test_hallucinated_fact_is_rejected(self):
        # nothing named GHOST_VAR is at line 3 — the gate must reject it
        dest, _ = self.store.emit(EmittedFact(
            subject="Function:svc.handler", predicate="READS_ENV_VAR",
            object="GHOST_VAR", file=self.src, line=3))
        self.assertEqual(dest, "rejected")
        self.assertEqual(len(self.store.verified), 0)
        self.assertEqual(len(self.store.rejected), 1)

    def test_note_bypasses_to_pgvector(self):
        dest, _ = self.store.emit(EmittedFact(
            subject="Function:svc.handler", predicate="FEEDS",
            object="downstream reader", file=self.src, line=4,
            kind="note", note="handler's bucket feeds the reader"))
        self.assertEqual(dest, "note")
        self.assertEqual(len(self.store.notes), 1)

    def test_uncheckable_fact_becomes_note(self):
        dest, _ = self.store.emit(EmittedFact(
            subject="Function:svc.handler", predicate="CALLS",
            object="Function:other.thing", file="", line=None))
        self.assertEqual(dest, "note")

    def test_to_quadfile_only_verified(self):
        self.store.emit(EmittedFact("Function:svc.handler", "READS_ENV_VAR",
                                    "DATA_BUCKET", self.src, 3))
        self.store.emit(EmittedFact("Function:svc.handler", "READS_ENV_VAR",
                                    "GHOST_VAR", self.src, 3))
        qf = self.store.to_quadfile()
        self.assertEqual(qf.app_id, "APP")
        self.assertEqual(len(qf.quads), 1)
        self.assertEqual(qf.quads[0].object, "DATA_BUCKET")

    def test_stats_reports_precision(self):
        self.store.emit(EmittedFact("Function:svc.handler", "READS_ENV_VAR",
                                    "DATA_BUCKET", self.src, 3))
        self.store.emit(EmittedFact("Function:svc.handler", "READS_ENV_VAR",
                                    "GHOST_VAR", self.src, 3))
        stats = self.store.stats()
        self.assertEqual(stats["graph_facts"], 1)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["precision"], 50.0)


if __name__ == "__main__":
    unittest.main()
