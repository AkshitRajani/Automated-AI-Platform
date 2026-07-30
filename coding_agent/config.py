"""
Configuration for the Coding Agent.

We do **not** re-implement config loading. The ``.env`` is explicitly shared
between ingestion and the coding agent (see ``implementation/.env.example``), so
this module reuses ``ingestion.config.load_config`` verbatim and only adds the
agent-specific accessors. Every value comes from ``.env`` / process env — nothing
is hardcoded.

Run with the implementation dir on the path (same convention as the validator):

    PYTHONPATH=/path/to/2026/implementation python -m coding_agent ...
"""
from __future__ import annotations

from coding_agent._env import load_config


class ConfigError(RuntimeError):
    """Raised when a required setting is missing, so the agent fails fast
    instead of silently running against a default it should never assume."""


def get_config() -> dict:
    """The full shared config dict: ``{postgres, neptune, bedrock}``."""
    return load_config()


def postgres_dsn_kwargs() -> dict:
    """psycopg2 connection kwargs for the live KB facts (kb_query)."""
    pg = load_config()["postgres"]
    return {
        "host": pg["host"],
        "port": pg["port"],
        "database": pg["database"],
        "user": pg["user"],
        "password": pg["password"],
    }


def neptune_settings() -> dict:
    """Neptune connection settings — kept for reference/rollback, no longer
    called by kb_graph (see neo4j_settings below). ``endpoint`` is empty when
    Neptune is not configured — callers must degrade gracefully (slice 1 treats
    Neptune as optional)."""
    return load_config()["neptune"]


def neo4j_settings() -> dict:
    """Neo4j connection settings for kb_graph — replaces neptune_settings().
    ``uri`` is empty when Neo4j is not configured — callers must degrade
    gracefully, same optionality contract as Neptune before it."""
    return load_config()["neo4j"]


def bedrock_settings() -> dict:
    """Bedrock model settings for the Strands BedrockModel.

    Raises:
        ConfigError: if ``BEDROCK_MODEL_ARN`` is unset — the model id is never
            defaulted, because guessing a model is exactly the kind of silent
            assumption we refuse to make.
    """
    bedrock = load_config()["bedrock"]
    if not bedrock.get("model_arn"):
        raise ConfigError(
            "BEDROCK_MODEL_ARN is not set. Set it in .env (an inference-profile "
            "ARN or a plain Bedrock model id). The agent never assumes a model."
        )
    return bedrock
