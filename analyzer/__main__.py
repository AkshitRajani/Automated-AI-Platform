"""
CLI front door — `python -m analyzer <app_dir> --app-id X [--out quad.yaml]`.

ONE command, start to finish:
  1. read everything (code + wiring + terraform), fill every blank the repo
     answers word-for-word;
  2. whatever is STILL blank: with a human attached (a terminal) it asks the
     questions right here, one at a time, each answer saved immediately to the
     worksheet; headless (a server) it writes the worksheet template and exits 2
     — fill the file and run the SAME command again;
  3. journeys are drawn only on the completed map, then the quad is written.

Answers live in <sheets>/<app_id>_worksheet.yaml (+ _decisions.yaml for
runtime/skip verdicts) — auditable, never asked twice, human beats repo.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

import yaml

from .emit import to_yaml, write
from .extract import analyze

_TOKEN = re.compile(r"\$\{([^}]+)\}")


# --- the worksheet files (the name checkpoint's answer + decision sheets) -------
def _sheet_paths(sheets_dir: str, app_id: str):
    return (os.path.join(sheets_dir, f"{app_id.lower()}_worksheet.yaml"),
            os.path.join(sheets_dir, f"{app_id.lower()}_decisions.yaml"))


def _load_sheet(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            try:
                data = yaml.safe_load(fh)
            except yaml.YAMLError as exc:          # operator error → clean halt
                raise ValueError(
                    f"{path} is not valid YAML — fix the file and re-run ({exc})")
            return data if isinstance(data, dict) else {}
    return {}


def _dump_sheet(path: str, data: dict, header: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(data, fh, sort_keys=True, allow_unicode=True,
                       default_flow_style=False)


def _usages(qf, tokens):
    """token -> [(subject, predicate, object)] samples from the quads."""
    out = defaultdict(list)
    wanted = set(tokens)
    for q in qf.quads:
        if "${" not in q.object:
            continue
        for t in _TOKEN.findall(q.object):
            if t in wanted:
                out[t].append((q.subject, q.predicate, q.object))
    return out


def _write_template(pending, worksheet_path):
    """(Re)write the worksheet WITHOUT ever destroying an operator's answers.

    Existing entries — answered or blank, pending or not — are preserved on
    every run; only pending tokens missing from the file gain a blank line.
    (Study S14: the old blanks-only overwrite deleted saved answers on every
    halt, making batch answering non-convergent.)"""
    existing = _load_sheet(worksheet_path)
    lines = ["# Name worksheet — fill the value after each token, then re-run the",
             "# SAME analyzer command. A value here beats anything a repo file declares.",
             "# Existing answers are preserved on every run."]
    for token in sorted(existing):
        value = existing[token]
        if value is None or str(value).strip() == "":
            lines.append(f"{token}: ")
        else:
            lines.append(yaml.safe_dump({token: value},
                                        default_flow_style=False).strip())
    if existing:
        lines.append("")
    for token, uses in pending.items():
        if token in existing:
            continue
        if token == "environment_file":
            lines.append("# environment_file: several files declare the same "
                         "settings with different values.")
            lines.append("# Name the ONE that grounds this map:")
            for _s, _p, cand in uses:
                lines.append(f"#   - {cand}")
        elif token == "confirm_lambda_names":
            lines.append("# confirm_lambda_names: the terraform declares these "
                         "deployed lambda names.")
            lines.append("# Review the list. Correct any wrong one by adding a line:")
            lines.append("#   lambda_name.<declared>: <real deployed name>")
            lines.append("# then set confirm_lambda_names: yes")
            for _s, _p, name in uses:
                lines.append(f"#   - {name}")
        else:
            for s, p, o in uses[:2]:
                lines.append(f"# {token}: used by {s} --{p}--> {o}")
        lines.append(f"{token}: ")
        lines.append("")
    os.makedirs(os.path.dirname(worksheet_path) or ".", exist_ok=True)
    with open(worksheet_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _ask(token, uses, idx, total):
    """One question. Returns (kind, value): ('value', v) | ('runtime', why) | ('skip', why)."""
    print(f"\n[{idx}/{total}]  ${{{token}}}")
    for s, p, o in uses[:3]:
        print(f"      used by  {s}  --{p}-->  {o}")
    if len(uses) > 3:
        print(f"      … and {len(uses) - 3} more usage(s)")
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


def _ask_env(candidates):
    print(f"\n{len(candidates)} files declare the same settings with different "
          f"values — different environments of one estate. Which ONE grounds "
          f"this map?")
    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c}")
    while True:
        raw = input(f"  choose [1-{len(candidates)}] (or type the file name): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            return candidates[int(raw) - 1]
        if raw in candidates or any(c.endswith(raw) for c in candidates if raw):
            return raw
        print("  not one of the listed files — try again.")


def _ask_all(qf, app_id, sheets_dir) -> None:
    worksheet_path, decisions_path = _sheet_paths(sheets_dir, app_id)
    answered = {str(k): str(v) for k, v in _load_sheet(worksheet_path).items()
                if v is not None and str(v).strip()}
    decided = _load_sheet(decisions_path)
    pending = list(qf.pending_names)
    if "environment_file" in pending:
        answered["environment_file"] = _ask_env(qf.env_candidates)
        _dump_sheet(worksheet_path, answered,
                    "# Human answers — a human beats a repo file.\n")
        print("  saved. (name questions may shrink once the environment's "
              "values are read — asking the rest on the re-run)")
        return                       # everything below depends on this answer
    if "confirm_lambda_names" in pending:
        print(f"\nThe terraform declares {len(qf.lambda_names_declared)} deployed "
              f"lambda name(s):")
        for name in qf.lambda_names_declared:
            print(f"   {name}")
        raw = input("  accept ALL as the real deployed names? "
                    "[y = yes / anything else = I need to correct some]: ").strip().lower()
        if raw in ("y", "yes"):
            answered["confirm_lambda_names"] = "yes"
            _dump_sheet(worksheet_path, answered,
                        "# Human answers — a human beats a repo file.\n")
            print("  saved.")
        else:
            print(f"  Add 'lambda_name.<declared>: <real name>' lines to "
                  f"{worksheet_path}, set confirm_lambda_names: yes, and run "
                  f"this same command again.")
        pending.remove("confirm_lambda_names")
        if not pending:
            return
    uses = _usages(qf, pending)
    total = len(pending)
    print(f"\nThe repo answered everything it could. {total} name(s) remain — "
          f"only a human can answer these.")
    for idx, token in enumerate(pending, 1):
        kind, value = _ask(token, uses.get(token, []), idx, total)
        if kind == "value":
            answered[token] = value
            _dump_sheet(worksheet_path, answered,
                        "# Human answers — a human beats a repo file.\n")
        else:
            decided[token] = {"decision": "runtime-data" if kind == "runtime" else "skipped",
                              "reason": value}
            _dump_sheet(decisions_path, decided,
                        "# Decisions — remembered so nobody is asked twice.\n")
        print("  saved.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m analyzer",
                                description="Codebase → quad file, one command "
                                            "(asks a human for unanswerable names).")
    p.add_argument("app_dir")
    p.add_argument("--app-id", required=True)
    p.add_argument("--out", default=None, help="write quad YAML here (default: stdout)")
    p.add_argument("--stats", action="store_true", help="print a per-predicate breakdown")
    p.add_argument("--names", default=None,
                   help="worksheet directory (default: <app_id>_sheets)")
    p.add_argument("--ask", action="store_true",
                   help="ask pending names interactively even without a terminal")
    p.add_argument("--no-ask", action="store_true",
                   help="never prompt, even in a terminal (server semantics)")
    p.add_argument("--env-file", default=None,
                   help="which of several competing environment .tfvars files "
                        "grounds this map (name or path); beats the worksheet's "
                        "environment_file entry")
    args = p.parse_args(argv)
    sheets = args.names or f"{args.app_id}_sheets"

    try:
        qf = analyze(args.app_dir, args.app_id, names_dir=sheets,
                     env_file=args.env_file)

        # The human step, inline — when a human is actually attached. Answers
        # can unlock NEW questions (an environment choice reveals its lambda
        # list), so ask-and-re-run until nothing new is answerable.
        interactive = (args.ask or sys.stdin.isatty()) and not args.no_ask
        rounds = 0
        while qf.pending_names and interactive and rounds < 5:
            before = list(qf.pending_names)
            try:
                _ask_all(qf, args.app_id, sheets)
            except (EOFError, KeyboardInterrupt):
                print("\n(no more input — answers so far are saved; the "
                      "worksheet below has the rest)", file=sys.stderr)
                break
            print("\nRe-running with your answers …")
            qf = analyze(args.app_dir, args.app_id, names_dir=sheets,
                         env_file=args.env_file)
            rounds += 1
            if qf.pending_names == before:      # nothing progressed — stop
                break                           # asking; halt below explains
    except ValueError as exc:                      # bad sheet file → clean halt
        print(f"\nHALT: {exc}", file=sys.stderr)
        return 2

    for note in qf.analyzer_notes:
        print(f"note: {note}", file=sys.stderr)
    for w in qf.sheet_warnings:
        print(f"warning: {w}", file=sys.stderr)

    if args.out:
        write(qf, args.out)
        print(f"wrote {args.out}: {len(qf.entities)} entities, {len(qf.quads)} quads")
    else:
        print(to_yaml(qf))

    if qf.unwired:
        print(f"needs wiring: {len(qf.unwired)} journey-shaped orphan(s) that no "
              f"front door reaches — listed in the quad metadata for review; "
              f"they were NOT promoted to journeys.", file=sys.stderr)

    if qf.pending_names:
        # Headless (or answers still missing): the quad above carries NO journeys
        # — they were never computed. Fill the worksheet, run the SAME command.
        worksheet_path, _ = _sheet_paths(sheets, args.app_id)
        pending_uses = _usages(qf, qf.pending_names)
        if "confirm_lambda_names" in qf.pending_names:
            pending_uses = {"confirm_lambda_names": [
                ("declared", "by the terraform", n)
                for n in qf.lambda_names_declared], **pending_uses}
        if "environment_file" in qf.pending_names:
            pending_uses = {"environment_file": [
                ("choose ONE of", "the competing environment files", c)
                for c in qf.env_candidates], **pending_uses}
        _write_template(pending_uses, worksheet_path)
        reserved = [t for t in qf.pending_names
                    if t in ("environment_file", "confirm_lambda_names")]
        blanks = len(qf.pending_names) - len(reserved)
        parts = []
        if "environment_file" in reserved:
            parts.append("the environment choice")
        if "confirm_lambda_names" in reserved:
            parts.append("the lambda-name confirmation")
        if blanks:
            parts.append(f"{blanks} blank name(s)")
        print(f"\nHALT: {' + '.join(parts)} still need a human — journeys "
              f"were NOT computed.", file=sys.stderr)
        print(f"Fill in {worksheet_path} and run this same command again.",
              file=sys.stderr)
        from .extract import discover
        if not discover(args.app_dir, exts=(".tf", ".tfvars")):
            print("Hint: no Terraform files were found in this upload. If this "
                  "app is provisioned from a deploy repo, include that repo — "
                  "the values for these blanks usually live there. (This is a "
                  "plain file parser, not a model: folder size is not a "
                  "constraint.)", file=sys.stderr)
        return 2

    js = sorted(e.id for e in qf.entities if e.type == "Journey")
    bg = [e for e in qf.entities if e.type == "BehaviorGroup"]
    print(f"journeys: {len(js)}  behavior groups: {len(bg)}  "
          f"needs-wiring: {len(qf.unwired)}", file=sys.stderr)
    for j in js:
        print(f"   {j}", file=sys.stderr)

    if args.stats:
        by_pred = {}
        by_type = {}
        for q in qf.quads:
            by_pred[q.predicate] = by_pred.get(q.predicate, 0) + 1
        for e in qf.entities:
            by_type[e.type] = by_type.get(e.type, 0) + 1
        print("entities:", dict(sorted(by_type.items())), file=sys.stderr)
        print("quads:", dict(sorted(by_pred.items())), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
