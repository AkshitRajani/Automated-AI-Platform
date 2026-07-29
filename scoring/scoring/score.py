"""
Behaviour-based scoring orchestrator — manual, requirements, and generated BDD.

Overall score is golden-first: manual recall and match quality dominate; suite
precision / coverage efficiency discourage pad-the-suite generators.
"""
from __future__ import annotations

from typing import List, Optional, Set, Union
from pathlib import Path

from .behavior_match import (
    action_coverage,
    feature_completeness,
    match_behaviors,
    path_coverage,
    profile_label_coverage,
    requirement_action_coverage,
    requirement_path_coverage,
    stage_coverage,
)
from .agent.context import profiling_context
from .agent.cache import collect_paths_from_source, fingerprint_paths
from .agent.config import resolve_profiling_mode
from .coverage_assist import filter_missing_after_credit, run_coverage_assist
from .integrity import build_integrity_report
from .compliance import check_suite
from .models import Scenario, ScoreBreakdown, ScoreReport
from .parse import load_features
from .requirements.parse import load_requirements, has_requirement_docs
from .requirements.profile import RequirementProfile, profile_requirements
from .triangulation import compute_triangulation, match_requirements_to_generated

# Golden-first weights with requirements (must sum to 1.0).
_WEIGHTS_FULL = {
    "manual_recall": 0.28,
    "manual_action": 0.10,
    "manual_positive": 0.06,
    "manual_negative": 0.08,
    "manual_stage": 0.04,
    "manual_feature": 0.04,
    "coverage_efficiency": 0.10,
    "suite_precision": 0.10,
    "requirement_recall": 0.12,
    "triangulation": 0.08,
}

# Same golden + discipline terms without req/tri, renormalized to 1.0.
_WEIGHTS_MANUAL_ONLY = {
    "manual_recall": 0.35,
    "manual_action": 0.125,
    "manual_positive": 0.075,
    "manual_negative": 0.10,
    "manual_stage": 0.05,
    "manual_feature": 0.05,
    "coverage_efficiency": 0.125,
    "suite_precision": 0.125,
}


def scoring_weights(has_requirements: bool) -> dict:
    """Public weight map for reports (stable keys for HTML/JSON)."""
    if has_requirements:
        return {
            "manual_recall": _WEIGHTS_FULL["manual_recall"],
            "manual_action_from_pairs": _WEIGHTS_FULL["manual_action"],
            "manual_positive_from_pairs": _WEIGHTS_FULL["manual_positive"],
            "manual_negative_from_pairs": _WEIGHTS_FULL["manual_negative"],
            "manual_stage_from_pairs": _WEIGHTS_FULL["manual_stage"],
            "manual_feature_from_pairs": _WEIGHTS_FULL["manual_feature"],
            "coverage_efficiency": _WEIGHTS_FULL["coverage_efficiency"],
            "suite_precision": _WEIGHTS_FULL["suite_precision"],
            "requirement_recall": _WEIGHTS_FULL["requirement_recall"],
            "generated_triangulation": _WEIGHTS_FULL["triangulation"],
            # Legacy aliases (reports / older readers).
            "generated_manual_alignment": _WEIGHTS_FULL["suite_precision"],
            "behavior_coverage": _WEIGHTS_FULL["manual_recall"],
        }
    return {
        "manual_recall": _WEIGHTS_MANUAL_ONLY["manual_recall"],
        "manual_action_from_pairs": _WEIGHTS_MANUAL_ONLY["manual_action"],
        "manual_positive_from_pairs": _WEIGHTS_MANUAL_ONLY["manual_positive"],
        "manual_negative_from_pairs": _WEIGHTS_MANUAL_ONLY["manual_negative"],
        "manual_stage_from_pairs": _WEIGHTS_MANUAL_ONLY["manual_stage"],
        "manual_feature_from_pairs": _WEIGHTS_MANUAL_ONLY["manual_feature"],
        "coverage_efficiency": _WEIGHTS_MANUAL_ONLY["coverage_efficiency"],
        "suite_precision": _WEIGHTS_MANUAL_ONLY["suite_precision"],
        "generated_manual_alignment": _WEIGHTS_MANUAL_ONLY["suite_precision"],
        "behavior_coverage": _WEIGHTS_MANUAL_ONLY["manual_recall"],
    }


