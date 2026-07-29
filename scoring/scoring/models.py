"""
Data model for behaviour-based BDD scoring.

Manual BDD is ground truth. Requirement docs are the behaviour contract the test
generator was given. Generated BDD is what we score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .report_views import build_detailed, build_simplified


@dataclass(frozen=True)
class Step:
    keyword: str
    text: str
    line: int = 0


@dataclass(frozen=True)
class Scenario:
    feature_file: str
    feature_name: str
    name: str
    tags: Tuple[str, ...] = ()
    steps: Tuple[Step, ...] = ()
    is_outline: bool = False
    examples_header: Tuple[str, ...] = ()
    outline_examples: Tuple[Tuple[str, ...], ...] = ()
    examples_block: str = ""

    @property
    def qualified_name(self) -> str:
        return f"{self.feature_file}::{self.name}"


@dataclass
class BehaviorMatch:
    manual_scenario: str
    generated_scenario: str
    manual_feature: str
    generated_feature: str
    workflow_stage: str
    intent: str
    shared_actions: List[str]
    shared_outcomes: List[str]
    match_score: float
    why_matched: str
    reference_side: str = "manual"
    candidate_side: str = "generated"

    def to_dict(self) -> dict:
        return {
            "manual_scenario": self.manual_scenario,
            "generated_scenario": self.generated_scenario,
            "manual_feature": self.manual_feature,
            "generated_feature": self.generated_feature,
            "workflow_stage": self.workflow_stage,
            "intent": self.intent,
            "shared_actions": self.shared_actions,
            "shared_outcomes": self.shared_outcomes,
            "match_score": round(self.match_score, 4),
            "why_matched": self.why_matched,
            "reference_side": self.reference_side,
            "candidate_side": self.candidate_side,
        }


@dataclass
class RequirementMatch:
    requirement_ac: str
    generated_scenario: str
    unit_id: str
    unit_type: str
    workflow_stage: str
    intent: str
    shared_actions: List[str]
    match_score: float
    why_matched: str
    negative_path: bool = False
    requirement_backed: bool = False
    source_section: str = "User Stories"

    def to_dict(self) -> dict:
        return {
            "requirement_ac": self.requirement_ac,
            "generated_scenario": self.generated_scenario,
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "workflow_stage": self.workflow_stage,
            "intent": self.intent,
            "shared_actions": self.shared_actions,
            "match_score": round(self.match_score, 4),
            "why_matched": self.why_matched,
            "negative_path": self.negative_path,
            "requirement_backed": self.requirement_backed,
            "source_section": self.source_section,
        }


@dataclass
class MissingBehavior:
    """An unaligned scenario on one side and its closest counterpart on the other."""

    scenario: str
    feature_file: str
    workflow_stage: str
    intent: str
    actions: List[str]
    why_missing: str
    side: str = "manual"
    best_near_match: Optional[float] = None
    nearest_scenario: Optional[str] = None
    nearest_feature_file: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "feature_file": self.feature_file,
            "workflow_stage": self.workflow_stage,
            "intent": self.intent,
            "actions": self.actions,
            "why_missing": self.why_missing,
            "side": self.side,
            "best_near_match": self.best_near_match,
            "nearest_scenario": self.nearest_scenario,
            "nearest_feature_file": self.nearest_feature_file,
        }


@dataclass
class ScoreBreakdown:
    behavior_coverage_pct: float
    action_coverage_pct: float
    positive_path_coverage_pct: float
    negative_path_coverage_pct: float
    workflow_stage_coverage_pct: float
    feature_completeness_pct: float
    granularity_ratio: float
    golden_gherkin_compliance_pct: float
    generated_gherkin_compliance_pct: float
    overall_score: float
    explanation: List[str] = field(default_factory=list)
    # Phase 1–3: requirement + triangulation metrics (0 when no requirements input).
    requirement_ac_coverage_pct: float = 0.0
    requirement_negative_coverage_pct: float = 0.0
    requirement_action_coverage_pct: float = 0.0
    triangulation_pct: float = 0.0
    scoring_mode: str = "manual_only"
    # Generated-centric alignment (suite precision / secondary).
    generated_manual_alignment_pct: float = 0.0
    generated_requirement_alignment_pct: float = 0.0
    generated_triangulated_count: int = 0
    # Golden-first extras.
    manual_recall_pct: float = 0.0
    coverage_efficiency_pct: float = 0.0
    suite_precision_pct: float = 0.0
    agent_credited_manual_count: int = 0
    redundant_generated_count: int = 0

    def to_dict(self) -> dict:
        return {
            "behavior_coverage_pct": round(self.behavior_coverage_pct, 2),
            "action_coverage_pct": round(self.action_coverage_pct, 2),
            "positive_path_coverage_pct": round(self.positive_path_coverage_pct, 2),
            "negative_path_coverage_pct": round(self.negative_path_coverage_pct, 2),
            "workflow_stage_coverage_pct": round(self.workflow_stage_coverage_pct, 2),
            "feature_completeness_pct": round(self.feature_completeness_pct, 2),
            "granularity_ratio": round(self.granularity_ratio, 3),
            "golden_gherkin_compliance_pct": round(self.golden_gherkin_compliance_pct, 2),
            "generated_gherkin_compliance_pct": round(self.generated_gherkin_compliance_pct, 2),
            "overall_score": round(self.overall_score, 2),
            "explanation": self.explanation,
            "requirement_ac_coverage_pct": round(self.requirement_ac_coverage_pct, 2),
            "requirement_negative_coverage_pct": round(self.requirement_negative_coverage_pct, 2),
            "requirement_action_coverage_pct": round(self.requirement_action_coverage_pct, 2),
            "triangulation_pct": round(self.triangulation_pct, 2),
            "scoring_mode": self.scoring_mode,
            "generated_manual_alignment_pct": round(self.generated_manual_alignment_pct, 2),
            "generated_requirement_alignment_pct": round(self.generated_requirement_alignment_pct, 2),
            "generated_triangulated_count": self.generated_triangulated_count,
            "manual_recall_pct": round(self.manual_recall_pct, 2),
            "coverage_efficiency_pct": round(self.coverage_efficiency_pct, 2),
            "suite_precision_pct": round(self.suite_precision_pct, 2),
            "agent_credited_manual_count": self.agent_credited_manual_count,
            "redundant_generated_count": self.redundant_generated_count,
        }


@dataclass
class ScoreReport:
    threshold: float
    manual_scenarios: int
    generated_scenarios: int
    matched_behaviors: int
    breakdown: ScoreBreakdown
    matched: List[BehaviorMatch] = field(default_factory=list)
    missing_behaviors: List[MissingBehavior] = field(default_factory=list)
    extra_behaviors: List[MissingBehavior] = field(default_factory=list)
    covered_actions: List[str] = field(default_factory=list)
    uncovered_actions: List[str] = field(default_factory=list)
    covered_stages: List[str] = field(default_factory=list)
    missing_stages: List[str] = field(default_factory=list)
    missing_features: List[str] = field(default_factory=list)
    golden_compliance: dict = field(default_factory=dict)
    generated_compliance: dict = field(default_factory=dict)
    # Requirements + triangulation (empty when manual-only mode).
    requirement_acs: int = 0
    matched_requirements: int = 0
    requirement_matches: List[RequirementMatch] = field(default_factory=list)
    missing_requirements: List[MissingBehavior] = field(default_factory=list)
    misaligned_generated_vs_requirements: List[MissingBehavior] = field(default_factory=list)
    requirement_only_gaps: List[str] = field(default_factory=list)
    triangulation: List = field(default_factory=list)
    unit_traceability: List = field(default_factory=list)
    has_requirements: bool = False
    generated_aligned_to_manual: int = 0
    generated_aligned_to_requirements: int = 0
    generated_unaligned_manual: int = 0
    generated_unaligned_requirements: int = 0
    input_integrity: dict = field(default_factory=dict)

    @property
    def matched_pairs(self) -> int:
        return self.matched_behaviors

    @property
    def manual_scenario_coverage_pct(self) -> float:
        return self.breakdown.behavior_coverage_pct

    @property
    def generated_manual_alignment_pct(self) -> float:
        return self.breakdown.generated_manual_alignment_pct

    @property
    def generated_requirement_alignment_pct(self) -> float:
        return self.breakdown.generated_requirement_alignment_pct

    @property
    def generated_alignment_pct(self) -> float:
        return self.generated_manual_alignment_pct

    @property
    def overall_score(self) -> float:
        return self.breakdown.overall_score

    def to_dict(self) -> dict:
        simplified = build_simplified(self)
        detailed = build_detailed(self)
        payload = {
            "simplified": simplified,
            "detailed": detailed,
            "threshold": self.threshold,
            "manual_scenarios": self.manual_scenarios,
            "generated_scenarios": self.generated_scenarios,
            "matched_behaviors": self.matched_behaviors,
            "breakdown": self.breakdown.to_dict(),
            "matched": [m.to_dict() for m in self.matched],
            "missing_behaviors": [m.to_dict() for m in self.missing_behaviors],
            "extra_behaviors": [m.to_dict() for m in self.extra_behaviors],
            "covered_actions": self.covered_actions,
            "uncovered_actions": self.uncovered_actions,
            "covered_stages": self.covered_stages,
            "missing_stages": self.missing_stages,
            "missing_features": self.missing_features,
            "golden_compliance": self.golden_compliance,
            "generated_compliance": self.generated_compliance,
            "has_requirements": self.has_requirements,
            "requirement_acs": self.requirement_acs,
            "matched_requirements": self.matched_requirements,
            "requirement_matches": [m.to_dict() for m in self.requirement_matches],
            "missing_requirements": [m.to_dict() for m in self.missing_requirements],
            "misaligned_generated_vs_requirements": [
                m.to_dict() for m in self.misaligned_generated_vs_requirements
            ],
            "requirement_only_gaps": self.requirement_only_gaps,
            "triangulation": [
                t.to_dict() if hasattr(t, "to_dict") else t for t in self.triangulation
            ],
            "unit_traceability": [
                u.to_dict() if hasattr(u, "to_dict") else u for u in self.unit_traceability
            ],
            "input_integrity": self.input_integrity,
        }
        return payload
