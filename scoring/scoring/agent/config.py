"""
Bedrock and profiling settings for the scoring agent.

Scoring uses Claude Opus 4.8 (same as Coding / Requirement / Analyzer agents) unless
overridden via SCORING_BEDROCK_MODEL_ARN or BEDROCK_MODEL_ARN.
"""
from __future__ import annotations

from pathlib import Path

from ..config import _PACKAGE_DIR, _env_bool, _env_str

# Same model id as requirement_agent / coding_agent (.env.example).
DEFAULT_SCORING_MODEL_ARN = "us.anthropic.claude-opus-4-8"
# IAM for this project is often scoped to us-east-2 — override with AWS_REGION if needed.
DEFAULT_SCORING_REGION = "us-east-2"


class AgentConfigError(RuntimeError):
    """Raised when agent mode is requested but Bedrock is not configured."""


def resolved_model_arn() -> str:
    """Model for scoring — explicit env wins, else Opus default."""
    return _env_str("SCORING_BEDROCK_MODEL_ARN", "BEDROCK_MODEL_ARN") or DEFAULT_SCORING_MODEL_ARN


def _has_aws_credentials() -> bool:
    return bool(_env_str("AWS_ACCESS_KEY_ID") and _env_str("AWS_SECRET_ACCESS_KEY"))


def bedrock_settings() -> dict:
    """Bedrock model settings for the profiling agent."""
    if not has_bedrock():
        raise AgentConfigError(
            "Bedrock not configured for scoring. Add AWS_ACCESS_KEY_ID, "
            "AWS_SECRET_ACCESS_KEY, and optionally BEDROCK_MODEL_ARN to .env. "
            f"Scoring defaults to {DEFAULT_SCORING_MODEL_ARN} in {DEFAULT_SCORING_REGION}."
        )
    return {
        "model_arn": resolved_model_arn(),
        "region": _env_str("AWS_REGION", "SCORING_AWS_REGION", default=DEFAULT_SCORING_REGION),
    }


def has_bedrock() -> bool:
    """True when explicit model env is set or AWS access keys are present."""
    if _env_str("SCORING_BEDROCK_MODEL_ARN", "BEDROCK_MODEL_ARN"):
        return True
    return _has_aws_credentials()


def profiling_mode() -> str:
    """regex | agent | auto — auto uses agent when Bedrock is configured."""
    mode = _env_str("SCORING_PROFILING_MODE", default="auto").lower()
    if mode not in ("regex", "agent", "auto"):
        return "auto"
    return mode


def resolve_profiling_mode(explicit: str | None = None) -> str:
    mode = (explicit or profiling_mode()).lower()
    if mode == "auto":
        return "agent" if has_bedrock() else "regex"
    return mode


def profile_cache_dir() -> Path:
    raw = _env_str("SCORING_PROFILE_CACHE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (_PACKAGE_DIR / ".profile_cache").resolve()


def prompt_version() -> str:
    return _env_str("SCORING_PROMPT_VERSION", default="3")


def requirement_compact_line_limit() -> int:
    """MD/JSON docs above this line count use compact item labelling, not full MD."""
    raw = _env_str("SCORING_REQUIREMENT_COMPACT_LINE_LIMIT")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 150


def requirement_compact_byte_limit() -> int:
    raw = _env_str("SCORING_REQUIREMENT_COMPACT_BYTE_LIMIT")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 20_000


def requirement_compact_item_limit() -> int:
    raw = _env_str("SCORING_REQUIREMENT_COMPACT_ITEM_LIMIT")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 40


def agent_max_tokens() -> int:
    raw = _env_str("SCORING_AGENT_MAX_TOKENS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 8192


def requirement_md_direct_limit() -> int:
    """When MD file count is at or below this, send each full file to Bedrock."""
    raw = _env_str("SCORING_REQUIREMENT_MD_DIRECT_LIMIT")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 15


def requirement_label_batch_size() -> int:
    """Pre-parsed requirement items per Bedrock call when above direct limit."""
    raw = _env_str("SCORING_REQUIREMENT_LABEL_BATCH_SIZE")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 25


def requirement_label_batch_char_limit() -> int:
    """Max combined verbatim_text chars per Bedrock label batch."""
    raw = _env_str("SCORING_REQUIREMENT_LABEL_BATCH_CHAR_LIMIT")
    if raw:
        try:
            return max(1000, int(raw))
        except ValueError:
            pass
    return 12_000


def requirement_label_concurrency() -> int:
    """Parallel Bedrock label batches (same model quota applies)."""
    raw = _env_str("SCORING_REQUIREMENT_LABEL_CONCURRENCY")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 3


def requirement_force_compact() -> bool:
    """Always use tier extract + batched labelling; skip full-MD Bedrock calls."""
    return _env_bool("SCORING_REQUIREMENT_FORCE_COMPACT", default=True)


def requirement_aggregate_stories() -> bool:
    """One Bedrock item per user story (all G/W/T ACs combined)."""
    return _env_bool("SCORING_REQUIREMENT_AGGREGATE_STORIES", default=True)


def requirement_include_secondary_for_agent() -> bool:
    """Include Function Spec / Gap items in agent extraction (regex if false)."""
    return _env_bool("SCORING_REQUIREMENT_INCLUDE_SECONDARY", default=False)


def requirement_dedupe_shall_against_stories() -> bool:
    """Drop consolidated shall bullets redundant with user stories."""
    return _env_bool("SCORING_REQUIREMENT_DEDUPE_SHALL", default=True)


def bypass_tool_consent() -> bool:
    return _env_bool("BYPASS_TOOL_CONSENT", "STRANDS_BYPASS_TOOL_CONSENT", default=True)
