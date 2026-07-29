"""
Self-contained .env / environment loader for the analyzer agent.

The agent reads exactly one thing from config: the Bedrock model settings (for the
Strands BedrockModel). This vendors the shared loader so the analyzer bundle has
**no dependency on any other package** — point it at a ``.env`` (or rely on process
env) and nothing is hardcoded. The model id is never defaulted.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_config() -> dict:
    """Load config from a ``.env`` file (then process env) → ``{bedrock: {...}}``."""
    _load_dotenv()
    return {
        "bedrock": {
            "model_arn": os.environ.get("BEDROCK_MODEL_ARN", ""),
            "embedding_model": os.environ.get(
                "BEDROCK_EMBEDDING_MODEL",
                "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0",
            ),
            "region": os.environ.get("AWS_REGION", "us-east-1"),
        },
    }


def _load_dotenv() -> None:
    """Load a ``.env`` if present (cwd, then parent dirs). No external dependency.
    Never overrides a value already set in the environment."""
    env_path = Path(".env")
    if not env_path.exists():
        for parent in [Path.cwd(), *Path.cwd().parents]:
            candidate = parent / ".env"
            if candidate.exists():
                env_path = candidate
                break
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key not in os.environ or not os.environ[key]:
                os.environ[key] = value
