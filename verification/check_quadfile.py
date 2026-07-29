#!/usr/bin/env python3
"""
CHECK 1 — did the ANALYZER produce a healthy output file, and is it READY TO INGEST?

    python check_quadfile.py <quad_file.yaml> [--against <previous_quad.yaml>]

Verifies (no database needed):  the file parses · entities by type · facts by
relationship · journeys + behavior families present · repo-declared answers
(bindings) · whether the run is BLOCKED waiting for a human (which names, used
where) · every name a human supplied (and the facts it produced) · every
skip/runtime decision and its reason · worksheet warnings · journey-shaped
fragments held for wiring review.

The LAST line is the decision:  READY TO INGEST (PASS) or WAIT (FAIL) — so
`python check_quadfile.py quad.yaml && <ingest>` is scriptable: exit 0 = go.
WAIT is a state, not a judgment: it fires only when the analyzer itself said
the run is incomplete (names unanswered → zero journeys) or the file is
unhealthy (unreadable / empty).

``--against`` compares this file with a PREVIOUS run of the same app and shows
what changed (blanks, journeys, unresolved facts, human answers …) — the
numbers are shown side by side; nothing is scored.
"""
from __future__ import annotations

import re
import sys
from collections import Counter

import yaml

from _common import record, write_report, exit_code

TOKEN = re.compile(r"\$\{([^}]+)\}")


