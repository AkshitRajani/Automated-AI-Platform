"""
Orchestrate behaviour profiling — cache → Bedrock agent → BehaviorProfile conversion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from ..behavior import BehaviorProfile
from ..models import Scenario
from .bedrock_agent import profile_summaries_with_agent
from .boundary import normalize_batch
from .cache import (
    collect_paths_from_source,
    fingerprint_paths,
    load_cached_profiles,
    save_cached_profiles,
)
from .context import get_source_fingerprint
from .schemas import ProfileBatchOut, ScenarioProfileOut
from .summarize import group_by_feature, scenario_id, summarize_scenarios


def _outcomes_from_profile(profile: ScenarioProfileOut) -> frozenset:
    outcomes: Set[str] = set()
    for action in profile.actions:
        outcomes.add(f"expect_{action}")
    if profile.intent == "negative":
        outcomes.add("expect_stop")
    if "notify" in profile.actions:
        outcomes.add("expect_notify")
    return frozenset(outcomes)


def _to_behavior_profile(scenario: Scenario, raw: ScenarioProfileOut) -> BehaviorProfile:
    return BehaviorProfile(
        feature_file=scenario.feature_file,
        feature_name=scenario.feature_name,
        scenario=scenario.name,
        workflow_stage=raw.workflow_stage,
        intent=raw.intent,
        actions=frozenset(raw.actions),
        outcomes=_outcomes_from_profile(raw),
    )


def _batch_to_cache_dict(batch: ProfileBatchOut) -> Dict[str, dict]:
    return {p.scenario_id: p.model_dump() for p in batch.profiles}


def profile_scenarios_agent(
    scenarios: List[Scenario],
    *,
    kind: str = "bdd",
    source: Optional[str | Path] = None,
) -> List[BehaviorProfile]:
    """Profile scenarios via Bedrock agent with content-addressed cache."""
    if not scenarios:
        return []

    use_cache = kind not in ("bdd_single",)
    fingerprint = get_source_fingerprint(kind) if use_cache else None
    if not fingerprint and source is not None and use_cache:
        paths = collect_paths_from_source(source)
        fingerprint = fingerprint_paths(paths)

    if fingerprint:
        cached = load_cached_profiles(kind, fingerprint)
        if cached is not None:
            id_to_scenario = {scenario_id(s): s for s in scenarios}
            profiles: List[BehaviorProfile] = []
            for sid in [scenario_id(s) for s in scenarios]:
                raw = ScenarioProfileOut.model_validate(cached[sid])
                profiles.append(_to_behavior_profile(id_to_scenario[sid], raw))
            return profiles

    all_profiles: Dict[str, ScenarioProfileOut] = {}
    for _feature_file, group in group_by_feature(scenarios).items():
        summaries = summarize_scenarios(group)
        batch = profile_summaries_with_agent(summaries)
        all_profiles.update(normalize_batch(batch))

    if fingerprint:
        save_cached_profiles(kind, fingerprint, _batch_to_cache_dict(
            ProfileBatchOut(profiles=list(all_profiles.values()))
        ))

    id_to_scenario = {scenario_id(s): s for s in scenarios}
    return [
        _to_behavior_profile(id_to_scenario[sid], all_profiles[sid])
        for sid in [scenario_id(s) for s in scenarios]
    ]


def profile_requirement_texts_agent(
    entries: List[dict],
    *,
    source: Optional[str | Path] = None,
) -> Dict[str, ScenarioProfileOut]:
    """Profile requirement AC entries (pre-parsed structure, agent labels behaviour)."""
    if not entries:
        return {}

    from .schemas import ScenarioSummary

    kind = "requirements"
    fingerprint = get_source_fingerprint(kind)
    if not fingerprint and source is not None:
        fingerprint = fingerprint_paths(collect_paths_from_source(source))

    if fingerprint:
        cached = load_cached_profiles(kind, fingerprint)
        if cached is not None:
            return {k: ScenarioProfileOut.model_validate(v) for k, v in cached.items()}

    summaries = [
        ScenarioSummary(
            scenario_id=e["scenario_id"],
            feature_file=e.get("feature_file", ""),
            feature_name=e.get("feature_name", ""),
            scenario_name=e.get("scenario_name", e["scenario_id"]),
            when_then_lines=e["when_then_lines"],
        )
        for e in entries
    ]

    all_profiles: Dict[str, ScenarioProfileOut] = {}
    # Batch by feature_file to limit calls
    by_file: Dict[str, List[ScenarioSummary]] = {}
    for summary in summaries:
        by_file.setdefault(summary.feature_file or "requirements", []).append(summary)

    for group in by_file.values():
        batch = profile_summaries_with_agent(group)
        all_profiles.update(normalize_batch(batch))

    if fingerprint:
        save_cached_profiles(
            kind,
            fingerprint,
            {k: v.model_dump() for k, v in all_profiles.items()},
        )

    return all_profiles
