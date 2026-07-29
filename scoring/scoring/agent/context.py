"""
Profiling mode context for the duration of a score() run.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_profiling_mode: ContextVar[str] = ContextVar("scoring_profiling_mode", default="regex")
_source_fingerprints: ContextVar[dict] = ContextVar("scoring_source_fingerprints", default={})
_strict_matching: ContextVar[bool] = ContextVar("scoring_strict_matching", default=False)


def get_profiling_mode() -> str:
    return _profiling_mode.get()


def get_strict_matching() -> bool:
    """Strict behaviour matching is always enabled when using the Bedrock agent."""
    return _strict_matching.get()


def get_source_fingerprint(kind: str) -> Optional[str]:
    return _source_fingerprints.get().get(kind)


@contextmanager
def profiling_context(
    mode: str,
    *,
    fingerprints: Optional[dict] = None,
) -> Iterator[None]:
    mode_token = _profiling_mode.set(mode)
    fp_token = _source_fingerprints.set(fingerprints or {})
    strict_token = _strict_matching.set(mode == "agent")
    try:
        yield
    finally:
        _profiling_mode.reset(mode_token)
        _source_fingerprints.reset(fp_token)
        _strict_matching.reset(strict_token)
