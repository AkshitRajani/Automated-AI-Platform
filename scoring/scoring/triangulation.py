"""
Triangulation — generated scored against manual (ground truth) and requirements (contract).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .behavior import BehaviorProfile
from .behavior_match import match_profile_sets
from .models import BehaviorMatch, MissingBehavior, RequirementMatch
from .requirements.profile import RequirementProfile


@dataclass
class TriangulationMatch:
    """Generated scenario aligned with both manual and requirement references."""

    manual_scenario: str
    requirement_ac: str
    generated_scenario: str
    unit_id: str
    workflow_stage: str
    intent: str
    manual_score: float
    requirement_score: float
    why: str

    def to_dict(self) -> dict:
        return {
            "manual_scenario": self.manual_scenario,
            "requirement_ac": self.requirement_ac,
            "generated_scenario": self.generated_scenario,
            "unit_id": self.unit_id,
            "workflow_stage": self.workflow_stage,
            "intent": self.intent,
            "manual_score": round(self.manual_score, 4),
            "requirement_score": round(self.requirement_score, 4),
            "why": self.why,
        }


@dataclass
class UnitTraceability:
    """Per-unit coverage across manual, requirements, and generated."""

    unit_id: str
    unit_type: str
    requirement_acs: int
    requirement_acs_covered: int
    manual_scenarios_near_unit: int
    manual_covered: int
    generated_scenarios: List[str]
    requirement_coverage_pct: float
    manual_coverage_pct: float

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "requirement_acs": self.requirement_acs,
            "requirement_acs_covered": self.requirement_acs_covered,
            "manual_scenarios_near_unit": self.manual_scenarios_near_unit,
            "manual_covered": self.manual_covered,
            "generated_scenarios": self.generated_scenarios,
            "requirement_coverage_pct": round(self.requirement_coverage_pct, 2),
            "manual_coverage_pct": round(self.manual_coverage_pct, 2),
        }


def compute_triangulation(
    manual_matches: Sequence[BehaviorMatch],
    requirement_matches: Sequence[RequirementMatch],
    manual_profiles: Sequence[BehaviorProfile],
    requirement_profiles: Sequence[RequirementProfile],
    generated_profiles: Sequence[BehaviorProfile],
    threshold: float,
) -> Tuple[List[TriangulationMatch], float, List[UnitTraceability]]:
    """Find triple-alignments and compute triangulation score."""
    req_by_gen: Dict[str, RequirementMatch] = {
        m.generated_scenario: m for m in requirement_matches
    }
    manual_by_gen: Dict[str, BehaviorMatch] = {
        m.generated_scenario: m for m in manual_matches
    }

    triples: List[TriangulationMatch] = []
    seen: Set[str] = set()

    for gen_name, mm in manual_by_gen.items():
        rm = req_by_gen.get(gen_name)
        if not rm:
            continue
        key = f"{mm.manual_scenario}|{rm.requirement_ac}|{gen_name}"
        if key in seen:
            continue
        seen.add(key)
        triples.append(TriangulationMatch(
            manual_scenario=mm.manual_scenario,
            requirement_ac=rm.requirement_ac,
            generated_scenario=gen_name,
            unit_id=rm.unit_id,
            workflow_stage=mm.workflow_stage,
            intent=mm.intent,
            manual_score=mm.match_score,
            requirement_score=rm.match_score,
            why=(
                f"Generated '{gen_name}' aligns with manual '{mm.manual_scenario}' "
                f"({mm.match_score:.0%}) and requirement '{rm.requirement_ac}' "
                f"({rm.match_score:.0%})"
            ),
        ))

    n_gen = len(generated_profiles)
    triangulation_pct = (
        len({t.generated_scenario for t in triples}) / n_gen * 100.0 if n_gen else 0.0
    )

    unit_rows = _build_unit_traceability(
        requirement_profiles,
        requirement_matches,
        manual_profiles,
        manual_matches,
        generated_profiles,
    )

    return triples, triangulation_pct, unit_rows


def _build_unit_traceability(
    requirement_profiles: Sequence[RequirementProfile],
    requirement_matches: Sequence[RequirementMatch],
    manual_profiles: Sequence[BehaviorProfile],
    manual_matches: Sequence[BehaviorMatch],
    generated_profiles: Sequence[BehaviorProfile],
) -> List[UnitTraceability]:
    matched_req_acs = {m.requirement_ac for m in requirement_matches}
    matched_manual = {m.manual_scenario for m in manual_matches}

    units: Dict[str, Dict] = {}
    for rp in requirement_profiles:
        bucket = units.setdefault(rp.unit_id, {
            "unit_type": rp.unit_type,
            "req_acs": [],
            "req_covered": 0,
            "manual_near": 0,
            "manual_covered": 0,
            "generated": set(),
        })
        bucket["req_acs"].append(rp.ac_label)
        if rp.ac_label in matched_req_acs:
            bucket["req_covered"] += 1

    for mp in manual_profiles:
        for unit_id in units:
            if unit_id.lower() in mp.feature_file.lower() or unit_id.lower() in mp.scenario.lower():
                units[unit_id]["manual_near"] += 1
                if mp.scenario in matched_manual:
                    units[unit_id]["manual_covered"] += 1

    gen_names = {p.scenario for p in generated_profiles}
    for rm in requirement_matches:
        if rm.unit_id in units and rm.generated_scenario in gen_names:
            units[rm.unit_id]["generated"].add(rm.generated_scenario)

    rows: List[UnitTraceability] = []
    for unit_id, data in sorted(units.items()):
        n_req = len(data["req_acs"])
        n_man = data["manual_near"]
        rows.append(UnitTraceability(
            unit_id=unit_id,
            unit_type=data["unit_type"],
            requirement_acs=n_req,
            requirement_acs_covered=data["req_covered"],
            manual_scenarios_near_unit=n_man,
            manual_covered=data["manual_covered"],
            generated_scenarios=sorted(data["generated"]),
            requirement_coverage_pct=(
                data["req_covered"] / n_req * 100.0 if n_req else 100.0
            ),
            manual_coverage_pct=(
                data["manual_covered"] / n_man * 100.0 if n_man else 100.0
            ),
        ))
    return rows


def match_requirements_to_generated(
    requirement_profiles: Sequence[RequirementProfile],
    generated_profiles: Sequence[BehaviorProfile],
    threshold: float,
) -> Tuple[
    List[RequirementMatch],
    List[MissingBehavior],
    List[MissingBehavior],
]:
    """Match requirement ACs to generated scenarios."""
    ref = [rp.to_behavior_profile() for rp in requirement_profiles]
    matches_raw, missing, extra, _ref, _gen = match_profile_sets(
        ref, generated_profiles, threshold,
        reference_side="requirement",
        candidate_side="generated",
    )

    req_matches: List[RequirementMatch] = []
    req_by_label = {rp.ac_label: rp for rp in requirement_profiles}

    for m in matches_raw:
        rp = req_by_label.get(m.manual_scenario)
        if not rp:
            continue
        req_matches.append(RequirementMatch(
            requirement_ac=rp.ac_label,
            generated_scenario=m.generated_scenario,
            unit_id=rp.unit_id,
            unit_type=rp.unit_type,
            workflow_stage=m.workflow_stage,
            intent=m.intent,
            shared_actions=m.shared_actions,
            match_score=m.match_score,
            why_matched=m.why_matched,
            negative_path=rp.negative_path,
            requirement_backed=rp.requirement_backed,
            source_section=rp.source_section,
        ))

    # Relabel missing/extra sides for requirements context
    for row in missing:
        row.side = "requirement"
    for row in extra:
        if row.side == "manual":
            row.side = "requirement"

    return req_matches, missing, extra
