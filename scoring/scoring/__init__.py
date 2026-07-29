"""
Scoring — BDD benchmark with optional Bedrock behaviour profiling.

Scores generated BDD against manual (ground truth) and optional requirement-agent
docs. Matching and weights are deterministic; behaviour labels come from regex
(default) or a Bedrock agent (when configured).

Public surface::

    from scoring import score, ScoreReport

    report = score(
        golden="./feature",
        generated="./generated_feature",
        requirements="./requirements",
        profiling_mode="auto",  # agent when BEDROCK_MODEL_ARN set
    )
"""
from __future__ import annotations

from .behavior import BehaviorProfile, profile_scenario, profile_suite
from .models import (
    BehaviorMatch,
    MissingBehavior,
    RequirementMatch,
    Scenario,
    ScoreBreakdown,
    ScoreReport,
    Step,
)
from .parse import load_features, parse_feature_text
from .config import ScoringConfig, apply_python_path, default_scoring_root, env_file_path, load_env_file
from .html_report import render_html, write_html
from .requirements import RequirementProfile, load_requirements, profile_requirements
from .score import score
from .standalone import StandaloneResult, run_from_zips
from .triangulation import TriangulationMatch, UnitTraceability

__all__ = [
    "score",
    "run_from_zips",
    "StandaloneResult",
    "ScoringConfig",
    "apply_python_path",
    "default_scoring_root",
    "env_file_path",
    "load_env_file",
    "render_html",
    "write_html",
    "ScoreReport",
    "ScoreBreakdown",
    "BehaviorMatch",
    "RequirementMatch",
    "MissingBehavior",
    "TriangulationMatch",
    "UnitTraceability",
    "BehaviorProfile",
    "RequirementProfile",
    "Scenario",
    "Step",
    "load_features",
    "load_requirements",
    "profile_requirements",
    "parse_feature_text",
    "profile_scenario",
    "profile_suite",
]
