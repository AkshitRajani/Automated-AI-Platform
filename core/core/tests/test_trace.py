"""The trace backbone — spans nest, events carry parent ids, sinks never break a run."""
import unittest

from core.trace import Event, TraceEmitter


class TestTrace(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.em = TraceEmitter()
        self.em.add_listener(self.events.append)

    def test_span_emits_start_and_end(self):
        with self.em.span("stage", a=1) as sp:
            sp.set(b=2)
        kinds = [e.kind for e in self.events]
        self.assertEqual(kinds, ["span.start", "span.end"])
        self.assertEqual(self.events[-1].status, "ok")
        self.assertEqual(self.events[-1].data["b"], 2)

    def test_nested_spans_carry_parent(self):
        with self.em.span("outer"):
            with self.em.span("inner"):
                pass
        starts = [e for e in self.events if e.kind == "span.start"]
        outer, inner = starts[0], starts[1]
        self.assertIsNone(outer.parent_id)
        self.assertEqual(inner.parent_id, outer.span_id)

    def test_failure_marks_span_fail_and_reraises(self):
        with self.assertRaises(ValueError):
            with self.em.span("boom"):
                raise ValueError("x")
        end = self.events[-1]
        self.assertEqual(end.kind, "span.end")
        self.assertEqual(end.status, "fail")
        self.assertIn("error", end.data)

    def test_broken_listener_does_not_break_run(self):
        def broken(_):
            raise RuntimeError("sink down")
        self.em.add_listener(broken)
        with self.em.span("ok"):       # must not raise despite the broken sink
            pass
        self.assertTrue(any(e.kind == "span.end" for e in self.events))


if __name__ == "__main__":
    unittest.main()
