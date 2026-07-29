"""
Requirement document contract — aligned with requirement_agent/schemas.py.

Single source of truth for canonical sections and extraction tiers used by scoring.
"""
from __future__ import annotations

from typing import FrozenSet, Literal

# Same nine sections as requirement_agent RequirementDoc (case/number insensitive).
CANONICAL_SECTIONS: tuple[str, ...] = (
    "System Overview",
    "Input Specification",
    "Consolidated Requirements",
    "Output Specification",
    "Function Specification",
    "User Stories",
    "Traceability Matrix",
    "Confidence Mapping",
    "Gap Analysis",
)

ExtractionTier = Literal["primary", "secondary", "metadata", "fallback"]


def section_key(name: str) -> str:
    """Normalize section name — matches requirement_agent.schemas.section_key."""
    s = (name or "").strip().lower()
    while s and (s[0].isdigit() or s[0] in ".)-: "):
        s = s[1:]
    return s.strip()


_CANON_KEYS: FrozenSet[str] = frozenset(section_key(s) for s in CANONICAL_SECTIONS)

# Tier A: behavioural oracle (User Stories ACs, shall bullets)
_TIER_PRIMARY: FrozenSet[str] = frozenset({
    section_key("User Stories"),
    section_key("Consolidated Requirements"),
})

# Tier B: selective secondary context
_TIER_SECONDARY: FrozenSet[str] = frozenset({
    section_key("Function Specification"),
    section_key("Gap Analysis"),
})

# Tier C: metadata — preserve in doc model, skip for Bedrock extraction
_TIER_METADATA: FrozenSet[str] = frozenset({
    section_key("Traceability Matrix"),
    section_key("Confidence Mapping"),
    section_key("Input Specification"),
    section_key("Output Specification"),
    section_key("System Overview"),
})


def extraction_tier(section_name: str) -> ExtractionTier:
    """Classify a section for tiered extraction."""
    key = section_key(section_name)
    if key in _TIER_PRIMARY:
        return "primary"
    if key in _TIER_SECONDARY:
        return "secondary"
    if key in _CANON_KEYS and key in _TIER_METADATA:
        return "metadata"
    if key in _CANON_KEYS:
        return "metadata"
    # Extra sections (10+) from requirement agent — treat as secondary
    return "secondary"


def is_metadata_section(section_name: str) -> bool:
    return extraction_tier(section_name) == "metadata"
