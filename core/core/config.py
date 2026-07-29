"""
Core configuration — every knob from `.env` / env, nothing hardcoded.

Reuses `ingestion.config.load_config` (so the core shares one `.env` with ingestion,
the coding agent, and the analyzer) and adds the orchestration knobs: the onboarding
source default, the execution-env selector, the quad staging dir, and the repair
cap. AWS credentials and store endpoints are inherited from the shared config
(Postgres / Neptune / Bedrock), so the same file configures the whole system.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ingestion.config import load_config


class ConfigError(RuntimeError):
    """A required setting is missing — fail fast, never assume a default."""


@dataclass
class CoreConfig:
    shared: dict                    # {postgres, neptune, bedrock} from ingestion
    eval_env: str                   # "inprocess" (default) | "sandbox"
    sandbox_dir: str                # path to the sandbox (when eval_env="sandbox")
    quad_dir: str                   # where merged quad YAMLs are staged for ingestion
    aws_region: str
    max_repairs: int
    stability_runs: int
    mutation_max: int
    golden_bdd_root: str            # root folder for manual golden BDD per app
    score_output_dir: str           # where score_report.{json,html} are written
    scoring_threshold: float        # behaviour match threshold (0..1)

    @classmethod
    def from_env(cls) -> "CoreConfig":
        shared = load_config()
        return cls(
            shared=shared,
            eval_env=os.environ.get("CORE_EVAL_ENV", "inprocess").strip().lower(),
            sandbox_dir=os.environ.get("CORE_SANDBOX_DIR", ""),
            quad_dir=os.environ.get("CORE_QUAD_DIR", ""),   # "" → a temp dir per run
            aws_region=shared["bedrock"]["region"],
            max_repairs=int(os.environ.get("CORE_MAX_REPAIRS", "2")),
            stability_runs=int(os.environ.get("CORE_STABILITY_RUNS", "3")),
            mutation_max=int(os.environ.get("CORE_MUTATION_MAX", "8")),
            golden_bdd_root=os.environ.get("CORE_GOLDEN_BDD_ROOT", "golden_bdd"),
            score_output_dir=os.environ.get("CORE_SCORE_OUTPUT_DIR", ""),
            scoring_threshold=float(os.environ.get("SCORING_THRESHOLD", "0.45")),
        )

    # --- convenience accessors -------------------------------------------------

    @property
    def bedrock_model_arn(self) -> str:
        arn = self.shared["bedrock"].get("model_arn", "")
        if not arn:
            raise ConfigError(
                "BEDROCK_MODEL_ARN is not set. The analyzer agent and coding agent "
                "need it; set it in .env (ARN or model id). Never assumed."
            )
        return arn

    @property
    def has_bedrock(self) -> bool:
        return bool(self.shared["bedrock"].get("model_arn"))

    @property
    def has_postgres(self) -> bool:
        return bool(self.shared["postgres"].get("password") or
                    self.shared["postgres"].get("host"))