def _coverage_efficiency_pct(covered_manual: int, n_gen: int) -> float:
    """covered_manual / n_gen scaled to 0–100 with soft cap (rewards lean coverage)."""
    if n_gen <= 0:
        return 0.0
    return min(100.0, (covered_manual / n_gen) * 100.0)


def _suite_precision_pct(
    n_matched: int,
    n_gen: int,
    redundant: Set[str],
    matched_gen_names: Set[str],
) -> float:
    """Aligned generated / n_gen, treating agent-flagged redundant matches as noise."""
    if n_gen <= 0:
        return 0.0
    redundant_matched = len(redundant & matched_gen_names)
    effective = max(0, n_matched - redundant_matched)
    return effective / n_gen * 100.0


def score(
    golden: Union[str, List[Scenario]],
    generated: Union[str, List[Scenario]],
    threshold: float = 0.45,
    requirements: Optional[
        Union[str, List[str], List[RequirementProfile]]
    ] = None,
    profiling_mode: Optional[str] = None,
    *,
    coverage_assist_invoke: Optional[object] = None,
) -> ScoreReport:
    """Score generated BDD against manual (ground truth) and optional requirement docs.

    Manual tests are always treated as correct. Overall score is golden-first:
    manual recall dominates; suite precision and coverage efficiency discourage
    inflated generated suites that do not cover more golden behaviour.

    ``requirements`` may be a folder/file path, a list of folder/file paths (e.g. explicit
    requirements folder plus docs sitting next to manual ``.feature`` files), or a
    pre-built list of ``RequirementProfile`` objects. When the manual/golden tree contains
    ``.md`` / ``.json`` docs, those are included automatically.
    """
    manual = golden if isinstance(golden, list) else load_features(golden)
    gen = generated if isinstance(generated, list) else load_features(generated)

    golden_path = str(golden) if isinstance(golden, (str, Path)) else None
    generated_path = str(generated) if isinstance(generated, (str, Path)) else None

    prebuilt_profiles = (
        isinstance(requirements, list)
        and bool(requirements)
        and not isinstance(requirements[0], str)
    )

    req_path_list: List[str] = []
    if prebuilt_profiles:
        pass
    elif isinstance(requirements, list):
        req_path_list = [str(p) for p in requirements]
    elif isinstance(requirements, (str, Path)):
        as_str = str(requirements).strip()
        if as_str:
            req_path_list = [as_str]

    if golden_path and has_requirement_docs(golden_path) and golden_path not in req_path_list:
        req_path_list.append(golden_path)

    requirements_path = req_path_list[0] if req_path_list else None

    mode = resolve_profiling_mode(profiling_mode)
    strict_matching = mode == "agent"
    fingerprints: dict = {}
    if golden_path:
        fingerprints["manual"] = fingerprint_paths(collect_paths_from_source(golden_path))
    if generated_path:
        fingerprints["generated"] = fingerprint_paths(collect_paths_from_source(generated_path))
    for i, rp in enumerate(req_path_list):
        key = "requirements" if i == 0 else f"requirements_{i}"
        fingerprints[key] = fingerprint_paths(collect_paths_from_source(rp))

    with profiling_context(mode, fingerprints=fingerprints):
        req_profiles: List[RequirementProfile] = []
        if prebuilt_profiles:
            req_profiles = requirements  # type: ignore[assignment]
        elif req_path_list:
            docs = load_requirements(
                req_path_list if len(req_path_list) > 1 else req_path_list[0]
            )
            req_profiles = profile_requirements(docs, source=req_path_list[0])

        matches, missing, extra, manual_profiles, gen_profiles = match_behaviors(
            manual,
            gen,
            threshold,
            manual_source=golden_path,
            generated_source=generated_path,
        )

        assist = run_coverage_assist(
            manual_profiles=manual_profiles,
            gen_profiles=gen_profiles,
            matches=matches,
            missing=missing,
            profiling_mode=mode,
            invoke_fn=coverage_assist_invoke,  # type: ignore[arg-type]
        )

    missing = filter_missing_after_credit(missing, assist.credited_manual_scenarios)

    req_strategy = ""
    if req_path_list and mode == "agent":
        from .requirements.agent_profile import requirement_profiling_strategy
        docs = load_requirements(
            req_path_list if len(req_path_list) > 1 else req_path_list[0]
        )
        req_strategy = requirement_profiling_strategy(docs)

    integrity = build_integrity_report(
        manual=golden_path or manual,
        generated=generated_path or gen,
        requirements=req_path_list if len(req_path_list) > 1 else requirements_path,
        req_profiles_count=len(req_profiles),
        profiling_mode=mode,
        strict_matching=strict_matching,
        requirement_strategy=req_strategy,
    )

    matched_manual_names = {m.manual_scenario for m in matches} | set(
        assist.credited_manual_scenarios
    )
    matched_gen_names = {m.generated_scenario for m in matches}

    behavior_cov = profile_label_coverage(manual_profiles, matched_manual_names)
    action_cov, covered_actions, all_actions = action_coverage(manual_profiles, matches)
    uncovered_actions = sorted(all_actions - set(covered_actions))
    pos_cov = path_coverage(manual_profiles, {m.manual_scenario for m in matches}, "positive")
    neg_cov = path_coverage(manual_profiles, {m.manual_scenario for m in matches}, "negative")
    stage_cov, covered_stages, missing_stages = stage_coverage(manual_profiles, matches)
    feat_cov, missing_features = feature_completeness(manual, matches)
    if assist.credited_manual_scenarios:
        manual_files = {s.feature_file for s in manual}
        covered_files = {s.feature_file for s in manual if s.name in matched_manual_names}
        missing_features = sorted(manual_files - covered_files)
        feat_cov = (
            len(covered_files) / len(manual_files) * 100.0 if manual_files else 100.0
        )

    n_manual = len(manual)
    n_gen = len(gen)
    granularity = (n_gen / n_manual) if n_manual else 0.0
    n_matched = len(matches)
    covered_manual_count = len(matched_manual_names)
    suite_precision = _suite_precision_pct(
        n_matched, n_gen, assist.redundant_generated_scenarios, matched_gen_names,
    )
    coverage_efficiency = _coverage_efficiency_pct(covered_manual_count, n_gen)
    manual_recall = behavior_cov
    gen_unaligned_manual = n_gen - n_matched

    golden_compliance = check_suite(manual)
    gen_compliance = check_suite(gen)

    req_matches = []
    missing_req: List = []
    misaligned_req: List = []
    req_ac_cov = 0.0
    req_neg_cov = 0.0
    req_action_cov = 0.0
    triangulation_rows = []
    unit_trace = []
    triangulation_pct = 0.0
    requirement_only_gaps: List[str] = []
    gen_req_align = 0.0
    gen_req_count = 0
    gen_unaligned_req = n_gen
    gen_tri_count = 0

    has_requirements = bool(req_profiles)

    if has_requirements:
        req_matches, missing_req, misaligned_req = match_requirements_to_generated(
            req_profiles, gen_profiles, threshold,
        )
        matched_ac_labels = {m.requirement_ac for m in req_matches}
        req_ac_cov = (
            len(req_matches) / len(req_profiles) * 100.0 if req_profiles else 100.0
        )
        req_neg_cov = requirement_path_coverage(
            req_profiles, matched_ac_labels, negative_only=True,
        )
        req_pos_cov = requirement_path_coverage(
            req_profiles, matched_ac_labels, negative_only=False,
        )
        req_action_cov, _, _ = requirement_action_coverage(
            [rp.to_behavior_profile() for rp in req_profiles],
            req_matches,
        )

        triangulation_rows, triangulation_pct, unit_trace = compute_triangulation(
            matches,
            req_matches,
            manual_profiles,
            req_profiles,
            gen_profiles,
            threshold,
        )
        gen_tri_count = len({t.generated_scenario for t in triangulation_rows})
        gen_req_matched = {m.generated_scenario for m in req_matches}
        gen_req_count = len(gen_req_matched)
        gen_req_align = (gen_req_count / n_gen * 100.0) if n_gen else 0.0
        gen_unaligned_req = n_gen - gen_req_count

        matched_gen = {m.generated_scenario for m in matches}
        requirement_only_gaps = [
            rm.requirement_ac for rm in req_matches
            if rm.generated_scenario not in matched_gen
        ]

        w = _WEIGHTS_FULL
        overall = (
            w["manual_recall"] * manual_recall
            + w["manual_action"] * action_cov
            + w["manual_positive"] * pos_cov
            + w["manual_negative"] * neg_cov
            + w["manual_stage"] * stage_cov
            + w["manual_feature"] * feat_cov
            + w["coverage_efficiency"] * coverage_efficiency
            + w["suite_precision"] * suite_precision
            + w["requirement_recall"] * req_ac_cov
            + w["triangulation"] * triangulation_pct
        )
        scoring_mode = f"golden_first_manual_requirements_{mode}"
        _ = req_pos_cov
    else:
        w = _WEIGHTS_MANUAL_ONLY
        overall = (
            w["manual_recall"] * manual_recall
            + w["manual_action"] * action_cov
            + w["manual_positive"] * pos_cov
            + w["manual_negative"] * neg_cov
            + w["manual_stage"] * stage_cov
            + w["manual_feature"] * feat_cov
            + w["coverage_efficiency"] * coverage_efficiency
            + w["suite_precision"] * suite_precision
        )
        scoring_mode = f"golden_first_manual_only_{mode}"

    explanation = _build_explanation(
        behavior_cov=manual_recall,
        action_cov=action_cov,
        pos_cov=pos_cov,
        neg_cov=neg_cov,
        stage_cov=stage_cov,
        feat_cov=feat_cov,
        granularity=granularity,
        matches=matches,
        extra=extra,
        uncovered_actions=uncovered_actions,
        missing_stages=missing_stages,
        missing_features=missing_features,
        overall=overall,
        has_requirements=has_requirements,
        gen_manual_align=suite_precision,
        gen_req_align=gen_req_align,
        gen_tri_count=gen_tri_count,
        gen_unaligned_manual=gen_unaligned_manual,
        gen_unaligned_req=gen_unaligned_req,
        n_gen=n_gen,
        req_neg_cov=req_neg_cov,
        req_matches=req_matches,
        triangulation_pct=triangulation_pct,
        scoring_mode=scoring_mode,
        coverage_efficiency=coverage_efficiency,
        req_ac_cov=req_ac_cov,
        assist_notes=assist.notes,
    )

    breakdown = ScoreBreakdown(
        behavior_coverage_pct=manual_recall,
        action_coverage_pct=action_cov,
        positive_path_coverage_pct=pos_cov,
        negative_path_coverage_pct=neg_cov,
        workflow_stage_coverage_pct=stage_cov,
        feature_completeness_pct=feat_cov,
        granularity_ratio=granularity,
        golden_gherkin_compliance_pct=golden_compliance.compliance_pct,
        generated_gherkin_compliance_pct=gen_compliance.compliance_pct,
        overall_score=overall,
        explanation=explanation,
        requirement_ac_coverage_pct=req_ac_cov,
        requirement_negative_coverage_pct=req_neg_cov,
        requirement_action_coverage_pct=req_action_cov,
        triangulation_pct=triangulation_pct,
        scoring_mode=scoring_mode,
        generated_manual_alignment_pct=suite_precision,
        generated_requirement_alignment_pct=gen_req_align,
        generated_triangulated_count=gen_tri_count,
        manual_recall_pct=manual_recall,
        coverage_efficiency_pct=coverage_efficiency,
        suite_precision_pct=suite_precision,
        agent_credited_manual_count=len(assist.credited_manual_scenarios),
        redundant_generated_count=len(assist.redundant_generated_scenarios),
    )

    return ScoreReport(
        threshold=threshold,
        manual_scenarios=n_manual,
        generated_scenarios=n_gen,
        matched_behaviors=n_matched,
        breakdown=breakdown,
        matched=sorted(matches, key=lambda m: m.match_score, reverse=True),
        missing_behaviors=missing,
        extra_behaviors=extra,
        covered_actions=sorted(covered_actions),
        uncovered_actions=uncovered_actions,
        covered_stages=covered_stages,
        missing_stages=missing_stages,
        missing_features=missing_features,
        golden_compliance=golden_compliance.to_dict(),
        generated_compliance=gen_compliance.to_dict(),
        has_requirements=has_requirements,
        requirement_acs=len(req_profiles),
        matched_requirements=len(req_matches),
        requirement_matches=sorted(req_matches, key=lambda m: m.match_score, reverse=True),
        missing_requirements=missing_req,
        misaligned_generated_vs_requirements=misaligned_req,
        requirement_only_gaps=requirement_only_gaps,
        triangulation=triangulation_rows,
        unit_traceability=unit_trace,
        generated_aligned_to_manual=n_matched,
        generated_aligned_to_requirements=gen_req_count,
        generated_unaligned_manual=gen_unaligned_manual,
        generated_unaligned_requirements=gen_unaligned_req,
        input_integrity=integrity.to_dict(),
    )


