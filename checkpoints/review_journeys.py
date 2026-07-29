#!/usr/bin/env python3
"""
Journey review — a human confirms the journey list is right and complete.

The analyzer WALKS the graph and records journeys; the spec agent NARRATES them.
Neither can answer two questions only a person can: "is this chain a real
business journey?" and "did we miss one?" This checkpoint asks exactly those,
right after spec generation:

    PYTHONPATH=. python review_journeys.py <quad_file> --sheets <dir> \\
        [--specs <spec_workspace>]

  * Interactive: one verdict per journey — [c]onfirm (+ its business name),
    [r]eject (why it isn't a real journey), [d]efer (decide later). Then:
    "any journey we missed?" — add it by naming a REAL entry node (validated
    against the analysis; invented names are refused). Every verdict is saved
    immediately; a re-run only asks about journeys with no verdict yet.
  * Headless (--headless / no terminal): writes the review sheet as a fillable
    template and exits 2 ("waiting for review").

Exit codes:  0 = every journey has a verdict (confirmed/rejected)
             2 = verdicts pending (deferred or unasked)

Verdicts persist in ``<sheets>/<app>_journeys.yaml`` — human words, auditable,
and loadable into the KB (``app_journeys``) at ingestion time. A human-added
journey records WHY the walker missed it — each one is an analyzer gap ticket.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Tuple

import yaml


# --- reading the state -----------------------------------------------------------
def load_quads(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def journeys_from(doc: dict) -> Dict[str, dict]:
    """journey id -> {'entry', 'members': [(hop, node)...]} straight from the
    analyzer's own STARTS_AT / HAS_MEMBER facts."""
    out: Dict[str, dict] = {}
    for e in doc.get("entities") or []:
        if isinstance(e, dict) and e.get("type") == "Journey":
            out[str(e["id"])] = {"entry": "", "members": []}
    for q in doc.get("quads") or []:
        if not isinstance(q, dict):
            continue
        subj = str(q.get("subject", ""))
        if subj not in out:
            continue
        if q.get("predicate") == "STARTS_AT":
            out[subj]["entry"] = str(q.get("object", ""))
        elif q.get("predicate") == "HAS_MEMBER":
            hop = (q.get("context") or {}).get("line_start") or q.get("line") or 0
            out[subj]["members"].append((hop or 0, str(q.get("object", ""))))
    for j in out.values():
        j["members"].sort()
    return dict(sorted(out.items()))


def real_nodes(doc: dict) -> set:
    """Every id the analysis knows — the grounding set for human-added entries."""
    nodes = {str(e.get("id", "")) for e in (doc.get("entities") or []) if isinstance(e, dict)}
    for q in doc.get("quads") or []:
        if isinstance(q, dict):
            nodes.add(str(q.get("subject", "")))
            nodes.add(str(q.get("object", "")))
    nodes.discard("")
    return nodes


def spec_status(specs_dir: str) -> Dict[str, str]:
    """journey unit -> documented/skipped, from the spec agent's manifest (if given)."""
    path = os.path.join(specs_dir, "requirements_manifest.json")
    if not (specs_dir and os.path.isfile(path)):
        return {}
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        return {str(e.get("unit", "")): str(e.get("status", ""))
                for e in manifest.get("entries", [])}
    except Exception:
        return {}


# --- the verdict sheet, persisted immediately ---------------------------------------
def sheet_path(sheets_dir: str, app_id: str) -> str:
    return os.path.join(sheets_dir, f"{app_id}_journeys.yaml")


