"""
Configuration loader.
Reads from .env file first, then falls back to environment variables.
"""
import os
from pathlib import Path


def load_config() -> dict:
    """
    Load pipeline configuration from .env file or environment variables.
    """
    _load_dotenv()

    return {
        "postgres": {
            "host": os.environ.get("PG_HOST", "localhost"),
            "port": int(os.environ.get("PG_PORT", "5432")),
            "database": os.environ.get("PG_DATABASE", "knowledge_base"),
            "user": os.environ.get("PG_USER", "postgres"),
            "password": os.environ.get("PG_PASSWORD", ""),
        },
        # Neptune — kept for reference/rollback, no longer wired up by
        # coding_agent/kb/graph.py (replaced by "neo4j" below).
        "neptune": {
            "endpoint": os.environ.get("NEPTUNE_ENDPOINT", ""),
            "port": int(os.environ.get("NEPTUNE_PORT", "8182")),
            "s3_bucket": os.environ.get("NEPTUNE_S3_BUCKET", ""),
            "iam_role_arn": os.environ.get("NEPTUNE_IAM_ROLE", ""),
            # Neptune + its load bucket may live in a different region than Bedrock.
            "region": os.environ.get("NEPTUNE_REGION", os.environ.get("AWS_REGION", "us-east-1")),
        },
        "neo4j": {
            "uri": os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            "user": os.environ.get("NEO4J_USER", "neo4j"),
            "password": os.environ.get("NEO4J_PASSWORD", ""),
        },
        "bedrock": {
            "model_arn": os.environ.get("BEDROCK_MODEL_ARN", ""),
            "embedding_model": os.environ.get(
                "BEDROCK_EMBEDDING_MODEL",
                "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
            ),
            "region": os.environ.get("AWS_REGION", "us-east-1"),
        },
    }


def _load_dotenv():
    """Load .env file if it exists. No external dependency needed."""
    env_path = Path(".env")
    if not env_path.exists():
        # Also check parent directories (for running from sub-folders)
        for parent in Path.cwd().parents:
            candidate = parent / "ingestion" / ".env"
            if candidate.exists():
                env_path = candidate
                break
            candidate = parent / ".env"
            if candidate.exists():
                env_path = candidate
                break

    if not env_path.exists():
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                # Don't override existing env vars
                if key not in os.environ or not os.environ[key]:
                    os.environ[key] = value
