"""
Extract business behaviour from Gherkin — the only source of truth.

All signals come from feature/scenario names and step text. No source code,
config, or external systems are consulted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from pathlib import Path

from .models import Scenario, Step

_WS = re.compile(r"\s+")
_SNAKE = re.compile(r"[_-]+")

# Canonical business actions detected by phrase patterns (longest first).
ACTION_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("initialize", ("initialize", "bootstrap", "startup", "load configuration", "settings document", "configuration")),
    ("retrieve", ("retrieve", "extract", "pull rows", "ingest", "source data", "fetch", "connector")),
    ("transform", ("prepare", "transform", "merge", "convert", "shape", "rename", "cast", "consolidate", "duplicate")),
    ("validate", ("validate", "validation", "quality gate", "quality rules", "mandatory field", "schema check")),
    ("import", ("import", "load phase", "upload", "submit", "anaplan action", "model load", "push into anaplan")),
    ("monitor", ("monitor", "poll", "progress", "execution", "live progress", "terminal state")),
    ("notify", ("notify", "notification", "communique", "stakeholder", "feed owner")),
    ("retry", ("retry", "recovery", "transient", "attempt recovery")),
    ("reject", ("reject", "fail", "failure", "abort", "halt", "stop", "block", "terminate", "must not")),
    ("route", ("route", "dispatch", "based on", "connector registered", "path")),
    ("complete", ("complete", "success", "successfully", "happy path", "approved", "eligible")),
    ("history", ("history", "historical", "audit", "browse", "review")),
    ("summarize", ("summary", "metrics", "report", "gate report", "archived")),
)

# Workflow stages inferred from feature/scenario/step vocabulary.
STAGE_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("bootstrap", ("initialize", "bootstrap", "startup", "configuration", "settings")),
    ("extract", ("retrieve", "extract", "source", "pull", "ingest", "connector", "feed")),
    ("transform", ("prepare", "transform", "shape", "merge", "convert", "consolidate")),
    ("validate", ("validate", "validation", "quality gate", "quality rules", "mandatory")),
    ("load", ("import", "load", "upload", "submit", "anaplan")),
    ("monitor", ("monitor", "poll", "progress", "status", "execution", "visibility")),
    ("notify", ("notify", "notification", "communique", "stakeholder")),
    ("e2e", ("end to end", "e2e", "full happy path", "workflow")),
)

_POSITIVE_HINTS = frozenset({
    "success", "successfully", "complete", "valid", "approved", "eligible",
    "healthy", "compliant", "clear", "resolve", "ready", "pass", "continues",
})

_NEGATIVE_HINTS = frozenset({
    "fail", "failure", "reject", "stop", "abort", "halt", "block", "missing",
    "absent", "unavailable", "empty", "zero", "timeout", "invalid", "cannot",
    "not continue", "must not", "no ", "terminate", "exhausted", "cancel",
})


def _normalize(text: str) -> str:
    out = text.lower().strip()
    out = _SNAKE.sub(" ", out)
    out = _WS.sub(" ", out)
    return out


def _tokens(text: str) -> Set[str]:
    return set(_normalize(text).split())


def _detect_phrases(text: str, patterns: Sequence[Tuple[str, Tuple[str, ...]]]) -> Set[str]:
    norm = _normalize(text)
    found: Set[str] = set()
    for label, phrases in patterns:
        for phrase in phrases:
            if phrase in norm:
                found.add(label)
                break
    return found


def detect_actions(text: str) -> FrozenSet[str]:
    return frozenset(_detect_phrases(text, ACTION_PATTERNS))


def _pick_stage(stages: Set[str]) -> str:
    if not stages:
        return "general"
    priority = ("bootstrap", "extract", "transform", "validate", "load", "monitor", "notify", "e2e")
    for stage in priority:
        if stage in stages:
            return stage
    return sorted(stages)[0]


def detect_stage(text: str) -> str:
    return _pick_stage(_detect_phrases(text, STAGE_PATTERNS))


def detect_stage_for_scenario(feature_file: str, feature_name: str, scenario_name: str, full_text: str) -> str:
    """Prefer stage from file/feature/scenario names before step bodies."""
    for part in (feature_file, feature_name, scenario_name):
        stages = _detect_phrases(part, STAGE_PATTERNS)
        if stages:
            return _pick_stage(stages)
    return detect_stage(full_text)


def detect_intent(scenario_name: str, steps: Sequence[Step]) -> str:
    corpus = scenario_name + " " + " ".join(s.text for s in steps)
    norm = _normalize(corpus)
    neg = sum(1 for h in _NEGATIVE_HINTS if h in norm)
    pos = sum(1 for h in _POSITIVE_HINTS if h in norm)
    if neg > pos and neg > 0:
        return "negative"
    if pos > neg and pos > 0:
        return "positive"
    return "neutral"


def _outcomes_from_steps(steps: Sequence[Step]) -> FrozenSet[str]:
    outcomes: Set[str] = set()
    for step in steps:
        if step.keyword not in ("Then", "And", "But"):
            continue
        actions = detect_actions(step.text)
        outcomes.update(actions)
        # Outcome verbs from Then clause structure.
        norm = _normalize(step.text)
        if "should" in norm or "must" in norm:
            for action in actions:
                outcomes.add(f"expect_{action}")
        if "not" in norm and "continue" in norm:
            outcomes.add("expect_stop")
        if "notified" in norm or "notify" in norm:
            outcomes.add("expect_notify")
    return frozenset(outcomes)


@dataclass(frozen=True)
class BehaviorProfile:
    feature_file: str
    feature_name: str
    scenario: str
    workflow_stage: str
    intent: str
    actions: FrozenSet[str]
    outcomes: FrozenSet[str]

    @property
    def behavior_signature(self) -> str:
        acts = ",".join(sorted(self.actions)) or "none"
        return f"{self.workflow_stage}|{self.intent}|{acts}"

    @property
    def qualified_name(self) -> str:
        return f"{self.feature_file}::{self.scenario}"


def profile_scenario_regex(scenario: Scenario) -> BehaviorProfile:
    corpus = " ".join([
        scenario.feature_file,
        scenario.feature_name,
        scenario.name,
        " ".join(s.text for s in scenario.steps),
    ])
    stage = detect_stage_for_scenario(
        scenario.feature_file, scenario.feature_name, scenario.name, corpus,
    )
    intent = detect_intent(scenario.name, scenario.steps)
    actions: Set[str] = set()
    actions.update(detect_actions(scenario.name))
    for step in scenario.steps:
        # Behaviour lives in When/Then — Given is usually shared setup/background.
        if step.keyword in ("When", "Then"):
            actions.update(detect_actions(step.text))
        elif step.keyword in ("And", "But"):
            actions.update(detect_actions(step.text))
    outcomes = _outcomes_from_steps(scenario.steps)
    return BehaviorProfile(
        feature_file=scenario.feature_file,
        feature_name=scenario.feature_name,
        scenario=scenario.name,
        workflow_stage=stage,
        intent=intent,
        actions=frozenset(actions),
        outcomes=frozenset(outcomes),
    )


def profile_scenario(scenario: Scenario) -> BehaviorProfile:
    from .agent.context import get_profiling_mode
    if get_profiling_mode() == "agent":
        from .agent.profiler import profile_scenarios_agent
        return profile_scenarios_agent([scenario], kind="bdd_single")[0]
    return profile_scenario_regex(scenario)


def profile_suite(
    scenarios: Iterable[Scenario],
    *,
    source: Optional[str | Path] = None,
    kind: str = "bdd",
) -> List[BehaviorProfile]:
    from .agent.context import get_profiling_mode
    items = list(scenarios)
    if get_profiling_mode() == "agent":
        from .agent.profiler import profile_scenarios_agent
        return profile_scenarios_agent(items, kind=kind, source=source)
    return [profile_scenario_regex(s) for s in items]


def jaccard(left: FrozenSet[str], right: FrozenSet[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def stage_compatible(manual_stage: str, generated_stage: str) -> bool:
    if manual_stage == generated_stage:
        return True
    # Adjacent pipeline stages may cover the same business concern in different grouping.
    adjacent = {
        ("transform", "extract"),
        ("validate", "load"),
        ("load", "validate"),
        ("monitor", "e2e"),
        ("notify", "e2e"),
        ("e2e", "monitor"),
        ("e2e", "notify"),
        ("general", manual_stage),
        ("general", generated_stage),
    }
    return (manual_stage, generated_stage) in adjacent


def behavior_match_score(
    manual: BehaviorProfile,
    generated: BehaviorProfile,
) -> Tuple[float, dict]:
    """Score 0..1 and an explanation dict — behaviour, not wording."""
    from .agent.context import get_strict_matching

    strict = get_strict_matching()
    reasons: List[str] = []

    if manual.intent != generated.intent:
        if strict or (manual.intent != "neutral" and generated.intent != "neutral"):
            return 0.0, {
                "reason": "intent_mismatch",
                "detail": f"manual={manual.intent}, generated={generated.intent}",
                "strict_mode": strict,
            }
        reasons.append(f"intent partial (manual={manual.intent}, generated={generated.intent})")

    if manual.workflow_stage == generated.workflow_stage:
        stage_score = 1.0
        reasons.append(f"same workflow stage ({manual.workflow_stage})")
    elif strict:
        return 0.0, {
            "reason": "stage_mismatch",
            "detail": f"{manual.workflow_stage} vs {generated.workflow_stage}",
            "strict_mode": True,
        }
    elif stage_compatible(manual.workflow_stage, generated.workflow_stage):
        stage_score = 0.7
        reasons.append(
            f"compatible stages ({manual.workflow_stage} ~ {generated.workflow_stage})"
        )
    else:
        return 0.0, {
            "reason": "stage_mismatch",
            "detail": f"{manual.workflow_stage} vs {generated.workflow_stage}",
        }

    shared_actions = sorted(manual.actions & generated.actions)
    if strict and not shared_actions and (manual.actions or generated.actions):
        return 0.0, {
            "reason": "no_shared_actions",
            "detail": f"manual={sorted(manual.actions)}, generated={sorted(generated.actions)}",
            "strict_mode": True,
        }

    action_score = jaccard(manual.actions, generated.actions)
    if shared_actions:
        reasons.append(f"shared actions: {', '.join(shared_actions)}")
    else:
        reasons.append("no shared business actions")

    outcome_score = jaccard(manual.outcomes, generated.outcomes)
    shared_outcomes = sorted(manual.outcomes & generated.outcomes)

    score = 0.30 * stage_score + 0.45 * action_score + 0.25 * outcome_score
    if not strict and manual.intent == generated.intent and manual.intent != "neutral":
        score = min(1.0, score + 0.05)

    return score, {
        "stage_score": round(stage_score, 3),
        "action_score": round(action_score, 3),
        "outcome_score": round(outcome_score, 3),
        "shared_actions": shared_actions,
        "shared_outcomes": shared_outcomes,
        "why": "; ".join(reasons),
        "strict_mode": strict,
    }
