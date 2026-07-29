"""
Strands + Bedrock agent for behaviour profiling — structured output only, no tools.
"""
from __future__ import annotations

import json
import os
from typing import List, Set

from .boundary import GateResult, normalize_batch, profile_validity_gate
from .config import agent_max_tokens, bedrock_settings, bypass_tool_consent
from .prompts import (
    REQUIREMENT_DOC_SYSTEM_ADDENDUM,
    SYSTEM_PROMPT,
    batch_task_prompt,
    requirement_doc_task_prompt,
    requirement_label_batch_prompt,
)
from .schemas import (
    ProfileBatchOut,
    RequirementDocExtractionOut,
    RequirementItemCompact,
    RequirementLabelBatchOut,
    ScenarioSummary,
)


def _ensure_consent_bypass() -> None:
    if bypass_tool_consent():
        os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")
        os.environ.setdefault("STRANDS_BYPASS_TOOL_CONSENT", "true")


def build_profiling_agent(*, requirement_extraction: bool = False):
    """Construct a Strands Agent for batch behaviour classification (Claude Opus via Bedrock)."""
    from strands import Agent  # type: ignore
    from strands.models import BedrockModel  # type: ignore

    _ensure_consent_bypass()
    bedrock = bedrock_settings()
    model_kwargs = dict(
        model_id=bedrock["model_arn"],
        region_name=bedrock["region"],
        max_tokens=agent_max_tokens(),
    )
    try:
        model = BedrockModel(streaming=True, **model_kwargs)
    except TypeError:
        model = BedrockModel(**model_kwargs)
    system_prompt = SYSTEM_PROMPT
    if requirement_extraction:
        system_prompt = SYSTEM_PROMPT + REQUIREMENT_DOC_SYSTEM_ADDENDUM
    return Agent(model=model, system_prompt=system_prompt, tools=[])


def _invoke_batch(agent, summaries: List[ScenarioSummary]) -> ProfileBatchOut:
    payload = json.dumps([s.model_dump() for s in summaries], separators=(",", ":"))
    prompt = batch_task_prompt(payload)
    try:
        result = agent(prompt, structured_output_model=ProfileBatchOut)
    except Exception as exc:
        raise _wrap_bedrock_error(exc) from exc
    batch = result.structured_output
    if batch is None:
        raise RuntimeError("Bedrock agent returned no structured profiles")
    return batch


def _wrap_bedrock_error(exc: Exception) -> RuntimeError:
    msg = str(exc)
    if "AccessDenied" in msg or "not authorized" in msg.lower():
        return RuntimeError(
            "Bedrock access denied for the configured model. Your IAM policy may require "
            "an inference-profile ARN (not a plain model id). Ask your lead for the exact "
            "BEDROCK_MODEL_ARN and AWS_REGION for your account, then update scoring/.env. "
            f"Original: {msg[:300]}"
        )
    return RuntimeError(f"Bedrock profiling failed: {msg[:500]}")


def profile_summaries_with_agent(
    summaries: List[ScenarioSummary],
    *,
    max_repairs: int = 1,
) -> ProfileBatchOut:
    """Classify a batch of scenarios via Bedrock with bounded repair on gate failure."""
    if not summaries:
        return ProfileBatchOut(profiles=[])

    expected_ids = {s.scenario_id for s in summaries}
    agent = build_profiling_agent()
    batch = _invoke_batch(agent, summaries)
    gate = profile_validity_gate(batch, expected_ids)

    repairs = 0
    while not gate.ok and repairs < max_repairs:
        repair_prompt = (
            "Your previous response failed validation. Fix exactly these issues and "
            f"re-emit ALL profiles for scenario_ids: {sorted(expected_ids)}\n\n"
            + "\n".join(f"- {r}" for r in gate.reasons)
            + f"\n\nSCENARIOS JSON:\n{json.dumps([s.model_dump() for s in summaries], separators=(',', ':'))}"
        )
        try:
            result = agent(repair_prompt, structured_output_model=ProfileBatchOut)
        except Exception as exc:
            raise _wrap_bedrock_error(exc) from exc
        batch = result.structured_output
        if batch is None:
            raise RuntimeError("Bedrock agent repair returned no structured profiles")
        gate = profile_validity_gate(batch, expected_ids)
        repairs += 1

    if not gate.ok:
        raise RuntimeError(
            "Profiling agent failed validation after repair: " + "; ".join(gate.reasons[:5])
        )

    normalized = normalize_batch(batch)
    return ProfileBatchOut(profiles=list(normalized.values()))


def _invoke_structured(agent, prompt: str, model_cls):
    try:
        result = agent(prompt, structured_output_model=model_cls)
    except Exception as exc:
        raise _wrap_bedrock_error(exc) from exc
    payload = result.structured_output
    if payload is None:
        raise RuntimeError(f"Bedrock agent returned no structured {model_cls.__name__}")
    return payload


def profile_requirement_doc_with_agent(
    *,
    unit_id: str,
    source_file: str,
    raw_markdown: str,
) -> RequirementDocExtractionOut:
    """One Bedrock call per full requirement markdown file."""
    if not raw_markdown.strip():
        return RequirementDocExtractionOut(unit_id=unit_id, items=[])
    agent = build_profiling_agent(requirement_extraction=True)
    prompt = requirement_doc_task_prompt(
        unit_id=unit_id,
        source_file=source_file,
        raw_markdown=raw_markdown,
    )
    return _invoke_structured(agent, prompt, RequirementDocExtractionOut)


def profile_requirement_items_with_agent(
    items: List[RequirementItemCompact],
) -> RequirementLabelBatchOut:
    """Label pre-parsed requirement items (compact feed for many MD files)."""
    if not items:
        return RequirementLabelBatchOut(profiles=[])
    expected_ids = {item.item_id for item in items}
    agent = build_profiling_agent()
    payload = json.dumps([item.model_dump() for item in items], separators=(",", ":"))
    batch = _invoke_structured(
        agent,
        requirement_label_batch_prompt(payload),
        RequirementLabelBatchOut,
    )
    gate = profile_validity_gate(
        ProfileBatchOut(profiles=batch.profiles),
        expected_ids,
    )
    if not gate.ok:
        raise RuntimeError(
            "Requirement label batch failed validation: " + "; ".join(gate.reasons[:5])
        )
    return batch
