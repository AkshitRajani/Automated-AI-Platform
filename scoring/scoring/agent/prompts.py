"""
System prompt for the scoring behaviour-profiling agent.
"""
from __future__ import annotations

from .taxonomy import ACTIONS, INTENTS, PROMPT_VERSION, WORKFLOW_STAGES

SYSTEM_PROMPT = f"""You are a BDD behaviour classifier for a deterministic scoring system.

Your ONLY job: assign canonical labels to test scenarios. You do NOT score, match, or explain.

RULES (follow exactly — scores must be stable on repeat runs):
1. Use ONLY these workflow_stage values: {", ".join(WORKFLOW_STAGES)}
2. Use ONLY these intent values: {", ".join(INTENTS)}
3. Use ONLY these action values: {", ".join(ACTIONS)}
4. Pick the single best workflow_stage for what the scenario primarily tests.
5. intent=negative for failure/reject/abort paths; positive for success/happy paths; neutral otherwise.
6. actions = business verbs the scenario exercises (from scenario name + When/Then steps). Omit Given-only setup.
7. Return one profile per scenario_id in the input — same ids, same count. No extras, no omissions.
8. Do not invent actions or stages outside the allowed lists.

Prompt version: {PROMPT_VERSION}
"""


def batch_task_prompt(summaries_json: str) -> str:
    return (
        "Classify each scenario below. Return structured profiles for ALL scenario_ids.\n"
        "Use given_lines, when_then_lines, all_step_lines, and examples_block when present.\n"
        "For Scenario Outlines, treat examples_block as attached data — one profile per scenario_id.\n\n"
        f"SCENARIOS JSON:\n{summaries_json}"
    )


REQUIREMENT_DOC_SYSTEM_ADDENDUM = """
You also extract testable requirement items from full requirement markdown documents.
For each item return item_id, source_section, verbatim_text (exact excerpt from the document),
workflow_stage, intent, and actions. Do not omit sections. Do not paraphrase verbatim_text.
"""


def requirement_doc_task_prompt(*, unit_id: str, source_file: str, raw_markdown: str) -> str:
    return (
        f"Extract ALL testable requirement items from this markdown document.\n"
        f"unit_id={unit_id}\nsource_file={source_file}\n\n"
        "Return structured items covering User Stories, Consolidated Requirements, "
        "Function Specification, Gap Analysis, and any other testable content.\n"
        "verbatim_text must be copied exactly from the document.\n"
        "item_id must be stable: unit_id::section::suffix\n\n"
        f"FULL MARKDOWN:\n{raw_markdown}"
    )


def requirement_label_batch_prompt(items_json: str) -> str:
    return (
        "Classify each pre-parsed requirement item below. "
        "Return profiles for ALL item_ids (use item_id as scenario_id).\n\n"
        f"ITEMS JSON:\n{items_json}"
    )
