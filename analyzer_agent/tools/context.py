"""
Shared, injected run-context for the tools.

The domain tools (``repo_map``, ``parser_facts``, ``emit_fact``) need three things
that belong to *one run*: the repo root, the Step-1 parser draft, and the fact
store. Rather than thread them through every signature (Strands calls tools with
the model's args only), we inject them here once at assembly — the same
``set_client`` pattern the coding agent uses. Tests inject fakes the same way.
"""
from __future__ import annotations

from typing import Optional

from analyzer.models import QuadFile

from ..store import FactStore

_store: Optional[FactStore] = None
_draft: Optional[QuadFile] = None
_root: str = ""


def set_store(store: Optional[FactStore]) -> None:
    global _store
    _store = store


def get_store() -> FactStore:
    if _store is None:
        raise RuntimeError("FactStore not set — call set_store() at agent assembly.")
    return _store


def set_draft(draft: Optional[QuadFile]) -> None:
    global _draft
    _draft = draft


def get_draft() -> QuadFile:
    if _draft is None:
        raise RuntimeError("Parser draft not set — call set_draft() at agent assembly.")
    return _draft


def set_root(root: str) -> None:
    global _root
    _root = root


def get_root() -> str:
    return _root
