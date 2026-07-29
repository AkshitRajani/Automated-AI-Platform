#!/usr/bin/env python3
"""
CHECK 2 — did INGESTION load the app completely and cleanly?

    python check_kb.py --app <app_id>

Verifies (read-only, against the live KB):  the app is registered · every table's
row counts · duplicate facts (a re-load bug signature) · leftover ${} placeholders
in the KB · spec docs present AND joinable to the inventory · orphaned spec docs.
"""
from __future__ import annotations

import argparse
import sys

from _common import connect, q, record, write_report, exit_code

TABLES = ["app_applications", "app_components", "app_functions", "app_endpoints",
          "app_tables", "app_s3_paths", "app_parameters", "app_table_relationships",
          "app_service_invocations", "quad_archive", "param_bindings",
          "app_requirements", "app_embeddings", "app_feedback"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    args = ap.parse_args()
    conn = connect()
    app = args.app

    registered = q(conn, "SELECT 1 FROM app_applications WHERE app_id=%s", (app,))
    record("app registered", "PASS" if registered else "FAIL",
           f"'{app}' " + ("found" if registered else
                          "NOT FOUND — ingestion never completed for this app id "
                          "(check the app id spelling and the ingestion logs)"))

    counts = {}
    for t in TABLES:
        try:
            has_app = q(conn, "SELECT 1 FROM information_schema.columns "
                              "WHERE table_name=%s AND column_name='app_id'", (t,))
            n = q(conn, f"SELECT COUNT(*) FROM {t} WHERE app_id=%s", (app,))[0][0] \
                if has_app else q(conn, f"SELECT COUNT(*) FROM {t}")[0][0]
            counts[t] = n
        except Exception:
            counts[t] = "missing table"
    summary = ", ".join(f"{t.replace('app_', '')}:{n}" for t, n in counts.items())
    record("row counts", "PASS" if counts.get("quad_archive") else "FAIL", summary, counts)

    dup = q(conn, "SELECT COUNT(*) - COUNT(DISTINCT (subject_id, predicate, object_id)) "
                  "FROM quad_archive WHERE app_id=%s", (app,))[0][0]
    record("duplicate facts", "PASS" if dup == 0 else "WARN",
           f"{dup} duplicated fact rows "
           + ("" if dup == 0 else "— the app was loaded more than once (known re-load "
                                  "behavior); mention this when reporting"))

    leftover = q(conn, "SELECT COUNT(*) FROM quad_archive "
                       "WHERE app_id=%s AND object_id LIKE %s", (app, "%${%"))[0][0]
    record("placeholders in KB", "PASS" if leftover == 0 else "WARN",
           f"{leftover} facts still carry ${{}} placeholders "
           + ("" if leftover == 0 else "— names were not resolved before loading "
                                       "(answer them: re-run the analyzer command, then re-load)"))

    specs = q(conn, "SELECT COUNT(*) FROM app_requirements WHERE app_id=%s", (app,))[0][0]
    record("spec docs loaded", "PASS" if specs else "FAIL",
           f"{specs} spec documents in app_requirements "
           + ("" if specs else "— the spec step was skipped or failed "
                               "(python -m ingestion --requirements <dir> --app-id <id>)"))

    if specs:
        joined = q(conn, "SELECT COUNT(*) FROM app_requirements r JOIN app_functions f "
                         "ON f.app_id=r.app_id AND f.symbol=r.unit WHERE r.app_id=%s",
                   (app,))[0][0]
        record("spec ↔ inventory join", "PASS" if joined == specs else "WARN",
               f"{joined}/{specs} spec docs join to the inventory by name "
               + ("" if joined == specs else "— a mismatch means the test generator "
                                             "cannot find some specs (send this report)"))

    orphans = q(conn, "SELECT COUNT(*) FROM app_requirements r WHERE NOT EXISTS "
                      "(SELECT 1 FROM app_applications a WHERE a.app_id=r.app_id)")[0][0]
    record("orphan spec docs (any app)", "PASS" if orphans == 0 else "WARN",
           f"{orphans} spec rows belong to apps that were never loaded "
           + ("" if orphans == 0 else "— specs were loaded before facts somewhere"))

    conn.close()
    write_report("check_kb")
    return exit_code()


if __name__ == "__main__":
    sys.exit(main())