def _load_yaml(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
    return {}


def _save(path: str, verdicts: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Journey review — human verdicts. confirmed/rejected + names + reasons.\n"
                 "# human-added journeys record why the walker missed them (analyzer gaps).\n")
        yaml.safe_dump(verdicts, fh, sort_keys=True, allow_unicode=True,
                       default_flow_style=False)


# --- interactive ---------------------------------------------------------------------
def show(jid: str, info: dict, status: str, idx: int, total: int) -> None:
    print(f"\n[{idx}/{total}]  {jid}")
    if status:
        print(f"      spec: {status}")
    chain = [n for _h, n in info["members"][:5]]
    if info.get("entry"):
        print(f"      starts at  {info['entry']}")
    if chain:
        print(f"      chain      {'  ->  '.join(chain)}"
              + (f"  -> … ({len(info['members'])} nodes)" if len(info["members"]) > 5 else ""))


def ask_verdict() -> Tuple[str, str]:
    while True:
        raw = input("  [c]onfirm / [r]eject / [d]efer: ").strip().lower()
        if raw == "c":
            name = input("  business name (enter = keep technical id): ").strip()
            return "confirmed", name
        if raw == "r":
            why = input("  why is this not a real journey?: ").strip()
            if why:
                return "rejected", why
            print("  a rejection needs a reason — it has to be auditable.")
            continue
        if raw == "d":
            return "deferred", ""
        print("  c, r, or d.")


def ask_missing(nodes: set, verdicts: dict, path: str) -> None:
    while True:
        raw = input("\nAny journey we MISSED? (business name, or enter = no): ").strip()
        if not raw:
            return
        entry = input(f"  where does '{raw}' start? (a real node id from the analysis): ").strip()
        if entry not in nodes:
            print(f"  '{entry}' is not a node the analysis knows — an invented name here "
                  f"would be a lie in the database. Check the id and try again.")
            continue
        why = input("  why did the walker miss it? (one line): ").strip() or "not stated"
        jid = f"Journey:{entry}"
        verdicts[jid] = {"status": "human-added", "name": raw, "entry": entry,
                         "missed_because": why}
        _save(path, verdicts)
        print(f"  saved — {jid} recorded as human-added (and '{why}' is an analyzer gap to fix).")


# --- main -----------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="review_journeys", description=__doc__)
    ap.add_argument("quad_file", help="the analyzer's quad YAML (holds the walked journeys)")
    ap.add_argument("--sheets", required=True, help="directory for the verdict sheet")
    ap.add_argument("--specs", default="", help="spec agent workspace (shows documented/skipped)")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args(argv)

    doc = load_quads(args.quad_file)
    app_id = str((doc.get("metadata") or {}).get("app_id", "app")).lower()
    path = sheet_path(args.sheets, app_id)
    verdicts = _load_yaml(path)
    journeys = journeys_from(doc)
    statuses = spec_status(args.specs)

    pending = {jid: info for jid, info in journeys.items()
               if verdicts.get(jid, {}).get("status") in (None, "", "deferred")}

    if not pending:
        confirmed = sum(1 for v in verdicts.values() if v.get("status") == "confirmed")
        added = sum(1 for v in verdicts.values() if v.get("status") == "human-added")
        print(f"Journey review complete: {confirmed} confirmed, "
              f"{sum(1 for v in verdicts.values() if v.get('status') == 'rejected')} rejected, "
              f"{added} human-added. Nothing pending.")
        return 0

    if args.headless or not sys.stdin.isatty():
        for jid in pending:
            verdicts.setdefault(jid, {"status": "", "name": "",
                                      "reason": "fill status: confirmed|rejected"})
        _save(path, verdicts)
        print(f"HALT: {len(pending)} journey(s) need review. Fill in {path} and re-run.")
        return 2

    total = len(pending)
    print(f"\n{total} journey(s) need your verdict.")
    for idx, (jid, info) in enumerate(pending.items(), 1):
        show(jid, info, statuses.get(jid, ""), idx, total)
        status, extra = ask_verdict()
        if status == "deferred":
            verdicts[jid] = {"status": "deferred"}
        elif status == "confirmed":
            verdicts[jid] = {"status": "confirmed", "name": extra or jid.split(":", 1)[1]}
        else:
            verdicts[jid] = {"status": "rejected", "reason": extra}
        _save(path, verdicts)
        print("  saved.")

    ask_missing(real_nodes(doc), verdicts, path)

    left = [j for j, v in _load_yaml(path).items()
            if v.get("status") in ("", "deferred")]
    if left:
        print(f"\nHALT: {len(left)} journey verdict(s) still open.")
        return 2
    print("\nJourney review complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
