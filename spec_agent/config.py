"""
Configuration for the Requirement Agent. Every value comes from ``.env`` /
process env — nothing is hardcoded, and the model id is never defaulted.

    PYTHONPATH=/path/to/2026/implementation python -m spec_agent ...
"""
from __future__ import annotations

from spec_agent._env import load_config


class ConfigError(RuntimeError):
    """Raised when a required setting is missing, so the agent fails fast instead
    of silently running against a default it should never assume."""


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
