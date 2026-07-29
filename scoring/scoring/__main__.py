"""
CLI — standalone behaviour-based BDD scoring (Gherkin zips or folders).

Configure paths in ``scoring/scoring/.env`` (same folder as this module), then:

    python -m scoring
    python -m scoring serve

Or pass paths explicitly:

    python -m scoring --golden-zip manual.zip --generated-zip generated.zip
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from .config import ScoringConfig, apply_python_path, env_file_path, load_env_file
from .html_report import write_html
from .report_views import build_detailed, build_simplified
from .score import score
from .standalone import open_html_report, prompt_for_zip_pair, run_from_zips


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    load_env_file()
    root = apply_python_path()
    cfg = ScoringConfig.load()
    _print_env_hint(cfg, root)

    if not argv or argv[0] not in ("run", "serve", "help", "-h", "--help"):
        return _main_standalone(argv, cfg)

    parser = argparse.ArgumentParser(
        prog="python -m scoring",
        description=(
            "Standalone BDD behaviour scoring. Set paths in scoring/scoring/.env "
            "or pass --golden-zip / --generated-zip."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser(
        "serve",
        help="start upload UI — pick two zips in the browser, get JSON + HTML",
    )
    ps.add_argument("--host", default=None)
    ps.add_argument("--port", type=int, default=None)
    ps.add_argument("--open", action="store_true", help="open browser")
    ps.add_argument(
        "--runs-dir", default=None,
        help="where to store run outputs (default: SCORING_RUNS_DIR or system temp)",
    )

    pr = sub.add_parser("run", help="score from feature folders (paths from .env or flags)")
    pr.add_argument("--golden", default=None, help="golden .feature file or directory")
    pr.add_argument("--generated", default=None, help="generated .feature file or directory")
    pr.add_argument(
        "--requirements", default=None,
        help="requirement-agent output folder (.json / .md docs)",
    )
    pr.add_argument("--threshold", type=float, default=None)
    pr.add_argument("--json", dest="as_json", action="store_true")
    pr.add_argument("--output", "-o", default=None)
    pr.add_argument("--html", default=None, metavar="PATH")
    pr.add_argument("--open", action="store_true")
    pr.add_argument("--simple-only", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        from .web_ui import serve
        host = args.host or cfg.serve_host
        port = args.port if args.port is not None else cfg.serve_port
        runs_dir = args.runs_dir or cfg.runs_dir or None
        serve(host, port, open_browser=args.open or cfg.open_report, runs_dir=runs_dir)
        return 0

    return _main_run_dirs(args, cfg)


def _print_env_hint(cfg: ScoringConfig, root: Path) -> None:
    print(f"PYTHONPATH includes: {root}")
    if cfg.env_file:
        print(f"Using config from {cfg.env_file}")
    else:
        example = env_file_path().with_name(".env.example")
        hint = f" (copy {example} to {env_file_path()})" if example.is_file() else ""
        print(f"No .env found{hint}")


def _main_standalone(argv: list[str], cfg: ScoringConfig) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scoring",
        description=(
            "Standalone BDD scoring — set SCORING_GOLDEN_ZIP and SCORING_GENERATED_ZIP "
            "in scoring/scoring/.env, or pass zip paths on the command line."
        ),
    )
    parser.add_argument("--golden-zip", default=None, help="zip of manual (golden) .feature folder")
    parser.add_argument("--generated-zip", default=None, help="zip of generated .feature folder")
    parser.add_argument(
        "--requirements-zip", default=None,
        help="zip of requirement-agent output (optional)",
    )
    parser.add_argument(
        "--output-dir", "-d", default=None,
        help="write score_report.json and score_report.html here (default: SCORING_OUTPUT_DIR)",
    )
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--open", action="store_true", help="open HTML report in browser")
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="prompt for zip paths instead of using .env",
    )
    args = parser.parse_args(argv)

    golden_zip = args.golden_zip or cfg.golden_zip
    generated_zip = args.generated_zip or cfg.generated_zip
    requirements_zip = getattr(args, "requirements_zip", None) or cfg.requirements_zip
    output_dir = args.output_dir or cfg.output_dir or "."
    threshold = args.threshold if args.threshold is not None else cfg.threshold
    open_report = args.open or cfg.open_report

    if not golden_zip or not generated_zip:
        if args.interactive:
            golden_path, generated_path = prompt_for_zip_pair()
            golden_zip = str(golden_path)
            generated_zip = str(generated_path)
        else:
            parser.error(
                "Set SCORING_GOLDEN_ZIP and SCORING_GENERATED_ZIP in "
                f"{env_file_path()}, or pass --golden-zip / --generated-zip, "
                "or use --interactive"
            )

    for label, path in (("golden", golden_zip), ("generated", generated_zip)):
        if not Path(path).is_file() or not zipfile.is_zipfile(path):
            print(f"error: {label} zip not found or invalid: {path}", file=sys.stderr)
            return 2

    try:
        result = run_from_zips(
            golden_zip,
            generated_zip,
            requirements_zip=requirements_zip or None,
            output_dir=output_dir,
            threshold=threshold,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    b = result.report.breakdown
    print()
    print(f"Overall score:                 {b.overall_score:.1f}%")
    print(
        f"Generated → manual alignment:    "
        f"{result.report.generated_aligned_to_manual} / {result.report.generated_scenarios} "
        f"({b.generated_manual_alignment_pct:.1f}%)"
    )
    if result.report.has_requirements:
        print(
            f"Generated → requirement align:   "
            f"{result.report.generated_aligned_to_requirements} / "
            f"{result.report.generated_scenarios} "
            f"({b.generated_requirement_alignment_pct:.1f}%)"
        )
        print(
            f"Generated triangulated (both):   "
            f"{b.generated_triangulated_count} ({b.triangulation_pct:.1f}%)"
        )
    print(f"JSON report:                     {result.json_path}")
    print(f"HTML report:                     {result.html_path}")

    if open_report:
        open_html_report(result.html_path)

    return 0


def _main_run_dirs(args, cfg: ScoringConfig) -> int:
    golden = args.golden or cfg.golden_dir
    generated = args.generated or cfg.generated_dir
    requirements = args.requirements or cfg.requirements_dir or None
    threshold = args.threshold if args.threshold is not None else cfg.threshold
    open_report = args.open or cfg.open_report
    run_profiling_mode = cfg.profiling_mode if cfg.profiling_mode != "auto" else None

    if not golden or not generated:
        print(
            "error: set SCORING_GOLDEN and SCORING_GENERATED in "
            f"{env_file_path()} or pass --golden / --generated",
            file=sys.stderr,
        )
        return 2

    report = score(
        golden=golden,
        generated=generated,
        requirements=requirements,
        threshold=threshold,
        profiling_mode=run_profiling_mode,
    )
    payload = report.to_dict()

    if args.simple_only:
        payload = {"simplified": payload["simplified"]}

    output_json = args.output
    output_html = args.html
    if not output_json and not output_html and cfg.output_dir:
        out = Path(cfg.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        output_json = str(out / "score_report.json")
        output_html = str(out / "score_report.html")

    if output_json:
        with open(output_json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

    if output_html:
        write_html(report, output_html)
        print(f"HTML report written to {output_html}")
        if open_report:
            open_html_report(output_html)

    if args.as_json or output_json:
        if not output_json:
            print(json.dumps(payload, indent=2))
    elif not output_html:
        _print_human(report)

    return 0


def _print_human(report) -> None:
    simple = build_simplified(report)
    detailed = build_detailed(report)

    print()
    print("=" * 60)
    print("SIMPLIFIED REPORT (stakeholders)")
    print("=" * 60)
    print()
    print(f"  {simple['summary']}")
    print()
    print(f"  Overall score:  {simple['overall_score_pct']}%")
    print(f"  Verdict:        {simple['verdict']}")
    print()
    h = simple["headline"]
    print(f"  Generated (scored):           {h['generated_scored_scenarios']}")
    print(
        f"  Aligned → manual:             "
        f"{h['generated_aligned_to_manual']} ({h['generated_manual_alignment_pct']}%)"
    )
    print(f"  Not aligned → manual:         {h['generated_unaligned_manual']}")
    print(f"  Manual (reference only):      {h['manual_reference_scenarios']}")
    if report.has_requirements:
        print(
            f"  Aligned → requirements:       "
            f"{h.get('generated_aligned_to_requirements', 0)} "
            f"({h.get('generated_requirement_alignment_pct', 0)}%)"
        )
        print(
            f"  Triangulated (manual + req.): "
            f"{h.get('generated_triangulated_count', 0)} "
            f"({h.get('triangulation_pct', 0)}%)"
        )
        print(f"  Requirement ACs (reference):  --- {h.get('requirement_acs', 0)}")
    print()

    if simple["highlights"]:
        print("  Highlights:")
        for line in simple["highlights"]:
            print(f"    - {line}")
        print()

    if simple["top_gaps"]:
        print("  Top gaps:")
        for line in simple["top_gaps"]:
            print(f"    - {line}")
        print()

    if simple["top_matches"]:
        print("  Top generated alignments → manual:")
        for m in simple["top_matches"]:
            manual = m.get("manual_scenario", m["your_scenario"])
            print(
                f"    - [{m['area']}/{m['type']}] {m['generated_scenario']!r}  →  "
                f"{manual!r}"
            )
        print()

    print("=" * 60)
    print("DETAILED REPORT (developers)")
    print("=" * 60)
    b = report.breakdown
    print()
    print(f"  Threshold:              {report.threshold:.2f}")
    print(f"  Method:                 {detailed['method']}")
    print()
    print(f"  OVERALL SCORE:          {b.overall_score:.1f}%")
    print()
    print("  Breakdown (weighted):")
    w = detailed["scoring_weights"]
    if report.has_requirements:
        rows = [
            ("Manual coverage (recall)", b.manual_recall_pct or b.behavior_coverage_pct,
             w.get("manual_recall")),
            ("Coverage efficiency", b.coverage_efficiency_pct,
             w.get("coverage_efficiency")),
            ("Suite precision", b.suite_precision_pct or b.generated_manual_alignment_pct,
             w.get("suite_precision", w.get("generated_manual_alignment"))),
            ("Actions in aligned pairs", b.action_coverage_pct,
             w.get("manual_action_from_pairs")),
            ("Positive paths in aligned pairs", b.positive_path_coverage_pct,
             w.get("manual_positive_from_pairs")),
            ("Negative paths in aligned pairs", b.negative_path_coverage_pct,
             w.get("manual_negative_from_pairs")),
            ("Stages in aligned pairs", b.workflow_stage_coverage_pct,
             w.get("manual_stage_from_pairs")),
            ("Manual features touched", b.feature_completeness_pct,
             w.get("manual_feature_from_pairs")),
            ("Requirement AC recall", b.requirement_ac_coverage_pct,
             w.get("requirement_recall")),
            ("Generated triangulated", b.triangulation_pct,
             w.get("generated_triangulation")),
        ]
    else:
        rows = [
            ("Manual coverage (recall)", b.manual_recall_pct or b.behavior_coverage_pct,
             w.get("manual_recall", w.get("behavior_coverage"))),
            ("Coverage efficiency", b.coverage_efficiency_pct,
             w.get("coverage_efficiency")),
            ("Suite precision", b.suite_precision_pct or b.generated_manual_alignment_pct,
             w.get("suite_precision", w.get("generated_manual_alignment"))),
            ("Actions in aligned pairs", b.action_coverage_pct,
             w.get("manual_action_from_pairs", w.get("action_coverage"))),
            ("Positive paths in aligned pairs", b.positive_path_coverage_pct,
             w.get("manual_positive_from_pairs", w.get("positive_path"))),
            ("Negative paths in aligned pairs", b.negative_path_coverage_pct,
             w.get("manual_negative_from_pairs", w.get("negative_path"))),
            ("Stages in aligned pairs", b.workflow_stage_coverage_pct,
             w.get("manual_stage_from_pairs", w.get("workflow_stage"))),
            ("Manual features touched", b.feature_completeness_pct,
             w.get("manual_feature_from_pairs", w.get("feature_completeness"))),
        ]
    for label, val, weight in rows:
        if weight is not None:
            print(f"    {label + ':':22} {val:.1f}%  (weight {weight})")
    print(f"    Granularity ratio:    {b.granularity_ratio:.2f}")
    print(f"    Manual Gherkin OK:    {b.golden_gherkin_compliance_pct:.1f}%")
    print(f"    Generated Gherkin OK: {b.generated_gherkin_compliance_pct:.1f}%")
    print()

    cov = detailed["coverage"]
    if cov["covered_actions"]:
        print(f"  Covered actions:   {', '.join(cov['covered_actions'])}")
    if cov["uncovered_actions"]:
        print(f"  Missing actions:   {', '.join(cov['uncovered_actions'])}")
    if cov["missing_stages"]:
        print(f"  Missing stages:    {', '.join(cov['missing_stages'])}")
    if cov["missing_features"]:
        print(f"  Missing features:  {', '.join(cov['missing_features'])}")
    print()

    print("  Why this score:")
    for line in b.explanation:
        print(f"    - {line}")
    print()

    if report.matched:
        print("  Generated → manual alignments:")
        for m in report.matched:
            acts = ", ".join(m.shared_actions) or "none"
            print(
                f"    - [{m.workflow_stage}/{m.intent}] {m.match_score:.0%}  "
                f"{m.generated_scenario!r} → {m.manual_scenario!r}"
            )
            print(f"      actions: {acts}")
            print(f"      why: {m.why_matched}")
        print()

    if report.extra_behaviors:
        print("  Generated not aligned → manual (nearest manual):")
        for m in report.extra_behaviors:
            near = (
                f" (nearest {m.best_near_match:.0%})"
                if m.best_near_match is not None else ""
            )
            nearest = f" -> {m.nearest_scenario!r}" if m.nearest_scenario else ""
            print(
                f"    - [{m.workflow_stage}/{m.intent}] {m.scenario!r}{nearest}{near}"
            )
            print(f"      actions: {', '.join(m.actions)}")
            print(f"      why: {m.why_missing}")
        print()

    if report.missing_behaviors:
        print("  Manual reference gaps (no aligned generated):")
        for m in report.missing_behaviors:
            near = (
                f" (nearest {m.best_near_match:.0%})"
                if m.best_near_match is not None else ""
            )
            nearest = f" -> {m.nearest_scenario!r}" if m.nearest_scenario else ""
            print(
                f"    - [{m.workflow_stage}/{m.intent}] {m.scenario!r}{nearest}{near}"
            )
            print(f"      actions: {', '.join(m.actions)}")
            print(f"      why: {m.why_missing}")
        print()

    if report.has_requirements and report.misaligned_generated_vs_requirements:
        print("  Generated not aligned → requirements:")
        for m in report.misaligned_generated_vs_requirements:
            near = (
                f" (nearest {m.best_near_match:.0%})"
                if m.best_near_match is not None else ""
            )
            nearest = f" -> {m.nearest_scenario!r}" if m.nearest_scenario else ""
            print(
                f"    - [{m.workflow_stage}/{m.intent}] {m.scenario!r}{nearest}{near}"
            )
            print(f"      why: {m.why_missing}")
        print()


if __name__ == "__main__":
    sys.exit(main())
