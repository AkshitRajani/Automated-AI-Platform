"""
Load requirement documents produced by the requirement agent.

Supports:
  - ``requirements/*.json`` (agent workspace layout)
  - flat ``*.json`` / ``*.md`` in a folder
  - a single file path
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Union

from .contract import CANONICAL_SECTIONS, section_key as _section_key


def _parse_md_sections(text: str) -> Dict[str, str]:
    """Split rendered markdown on ``##`` headers into a section map."""
    sections: Dict[str, str] = {}
    current_key = ""
    current_lines: List[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            heading = line[3:].strip()
            current_key = _section_key(heading)
            current_lines = []
        else:
            current_lines.append(line)
    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()
    return sections


def _load_json_doc(path: Path) -> Dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    sections = data.get("sections")
    if isinstance(sections, dict) and sections:
        return data
    # Markdown-only JSON wrapper is unlikely; accept empty sections as invalid.
    if "unit" in data:
        data.setdefault("sections", {})
        data.setdefault("raw_text", "")
        data.setdefault("_byte_count", 0)
        return data
    return None


def _load_md_doc(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    unit = path.stem
    title = unit
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        title = m.group(1).strip()
    return {
        "unit": unit,
        "unit_type": "",
        "title": title,
        "provenance": "code-derived",
        "requirement_backed": False,
        "sections": _parse_md_sections(text),
        "raw_text": text,
        "_source_file": path.name,
        "_byte_count": len(text.encode("utf-8")),
    }


def _discover_files(root: Path) -> List[Path]:
    """Find requirement docs (prefer ``requirements/`` then any nested ``.md``/``.json``)."""
    req_sub = root / "requirements"
    if req_sub.is_dir():
        files = sorted(
            p for p in req_sub.rglob("*")
            if p.is_file() and p.suffix.lower() in (".json", ".md")
        )
        if files:
            return files
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in (".json", ".md")
    )


def has_requirement_docs(root: Union[str, Path]) -> bool:
    """True if ``root`` contains at least one loadable requirement ``.md`` / ``.json``."""
    path = Path(root)
    if not path.is_dir():
        return False
    return any(
        not p.name.lower().startswith("readme")
        for p in _discover_files(path)
    )


def load_requirements(
    source: Union[str, Path, List[Union[str, Path]]],
) -> List[Dict[str, Any]]:
    """Load requirement docs from one or more directories / files.

    Manual (golden) trees may mix ``.feature`` and ``.md`` / ``.json`` — features
    are ignored here; only requirement docs are loaded.
    """
    if isinstance(source, (list, tuple)):
        roots = list(source)
    else:
        roots = [source]

    docs: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    any_dir = False

    for src in roots:
        path = Path(src).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Requirements path not found: {path}")

        if path.is_file():
            candidates = [path]
        else:
            any_dir = True
            candidates = _discover_files(path)

        for file_path in candidates:
            if file_path.name.lower().startswith("readme"):
                continue
            # Prefer first occurrence when the same filename appears in multiple roots.
            key = file_path.name.lower()
            if key in seen_names:
                continue
            if file_path.suffix.lower() == ".json":
                doc = _load_json_doc(file_path)
                if doc is None:
                    continue
                doc.setdefault("_source_file", file_path.name)
                docs.append(doc)
                seen_names.add(key)
            elif file_path.suffix.lower() == ".md":
                docs.append(_load_md_doc(file_path))
                seen_names.add(key)

    if any_dir and not docs and roots:
        raise ValueError(
            "No requirement .json or .md files found under "
            + ", ".join(str(Path(s).expanduser().resolve()) for s in roots)
        )

    return docs