def _build_explanation(
    *,
    behavior_cov: float,
    action_cov: float,
    pos_cov: float,
    neg_cov: float,
    stage_cov: float,
    feat_cov: float,
    granularity: float,
    matches: list,
    extra: list,
    uncovered_actions: List[str],
    missing_stages: List[str],
    missing_features: List[str],
    overall: float,
    has_requirements: bool,
    gen_manual_align: float,
    gen_req_align: float,
    gen_tri_count: int,
    gen_unaligned_manual: int,
    gen_unaligned_req: int,
    n_gen: int,
    req_neg_cov: float,
    req_matches: list,
    triangulation_pct: float,
    scoring_mode: str,
    coverage_efficiency: float = 0.0,
    req_ac_cov: float = 0.0,
    assist_notes: Optional[List[str]] = None,
) -> List[str]:
    lines = [
        f"Overall score {overall:.1f}% ({scoring_mode}): golden-first — "
        f"{behavior_cov:.0f}% of manual scenarios covered, "
        f"coverage efficiency {coverage_efficiency:.0f}%, "
        f"suite precision {gen_manual_align:.0f}%.",
        "Overall favours covering golden tests efficiently, not padding the generated suite.",
    ]
    if has_requirements:
        lines.append(
            f"Requirements (supporting): {req_ac_cov:.0f}% requirement AC recall; "
            f"{gen_tri_count} generated scenario(s) ({triangulation_pct:.0f}%) triangulated "
            f"with both manual and requirements."
        )

    if assist_notes:
        lines.extend(assist_notes)

    if matches:
        top = matches[0]
        lines.append(
            f"Strongest generated alignment: '{top.generated_scenario}' ↔ "
            f"manual '{top.manual_scenario}' ({top.match_score:.0%})."
        )

    if has_requirements and req_matches:
        rt = req_matches[0]
        lines.append(
            f"Strongest generated ↔ requirement: '{rt.generated_scenario}' ↔ "
            f"'{rt.requirement_ac}' ({rt.match_score:.0%})."
        )

    if gen_unaligned_manual:
        lines.append(
            f"{gen_unaligned_manual} generated scenario(s) do not align with any manual test."
        )

    if has_requirements and gen_unaligned_req:
        lines.append(
            f"{gen_unaligned_req} generated scenario(s) do not align with any requirement AC."
        )

    if uncovered_actions:
        lines.append(
            f"Manual business actions still missing from aligned generated tests: "
            f"{', '.join(uncovered_actions)}."
        )

    lines.append(
        f"Reference context: granularity ratio (generated/manual) is {granularity:.2f}."
    )
    _ = (
        action_cov, pos_cov, neg_cov, stage_cov, feat_cov, extra, n_gen,
        req_neg_cov, gen_req_align, missing_stages, missing_features,
    )
    return lines
