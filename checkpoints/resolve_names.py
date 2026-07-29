#!/usr/bin/env python3
"""
Name checkpoint — onboarding HALTS here until every placeholder has a decision.

After the analyzer runs (and its auto-harvest has filled what the repo declared),
some names may still be blanks (``${TOKEN}``). Loading an app with open blanks
means broken journeys nobody notices — so this step refuses to let them slide:

    PYTHONPATH=. python resolve_names.py <quad_file> --sheets <dir>

  * Interactive (a terminal): asks ONE QUESTION PER TOKEN (not per usage) —
    shows where it is used, takes the real value, or 'r' (runtime data: the
    value is chosen per run — a test precondition, not a name), or 's' (skip,
    with a reason). Every answer is written to the sheet IMMEDIATELY, so a
    re-run never asks the same question twice and every answer is auditable.
  * Headless (no terminal / --headless): writes the same questions as a
    template file and exits with code 2 ("waiting for names"). Fill the file,
    re-run, it proceeds.

Exit codes:  0 = every token answered or decided → safe to continue onboarding
             2 = pending questions remain (headless) → halt

The sheet directory is resolver-ready: point ``PARAM_BINDINGS_SOURCE`` at it and
ingestion applies the answers (a human's answer beats a repo file — doc 10).
Decisions (runtime-data / skip) live in a sidecar so they are remembered but
never fed to the resolver as fake values.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

import yaml

TOKEN = re.compile(r"\$\{([^}]+)\}")     # the analyzer's own blank syntax


# --- reading the state -----------------------------------------------------------
def load_quads(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def pending_tokens(doc: dict, answered: Dict[str, str],
                   decided: Dict[str, dict]) -> Dict[str, List[Tuple[str, str, str]]]:
    """token -> usage samples [(subject, predicate, object)], for every ``${token}``
    in the quad objects that no source has answered or decided yet. One entry per
    TOKEN — a token used in 40 places is one question."""
    repo = {str(k): str(v) for k, v in (doc.get("bindings") or {}).items()}
    out: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for q in doc.get("quads") or []:
        obj = str(q.get("object", ""))
        for token in TOKEN.findall(obj):
            if token in repo or token in answered or token in decided:
                continue
            out[token].append((str(q.get("subject", "")), str(q.get("predicate", "")), obj))
    return dict(sorted(out.items()))


# --- the sheets (answers + decisions), persisted immediately -----------------------
def _load_yaml(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
    return {}


def _dump_yaml(path: str, data: dict, header: str = "") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if header:
            fh.write(header)
        yaml.safe_dump(data, fh, sort_keys=True, allow_unicode=True,
                       default_flow_style=False)


def sheet_paths(sheets_dir: str, app_id: str) -> Tuple[str, str]:
    return (os.path.join(sheets_dir, f"{app_id}_worksheet.yaml"),
            os.path.join(sheets_dir, f"{app_id}_decisions.yaml"))


# --- interactive -------------------------------------------------------------------
def ask(token: str, usages: List[Tuple[str, str, str]], idx: int, total: int) -> Tuple[str, str]:
    """One question. Returns (kind, value): ('value', v) | ('runtime', why) | ('skip', why)."""
    print(f"\n[{idx}/{total}]  ${{{token}}}")
    for s, p, o in usages[:3]:
        print(f"      used by  {s}  --{p}-->  {o}")
    if len(usages) > 3:
        print(f"      … and {len(usages) - 3} more usage(s)")
    while True:
        raw = input("  real value  (or 'r' = runtime data, 's' = skip): ").strip()
        if raw.lower() == "r":
            why = input("  why is it per-run? (one line): ").strip() or "value chosen per run"
            return "runtime", why
        if raw.lower() == "s":
            why = input("  reason for skipping: ").strip()
            if why:
                return "skip", why
            print("  a skip needs a reason — it has to be auditable.")
            continue
        if raw:
            return "value", raw
        print("  empty answer — give a value, or 'r' / 's'.")


def run_interactive(pending, worksheet_path, decisions_path,
                    answered, decided) -> None:
    total = len(pending)
    print(f"\n{total} name(s) need a decision before this app can load.")
    for idx, (token, usages) in enumerate(pending.items(), 1):
        kind, value = ask(token, usages, idx, total)
        if kind == "value":
            answered[token] = value
            _dump_yaml(worksheet_path, answered,
                       "# Human answers — the resolver applies these; a human beats a repo file.\n")
        else:
            decided[token] = {"decision": "runtime-data" if kind == "runtime" else "skipped",
                              "reason": value}
            _dump_yaml(decisions_path, decided,
                       "# Decisions — remembered so nobody is asked twice; never fed to the resolver.\n")
        print("  saved.")


def write_template(pending, worksheet_path) -> None:
    lines = ["# Name worksheet — fill the value after each token, then re-run the checkpoint.",
             "# A value you write here beats anything a repo file declares (doc 10).",
             "# For a per-run value, delete the line and record it in the decisions file instead."]
    for token, usages in pending.items():
        for s, p, o in usages[:2]:
            lines.append(f"# {token}: used by {s} --{p}--> {o}")
        lines.append(f"{token}: ")
        lines.append("")
    os.makedirs(os.path.dirname(worksheet_path) or ".", exist_ok=True)
    with open(worksheet_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# --- main ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="resolve_names", description=__doc__)
    ap.add_argument("quad_file", help="the analyzer's quad YAML")
    ap.add_argument("--sheets", required=True,
                    help="directory for the worksheet + decisions (resolver-ready: "
                         "point PARAM_BINDINGS_SOURCE here)")
    ap.add_argument("--headless", action="store_true",
                    help="never prompt: write the question template and exit 2 if pending")
    args = ap.parse_args(argv)

    doc = load_quads(args.quad_file)
    app_id = str((doc.get("metadata") or {}).get("app_id", "app")).lower()
    worksheet_path, decisions_path = sheet_paths(args.sheets, app_id)
    answered = {str(k): str(v) for k, v in _load_yaml(worksheet_path).items()
                if v is not None and str(v).strip()}
    decided = _load_yaml(decisions_path)

    pending = pending_tokens(doc, answered, decided)
    if not pending:
        print("No open names — every placeholder is answered or decided. Safe to load.")
        return 0

    if args.headless or not sys.stdin.isatty():
        write_template(pending, worksheet_path)
        print(f"HALT: {len(pending)} name(s) need answers. "
              f"Fill in {worksheet_path} and re-run.")
        return 2

    run_interactive(pending, worksheet_path, decisions_path, answered, decided)
    left = pending_tokens(doc, {**answered, **{k: str(v) for k, v in _load_yaml(worksheet_path).items() if v}},
                          _load_yaml(decisions_path))
    if left:
        print(f"\nHALT: {len(left)} name(s) still open.")
        return 2
    print("\nAll names answered or decided. Safe to load "
          f"(PARAM_BINDINGS_SOURCE={args.sheets}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
