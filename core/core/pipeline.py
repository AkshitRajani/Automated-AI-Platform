"""
The Pipeline facade — one object the web backend (or the CLI) drives.

It owns the config and the trace emitter, and exposes the two flows. Attach
listeners to ``pipe.trace`` to observe everything (the web layer adds MLflow + a
live feed; the CLI adds a stdout sink).
"""
from __future__ import annotations

from typing import Optional

from .config import CoreConfig
from .generate import GenerateResult, generate
from .onboarding import OnboardResult, onboard
from .score import ScoreResult, score_generated
from .trace import TraceEmitter


class Pipeline:
    def __init__(self, cfg: Optional[CoreConfig] = None,
                 trace: Optional[TraceEmitter] = None):
        self.cfg = cfg or CoreConfig.from_env()
        self.trace = trace or TraceEmitter()

    def onboard(self, src: str, app_id: str) -> OnboardResult:
        """codebase (dir / .zip / s3://) → KB."""
        return onboard(src, app_id, self.cfg, self.trace)

    def generate(self, ticket_text: str, diff: str, app_id: str,
                 workspace_dir: str, framework: str = "behave",
                 ticket_id: str = "TICKET",
                 source_dir: Optional[str] = None) -> GenerateResult:
        """ticket + diff → a delivered (or repaired/escalated) test."""
        return generate(ticket_id, ticket_text, diff, app_id,
                        workspace_dir, framework, self.cfg, self.trace,
                        source_dir=source_dir)

    def score(self, app_id: str, generated_dir: str,
              golden_dir: Optional[str] = None,
              output_dir: Optional[str] = None,
              threshold: Optional[float] = None) -> ScoreResult:
        """Compare generated BDD features against golden manual BDD → JSON + HTML."""
        return score_generated(
            app_id, generated_dir, self.cfg, self.trace,
            golden_dir=golden_dir,
            output_dir=output_dir,
            threshold=threshold,
        )
