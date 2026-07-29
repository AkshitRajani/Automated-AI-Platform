#!/usr/bin/env python3
"""
CHECK 3 — what does the GRAPH look like for this app?

    python check_graph.py --app <app_id>

Prints (read-only):  nodes by type · every relationship kind and its count (the
"graph linkage") · dead ends that should not be dead (state machines and invoked
lambdas that lead nowhere) · unresolved facts.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict

from _common import (connect, q, record, write_report, exit_code,
                     FORWARD, REVERSED_, EXCLUDED)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    args = ap.parse_args()
    conn = connect()
    app = args.app

    rows = q(conn, "SELECT subject_id, predicate, object_id, COALESCE(resolved, true) "
                   "FROM quad_archive WHERE app_id=%s", (app,))
    conn.close()
    if not rows:
        record("graph", "FAIL", f"no facts for '{app}' — run check_kb.py first")
        write_report("check_graph")
        return 1

    nodes = Counter()
    seen = set()
    for s, p, o, _r in rows:
        for n in (s, o):
            if n not in seen:
                seen.add(n)
                nodes[str(n).split(":", 1)[0]] += 1
    record("nodes", "PASS", f"{len(seen)} total — "
           + ", ".join(f"{t}:{c}" for t, c in sorted(nodes.items())), dict(nodes))

    preds = Counter(p for _s, p, _o, _r in rows)
    record("linkage (edges by kind)", "PASS",
           f"{len(rows)} facts across {len(preds)} kinds — "
           + ", ".join(f"{p}:{c}" for p, c in preds.most_common()), dict(preds))

    adj = defaultdict(set)
    for s, p, o, _r in rows:
        if p in EXCLUDED:
            continue
        if p in FORWARD:
            adj[s].add(o)
        elif p in REVERSED_:
            adj[o].add(s)

    sm = {n for s, p, o, _ in rows for n in (s, o) if str(n).startswith("StateMachine:")}
    sm_dead = sorted(n for n in sm if not adj.get(n))
    record("state machines lead somewhere", "PASS" if not sm_dead else "WARN",
           f"{len(sm) - len(sm_dead)}/{len(sm)} state machines have outgoing chains "
           + (f"— dead ends: {', '.join(sm_dead[:3])} (their definition file was not "
              f"found next to the code, or the manifest doesn't name it)" if sm_dead else ""))

    lam = {o for _s, p, o, _r in rows if p == "INVOKES_LAMBDA"}
    lam_dead = sorted(n for n in lam if not adj.get(n))
    record("invoked lambdas lead to code", "PASS" if not lam_dead else "WARN",
           f"{len(lam) - len(lam_dead)}/{len(lam)} invoked lambdas connect to their handler "
           + (f"— dead ends: {', '.join(lam_dead[:3])} (the deployment manifest is missing "
              f"or doesn't map these names to handlers)" if lam_dead else ""))

    unresolved = sum(1 for *_x, r in rows if not r)
    record("unresolved facts", "PASS" if unresolved == 0 else "INFO",
           f"{unresolved}/{len(rows)} facts unresolved")

    write_report("check_graph")
    return exit_code()


if __name__ == "__main__":
    sys.exit(main())
