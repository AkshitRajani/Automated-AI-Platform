"""
Unzip manual and generated feature folders for standalone scoring.

Accepts a ``.zip`` that contains ``.feature`` files at any depth (flat files,
a ``features/`` folder, or a nested project layout).

Manual (golden) zips may also include requirement ``.md`` / ``.json`` files —
those are collected for scoring alongside an optional dedicated requirements zip.
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple


class ZipInputError(Exception):
    """Invalid or empty feature zip."""


def _validate_zip(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ZipInputError(f"not a file: {resolved}")
    if not zipfile.is_zipfile(resolved):
        raise ZipInputError(f"not a zip archive: {resolved}")
    return resolved


def _feature_count(root: Path) -> int:
    return sum(1 for _ in root.rglob("*.feature"))


def _doc_paths(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in (".json", ".md")
        and not p.name.lower().startswith("readme")
    )


def _doc_count(root: Path) -> int:
    return len(_doc_paths(root))


def resolve_feature_root(extracted: Path) -> Path:
    """Return a directory tree that contains ``.feature`` files."""
    if _feature_count(extracted) == 0:
        raise ZipInputError(
            f"No .feature files found under {extracted}. "
            f"Zip your manual or generated feature folder and try again."
        )
    return extracted


def extract_feature_zip(zip_path: str | Path, dest: Path) -> Path:
    """Extract ``zip_path`` into ``dest`` and return the feature root."""
    archive = _validate_zip(zip_path)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(dest)
    return resolve_feature_root(dest)


def resolve_requirements_root(extracted: Path) -> Path:
    """Return a directory tree that contains requirement ``.json`` or ``.md`` files."""
    if _doc_count(extracted) == 0:
        raise ZipInputError(
            f"No requirement .json or .md files found under {extracted}. "
            f"Zip the requirement-agent output folder and try again."
        )
    return extracted


def extract_requirements_zip(zip_path: str | Path, dest: Path) -> Path:
    """Extract requirement docs zip into ``dest`` and return the root."""
    archive = _validate_zip(zip_path)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(dest)
    return resolve_requirements_root(dest)


def copy_requirement_docs(source_root: Path, dest_root: Path) -> int:
    """Copy ``.md`` / ``.json`` docs from ``source_root`` into ``dest_root``. Returns count."""
    dest_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in _doc_paths(source_root):
        target = dest_root / path.name
        # Avoid overwrite collisions from different nested folders with the same name.
        if target.exists():
            stem, suffix = path.stem, path.suffix
            n = 2
            while True:
                candidate = dest_root / f"{stem}_{n}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                n += 1
        shutil.copy2(path, target)
        copied += 1
    return copied


class FeatureZipPair:
    """Context manager: unzip feature archives (+ optional requirements) and clean up."""

    def __init__(
        self,
        golden_zip: str | Path,
        generated_zip: str | Path,
        *,
        requirements_zip: str | Path | None = None,
        work_dir: Optional[str | Path] = None,
    ) -> None:
        self.golden_zip = golden_zip
        self.generated_zip = generated_zip
        self.requirements_zip = requirements_zip
        self.work_dir = Path(work_dir) if work_dir else None
        self._tmpdir: Optional[Path] = None
        self.golden_dir: Optional[Path] = None
        self.generated_dir: Optional[Path] = None
        self.requirements_dir: Optional[Path] = None
        self._owned_tmp = False

    def __enter__(self) -> Tuple[Path, Path]:
        if self.work_dir is None:
            self._tmpdir = Path(tempfile.mkdtemp(prefix="scoring_"))
            self._owned_tmp = True
            base = self._tmpdir
        else:
            base = self.work_dir
            base.mkdir(parents=True, exist_ok=True)

        self.golden_dir = extract_feature_zip(
            self.golden_zip, base / "golden",
        )
        self.generated_dir = extract_feature_zip(
            self.generated_zip, base / "generated",
        )

        # Dedicated requirements zip and/or .md/.json living inside the manual zip.
        merged = base / "requirements"
        copied = 0
        if self.requirements_zip:
            explicit = extract_requirements_zip(
                self.requirements_zip, base / "requirements_explicit",
            )
            copied += copy_requirement_docs(explicit, merged)
        copied += copy_requirement_docs(self.golden_dir, merged)
        self.requirements_dir = merged if copied else None

        return self.golden_dir, self.generated_dir

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._owned_tmp and self._tmpdir and self._tmpdir.exists():
            shutil.rmtree(self._tmpdir, ignore_errors=True)
