"""
Build simplified (stakeholder) and detailed (developer) report views.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .models import ScoreReport


def _verdict(
    overall: float,
    gen_manual: float,
    gen_req: float,
    triangulation: float,
    *,
    has_requirements: bool = False,
    manual_recall: float = 0.0,
) -> str:
    if overall >= 75:
        level = "Strong golden coverage"
    elif overall >= 50:
        level = "Partial golden coverage"
    else:
        level = "Low golden coverage"
    parts = [level, f"{manual_recall:.0f}% of manual tests covered"]
    parts.append(f"suite precision {gen_manual:.0f}%")
    if has_requirements:
        parts.append(f"requirement AC recall in breakdown; triangulation {triangulation:.0f}%")
        _ = gen_req
    return " — ".join(parts) + "."


def build_simplified(report: "ScoreReport") -> dict:
    """Stakeholder summary — golden-first coverage of manual (+ supporting requirements)."""
    b = report.breakdown
    n_extra = len(report.extra_behaviors)
    n_extra_req = report.generated_unaligned_requirements

    gen_manual = b.suite_precision_pct or b.generated_manual_alignment_pct
    gen_req = b.generated_requirement_alignment_pct
    gen_tri = b.triangulation_pct
    manual_recall = b.manual_recall_pct or b.behavior_coverage_pct
    efficiency = b.coverage_efficiency_pct

    summary = (
        f"Golden-first overall {b.overall_score:.0f}%: "
        f"{manual_recall:.0f}% of manual scenarios covered, "
        f"coverage efficiency {efficiency:.0f}%, "
        f"suite precision {gen_manual:.0f}% "
        f"({report.generated_aligned_to_manual}/{report.generated_scenarios} generated aligned)."
    )
    if report.has_requirements:
        summary += (
            f" Requirement AC recall {b.requirement_ac_coverage_pct:.0f}%; "
            f"{b.generated_triangulated_count} triangulated ({gen_tri:.0f}%)."
        )

    highlights: List[str] = [
        f"Manual coverage (recall): {manual_recall:.0f}% "
        f"({report.matched_behaviors + b.agent_credited_manual_count}"
        f"/{report.manual_scenarios} behaviours covered)",
        f"Coverage efficiency: {efficiency:.0f}% "
        f"(manuals covered per generated scenario, capped at 100%)",
        f"Suite precision: {gen_manual:.0f}% "
        f"({report.generated_aligned_to_manual}/{report.generated_scenarios})",
    ]
    if report.has_requirements:
        highlights.append(
            f"Requirement AC recall: {b.requirement_ac_coverage_pct:.0f}% "
            f"({report.matched_requirements}/{report.requirement_acs})"
        )
        highlights.append(
            f"Generated fully triangulated (manual + requirement): "
            f"{b.generated_triangulated_count} scenarios ({gen_tri:.0f}%)"
        )
    highlights.append(
        f"Manual reference still uncovered: {len(report.missing_behaviors)} manual scenario(s) "
        f"have no aligned generated test"
    )
    if report.uncovered_actions:
        highlights.append(
            f"Business actions in aligned tests cover {b.action_coverage_pct:.0f}% of manual actions"
        )

    top_gaps: List[str] = []
    if n_extra > 0:
        top_gaps.append(
            f"{n_extra} generated scenario(s) not aligned with any manual test"
        )
    if report.has_requirements and n_extra_req > 0:
        top_gaps.append(
            f"{n_extra_req} generated scenario(s) not aligned with any requirement AC"
        )
    if report.missing_behaviors:
        top_gaps.append(
            f"{len(report.missing_behaviors)} manual test(s) still have no aligned generated scenario"
        )
    if report.has_requirements and report.missing_requirements:
        top_gaps.append(
            f"{len(report.missing_requirements)} requirement AC(s) have no aligned generated scenario"
        )
    if report.missing_stages:
        top_gaps.append(
            f"Manual stages not reflected in aligned generated tests: "
            f"{', '.join(report.missing_stages)}"
        )

    top_matches = [
        {
            "generated_scenario": m.generated_scenario,
            "manual_scenario": m.manual_scenario,
            "your_scenario": m.manual_scenario,
            "area": m.workflow_stage,
            "type": m.intent,
            "match_score": m.match_score,
        }
        for m in report.matched[:5]
    ]

    top_triangulation = [
        t.to_dict() if hasattr(t, "to_dict") else t
        for t in report.triangulation[:5]
    ]

    headline = {
        "generated_scored_scenarios": report.generated_scenarios,
        "generated_aligned_to_manual": report.generated_aligned_to_manual,
        "generated_manual_alignment_pct": round(gen_manual, 1),
        "generated_unaligned_manual": report.generated_unaligned_manual,
        "manual_reference_scenarios": report.manual_scenarios,
        "manual_recall_pct": round(manual_recall, 1),
        "coverage_efficiency_pct": round(efficiency, 1),
        "suite_precision_pct": round(gen_manual, 1),
        # legacy keys
        "your_test_scenarios": report.manual_scenarios,
        "generated_test_scenarios": report.generated_scenarios,
        "matched": report.generated_aligned_to_manual,
        "behaviour_coverage_pct": round(b.behavior_coverage_pct, 1),
    }
    if report.has_requirements:
        headline["requirement_acs"] = report.requirement_acs
        headline["generated_aligned_to_requirements"] = report.generated_aligned_to_requirements
        headline["generated_requirement_alignment_pct"] = round(gen_req, 1)
        headline["generated_unaligned_requirements"] = report.generated_unaligned_requirements
        headline["generated_triangulated_count"] = b.generated_triangulated_count
        headline["triangulation_pct"] = round(gen_tri, 1)
        headline["requirement_ac_coverage_pct"] = round(b.requirement_ac_coverage_pct, 1)

    return {
        "summary": summary,
        "overall_score_pct": round(b.overall_score, 1),
        "headline": headline,
        "highlights": highlights,
        "top_gaps": top_gaps[:8],
        "top_matches": top_matches,
        "top_triangulation": top_triangulation,
        "verdict": _verdict(
            b.overall_score, gen_manual, gen_req, gen_tri,
            has_requirements=report.has_requirements,
            manual_recall=manual_recall,
        ),
        "scoring_mode": b.scoring_mode,
    }


def build_detailed(report: "ScoreReport") -> dict:
    """Developer view — generated alignment metrics and pairings."""
    b = report.breakdown
    weights = _scoring_weights(report.has_requirements)
    method = (
        "Golden-first scoring: overall emphasises how much of the manual (golden) suite is "
        "covered and how efficiently, plus quality of matched pairs. Suite precision "
        "(aligned generated / generated count) is secondary so padded suites do not win by "
        "mimicry alone. Requirements contribute as supporting recall and triangulation. "
        "Matching uses workflow stage, intent, and shared business actions."
        if report.has_requirements
        else (
            "Golden-first scoring: overall emphasises manual (golden) coverage and "
            "efficiency, with suite precision as a secondary discipline term. Matching uses "
            "workflow stage, intent, and shared business actions."
        )
    )

    payload = {
        "threshold": report.threshold,
        "scoring_mode": b.scoring_mode,
        "inputs": {
            "generated_scored_scenarios": report.generated_scenarios,
            "manual_reference_scenarios": report.manual_scenarios,
            "requirement_acs": report.requirement_acs,
            "has_requirements": report.has_requirements,
        },
        "generated_alignment": {
            "aligned_to_manual": report.generated_aligned_to_manual,
            "unaligned_to_manual": report.generated_unaligned_manual,
            "manual_alignment_pct": b.generated_manual_alignment_pct,
            "suite_precision_pct": b.suite_precision_pct,
            "aligned_to_requirements": report.generated_aligned_to_requirements,
            "unaligned_to_requirements": report.generated_unaligned_requirements,
            "requirement_alignment_pct": b.generated_requirement_alignment_pct,
            "triangulated_count": b.generated_triangulated_count,
            "triangulation_pct": b.triangulation_pct,
        },
        "reference_coverage": {
            "manual_scenarios_with_generated_pair": report.matched_behaviors,
            "manual_coverage_pct": b.behavior_coverage_pct,
            "manual_recall_pct": b.manual_recall_pct,
            "coverage_efficiency_pct": b.coverage_efficiency_pct,
            "agent_credited_manual_count": b.agent_credited_manual_count,
            "requirement_acs_with_generated_pair": report.matched_requirements,
            "requirement_ac_coverage_pct": b.requirement_ac_coverage_pct,
        },
        "breakdown": b.to_dict(),
        "coverage": {
            "covered_actions": report.covered_actions,
            "uncovered_actions": report.uncovered_actions,
            "covered_stages": report.covered_stages,
            "missing_stages": report.missing_stages,
            "missing_features": report.missing_features,
        },
        "generated_manual_matches": [m.to_dict() for m in report.matched],
        "generated_not_aligned_manual": [m.to_dict() for m in report.extra_behaviors],
        "manual_without_generated": [m.to_dict() for m in report.missing_behaviors],
        "matched": [m.to_dict() for m in report.matched],
        "missing_behaviors": [m.to_dict() for m in report.missing_behaviors],
        "extra_behaviors": [m.to_dict() for m in report.extra_behaviors],
        "gherkin_compliance": {
            "manual": report.golden_compliance,
            "generated": report.generated_compliance,
        },
        "scoring_weights": weights,
        "method": method,
    }

    if report.has_requirements:
        payload["generated_requirement_matches"] = [
            m.to_dict() for m in report.requirement_matches
        ]
        payload["generated_not_aligned_requirements"] = [
            m.to_dict() for m in report.misaligned_generated_vs_requirements
        ]
        payload["requirement_acs_without_generated"] = [
            m.to_dict() for m in report.missing_requirements
        ]
        payload["triangulation"] = [
            t.to_dict() if hasattr(t, "to_dict") else t for t in report.triangulation
        ]
        payload["unit_traceability"] = [
            u.to_dict() if hasattr(u, "to_dict") else u for u in report.unit_traceability
        ]

    return payload


def _scoring_weights(has_requirements: bool) -> dict:
    from .score import scoring_weights
    return scoring_weights(has_requirements)
