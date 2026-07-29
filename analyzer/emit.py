"""
Serialize a QuadFile to the quad YAML the ingestion `quad_parser` consumes.
Shapes entities + quads exactly as `_parse_entity` / `_parse_quad` expect, so the
output drops straight into the existing pipeline (Postgres + Neptune + pgvector).
"""
from __future__ import annotations

from typing import Optional

import yaml

from .models import QuadFile


def to_dict(qf: QuadFile) -> dict:
    entities = []
    for e in qf.entities:
        rec = {"id": e.id, "type": e.type, "name": e.name, "language": e.language}
        if e.source:
            rec["source"] = {
                "file_path": e.source.file_path,
                "line_start": e.source.line_start,
                "line_end": e.source.line_end,
            }
        entities.append(rec)

    quads = []
    for q in qf.quads:
        quads.append({
            "subject": q.subject,
            "predicate": q.predicate,
            "object": q.object,
            "relationship_type": q.predicate,
            "context": {
                "source_language": q.language,
                "file_path": q.file_path,
                "line_start": q.line,
                "extraction_method": q.extraction_method,
                "confidence": q.confidence,
                "resolved": q.resolved,
            },
        })

    notes = [
        {
            "text": n.text,
            "subject": n.subject,
            "file_path": n.file_path,
            "line": n.line,
            "provenance": n.provenance,
        }
        for n in getattr(qf, "notes", [])
    ]

    languages = sorted({e.language for e in qf.entities} | {q.language for q in qf.quads}) or ["python"]
    pending = list(getattr(qf, "pending_names", []) or [])
    return {
        "metadata": {
            "app_id": qf.app_id,
            "generated_by": "analyzer-python-v1",
            # the exact reader that produced this quad — remote diagnosis must
            # never again depend on a filename's claim
            "analyzer_version": "3.4.2",
            "language": "python" if "python" in languages else languages[0],
            "languages_detected": languages,
            # The gate's paper trail: journeys exist ONLY when no names are
            # pending; unwired lists journey-shaped orphans held for review.
            "journeys_computed": not pending,
            "pending_names": pending,
            "unwired": list(getattr(qf, "unwired", []) or []),
            # The human trail: what a person supplied, what they decided, and
            # any operator-sheet inconsistencies — the audit travels WITH the
            # data (validation study: the side files never reached downstream).
            "human_answers": dict(getattr(qf, "human_answers", {}) or {}),
            "decisions": dict(getattr(qf, "decisions", {}) or {}),
            "sheet_warnings": list(getattr(qf, "sheet_warnings", []) or []),
            "analyzer_notes": list(getattr(qf, "analyzer_notes", []) or []),
            # lambdas whose code could not be identified (ambiguous/absent
            # handler target): the question, with its candidates — instead of
            # an edge to a node that doesn't exist.
            "handler_unlinked": list(getattr(qf, "handler_unlinked", []) or []),
            # which environment grounds this map (A15) — and which files were
            # deliberately NOT used, so a devl value can never hide in a test map
            "environment_file": getattr(qf, "environment_file", None),
            "environment_candidates": list(getattr(qf, "env_candidates", []) or []),
            # the deployed-name confirmation (A7): what the terraform declared,
            # whether a human confirmed the list, and every correction a human
            # supplied (declared -> deployed) — names are never silently trusted
            "lambda_names_declared": list(getattr(qf, "lambda_names_declared", []) or []),
            "lambda_names_confirmed": bool(getattr(qf, "lambda_names_confirmed", False)),
            "lambda_name_corrections": dict(getattr(qf, "lambda_name_corrections", {}) or {}),
            # what this run read, by category — absence is stated, not implied
            "parse_manifest": dict(getattr(qf, "parse_manifest", {}) or {}),
        },
        "summary": {"entity_count": len(entities), "quad_count": len(quads),
                    "note_count": len(notes)},
        "entities": entities,
        "quads": quads,
        "notes": notes,
        "bindings": dict(getattr(qf, "bindings", {}) or {}),
    }


def to_yaml(qf: QuadFile) -> str:
    return yaml.safe_dump(to_dict(qf), sort_keys=False, default_flow_style=False)


def write(qf: QuadFile, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_yaml(qf))
