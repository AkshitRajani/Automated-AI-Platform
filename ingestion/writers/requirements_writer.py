"""
Requirements writer — the requirement agent's per-unit docs -> Postgres (app_requirements).

The requirement agent emits one JSON doc per testable unit into a workspace
(``requirements/<unit>.json``). This writer reads those docs and stores each as one row
in ``app_requirements`` so the coding agent can look up "what is this unit supposed to do?"
by unit id. The whole 9-section doc is stored verbatim as JSONB — nothing is summarised,
capped, or dropped.

Design notes (match the rest of ingestion):
  - **Idempotent per app**: a re-run replaces the app's rows (DELETE then INSERT) — the
    requirements directory is the source of truth for that app, so removed units don't
    linger. Same shape as ``embedding_writer`` clearing an app's notes first.
  - **Connection injected or built from config** so the write path is testable without a
    live DB (``RequirementsWriter(conn=fake)``), while ``RequirementsWriter(config=...)``
    builds the real psycopg2 connection like the other writers.
  - **Per-record fault tolerance**: a single malformed doc is logged and skipped, never
    silently swallowed, and never fails the whole load.
  - We do **not** re-load ``grounded_identifiers`` as new fact rows — the requirement
    agent's grounding gate guarantees every name it used is already a real analyzer fact
    in the fact tables. We store only the behaviour layer.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

# psycopg2 is imported lazily (in the writer's DB methods) so the pure layer —
# RequirementRow / load_requirement_docs — is importable and unit-testable with no driver.

logger = logging.getLogger(__name__)


@dataclass
class RequirementRow:
    """One requirement doc, flattened to exactly the columns ``app_requirements`` holds.
    Built purely from a doc JSON — no DB needed — so it is unit-testable on its own."""
    unit: str
    unit_type: str = ""
    title: str = ""
    provenance: str = "code-derived"
    requirement_backed: bool = False
    confidence: Optional[float] = None
    grounding: str = ""
    grounded_identifiers: List[str] = field(default_factory=list)
    sections: dict = field(default_factory=dict)
    section_provenance: dict = field(default_factory=dict)   # section -> 'human-confirmed' (only corrected ones)
    source_hash: str = ""

    @classmethod
    def from_doc(cls, doc: dict) -> "RequirementRow":
        """Build a row from one requirement-doc dict (the requirement agent's JSON).

        Tolerant by design: every field except ``unit`` has a sane default, so a doc that
        omits an optional field still loads. ``source_hash`` is a content hash of the doc,
        for provenance and change detection — not fabricated, derived from the doc itself.
        """
        unit = str(doc.get("unit") or "").strip()
        if not unit:
            raise ValueError("requirement doc has no 'unit' id")
        canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False)
        return cls(
            unit=unit,
            unit_type=str(doc.get("unit_type") or ""),
            title=str(doc.get("title") or ""),
            provenance=str(doc.get("provenance") or "code-derived"),
            requirement_backed=bool(doc.get("requirement_backed", False)),
            confidence=doc.get("confidence"),          # may be None — kept as NULL, never a fake 0.0
            grounding=str(doc.get("grounding") or ""),
            grounded_identifiers=list(doc.get("grounded_identifiers") or []),
            sections=dict(doc.get("sections") or {}),
            section_provenance=dict(doc.get("section_provenance") or {}),
            source_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )


def load_requirement_docs(requirements_dir: str) -> List[RequirementRow]:
    """Load every per-unit requirement doc from a requirement-agent workspace.

    Reads ``<requirements_dir>/requirements/*.json`` if that subfolder exists (the agent's
    layout), else treats ``requirements_dir`` itself as the folder of docs. Pure: only the
    filesystem, no DB. A doc that fails to parse is logged and skipped (per-record fault
    tolerance), not dropped silently. Returns rows in sorted filename order for determinism.
    """
    folder = requirements_dir
    nested = os.path.join(requirements_dir, "requirements")
    if os.path.isdir(nested):
        folder = nested
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"requirements directory not found: {requirements_dir}")

    rows: List[RequirementRow] = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            rows.append(RequirementRow.from_doc(doc))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(f"  requirement doc skipped (could not load {name}): {exc}")
            continue
    return rows


class RequirementsWriter:
    """Writes requirement rows into ``app_requirements`` (idempotent per app)."""

    def __init__(self, config: Optional[dict] = None, conn=None):
        if conn is not None:
            self.conn = conn                # injected (tests / a shared connection)
        elif config is not None:
            import psycopg2
            self.conn = psycopg2.connect(
                host=config["host"], port=config["port"], database=config["database"],
                user=config["user"], password=config["password"],
            )
        else:
            raise ValueError("RequirementsWriter needs either a config or a conn")
        try:
            self.conn.autocommit = False
        except Exception:                   # some fakes don't expose autocommit
            pass

    def write_requirements(self, app_id: str, rows: List[RequirementRow],
                           code_version: Optional[str] = None,
                           replace: bool = True) -> int:
        """Write requirement rows for this app. Returns the count written.

        ``replace=True`` (the onboarding default) replaces the app's rows — the
        requirements directory is the source of truth, so removed units don't linger.
        ``replace=False`` upserts only the given rows — the single-unit rerun path
        (HITL regeneration), where the rest of the app's docs must stay untouched.

        ``code_version`` (optional) stamps every row so a requirement is tied to the code
        it was derived from; left NULL when not supplied — never invented.
        """
        if not app_id:
            raise ValueError("app_id is required to write requirements")
        from psycopg2.extras import Json, execute_batch
        params = [
            (
                app_id, r.unit, r.unit_type, r.title, r.provenance, r.requirement_backed,
                r.confidence, r.grounding, Json(r.grounded_identifiers), Json(r.sections),
                Json(r.section_provenance), code_version, r.source_hash,
            )
            for r in rows
        ]
        with self.conn.cursor() as cur:
            if replace:
                cur.execute("DELETE FROM app_requirements WHERE app_id = %s", (app_id,))
            if params:
                execute_batch(cur, """
                    INSERT INTO app_requirements (
                        app_id, unit, unit_type, title, provenance, requirement_backed,
                        confidence, grounding, grounded_identifiers, sections,
                        section_provenance, code_version, source_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (app_id, unit) DO UPDATE SET
                        unit_type = EXCLUDED.unit_type,
                        title = EXCLUDED.title,
                        provenance = EXCLUDED.provenance,
                        requirement_backed = EXCLUDED.requirement_backed,
                        confidence = EXCLUDED.confidence,
                        grounding = EXCLUDED.grounding,
                        grounded_identifiers = EXCLUDED.grounded_identifiers,
                        sections = EXCLUDED.sections,
                        section_provenance = EXCLUDED.section_provenance,
                        code_version = EXCLUDED.code_version,
                        source_hash = EXCLUDED.source_hash
                """, params, page_size=200)
        self.conn.commit()
        logger.info(f"  Requirements: {len(params)} unit(s) written for {app_id}"
                    + ("" if replace else " (upsert, single-unit path)"))
        return len(params)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
