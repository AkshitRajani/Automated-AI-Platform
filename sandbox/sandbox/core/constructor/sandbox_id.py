"""Compute sandbox_id = sha256(spec + every seed file's bytes)."""

import hashlib
from pathlib import Path


def compute_sandbox_id(profile_dir: Path) -> str:
    """sandbox_id binds verdicts to the exact spec + seed contents.

    Hashes:
      - spec.yaml bytes
      - every file under attachments/ (excluding manifest.json files)

    Sorted by path for determinism.
    """
    h = hashlib.sha256()
    spec = profile_dir / "spec.yaml"
    h.update(spec.read_bytes())

    attach = profile_dir / "attachments"
    files = sorted(
        f for f in attach.rglob("*")
        if f.is_file() and f.name != "manifest.json" and ".DS_Store" not in f.name
    )
    for f in files:
        h.update(str(f.relative_to(profile_dir)).encode())
        h.update(b"\0")
        h.update(f.read_bytes())

    return h.hexdigest()
