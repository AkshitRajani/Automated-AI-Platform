"""
``read_source`` — the agent's escape hatch into the onboarded app's RAW source.

The KB (``kb_query`` / ``kb_graph``) gives names and relationships, not the actual
code. When the agent hits a workflow or pipeline it cannot fully understand from the
facts alone, it can drop into the real source and map it. This is the planned
``kb_raw_code`` tool (MASTER_DESIGN §6.3).

Input is just a **pointer** (the ``AgentTask.codebase_zip`` — a ``.zip`` or a folder),
injected once via ``set_source``. The zip is unpacked lazily into a read-only temp
dir on first use. Three navigation tools, all **read-only** and **confined to the
source root** (they can never read the rest of the disk, and never write):

  - ``list_source(glob)``     — find files by name pattern
  - ``search_source(pattern)``— grep the code (substring or regex)
  - ``read_source(path)``     — read a file (numbered lines)

If no pointer was given, every tool returns an actionable "no source configured"
note instead of failing — KB grounding still works, the raw-code path just degrades.
"""
from __future__ import annotations

import fnmatch
import os
import re
import tempfile
import zipfile
from typing import Optional

from coding_agent.tools._strands import tool

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".idea",
              ".mypy_cache", ".pytest_cache", "__MACOSX"}

_pointer: Optional[str] = None       # the raw pointer (zip | folder)
_root_cache: Optional[str] = None    # resolved local dir (unzipped if needed)


def set_source(pointer: Optional[str]) -> None:
    """Inject the codebase pointer (a .zip path or a folder). Resets the cache."""
    global _pointer, _root_cache
    _pointer = pointer
    _root_cache = None


def _root() -> Optional[str]:
    """Resolve the pointer to a local dir (unzip a .zip once, lazily). None if unset."""
    global _root_cache
    if _root_cache is not None:
        return _root_cache
    if not _pointer:
        return None
    p = _pointer
    if os.path.isdir(p):
        _root_cache = os.path.realpath(p)
    elif os.path.isfile(p) and zipfile.is_zipfile(p):
        dest = tempfile.mkdtemp(prefix="aap_src_")
        with zipfile.ZipFile(p) as z:
            z.extractall(dest)
        # descend a single top-level folder (the common "repo/..." zip shape)
        kids = [e for e in os.listdir(dest) if e not in _SKIP_DIRS]
        if len(kids) == 1 and os.path.isdir(os.path.join(dest, kids[0])):
            dest = os.path.join(dest, kids[0])
        _root_cache = os.path.realpath(dest)
    return _root_cache


def _resolve(root: str, rel: str) -> Optional[str]:
    """Resolve ``rel`` under ``root``; None if it escapes the source root."""
    cand = os.path.realpath(os.path.join(root, rel))
    if cand == root or cand.startswith(root + os.sep):
        return cand
    return None


@tool
def list_source(glob: str = "*", max_results: int = 100) -> str:
    """List files in the onboarded app's RAW source whose name matches a glob.

    Use to find the real files behind a workflow/pipeline — e.g. "*.py", "*.yml",
    "*handler*", "*workflow*". Read-only. Returns relative paths.

    Args:
        glob: filename glob to match (matched against the file name, any folder).
        max_results: cap on paths returned.
    """
    root = _root()
    if not root:
        return ("No source configured (codebase_zip not provided). "
                "Ground from kb_query / kb_graph instead.")
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in sorted(filenames):
            if fnmatch.fnmatch(name, glob):
                out.append(os.path.relpath(os.path.join(dirpath, name), root))
                if len(out) >= max_results:
                    return "\n".join(out) + f"\n... (capped at {max_results})"
    return "\n".join(out) if out else f"No files match {glob!r}."


@tool
def search_source(pattern: str, glob: str = "*", max_results: int = 40) -> str:
    """Search the onboarded app's RAW source for a pattern (substring or regex).

    Use when the KB facts aren't enough to understand a workflow — find where a
    helper, table, or step is defined/used in the real code. Read-only. Returns
    matching ``path:line: text`` lines.

    Args:
        pattern: substring or regex to find (e.g. "execute_lambda", "def handler").
        glob: restrict to files matching this name glob (e.g. "*.py", "*.yml").
        max_results: cap on matches returned.
    """
    root = _root()
    if not root:
        return ("No source configured (codebase_zip not provided). "
                "Ground from kb_query / kb_graph instead.")
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not fnmatch.fnmatch(name, glob):
                continue
            fp = os.path.join(dirpath, name)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            rel = os.path.relpath(fp, root)
                            out.append(f"{rel}:{i}: {line.strip()[:200]}")
                            if len(out) >= max_results:
                                return "\n".join(out) + f"\n... (capped at {max_results})"
            except (OSError, UnicodeError):
                continue
    return "\n".join(out) if out else f"No matches for {pattern!r}."


@tool
def read_source(path: str, start: int = 1, end: int = 400) -> str:
    """Read a file from the onboarded app's RAW source by its relative path.

    Read-only. Returns the requested line range, numbered. Find the path first with
    list_source / search_source.

    Args:
        path: file path relative to the repo root.
        start: first line to return (1-based).
        end: last line to return.
    """
    root = _root()
    if not root:
        return "No source configured (codebase_zip not provided)."
    cand = _resolve(root, path)
    if cand is None:
        return f"Path {path!r} is outside the source root (refused)."
    if not os.path.isfile(cand):
        return f"No such file: {path!r}. Use list_source / search_source to find it."
    try:
        with open(cand, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError as e:
        return f"Could not read {path!r}: {e}"
    start = max(1, start)
    chunk = lines[start - 1:end]
    if not chunk:
        return "(empty range)"
    return "".join(f"{start + i:>6}\t{ln}" for i, ln in enumerate(chunk))
