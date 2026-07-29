"""
Pydantic contracts for the scoring profiling agent — kept flat for reliable structured output.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

from .taxonomy import ACTIONS, INTENTS, WORKFLOW_STAGES

WorkflowStage = Literal[
    "bootstrap", "extract", "transform", "validate", "load",
    "monitor", "notify", "e2e", "general",
]
Intent = Literal["positive", "negative", "neutral"]
Action = Literal[
    "initialize", "retrieve", "transform", "validate", "import",
    "monitor", "notify", "retry", "reject", "route", "complete",
    "history", "summarize",
]


class ScenarioProfileOut(BaseModel):
    """Behaviour labels for one BDD scenario or requirement AC."""

    scenario_id: str = Field(
        ...,
        description="Stable id exactly as provided in the input (file::name).",
    )
    workflow_stage: WorkflowStage
    intent: Intent
    actions: List[Action] = Field(
        default_factory=list,
        description="Distinct business actions exercised; sorted, deduplicated.",
    )


class ProfileBatchOut(BaseModel):
    """Profiles for a batch of scenarios — one structured-output response."""

    profiles: List[ScenarioProfileOut]


class ScenarioSummary(BaseModel):
    """Compact input sent to the agent (token-efficient but complete)."""

    scenario_id: str
    feature_file: str
    feature_name: str
    scenario_name: str
    tags: List[str] = Field(default_factory=list)
    given_lines: str = ""
    when_then_lines: str = ""
    all_step_lines: str = ""
    examples_block: str = ""
    is_outline: bool = False


class RequirementItemExtracted(BaseModel):
    """One testable requirement item extracted from a full markdown document."""

    item_id: str
    source_section: str
    verbatim_text: str
    workflow_stage: WorkflowStage
    intent: Intent
    actions: List[Action] = Field(default_factory=list)


class RequirementDocExtractionOut(BaseModel):
    """Structured extraction from one requirement markdown file."""

    unit_id: str
    items: List[RequirementItemExtracted]


class RequirementItemCompact(BaseModel):
    """Pre-parsed item for batched labelling when many MD files are present."""

    item_id: str
    unit_id: str
    source_file: str
    source_section: str
    verbatim_text: str


class RequirementLabelBatchOut(BaseModel):
    """Behaviour labels for pre-parsed requirement items."""

    profiles: List[ScenarioProfileOut]
