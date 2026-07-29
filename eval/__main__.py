"""
CLI front door — the reference handover, mirroring `python -m validator`.

    python -m eval --sut PATH --test PATH [options]

Options:
    --sut PATH              the code under test (a .py file)               [required]
    --test PATH             a test module exposing `def run(sut): ...`     [required]
    --app-id ID             KB scope for grounding                         [default: ""]
    --steps DIR             folder of step files → static validator layer
    --changed PATH:1,2,3    changed lines in the SUT (gate 5); repeatable
    --ground NAME:KIND      an identifier to ground (gate 2); repeatable
    --names FILE            newline-separated real names → a simple grounding resolver
    --runs N                stability re-runs (gate 7)                     [default: 3]
    --mutants N             max mutants (gate 6)                           [default: 8]
    --json                  machine-readable output

Exit code: 0 if delivered (all gates pass), 1 otherwise — CI-friendly.
"""
from __future__ import annotations

import argparse
import json
import sys
from types import SimpleNamespace
from typing import Dict, List, Set, Tuple

from .cascade import evaluate
from .context import EvalContext
from .execution import ExecCase
from .models import GateStatus


class _NamesResolver:
    """A trivial grounding resolver over a flat allow-list of real names — enough
    to exercise gate 2 from the CLI without a live KB. The real KBClient is the
    drop-in for production."""

    def __init__(self, names):
        self._names = set(names)

    def resolve(self, query: str, kind: str = "any", app_id: str = "", limit: int = 10):
        candidates = ([SimpleNamespace(canonical_name=query, resolved=True)]
                      if query in self._names else [])
        return SimpleNamespace(candidates=candidates)


def _parse_changed(values: List[str]) -> Dict[str, Set[int]]:
    out: Dict[str, Set[int]] = {}
    for spec in values or []:
        path, _, lines = spec.rpartition(":")
        if not path:
            continue
        nums = {int(n) for n in lines.split(",") if n.strip().isdigit()}
        out.setdefault(path, set()).update(nums)
    return out


def _parse_ground(values: List[str]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for spec in values or []:
        name, _, kind = spec.partition(":")
        if name:
            out.append((name, kind or "any"))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval",
                                     description="Deterministic 7-gate test eval.")
    parser.add_argument("--sut", required=True)
    parser.add_argument("--test", required=True)
    parser.add_argument("--app-id", default="")
    parser.add_argument("--steps", default=None)
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--ground", action="append", default=[])
    parser.add_argument("--names", default=None)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mutants", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    resolver = None
    if args.names:
        with open(args.names, encoding="utf-8") as handle:
            resolver = _NamesResolver(n.strip() for n in handle if n.strip())

    ctx = EvalContext(
        app_id=args.app_id,
        case=ExecCase(sut_path=args.sut, test_path=args.test),
        changed_lines=_parse_changed(args.changed),
        identifiers=_parse_ground(args.ground),
        steps_root=args.steps,
        stability_runs=args.runs,
        mutation_max=args.mutants,
    )
    verdict = evaluate(ctx, resolver=resolver)

    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2))
    else:
        _print_human(verdict)
    return 0 if verdict.deliver else 1


def _print_human(verdict) -> None:
    mark = {GateStatus.PASS: "PASS", GateStatus.FAIL: "FAIL", GateStatus.SKIP: "skip"}
    for g in verdict.gates:
        print(f"  [{mark[g.status]}] gate {g.number}  {g.name:<22} {g.detail}")
        for f in g.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"         → {f.rule} ({loc}): {f.message}")
            if f.suggestion:
                print(f"           fix: {f.suggestion}")
    print()
    if verdict.deliver:
        ev = verdict.evidence
        print(f"DELIVER — all gates passed "
              f"(evidence: {ev.get('mutants_caught', 0)} mutants caught, "
              f"{ev.get('lines_covered', 0)} lines covered)")
    else:
        print(f"REPAIR/DISCARD — failed at gate {verdict.failed_gate}")


if __name__ == "__main__":
    sys.exit(main())
