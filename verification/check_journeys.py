#!/usr/bin/env python3
"""
CHECK 4 — can the graph WALK journeys, and how far?

    python check_journeys.py --app <app_id>

Prints (read-only):  how many journeys and behavior families the analyzer walked ·
the LONGEST chain in the graph, printed node by node · how far a walk reaches on
average · storage handoffs that connect a writer to a reader · every journey's
spec status (documented or not).
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict, deque

from _common import (connect, q, record, write_report, exit_code,
                     FORWARD, REVERSED_, EXCLUDED)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    args = ap.parse_args()
    conn = connect()
    app = args.app

    rows = q(conn, "SELECT subject_id, predicate, object_id FROM quad_archive "
                   "WHERE app_id=%s", (app,))
    journeys = [r[0] for r in q(conn, "SELECT DISTINCT symbol FROM app_functions "
                                      "WHERE app_id=%s AND entity_type='Journey'", (app,))]
    groups = [r[0] for r in q(conn, "SELECT DISTINCT symbol FROM app_functions "
                                    "WHERE app_id=%s AND entity_type='BehaviorGroup'", (app,))]
    specs = {r[0] for r in q(conn, "SELECT unit FROM app_requirements WHERE app_id=%s", (app,))}
    conn.close()

    record("journey count", "PASS" if journeys else "WARN",
           f"{len(journeys)} journeys, {len(groups)} behavior families walked by the analyzer",
           {"journeys": journeys, "groups": groups})

    covered = [j for j in journeys + groups if j in specs]
    missing = [j for j in journeys + groups if j not in specs]
    record("journeys have specs", "PASS" if not missing else "WARN",
           f"{len(covered)}/{len(journeys) + len(groups)} journeys/families have a spec doc "
           + (f"— missing: {', '.join(missing[:4])}" if missing else ""))

    # flow graph + longest chain (breadth-first from every real start)
    adj = defaultdict(set)
    indeg = defaultdict(int)
    acting, buttons = set(), set()
    for s, p, o in rows:
        if p in FORWARD:
            acting.add(s)
        if p in ("EXPOSES_ENDPOINT", "RECEIVES_EVENT"):
            buttons.add(o)
        if p in EXCLUDED:
            continue
        if p in FORWARD:
            a, b = s, o
        elif p in REVERSED_:
            a, b = o, s
        else:
            continue
        if b not in adj[a]:
            adj[a].add(b)
            if p not in {"READS_FROM_S3", "QUERIES_DATABASE", "READS_DYNAMODB_TABLE",
                         "READS_FILE", "READS_CONFIG_FROM_S3"}:
                indeg[b] += 1
        indeg.setdefault(a, indeg.get(a, 0))

    starts = [n for n in adj if adj[n] and indeg.get(n, 0) == 0
              and (n in acting or n in buttons)]
    best = (0, None, None)
    reaches = []
    for src in sorted(starts):
        depth, par = {src: 0}, {src: None}
        dq = deque([src])
        while dq:
            n = dq.popleft()
            for m in sorted(adj.get(n, ())):
                if m not in depth:
                    depth[m] = depth[n] + 1
                    par[m] = n
                    dq.append(m)
        reaches.append(len(depth) - 1)
        far = max(depth.items(), key=lambda kv: kv[1])
        if far[1] > best[0]:
            best = (far[1], src, far[0])
            best_par = par

    if best[0]:
        chain = [best[2]]
        while best_par[chain[-1]] is not None:
            chain.append(best_par[chain[-1]])
        chain.reverse()
        record("longest chain", "PASS", f"{best[0]} hops:", {"path": chain})
        for i, n in enumerate(chain):
            print(f"        {i:>2}  {n}")
    else:
        record("longest chain", "FAIL",
               "no chain longer than 0 hops — the graph cannot walk (missing wiring "
               "files, or the app truly has no connected flows; send this report)")

    avg = round(sum(reaches) / len(reaches), 1) if reaches else 0
    record("reach", "PASS" if avg > 1 else "WARN",
           f"{len(starts)} starting points, average {avg} nodes reachable each, "
           f"{sum(1 for r in reaches if r == 0)} reach nothing")

    writers, readers = defaultdict(set), defaultdict(set)
    for s, p, o in rows:
        if p in {"WRITES_TO_S3", "WRITES_DATABASE", "WRITES_DYNAMODB_TABLE", "WRITES_FILE"}:
            writers[o].add(s)
        if p in {"READS_FROM_S3", "QUERIES_DATABASE", "READS_DYNAMODB_TABLE",
                 "READS_FILE", "READS_CONFIG_FROM_S3"}:
            readers[o].add(s)
    handoffs = [r for r in writers if r in readers]
    stranded = sum(1 for r in set(writers) | set(readers) if "${" in str(r))
    record("storage handoffs", "PASS" if handoffs else "WARN",
           f"{len(handoffs)} places where a writer's output is read by someone else; "
           f"{stranded} stranded on ${{}} placeholders"
           + (" (resolve names to connect more chains)" if stranded else ""))

    write_report("check_journeys")
    return exit_code()


if __name__ == "__main__":
    sys.exit(main())
