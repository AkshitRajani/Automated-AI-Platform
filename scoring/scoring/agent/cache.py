"""
Content-addressed profile cache — same inputs → same profiles, zero Bedrock tokens.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import profile_cache_dir, prompt_version


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.name.encode("utf-8"))
    try:
        h.update(path.read_bytes())
    except OSError:
        h.update(b"<unreadable>")
    return h.hexdigest()


def fingerprint_paths(paths: Iterable[Path]) -> str:
    """Stable hash over sorted file paths and contents."""
    digest = hashlib.sha256()
    digest.update(f"prompt_version={prompt_version()}".encode("utf-8"))
    for path in sorted(paths, key=lambda p: str(p).lower()):
        if path.is_file():
            digest.update(_file_digest(path).encode("utf-8"))
        elif path.is_dir():
            for child in sorted(path.rglob("*"), key=lambda p: str(p).lower()):
                if child.is_file() and child.suffix.lower() in (".feature", ".json", ".md"):
                    digest.update(_file_digest(child).encode("utf-8"))
    return digest.hexdigest()[:32]


def fingerprint_strings(items: Iterable[str]) -> str:
    digest = hashlib.sha256()
    digest.update(f"prompt_version={prompt_version()}".encode("utf-8"))
    for item in sorted(items):
        digest.update(item.encode("utf-8"))
    return digest.hexdigest()[:32]


def cache_path(kind: str, fingerprint: str) -> Path:
    return profile_cache_dir() / f"{kind}_{fingerprint}.json"


def load_cached_profiles(kind: str, fingerprint: str) -> Optional[Dict[str, dict]]:
    path = cache_path(kind, fingerprint)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("fingerprint") != fingerprint:
        return None
    if payload.get("prompt_version") != prompt_version():
        return None
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        return None
    return profiles


def save_cached_profiles(kind: str, fingerprint: str, profiles: Dict[str, dict]) -> Path:
    profile_cache_dir().mkdir(parents=True, exist_ok=True)
    path = cache_path(kind, fingerprint)
    payload = {
        "fingerprint": fingerprint,
        "prompt_version": prompt_version(),
        "kind": kind,
        "profiles": profiles,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def collect_paths_from_source(source: str | Path) -> List[Path]:
    path = Path(source).expanduser().resolve()
    if path.is_file():
        return [path]
    if path.is_dir():
        return [
            p for p in path.rglob("*")
            if p.is_file() and p.suffix.lower() in (".feature", ".json", ".md")
            and p.name.lower() != "readme.md"
        ]
    return []
