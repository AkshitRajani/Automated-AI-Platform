"""
Load scoring settings from ``.env`` next to this package (``scoring/scoring/.env``).

CLI flags override values from the file. Environment variables already set in
the shell override the file as well (file uses ``setdefault``).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_ENV_FILE = _PACKAGE_DIR / ".env"
_DEFAULT_SCORING_ROOT = _PACKAGE_DIR.parent


def default_scoring_root() -> Path:
    """Outer ``scoring/`` folder (parent of the Python package)."""
    return _DEFAULT_SCORING_ROOT


def resolve_scoring_root() -> Path:
    """Scoring root from ``SCORING_ROOT``, ``PYTHONPATH``, or package layout."""
    explicit = _env_str("SCORING_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    py_path = _env_str("PYTHONPATH")
    if py_path:
        first = py_path.split(os.pathsep)[0].strip()
        if first:
            return Path(first).expanduser().resolve()
    return _DEFAULT_SCORING_ROOT.resolve()


def apply_python_path() -> Path:
    """Ensure the scoring root is on ``sys.path`` and ``PYTHONPATH``."""
    root = resolve_scoring_root()
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    existing = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if root_s not in parts:
        os.environ["PYTHONPATH"] = root_s if not existing else f"{root_s}{os.pathsep}{existing}"
    return root


def env_file_path() -> Path:
    """Path to the ``.env`` file shipped beside ``__main__.py``."""
    return _DEFAULT_ENV_FILE


def load_env_file(path: Optional[Path] = None) -> Path | None:
    """Parse a ``.env`` file into ``os.environ``. Returns the path if read."""
    env_path = Path(path) if path else _DEFAULT_ENV_FILE
    if not env_path.is_file():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return env_path


def _env_str(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return default


def _env_float(*keys: str, default: float) -> float:
    raw = _env_str(*keys)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(*keys: str, default: bool = False) -> bool:
    raw = _env_str(*keys).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_int(*keys: str, default: int) -> int:
    raw = _env_str(*keys)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class ScoringConfig:
    """Paths and options for standalone scoring."""

    golden_zip: str = ""
    generated_zip: str = ""
    requirements_zip: str = ""
    requirements_dir: str = ""
    golden_dir: str = ""
    generated_dir: str = ""
    output_dir: str = "."
    threshold: float = 0.45
    open_report: bool = False
    serve_host: str = "127.0.0.1"
    serve_port: int = 8766
    runs_dir: str = ""
    scoring_root: str = ""
    env_file: str = ""
    profiling_mode: str = "auto"
    profile_cache_dir: str = ""
    prompt_version: str = "1"

    @classmethod
    def load(cls, env_path: Optional[Path] = None) -> "ScoringConfig":
        loaded = load_env_file(env_path)
        root = resolve_scoring_root()
        return cls(
            golden_zip=_env_str("SCORING_GOLDEN_ZIP", "GOLDEN_ZIP"),
            generated_zip=_env_str("SCORING_GENERATED_ZIP", "GENERATED_ZIP"),
            requirements_zip=_env_str("SCORING_REQUIREMENTS_ZIP", "REQUIREMENTS_ZIP"),
            golden_dir=_env_str("SCORING_GOLDEN", "GOLDEN_DIR", "GOLDEN"),
            generated_dir=_env_str("SCORING_GENERATED", "GENERATED_DIR", "GENERATED"),
            requirements_dir=_env_str("SCORING_REQUIREMENTS", "REQUIREMENTS_DIR", "REQUIREMENTS"),
            output_dir=_env_str("SCORING_OUTPUT_DIR", "OUTPUT_DIR", default="."),
            threshold=_env_float("SCORING_THRESHOLD", "THRESHOLD", default=0.45),
            open_report=_env_bool("SCORING_OPEN", "OPEN_REPORT", default=False),
            serve_host=_env_str("SCORING_SERVE_HOST", default="127.0.0.1"),
            serve_port=_env_int("SCORING_SERVE_PORT", default=8766),
            runs_dir=_env_str("SCORING_RUNS_DIR", "RUNS_DIR"),
            scoring_root=str(root),
            env_file=str(loaded) if loaded else "",
            profiling_mode=_env_str("SCORING_PROFILING_MODE", default="auto").lower(),
            profile_cache_dir=_env_str("SCORING_PROFILE_CACHE_DIR"),
            prompt_version=_env_str("SCORING_PROMPT_VERSION", default="1"),
        )

    @property
    def has_bedrock(self) -> bool:
        from .agent.config import has_bedrock as _has_bedrock
        return _has_bedrock()

    @property
    def has_zip_paths(self) -> bool:
        return bool(self.golden_zip and self.generated_zip)

    @property
    def has_dir_paths(self) -> bool:
        return bool(self.golden_dir and self.generated_dir)
