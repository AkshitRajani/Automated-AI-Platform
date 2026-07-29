"""
Deterministic validation gate for agent-produced behaviour profiles.
"""
from __future__ import annotations

from typing import Dict, List, Set

from pydantic import BaseModel

from .schemas import ProfileBatchOut, ScenarioProfileOut
from .taxonomy import ACTIONS_SET, INTENTS_SET, WORKFLOW_STAGES_SET


class GateResult(BaseModel):
    ok: bool
    rejected: List[str] = []
    reasons: List[str] = []


def _normalize_profile(raw: ScenarioProfileOut) -> ScenarioProfileOut:
    actions = sorted(set(raw.actions), key=lambda a: a)
    return ScenarioProfileOut(
        scenario_id=raw.scenario_id.strip(),
        workflow_stage=raw.workflow_stage,
        intent=raw.intent,
        actions=actions,
    )


def profile_validity_gate(
    batch: ProfileBatchOut,
    expected_ids: Set[str],
) -> GateResult:
    """Every profile must use allowed enums and cover exactly the expected scenario ids."""
    rejected: List[str] = []
    reasons: List[str] = []
    seen: Set[str] = set()

    for profile in batch.profiles:
        pid = profile.scenario_id.strip()
        if pid in seen:
            rejected.append(pid)
            reasons.append(f"duplicate scenario_id '{pid}'")
            continue
        seen.add(pid)

        if profile.workflow_stage not in WORKFLOW_STAGES_SET:
            rejected.append(pid)
            reasons.append(f"'{pid}': invalid stage '{profile.workflow_stage}'")
        if profile.intent not in INTENTS_SET:
            rejected.append(pid)
            reasons.append(f"'{pid}': invalid intent '{profile.intent}'")
        for action in profile.actions:
            if action not in ACTIONS_SET:
                rejected.append(pid)
                reasons.append(f"'{pid}': invalid action '{action}'")
                break

    missing = expected_ids - seen
    extra = seen - expected_ids
    for pid in sorted(missing):
        rejected.append(pid)
        reasons.append(f"missing profile for '{pid}'")
    for pid in sorted(extra):
        rejected.append(pid)
        reasons.append(f"unexpected profile '{pid}'")

    return GateResult(ok=not rejected and not reasons, rejected=rejected, reasons=reasons)


def normalize_batch(batch: ProfileBatchOut) -> Dict[str, ScenarioProfileOut]:
    return {
        p.scenario_id.strip(): _normalize_profile(p)
        for p in batch.profiles
    }
