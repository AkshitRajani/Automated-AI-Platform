"""
Match scenarios by extracted business behaviour — not sentence similarity.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple

from .behavior import BehaviorProfile, behavior_match_score, profile_suite
from .models import BehaviorMatch, MissingBehavior, Scenario


def match_behaviors(
    manual: Sequence[Scenario],
    generated: Sequence[Scenario],
    threshold: float,
    *,
    manual_source: Optional[str] = None,
    generated_source: Optional[str] = None,
) -> Tuple[
    List[BehaviorMatch],
    List[MissingBehavior],
    List[MissingBehavior],
    List[BehaviorProfile],
    List[BehaviorProfile],
]:
    manual_profiles = profile_suite(manual, source=manual_source, kind="manual")
    generated_profiles = profile_suite(generated, source=generated_source, kind="generated")
    matches, missing, extra, _, _ = match_profile_sets(
        manual_profiles,
        generated_profiles,
        threshold,
        reference_side="manual",
        candidate_side="generated",
    )
    return matches, missing, extra, manual_profiles, generated_profiles


def match_profile_sets(
    reference_profiles: Sequence[BehaviorProfile],
    candidate_profiles: Sequence[BehaviorProfile],
    threshold: float,
    *,
    reference_side: str = "manual",
    candidate_side: str = "generated",
) -> Tuple[
    List[BehaviorMatch],
    List[MissingBehavior],
    List[MissingBehavior],
    List[BehaviorProfile],
    List[BehaviorProfile],
]:
    """Greedy 1:1 behaviour matching between two profile sets."""
    candidates: List[Tuple[float, dict, int, int]] = []
    best_ref: Dict[int, float] = {i: 0.0 for i in range(len(reference_profiles))}
    best_cand: Dict[int, float] = {j: 0.0 for j in range(len(candidate_profiles))}
    best_ref_partner: Dict[int, int] = {i: -1 for i in range(len(reference_profiles))}
    best_cand_partner: Dict[int, int] = {j: -1 for j in range(len(candidate_profiles))}

    for i, rp in enumerate(reference_profiles):
        for j, cp in enumerate(candidate_profiles):
            score, detail = behavior_match_score(rp, cp)
            candidates.append((score, detail, i, j))
            if score > best_ref[i]:
                best_ref[i] = score
                best_ref_partner[i] = j
            if score > best_cand[j]:
                best_cand[j] = score
                best_cand_partner[j] = i

    candidates.sort(key=lambda row: row[0], reverse=True)

    used_ref: Set[int] = set()
    used_cand: Set[int] = set()
    matches: List[BehaviorMatch] = []

    for score, detail, i, j in candidates:
        if score < threshold:
            break
        if i in used_ref or j in used_cand:
            continue
        rp, cp = reference_profiles[i], candidate_profiles[j]
        used_ref.add(i)
        used_cand.add(j)
        matches.append(BehaviorMatch(
            manual_scenario=rp.scenario,
            generated_scenario=cp.scenario,
            manual_feature=rp.feature_name,
            generated_feature=cp.feature_name,
            workflow_stage=rp.workflow_stage,
            intent=rp.intent,
            shared_actions=list(detail.get("shared_actions", [])),
            shared_outcomes=list(detail.get("shared_outcomes", [])),
            match_score=score,
            why_matched=detail.get("why", ""),
            reference_side=reference_side,
            candidate_side=candidate_side,
        ))

    missing_ref: List[MissingBehavior] = []
    for i, rp in enumerate(reference_profiles):
        if i in used_ref:
            continue
        best = best_ref[i]
        why = _why_missing_ref(rp, best, reference_side, candidate_side)
        partner_j = best_ref_partner[i]
        nearest_cp = (
            candidate_profiles[partner_j]
            if partner_j >= 0 and best > 0 else None
        )
        missing_ref.append(MissingBehavior(
            scenario=rp.scenario,
            feature_file=rp.feature_file,
            workflow_stage=rp.workflow_stage,
            intent=rp.intent,
            actions=sorted(rp.actions),
            side=reference_side,
            best_near_match=round(best, 3) if best > 0 else None,
            nearest_scenario=nearest_cp.scenario if nearest_cp else None,
            nearest_feature_file=nearest_cp.feature_file if nearest_cp else None,
            why_missing=why,
        ))

    extra_cand: List[MissingBehavior] = []
    for j, cp in enumerate(candidate_profiles):
        if j in used_cand:
            continue
        best = best_cand[j]
        partner_i = best_cand_partner[j]
        nearest_rp = (
            reference_profiles[partner_i]
            if partner_i >= 0 and best > 0 else None
        )
        why = _why_extra_cand(
            cp, best,
            nearest_rp.scenario if nearest_rp else None,
            reference_side,
            candidate_side,
        )
        extra_cand.append(MissingBehavior(
            scenario=cp.scenario,
            feature_file=cp.feature_file,
            workflow_stage=cp.workflow_stage,
            intent=cp.intent,
            actions=sorted(cp.actions),
            side=candidate_side,
            best_near_match=round(best, 3) if best > 0 else None,
            nearest_scenario=nearest_rp.scenario if nearest_rp else None,
            nearest_feature_file=nearest_rp.feature_file if nearest_rp else None,
            why_missing=why,
        ))

    return matches, missing_ref, extra_cand, reference_profiles, candidate_profiles


def _why_missing_ref(
    profile: BehaviorProfile,
    best_score: float,
    reference_side: str,
    candidate_side: str,
) -> str:
    if reference_side == "manual":
        return _why_missing_manual(profile, best_score)
    if reference_side == "requirement":
        if best_score <= 0:
            return (
                f"Requirement AC not covered by generated BDD — no scenario in stage "
                f"'{profile.workflow_stage}' with actions {sorted(profile.actions)}"
            )
        if best_score < 0.5:
            return (
                f"Requirement AC not covered — nearest generated scenario only "
                f"{best_score:.0%} aligned"
            )
        return (
            f"Requirement AC not covered — nearest generated {best_score:.0%} "
            f"aligned but below threshold"
        )
    return f"{reference_side} behaviour not covered by {candidate_side} ({best_score:.0%})"


def _why_missing_manual(profile: BehaviorProfile, best_score: float) -> str:
    if best_score <= 0:
        return (
            f"Correct manual test not covered — no generated scenario in stage "
            f"'{profile.workflow_stage}' with actions {sorted(profile.actions)}"
        )
    if best_score < 0.5:
        return (
            f"Correct manual test not covered — nearest generated scenario only "
            f"{best_score:.0%} aligned (actions {sorted(profile.actions)} missing)"
        )
    return (
        f"Correct manual test not covered — nearest generated scenario "
        f"{best_score:.0%} aligned but not accepted as a match"
    )


def _why_extra_cand(
    profile: BehaviorProfile,
    best_score: float,
    nearest_ref: str | None,
    reference_side: str,
    candidate_side: str,
) -> str:
    if reference_side == "manual":
        return _why_extra_manual(profile, best_score, nearest_ref)
    if not nearest_ref or best_score <= 0:
        return f"Generated scenario does not map to any {reference_side} behaviour"
    if best_score < 0.5:
        return (
            f"Generated scenario poorly aligned to {reference_side} "
            f"'{nearest_ref}' ({best_score:.0%})"
        )
    return (
        f"Generated closest to {reference_side} '{nearest_ref}' ({best_score:.0%}) "
        f"but not accepted — misaligned or redundant"
    )


def _why_extra_manual(
    profile: BehaviorProfile,
    best_score: float,
    nearest_manual: str | None,
) -> str:
    if best_score <= 0 or not nearest_manual:
        return "Generated scenario does not map to any correct manual test"
    if best_score < 0.5:
        return (
            f"Generated scenario poorly aligned to correct manual test "
            f"'{nearest_manual}' ({best_score:.0%})"
        )
    return (
        f"Generated scenario closest to correct manual test '{nearest_manual}' "
        f"({best_score:.0%}) but not accepted — misaligned or redundant agent output"
    )


def action_coverage(
    manual_profiles: Sequence[BehaviorProfile],
    matches: Sequence[BehaviorMatch],
) -> Tuple[float, Set[str], Set[str]]:
    all_actions: Set[str] = set()
    covered: Set[str] = set()
    for mp in manual_profiles:
        all_actions.update(mp.actions)
    for m in matches:
        covered.update(m.shared_actions)
    if not all_actions:
        return 100.0, covered, all_actions
    return len(covered) / len(all_actions) * 100.0, covered, all_actions


def requirement_action_coverage(
    requirement_profiles: Sequence[BehaviorProfile],
    matches: Sequence,
) -> Tuple[float, Set[str], Set[str]]:
    all_actions: Set[str] = set()
    covered: Set[str] = set()
    for rp in requirement_profiles:
        all_actions.update(rp.actions)
    for m in matches:
        covered.update(getattr(m, "shared_actions", []))
    if not all_actions:
        return 100.0, covered, all_actions
    return len(covered) / len(all_actions) * 100.0, covered, all_actions


def path_coverage(
    manual_profiles: Sequence[BehaviorProfile],
    matched_manual_scenarios: Set[str],
    intent: str,
) -> float:
    subset = [p for p in manual_profiles if p.intent == intent]
    if not subset:
        return 100.0
    matched = sum(1 for p in subset if p.scenario in matched_manual_scenarios)
    return matched / len(subset) * 100.0


def requirement_path_coverage(
    requirement_profiles,
    matched_ac_labels: Set[str],
    *,
    negative_only: bool = False,
) -> float:
    if negative_only:
        subset = [p for p in requirement_profiles if p.negative_path or p.intent == "negative"]
    else:
        subset = [p for p in requirement_profiles if not p.negative_path and p.intent != "negative"]
    if not subset:
        return 100.0
    matched = sum(1 for p in subset if p.ac_label in matched_ac_labels)
    return matched / len(subset) * 100.0


def profile_label_coverage(
    profiles: Sequence[BehaviorProfile],
    matched_labels: Set[str],
) -> float:
    if not profiles:
        return 100.0
    return sum(1 for p in profiles if p.scenario in matched_labels) / len(profiles) * 100.0


def stage_coverage(
    manual_profiles: Sequence[BehaviorProfile],
    matches: Sequence[BehaviorMatch],
) -> Tuple[float, List[str], List[str]]:
    manual_stages = {p.workflow_stage for p in manual_profiles}
    matched_stages = {m.workflow_stage for m in matches}
    missing = sorted(manual_stages - matched_stages)
    if not manual_stages:
        return 100.0, sorted(matched_stages), missing
    return (
        len(matched_stages & manual_stages) / len(manual_stages) * 100.0,
        sorted(matched_stages & manual_stages),
        missing,
    )


def feature_completeness(
    manual: Sequence[Scenario],
    matches: Sequence[BehaviorMatch],
) -> Tuple[float, List[str]]:
    manual_files = {s.feature_file for s in manual}
    matched_scenarios = {m.manual_scenario for m in matches}
    covered_files = {s.feature_file for s in manual if s.name in matched_scenarios}
    missing = sorted(manual_files - covered_files)
    if not manual_files:
        return 100.0, missing
    return len(covered_files) / len(manual_files) * 100.0, missing


def behavior_signature_coverage(
    manual_profiles: Sequence[BehaviorProfile],
    matches: Sequence[BehaviorMatch],
) -> float:
    return profile_label_coverage(
        manual_profiles,
        {m.manual_scenario for m in matches},
    )
