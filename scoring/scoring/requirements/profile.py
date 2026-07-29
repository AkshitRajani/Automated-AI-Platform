"""
Extract behaviour profiles from requirement-agent documents.

Deterministic extraction scans every section. Bedrock agent labels behaviour
(full markdown per file when <=15 MDs, compact batched labelling otherwise).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Set

from ..behavior import (
    BehaviorProfile,
    detect_actions,
    detect_intent,
    detect_stage,
)
from .extract import RequirementItem, extract_items_from_doc
from .parse import _section_key

_NEG_TAG = re.compile(r"negative\s*path|\(negative", re.IGNORECASE)


@dataclass(frozen=True)
class RequirementProfile:
    """One testable acceptance criterion or consolidated requirement."""

    doc_file: str
    unit_id: str
    unit_type: str
    story_id: str
    ac_label: str
    ac_text: str
    workflow_stage: str
    intent: str
    actions: FrozenSet[str]
    outcomes: FrozenSet[str]
    provenance: str
    requirement_backed: bool
    negative_path: bool
    source_section: str

    @property
    def scenario(self) -> str:
        return self.ac_label

    @property
    def feature_file(self) -> str:
        return self.doc_file

    @property
    def feature_name(self) -> str:
        return self.unit_id

    def to_behavior_profile(self) -> BehaviorProfile:
        return BehaviorProfile(
            feature_file=self.doc_file,
            feature_name=self.unit_id,
            scenario=self.ac_label,
            workflow_stage=self.workflow_stage,
            intent=self.intent,
            actions=self.actions,
            outcomes=self.outcomes,
        )


def _outcomes_from_actions(actions: Iterable[str], intent: str) -> FrozenSet[str]:
    outcomes: Set[str] = set()
    for action in actions:
        outcomes.add(f"expect_{action}")
    if intent == "negative":
        outcomes.add("expect_stop")
    if "notify" in actions:
        outcomes.add("expect_notify")
    return frozenset(outcomes)


def _profile_text_regex(
    *,
    doc_file: str,
    unit_id: str,
    unit_type: str,
    story_id: str,
    ac_label: str,
    ac_text: str,
    provenance: str,
    requirement_backed: bool,
    source_section: str,
) -> RequirementProfile:
    corpus = f"{unit_id} {story_id} {ac_text}"
    stage = detect_stage(corpus)
    negative = bool(_NEG_TAG.search(ac_text))
    intent = "negative" if negative else detect_intent(ac_label, [])
    if intent == "neutral" and negative:
        intent = "negative"
    actions: Set[str] = set(detect_actions(corpus))
    norm = ac_text.lower()
    if "then" in norm:
        then_part = norm.split("then", 1)[-1]
        actions.update(detect_actions(then_part))
    if "raises" in norm or "error" in norm or "reject" in norm:
        pass
    return RequirementProfile(
        doc_file=doc_file,
        unit_id=unit_id,
        unit_type=unit_type or "",
        story_id=story_id,
        ac_label=ac_label,
        ac_text=ac_text.strip(),
        workflow_stage=stage,
        intent=intent,
        actions=frozenset(actions),
        outcomes=_outcomes_from_actions(actions, intent),
        provenance=provenance,
        requirement_backed=requirement_backed,
        negative_path=negative or intent == "negative",
        source_section=source_section,
    )


def _item_to_requirement_profile(
    item: RequirementItem,
    agent_label: Optional["ScenarioProfileOut"] = None,
) -> RequirementProfile:
    from ..agent.schemas import ScenarioProfileOut

    if agent_label is None:
        return _profile_text_regex(
            doc_file=item.doc_file,
            unit_id=item.unit_id,
            unit_type=item.unit_type,
            story_id=item.story_id,
            ac_label=item.item_id,
            ac_text=item.verbatim_text,
            provenance=item.provenance,
            requirement_backed=item.requirement_backed,
            source_section=item.source_section,
        )
    if not isinstance(agent_label, ScenarioProfileOut):
        agent_label = ScenarioProfileOut.model_validate(agent_label)
    return RequirementProfile(
        doc_file=item.doc_file,
        unit_id=item.unit_id,
        unit_type=item.unit_type,
        story_id=item.story_id,
        ac_label=item.item_id,
        ac_text=item.verbatim_text,
        workflow_stage=agent_label.workflow_stage,
        intent=agent_label.intent,
        actions=frozenset(agent_label.actions),
        outcomes=_outcomes_from_actions(agent_label.actions, agent_label.intent),
        provenance=item.provenance,
        requirement_backed=item.requirement_backed,
        negative_path=agent_label.intent == "negative" or item.negative_path,
        source_section=item.source_section,
    )


def profile_requirement_doc(doc: Dict) -> List[RequirementProfile]:
    """Extract behaviour profiles from one requirement document (regex labelling)."""
    items = extract_items_from_doc(doc)
    return [_item_to_requirement_profile(item) for item in items]


def profile_requirements(
    docs: Iterable[Dict],
    *,
    source: Optional[str] = None,
) -> List[RequirementProfile]:
    doc_list = list(docs)
    from ..agent.context import get_profiling_mode
    if get_profiling_mode() == "agent":
        from .agent_profile import profile_requirements_agent
        return profile_requirements_agent(doc_list, source=source)
    out: List[RequirementProfile] = []
    for doc in doc_list:
        out.extend(profile_requirement_doc(doc))
    return out