def _snapshot(doc: dict) -> dict:
    """The comparable numbers of one quad file — same fields for old and new."""
    entities = doc.get("entities") or []
    quads = doc.get("quads") or []
    md = doc.get("metadata") or {}
    by_type = Counter(str(e.get("type", "?")) for e in entities if isinstance(e, dict))
    unresolved = [q for q in quads if isinstance(q, dict)
                  and not (q.get("context") or {}).get("resolved", True)]
    tokens = {t for q in quads if isinstance(q, dict)
              for t in TOKEN.findall(str(q.get("object", "")))}
    return {
        "entities": len(entities),
        "facts": len(quads),
        "journeys": by_type.get("Journey", 0),
        "behavior groups": by_type.get("BehaviorGroup", 0),
        "blank names (${})": len(tokens),
        "unresolved facts": len(unresolved),
        "questions still open": len(md.get("pending_names") or []),
        "human-supplied answers": len(md.get("human_answers") or {}),
        "skip/runtime decisions": len(md.get("decisions") or {}),
        "needs-wiring fragments": len(md.get("unwired") or []),
        "web calls": len({str(q.get("object")) for q in quads if isinstance(q, dict)
                          and q.get("predicate") == "CALLS_HTTP_API"}),
        "secrets read": len({str(q.get("object")) for q in quads if isinstance(q, dict)
                             and q.get("predicate") == "READS_SECRET"}),
        "parameters read": len({str(q.get("object")) for q in quads if isinstance(q, dict)
                                and q.get("predicate") == "READS_SSM_PARAMETER"}),
        "database tables": len({str(q.get("object")) for q in quads if isinstance(q, dict)
                                and q.get("predicate") in ("QUERIES_DATABASE",
                                                           "WRITES_DATABASE")}),
        "lambda code links": sum(1 for q in quads if isinstance(q, dict)
                                 and q.get("predicate") == "HANDLED_BY"),
        "lambdas unlinked": len(md.get("handler_unlinked") or []),
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("quad_file")
    ap.add_argument("--against", default=None,
                    help="a PREVIOUS quad of the same app — show what changed")
    args = ap.parse_args()
    path = args.quad_file

    try:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except Exception as exc:
        record("file parses", "FAIL", f"{path} is not readable YAML: {exc}")
        record("ready to ingest", "FAIL",
               "WAIT — the file is not readable; do not ingest")
        write_report("check_quadfile")
        return 1
    record("file parses", "PASS", path)

    md_top = doc.get("metadata") or {}
    ver = md_top.get("analyzer_version")
    record("analyzer version", "INFO" if ver else "WARN",
           f"produced by analyzer {ver}" if ver else
           "not stamped — this quad was produced by an analyzer OLDER than "
           "3.4.2; the capture sections below will be empty for that reason, "
           "not because the app lacks those interactions")

    manifest = md_top.get("parse_manifest") or {}
    notes = md_top.get("analyzer_notes") or []
    if manifest:
        zips = manifest.get("zip_files_not_opened", 0)
        tf_note = next((n for n in notes if str(n).startswith("terraform:")), None)
        record("what this run read", "WARN" if zips else "PASS",
               f"python {manifest.get('python_files_parsed', 0)}"
               f"/{manifest.get('python_files_found', 0)}"
               f" · workflows {manifest.get('workflow_files_parsed', 0)}"
               f" · terraform {manifest.get('terraform_files_found', 0)}"
               f" · java {manifest.get('java_files_found', 0)}"
               f" · config-SQL {manifest.get('config_files_with_sql', 0)}"
               f" · zips NOT opened {zips}"
               + (f" · {tf_note}" if tf_note else ""),
               {"manifest": dict(manifest), "analyzer_notes": list(notes)})

    app = (doc.get("metadata") or {}).get("app_id", "?")
    entities = doc.get("entities") or []
    quads = doc.get("quads") or []
    by_type = Counter(str(e.get("type", "?")) for e in entities if isinstance(e, dict))
    by_pred = Counter(str(q.get("predicate", "?")) for q in quads if isinstance(q, dict))

    record("entities", "PASS" if entities else "FAIL",
           f"{len(entities)} total — " + ", ".join(f"{t}:{n}" for t, n in sorted(by_type.items())),
           dict(by_type))
    record("facts", "PASS" if quads else "FAIL",
           f"{len(quads)} total across {len(by_pred)} relationship kinds", dict(by_pred))

    journeys = by_type.get("Journey", 0)
    groups = by_type.get("BehaviorGroup", 0)
    record("journeys walked", "PASS" if journeys else "WARN",
           f"{journeys} journeys + {groups} behavior families "
           + ("" if journeys else "— ZERO journeys: the app may be all small behaviors, "
                                  "or the graph has no walkable chains (send this report)"))

    bindings = doc.get("bindings") or {}
    record("repo-declared answers", "INFO", f"{len(bindings)} bindings harvested from the repo")

    # --- what the map captured (the 3.4.2 capture inventory) --------------------
    def _facts(*preds):
        return [qd for qd in quads if isinstance(qd, dict)
                and qd.get("predicate") in preds]

    def _objects(*preds):
        return sorted({str(qd.get("object", "")) for qd in _facts(*preds)})

    web = _objects("CALLS_HTTP_API")
    record("web calls (outbound APIs)", "PASS" if web else "INFO",
           f"{len(web)} distinct outside address(es) the code calls"
           + (": " + ", ".join(w.replace("APIEndpoint:", "") for w in web[:5])
              if web else " — none found in the code"),
           {"addresses": web})

    secrets = _objects("READS_SECRET")
    record("secrets read (names only)", "PASS" if secrets else "INFO",
           f"{len(secrets)} secret name(s) the code fetches — the names only; "
           f"secret VALUES are never read or stored"
           + (": " + ", ".join(x.replace("Secret:", "") for x in secrets[:5])
              if secrets else ""),
           {"secrets": secrets})

    params = _objects("READS_SSM_PARAMETER")
    record("parameters read", "PASS" if params else "INFO",
           f"{len(params)} parameter-store name(s) the code fetches"
           + (": " + ", ".join(x.replace("Parameter:", "") for x in params[:5])
              if params else ""),
           {"parameters": params})

    topics = _objects("PUBLISHES_TO_SNS")
    record("notifications published", "PASS" if topics else "INFO",
           f"{len(topics)} notification topic(s) the code publishes to"
           + (": " + ", ".join(x.replace("Topic:", "") for x in topics[:5])
              if topics else ""),
           {"topics": topics})

    db_facts = _facts("QUERIES_DATABASE", "WRITES_DATABASE")
    tables_read = _objects("QUERIES_DATABASE")
    tables_written = _objects("WRITES_DATABASE")
    from_config = sorted({str(qd.get("object", "")) for qd in db_facts
                          if str(qd.get("subject", "")).startswith("ConfigFile:")})
    cfg_files = sorted({str(e.get("id", "")) for e in entities
                        if isinstance(e, dict) and e.get("type") == "ConfigFile"})
    record("database tables", "PASS" if db_facts else "INFO",
           f"{len(set(tables_read) | set(tables_written))} distinct table(s) — "
           f"{len(tables_read)} read, {len(tables_written)} written"
           + (f"; {len(from_config)} table(s) come from SQL kept in "
              f"{len(cfg_files)} config file(s), not in the code"
              if from_config else "")
           + ("" if db_facts else " — no SQL found in code or config"),
           {"read": tables_read, "written": tables_written,
            "from_config_files": from_config, "config_files": cfg_files})

    s3_facts = _facts("READS_FROM_S3", "WRITES_TO_S3")
    s3_resolved = [qd for qd in s3_facts
                   if (qd.get("context") or {}).get("resolved", False)]
    s3_unresolved = [qd for qd in s3_facts if qd not in s3_resolved]
    buckets = sorted({str(qd.get("object", ""))[len("S3Object:"):].split("/", 1)[0]
                      for qd in s3_resolved})
    record("bucket names readable", "PASS" if not s3_unresolved else "WARN",
           f"{len(s3_resolved)} of {len(s3_facts)} storage fact(s) carry a real, "
           f"readable object name ({len(buckets)} distinct bucket(s)"
           + (": " + ", ".join(buckets[:4]) if buckets else "") + ")"
           + (f"; {len(s3_unresolved)} still show a placeholder or raw code "
              f"text — their names come from unanswered settings"
              if s3_unresolved else ""),
           {"buckets": buckets,
            "unreadable": [str(qd.get("object", "")) for qd in s3_unresolved][:10]})

    handled = _facts("HANDLED_BY")
    unlinked = md_top.get("handler_unlinked") or []
    lam_count = by_type.get("LambdaFunction", 0)
    if lam_count or handled or unlinked:
        record("lambda code links", "PASS" if not unlinked else "WARN",
               f"{len(handled)} of {lam_count} lambda(s) are linked to the code "
               f"they run"
               + (f"; {len(unlinked)} could NOT be linked (ambiguous or absent "
                  f"code) — listed with their candidates, never guessed"
                  if unlinked else " — every declared lambda's code is identified"),
               {"unlinked": unlinked})
    else:
        record("lambda code links", "INFO", "no lambdas declared in this upload")

    env_chosen = md_top.get("environment_file")
    env_cands = md_top.get("environment_candidates") or []
    if env_chosen:
        record("environment", "PASS",
               f"this map is grounded by {env_chosen}; "
               f"{max(len(env_cands) - 1, 0)} other environment file(s) present, "
               f"deliberately NOT used",
               {"chosen": env_chosen, "candidates": env_cands})
    elif env_cands:
        record("environment", "WARN",
               f"{len(env_cands)} files declare the same settings with different "
               f"values and NO environment was chosen — nothing from any of them "
               f"was used; answer 'environment_file' in the worksheet",
               {"candidates": env_cands})
    else:
        record("environment", "INFO",
               "single-environment upload — no competing settings files")

    declared = md_top.get("lambda_names_declared") or []
    confirmed = md_top.get("lambda_names_confirmed")
    corrections = md_top.get("lambda_name_corrections") or {}
    if declared:
        record("lambda names confirmed", "PASS" if confirmed else "WARN",
               (f"{len(declared)} declared name(s) reviewed and confirmed by a "
                f"person" + (f"; {len(corrections)} corrected to the real "
                             f"deployed name" if corrections else "")
                if confirmed else
                f"{len(declared)} name(s) declared by the terraform are NOT yet "
                f"confirmed — tests would use unverified names; answer "
                f"'confirm_lambda_names' in the worksheet"),
               {"declared": declared, "corrections": dict(corrections)})
    elif "lambda_names_confirmed" in md_top:
        record("lambda names confirmed", "INFO",
               "no terraform-declared lambda names in this upload")

    unresolved = [q for q in quads if isinstance(q, dict)
                  and not (q.get("context") or {}).get("resolved", True)]
    tokens = Counter(t for q in unresolved for t in TOKEN.findall(str(q.get("object", ""))))
    status = "PASS" if not tokens else "WARN"
    record("placeholders", status,
           f"{len(unresolved)} unresolved facts; {len(tokens)} distinct ${{}} tokens "
           + (f"(re-run the analyzer command — it asks, or fill the worksheet): "
              f"{', '.join(sorted(tokens)[:8])}"
              if tokens else "— nothing needs the name checkpoint"),
           {"tokens": sorted(tokens)})

    # --- the gate + the human trail (analyzer metadata, 2026-07 format) --------
    md = doc.get("metadata") or {}

    def _usages(token, limit=2):
        out = []
        for qd in quads:
            if isinstance(qd, dict) and f"${{{token}}}" in str(qd.get("object", "")):
                out.append(f"{qd.get('subject')} --{qd.get('predicate')}--> {qd.get('object')}")
                if len(out) >= limit:
                    break
        return out

    if "journeys_computed" in md:
        pending = list(md.get("pending_names") or [])
        if md.get("journeys_computed"):
            record("blocked or complete", "PASS",
                   "COMPLETE — every name is answered or decided; journeys were computed")
        else:
            record("blocked or complete", "WARN",
                   f"BLOCKED waiting for a human — {len(pending)} name(s) have no answer, "
                   f"so journeys were NOT computed (this file carries zero journeys "
                   f"on purpose): {', '.join(pending[:8])}",
                   {"pending": pending})
        if pending:
            record("questions for a human", "INFO",
                   f"{len(pending)} question(s); each shown with where the name is used",
                   {t: _usages(t) for t in pending})
    else:
        record("blocked or complete", "INFO",
               "this quad predates the gate metadata — blocked state not recorded")

    human_answers = md.get("human_answers") or {}
    human_facts = [f"{qd.get('subject')} --{qd.get('predicate')}--> {qd.get('object')}"
                   for qd in quads if isinstance(qd, dict)
                   and (qd.get("context") or {}).get("extraction_method") == "human"]
    record("human-supplied answers", "INFO" if not human_answers else "PASS",
           f"{len(human_answers)} name(s) supplied by a person, producing "
           f"{len(human_facts)} human-stamped fact(s) — each is marked so it can "
           f"never be mistaken for something the code said",
           {"answers": dict(human_answers), "facts": human_facts})

    decisions = md.get("decisions") or {}
    if decisions:
        lines = {t: f"{d.get('decision', '?')} — {d.get('reason', 'no reason recorded')}"
                 for t, d in decisions.items() if isinstance(d, dict)}
        record("skip / runtime decisions", "WARN",
               f"{len(decisions)} name(s) deliberately left blank by a person; the "
               f"facts keep their ${{placeholder}} and stay low-confidence — these "
               f"are signed-off holes, listed with their reasons", lines)
    else:
        record("skip / runtime decisions", "INFO", "none — no name was skipped")

    warnings = md.get("sheet_warnings") or []
    record("worksheet warnings", "WARN" if warnings else "PASS",
           f"{len(warnings)} operator-sheet issue(s)"
           + (" — " + " | ".join(warnings[:3]) if warnings else
              " — the answer sheets are consistent"),
           {"warnings": warnings})

    unwired = md.get("unwired") or []
    record("needs wiring", "WARN" if unwired else "PASS",
           f"{len(unwired)} journey-shaped fragment(s) that no front door reaches — "
           f"held for review, NOT promoted to journeys"
           + (f": {', '.join(unwired[:5])}" if unwired else ""),
           {"unwired": unwired})

    record("app id", "INFO", f"{app}")

    # --- what changed since the previous run (numbers side by side, no scoring) ----
    if args.against:
        try:
            with open(args.against, encoding="utf-8") as fh:
                prev_doc = yaml.safe_load(fh) or {}
        except Exception as exc:
            record("compared with previous run", "WARN",
                   f"{args.against} is not readable ({exc}) — comparison skipped")
        else:
            prev, now = _snapshot(prev_doc), _snapshot(doc)
            moved = {k: f"{prev.get(k, 0)} → {now[k]}" for k in now
                     if prev.get(k, 0) != now[k]}
            same = [k for k in now if prev.get(k, 0) == now[k]]
            record("compared with previous run", "INFO",
                   (("changed: " + ", ".join(f"{k} {v}" for k, v in moved.items()))
                    if moved else "nothing changed")
                   + (f" · unchanged: {len(same)} measure(s)" if moved else ""),
                   {"previous": prev, "current": now})

    # --- THE DECISION: ready to ingest, or wait? -----------------------------------
    # A state readout, not a judgment: WAIT fires only when the analyzer itself
    # declared the run incomplete (unanswered names → zero journeys) or the file
    # is unhealthy. Known holes a human signed off (skips, unwired fragments)
    # do NOT block — they ride along visibly.
    from _common import RESULTS
    unhealthy = any(r["status"] == "FAIL" for r in RESULTS)
    md = doc.get("metadata") or {}
    blocked = md.get("journeys_computed") is False
    if unhealthy:
        record("ready to ingest", "FAIL",
               "WAIT — the file itself is unhealthy (see the FAIL lines above); "
               "do not ingest")
    elif blocked:
        pending = list(md.get("pending_names") or [])
        record("ready to ingest", "FAIL",
               f"WAIT — {len(pending)} name(s) still need a human's answer and this "
               f"file carries zero journeys; answer them (re-run the analyzer "
               f"command) and re-check: {', '.join(pending[:6])}")
    else:
        holes = []
        if md.get("decisions"):
            holes.append(f"{len(md['decisions'])} signed-off skip(s)")
        if md.get("unwired"):
            holes.append(f"{len(md['unwired'])} needs-wiring fragment(s)")
        if md.get("sheet_warnings"):
            holes.append(f"{len(md['sheet_warnings'])} worksheet warning(s)")
        record("ready to ingest", "PASS",
               "READY TO INGEST"
               + (" — with known, visible holes: " + ", ".join(holes)
                  if holes else " — complete and clean"))

    write_report("check_quadfile")
    return exit_code()


if __name__ == "__main__":
    sys.exit(main())
