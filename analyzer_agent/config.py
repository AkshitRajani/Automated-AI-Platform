"""
Configuration for the Analyzer Agent.

We do **not** re-implement config loading: the ``.env`` is shared across ingestion,
the coding agent, and this agent. This module reuses ``ingestion.config.load_config``
verbatim and adds analyzer-specific accessors. Every value comes from ``.env`` /
process env — nothing is hardcoded, and the model is **never defaulted**.

Run with the implementation dir on the path (same convention as the others)::

    PYTHONPATH=/path/to/2026/implementation python -m analyzer_agent <repo> --app-id X
"""
from __future__ import annotations

import os

from ._env import load_config


class ConfigError(RuntimeError):
    """Raised when a required setting is missing, so the agent fails fast instead
    of silently running against a default it should never assume."""


def get_config() -> dict:
    """The full shared config dict: ``{postgres, neptune, bedrock}``."""
    return load_config()


def bedrock_settings() -> dict:
    """Bedrock model settings for the Strands ``BedrockModel``.

    Raises:
        ConfigError: if ``BEDROCK_MODEL_ARN`` is unset — the model id is never
            defaulted, because guessing a model is exactly the silent assumption
            we refuse to make.
    """
    bedrock = load_config()["bedrock"]
    if not bedrock.get("model_arn"):
        raise ConfigError(
            "BEDROCK_MODEL_ARN is not set. Set it in .env (an inference-profile "
            "ARN or a plain Bedrock model id). The agent never assumes a model."
        )
    return bedrock


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def analyzer_settings() -> dict:
    """All analyzer-agent knobs, every one parameterized via env / .env.

    None of these are hardcoded behaviour: the same binary behaves differently
    purely from config, so a run can be made cheaper (fan-out off), narrower
    (changed-only), or multi-language without touching code.
    """
    return {
        # Which front-ends the agent should consider. v1 ships "python".
        "languages": [s.strip() for s in
                      os.environ.get("ANALYZER_LANGUAGES", "python").split(",") if s.strip()],
        # Hard cap on the autonomous loop (cost guardrail).
        "max_iterations": int(os.environ.get("ANALYZER_MAX_ITERATIONS", "40")),
        # Sub-agent fan-out: one isolated explorer per module, summary-only.
        "fanout": _flag("ANALYZER_FANOUT", False),
        "max_subagents": int(os.environ.get("ANALYZER_MAX_SUBAGENTS", "4")),
        # "exhaustive" (once per app) vs "changed-only" (re-onboard a diff).
        "scope": os.environ.get("ANALYZER_SCOPE", "exhaustive"),
        # Optional LSP-over-MCP endpoint (pyright/jdtls). Empty → LSP tool not wired,
        # the agent leans on grep + the parser's CALLS facts. Graceful degrade.
        "lsp_endpoint": os.environ.get("ANALYZER_LSP_ENDPOINT", ""),
    }
