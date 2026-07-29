"""
Load a quad YAML back into a ``QuadFile`` — the inverse of ``emit.py``.

This lets the analyzer agent (Step 2) take **a codebase PLUS an existing parser
quad file** as its draft, instead of re-parsing from scratch:

    from analyzer import load_quadfile
    draft = load_quadfile("DEMO.parser.yaml")     # the Step-1 output on disk

Tolerant by design: missing optional fields fall back to defaults, so a
hand-edited or partial quad file still loads.
"""
from __future__ import annotations

import yaml

from .models import Entity, Note, Quad, QuadFile, Source


def load_quadfile(path: str) -> QuadFile:
    """Read a quad YAML (as produced by ``emit.to_yaml``) into a ``QuadFile``."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}

    app_id = (doc.get("metadata") or {}).get("app_id", "")

    entities = []
    for e in doc.get("entities") or []:
        src = e.get("source") or {}
        entities.append(Entity(
            id=e["id"], type=e.get("type", "Unknown"), name=e.get("name", ""),
            language=e.get("language", "python"),
            source=Source(
                file_path=src.get("file_path", ""),
                line_start=src.get("line_start"),
                line_end=src.get("line_end"),
            ) if src else None,
        ))

    quads = []
    for q in doc.get("quads") or []:
        ctx = q.get("context") or {}
        quads.append(Quad(
            subject=q["subject"], predicate=q["predicate"], object=q["object"],
            resolved=ctx.get("resolved", True),
            confidence=ctx.get("confidence", 1.0),
            file_path=ctx.get("file_path", "") or "",
            line=ctx.get("line_start"),
            extraction_method=ctx.get("extraction_method", "ast"),
        ))

    notes = []
    for n in doc.get("notes") or []:
        if not (n.get("text") or "").strip():
            continue
        notes.append(Note(
            text=n["text"], subject=n.get("subject", ""),
            file_path=n.get("file_path", ""), line=n.get("line"),
            provenance=n.get("provenance", "agent"),
        ))

    return QuadFile(app_id=app_id, entities=entities, quads=quads, notes=notes)
