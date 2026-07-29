"""Bedrock behaviour-profiling agent for deterministic scoring (Claude Opus 4.8)."""
from .config import (
    DEFAULT_SCORING_MODEL_ARN,
    DEFAULT_SCORING_REGION,
    has_bedrock,
    profiling_mode,
    resolve_profiling_mode,
)
from .context import get_profiling_mode, profiling_context

__all__ = [
    "has_bedrock",
    "profiling_mode",
    "resolve_profiling_mode",
    "get_profiling_mode",
    "profiling_context",
    "DEFAULT_SCORING_MODEL_ARN",
    "DEFAULT_SCORING_REGION",
]
