"""
Scenario summaries for Bedrock calls — full step context, no silent omission.
"""
from __future__ import annotations

import json
from typing import Iterable, List

from ..models import Scenario
from .schemas import ScenarioSummary


def scenario_id(scenario: Scenario) -> str:
    return f"{scenario.feature_file}::{scenario.name}"


def _step_lines(scenario: Scenario, keywords: tuple[str, ...]) -> str:
    lines: List[str] = []
    for step in scenario.steps:
        if step.keyword in keywords:
            lines.append(f"{step.keyword} {step.text}")
    return "\n".join(lines)


def _all_step_lines(scenario: Scenario) -> str:
    return "\n".join(f"{step.keyword} {step.text}" for step in scenario.steps)


def summarize_scenario(scenario: Scenario) -> ScenarioSummary:
    return ScenarioSummary(
        scenario_id=scenario_id(scenario),
        feature_file=scenario.feature_file,
        feature_name=scenario.feature_name,
        scenario_name=scenario.name,
        tags=list(scenario.tags),
        given_lines=_step_lines(scenario, ("Given", "Background")),
        when_then_lines=_step_lines(scenario, ("When", "Then", "And", "But", "Step")),
        all_step_lines=_all_step_lines(scenario),
        examples_block=scenario.examples_block,
        is_outline=scenario.is_outline,
    )


def summarize_scenarios(scenarios: Iterable[Scenario]) -> List[ScenarioSummary]:
    return [summarize_scenario(s) for s in scenarios]


def summaries_to_json(summaries: List[ScenarioSummary]) -> str:
    payload = [s.model_dump() for s in summaries]
    return json.dumps(payload, separators=(",", ":"))


def group_by_feature(scenarios: List[Scenario]) -> dict[str, List[Scenario]]:
    groups: dict[str, List[Scenario]] = {}
    for scenario in scenarios:
        groups.setdefault(scenario.feature_file, []).append(scenario)
    return groups
