"""
Closed vocabulary for behaviour profiling — agent must pick from these lists only.
"""
from __future__ import annotations

from typing import FrozenSet, Tuple

WORKFLOW_STAGES: Tuple[str, ...] = (
    "bootstrap",
    "extract",
    "transform",
    "validate",
    "load",
    "monitor",
    "notify",
    "e2e",
    "general",
)

INTENTS: Tuple[str, ...] = ("positive", "negative", "neutral")

ACTIONS: Tuple[str, ...] = (
    "initialize",
    "retrieve",
    "transform",
    "validate",
    "import",
    "monitor",
    "notify",
    "retry",
    "reject",
    "route",
    "complete",
    "history",
    "summarize",
)

WORKFLOW_STAGES_SET: FrozenSet[str] = frozenset(WORKFLOW_STAGES)
INTENTS_SET: FrozenSet[str] = frozenset(INTENTS)
ACTIONS_SET: FrozenSet[str] = frozenset(ACTIONS)

PROMPT_VERSION = "2"
