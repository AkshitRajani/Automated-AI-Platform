"""
Agent-only golden coverage assist — many-to-one credits and redundancy flags.

Does not invent generated↔manual 1:1 matches for suite precision. It only expands
which manual scenarios count as covered for recall / efficiency.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Set

from .agent.cache import load_cached_profiles, save_cached_profiles
from .agent.config import prompt_version, resolve_profiling_mode
from .behavior import BehaviorProfile
from .models import BehaviorMatch, MissingBehavior


@dataclass
class CoverageAssistResult:
    """Extra manual scenarios covered + generated scenarios flagged as redundant."""

    credited_manual_scenarios: Set[str] = field(default_factory=set)
    redundant_generated_scenarios: Set[str] = field(default_factory=set)
    notes: List[str] = field(default_factory=list)


def _fingerprint_assist(
    unmatched_manual: Sequence[BehaviorProfile],
    candidates: Sequence[BehaviorProfile],
) -> str:
    digest = hashlib.sha256()
    digest.update(f"prompt_version={prompt_version()}".encode("utf-8"))
    digest.update(b"coverage_assist_v1")
    for p in unmatched_manual:
        digest.update(
            f"m|{p.scenario}|{p.workflow_stage}|{p.intent}|{','.join(sorted(p.actions))}".encode(
                "utf-8"
            )
        )
    for p in candidates:
        digest.update(
            f"g|{p.scenario}|{p.workflow_stage}|{p.intent}|{','.join(sorted(p.actions))}".encode(
                "utf-8"
            )
        )
    return digest.hexdigest()[:32]


def _profile_brief(p: BehaviorProfile) -> dict:
    return {
        "scenario": p.scenario,
        "workflow_stage": p.workflow_stage,
        "intent": p.intent,
        "actions": sorted(p.actions),
        "feature": p.feature_name,
    }


def _invoke_coverage_assist_agent(
    unmatched_manual: Sequence[BehaviorProfile],
    candidates: Sequence[BehaviorProfile],
) -> dict:
    """Call Bedrock for many-to-one coverage + redundancy. Returns raw dict."""
    from typing import List as TypingList

    from pydantic import BaseModel, Field

    from .agent.bedrock_agent import _wrap_bedrock_error, build_profiling_agent

    class CoverageCredit(BaseModel):
        manual_scenario: str
        covering_generated_scenario: str
        covers: bool
        why: str = ""

    class CoverageAssistOut(BaseModel):
        credits: TypingList[CoverageCredit] = Field(default_factory=list)
        redundant_generated: TypingList[str] = Field(
            default_factory=list,
            description=(
                "Generated scenario names that are near-duplicates and do not add "
                "distinct manual coverage beyond another generated scenario."
            ),
        )

    agent = build_profiling_agent()
    payload = {
        "unmatched_manual": [_profile_brief(p) for p in unmatched_manual],
        "generated_candidates": [_profile_brief(p) for p in candidates],
    }
    prompt = (
        "You assist BDD scoring. Given unmatched MANUAL behaviours and GENERATED "
        "candidates (may already match other manuals), decide:\n"
        "1) credits — for each unmatched manual that is meaningfully covered by ANY "
        "generated candidate (same stage/intent and overlapping business actions), "
        "set covers=true with that generated scenario. Prefer one best cover. "
        "Do NOT invent coverage; if unclear, covers=false.\n"
        "2) redundant_generated — generated scenarios that are near-duplicates of "
        "other generated scenarios and do not add distinct manual coverage.\n\n"
        f"INPUT JSON:\n{json.dumps(payload, separators=(',', ':'))}"
    )
    try:
        result = agent(prompt, structured_output_model=CoverageAssistOut)
    except Exception as exc:
        raise _wrap_bedrock_error(exc) from exc
    out = result.structured_output
    if out is None:
        raise RuntimeError("Bedrock coverage assist returned no structured output")
    return out.model_dump()


def run_coverage_assist(
    *,
    manual_profiles: Sequence[BehaviorProfile],
    gen_profiles: Sequence[BehaviorProfile],
    matches: Sequence[BehaviorMatch],
    missing: Sequence[MissingBehavior],
    profiling_mode: Optional[str] = None,
    invoke_fn: Optional[
        Callable[
            [Sequence[BehaviorProfile], Sequence[BehaviorProfile]],
            dict,
        ]
    ] = None,
) -> CoverageAssistResult:
    """Expand golden recall via agent many-to-one; flag redundant generated scenarios.

    No-op outside agent mode. ``invoke_fn`` is injectable for tests.
    """
    mode = resolve_profiling_mode(profiling_mode)
    result = CoverageAssistResult()
    if mode != "agent":
        return result

    matched_manual = {m.manual_scenario for m in matches}
    unmatched = [p for p in manual_profiles if p.scenario not in matched_manual]
    candidates = list(gen_profiles)

    # Nothing useful to ask: no unmatched manuals and fewer than 2 gens for redundancy.
    if not unmatched and len(candidates) < 2:
        return result
    if not candidates:
        return result

    fingerprint = _fingerprint_assist(unmatched, candidates)
    cached = load_cached_profiles("coverage_assist", fingerprint)
    raw: Optional[dict] = None
    if cached is not None:
        raw = cached.get("__assist__") if isinstance(cached.get("__assist__"), dict) else None

    if raw is None:
        try:
            caller = invoke_fn or _invoke_coverage_assist_agent
            raw = caller(unmatched, candidates)
        except Exception as exc:
            result.notes.append(f"Coverage assist skipped: {exc}")
            return result
        if isinstance(raw, dict):
            save_cached_profiles("coverage_assist", fingerprint, {"__assist__": raw})

    if not isinstance(raw, dict):
        return result

    manual_names = {p.scenario for p in unmatched}
    gen_names = {p.scenario for p in candidates}
    for credit in raw.get("credits") or []:
        if not isinstance(credit, dict):
            continue
        if not credit.get("covers"):
            continue
        man = str(credit.get("manual_scenario") or "").strip()
        gen = str(credit.get("covering_generated_scenario") or "").strip()
        if man in manual_names and gen in gen_names:
            result.credited_manual_scenarios.add(man)

    for name in raw.get("redundant_generated") or []:
        label = str(name).strip()
        if label in gen_names:
            result.redundant_generated_scenarios.add(label)

    if result.credited_manual_scenarios:
        result.notes.append(
            f"Agent coverage assist credited {len(result.credited_manual_scenarios)} "
            f"additional manual scenario(s) via many-to-one coverage."
        )
    if result.redundant_generated_scenarios:
        result.notes.append(
            f"Agent flagged {len(result.redundant_generated_scenarios)} "
            f"generated scenario(s) as redundant noise."
        )
    # silence unused in non-assist paths
    _ = missing
    return result


def filter_missing_after_credit(
    missing: Sequence[MissingBehavior],
    credited: Set[str],
) -> List[MissingBehavior]:
    if not credited:
        return list(missing)
    return [m for m in missing if m.scenario not in credited]
