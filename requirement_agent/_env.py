"""
Configuration loader (shared shape with ingestion / coding agent).
Reads from a .env file first, then falls back to environment variables. No
external dependency. The requirement agent only needs the Bedrock block (it does
not touch Postgres/Neptune), but the full shape is kept for consistency.
"""
import os
from pathlib import Path


def load_config() -> dict:
    """Load configuration from a .env file or environment variables."""
    _load_dotenv()
    return {
        "bedrock": {
            "model_arn": os.environ.get("BEDROCK_MODEL_ARN", ""),
            "region": os.environ.get("AWS_REGION", "us-east-1"),
        },
    }


def _load_dotenv():
    """Load a .env file if present (cwd, then parents). No override of set vars."""
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
