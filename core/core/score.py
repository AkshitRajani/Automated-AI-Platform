"""
BDD behaviour scoring — compare generated features against golden (manual) BDD.

Runs after the coding agent has written ``features/``. Reads only Gherkin files —
no source code, Bedrock, or KB required.

    golden_bdd/<app_id>/features  vs  <workspace>/features
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import ConfigError, CoreConfig


@dataclass
class ScoreResult:
    app_id: str
    golden_dir: str
    generated_dir: str
    report_json: str
    report_html: str
    overall_score: float
    behavior_coverage_pct: float
    matched_behaviors: int
    manual_scenarios: int
    report: object


def resolve_golden_dir(cfg: CoreConfig, app_id: str,
                       golden_dir: Optional[str] = None) -> str:
    """Locate golden BDD for an app under ``CORE_GOLDEN_BDD_ROOT``."""
    if golden_dir:
        path = os.path.abspath(golden_dir)
        if not os.path.isdir(path):
            raise ConfigError(f"golden BDD path is not a directory: {path}")
        return path

    root = cfg.golden_bdd_root
    if not root:
        raise ConfigError(
            "Golden BDD location not set. Pass --golden, or set "
            "CORE_GOLDEN_BDD_ROOT in .env (e.g. golden_bdd)."
        )

    candidates = [
        os.path.join(root, app_id, "features"),
        os.path.join(root, app_id),
        root,
    ]
    for path in candidates:
        if os.path.isdir(path) and any(Path(path).rglob("*.feature")):
            return os.path.abspath(path)

    raise ConfigError(
        f"No golden .feature files found for app_id={app_id!r} under {root}. "
        f"Expected {root}/{app_id}/features/ or pass --golden explicitly."
    )


def resolve_generated_dir(generated_dir: str) -> str:
    path = os.path.abspath(generated_dir)
    if not os.path.isdir(path):
        raise ConfigError(f"generated BDD path is not a directory: {path}")
    if not any(Path(path).rglob("*.feature")):
        raise ConfigError(
            f"No .feature files under {path}. Run the coding agent first "
            f"or pass --generated pointing at its features/ output."
        )
    return path


def score_generated(
    app_id: str,
    generated_dir: str,
    cfg: CoreConfig,
    trace,
    *,
    golden_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    threshold: Optional[float] = None,
) -> ScoreResult:
    """Score generated BDD against golden reference; write JSON + HTML reports."""
    try:
        from scoring import score, write_html
    except ImportError as exc:
        raise ConfigError(
            "scoring package not on PYTHONPATH. Add the repo's scoring/ folder."
        ) from exc

    golden = resolve_golden_dir(cfg, app_id, golden_dir=golden_dir)
    generated = resolve_generated_dir(generated_dir)
    out = os.path.abspath(output_dir or cfg.score_output_dir or os.getcwd())
    os.makedirs(out, exist_ok=True)

    thresh = threshold if threshold is not None else cfg.scoring_threshold
    json_path = os.path.join(out, "score_report.json")
    html_path = os.path.join(out, "score_report.html")

    with trace.span("score", data={
        "app_id": app_id,
        "golden": golden,
        "generated": generated,
        "threshold": thresh,
    }) as span:
        with trace.span("scoring.run"):
            report = score(golden=golden, generated=generated, threshold=thresh)

        with trace.span("scoring.write_reports"):
            import json
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump(report.to_dict(), handle, indent=2)
                handle.write("\n")
            write_html(report, html_path, title=f"BDD Score - {app_id}")

        span.log(
            "scoring complete",
            overall_score=report.breakdown.overall_score,
            behavior_coverage_pct=report.breakdown.behavior_coverage_pct,
            matched=report.matched_behaviors,
            report_json=json_path,
            report_html=html_path,
        )

    return ScoreResult(
        app_id=app_id,
        golden_dir=golden,
        generated_dir=generated,
        report_json=json_path,
        report_html=html_path,
        overall_score=report.breakdown.overall_score,
        behavior_coverage_pct=report.breakdown.behavior_coverage_pct,
        matched_behaviors=report.matched_behaviors,
        manual_scenarios=report.manual_scenarios,
        report=report,
    )
