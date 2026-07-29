"""
AnalyzerFacts — the onboarding-time analogue of the coding agent's KB client.

At onboarding the live KB does not exist yet, so the requirement agent grounds
against the **analyzer's output file** (a quad YAML: ``entities`` + ``quads``) plus
the raw source. This module loads that file once and answers three questions:

  * ``inventory()``    — what testable units exist (entities grouped by type) — the
                         agent's discovery surface AND the coverage denominator.
  * ``facts_for(unit)``— what does this unit touch (its quads: predicate → object)
                         — so the agent can state the unit's behavior/contract.
  * ``resolve(name)``  — is this name real (an entity or a quad object)? — the
                         grounding gate.

Tolerant by design: it reads both the analyzer-emitted shape and a hand-authored /
client-style quad file (``entities``/``quads`` at the top level), defaulting missing
optional fields rather than failing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import os

import yaml


@dataclass
class UnitFact:
    predicate: str
    object: str
    resolved: bool = True


@dataclass
class Unit:
    id: str
    type: str
    name: str
    file_path: str = ""
    line: Optional[int] = None


@dataclass
class Inventory:
    app_id: str
    groups: Dict[str, List[str]] = field(default_factory=dict)   # entity_type -> [unit ids]
    endpoints: List[str] = field(default_factory=list)
    note: str = ""


class AnalyzerFacts:
    """Loaded view of one analyzer quad file."""

    def __init__(self, app_id: str, entities: List[Unit],
                 quads_by_subject: Dict[str, List[UnitFact]],
                 resolvable: set):
        self.app_id = app_id
        self._entities = {e.id: e for e in entities}
        self._quads_by_subject = quads_by_subject
        self._resolvable = resolvable   # every groundable name (entity ids/names + quad objects)

    # -- loading ---------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str, worksheet: str = "") -> "AnalyzerFacts":
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        meta = data.get("metadata") or {}
        app_id = str(meta.get("app_id") or data.get("app_id") or "")

        # Name resolution (doc 10): apply the quad file's own repo-declared
        # bindings, then the human worksheet ON TOP (a person beats a file), so
        # the specs narrate real names wherever an answer exists. Same rule as
        # ingestion; unanswered tokens stay honestly symbolic.
        bindings = {str(k): str(v) for k, v in (data.get("bindings") or {}).items()
                    if isinstance(v, (str, int, float, bool))}
        if worksheet and os.path.isfile(worksheet):
            with open(worksheet, "r", encoding="utf-8") as fh:
                sheet = yaml.safe_load(fh) or {}
            if isinstance(sheet, dict):
                bindings.update({str(k): str(v) for k, v in sheet.items()
                                 if isinstance(v, (str, int, float, bool))})
        if bindings:
            import re as _re
            token_re = _re.compile(r"\$\{([^}]+)\}")

            def _apply(text: str) -> str:
                return token_re.sub(lambda m: bindings.get(m.group(1), m.group(0)), text)

            for q in (data.get("quads") or []):
                if isinstance(q, dict) and isinstance(q.get("object"), str) and "${" in q["object"]:
                    new_obj = _apply(q["object"])
                    if new_obj != q["object"]:
                        q["object"] = new_obj
                        ctx = q.get("context")
                        if isinstance(ctx, dict) and "${" not in new_obj:
                            ctx["resolved"] = True

        entities: List[Unit] = []
        resolvable: set = set()
        for e in (data.get("entities") or []):
            if not isinstance(e, dict):
                continue
            src = e.get("source") or {}
            uid = str(e.get("id") or e.get("name") or "")
            name = str(e.get("name") or uid)
            entities.append(Unit(
                id=uid,
                type=str(e.get("type") or "Unknown"),
                name=name,
                file_path=str(src.get("file_path") or ""),
                line=src.get("line_start"),
            ))
            if uid:
                resolvable.add(uid)
            if name:
                resolvable.add(name)

        quads_by_subject: Dict[str, List[UnitFact]] = {}
        for q in (data.get("quads") or []):
            if not isinstance(q, dict):
                continue
            subj = str(q.get("subject") or "")
            obj = str(q.get("object") or "")
            pred = str(q.get("predicate") or q.get("relationship_type") or "")
            ctx = q.get("context") or {}
            resolved = bool(ctx.get("resolved", True))
            quads_by_subject.setdefault(subj, []).append(
                UnitFact(predicate=pred, object=obj, resolved=resolved)
            )
            if obj:
                resolvable.add(obj)

        return cls(app_id, entities, quads_by_subject, resolvable)

    # -- queries ---------------------------------------------------------------

    def inventory(self) -> Inventory:
        """Every entity grouped by type (+ endpoints) — UNCAPPED. The agent decides which
        groups are testable units; this reports whatever the analyzer recorded, in full,
        so nothing is ever hidden from discovery (no fixed list, no truncation)."""
        groups: Dict[str, List[str]] = {}
        endpoints: List[str] = []
        for e in self._entities.values():
            groups.setdefault(e.type, []).append(e.id)
            if e.type in ("APIEndpoint", "Endpoint"):
                endpoints.append(e.id)
        groups = {t: sorted(ids) for t, ids in sorted(groups.items())}
        note = "" if groups else f"No entities found in the analyzer output for '{self.app_id}'."
        return Inventory(app_id=self.app_id, groups=groups,
                         endpoints=sorted(endpoints), note=note)

    def entity(self, unit: str) -> Optional[Unit]:
        return self._entities.get(unit)

    def facts_for(self, unit: str) -> List[UnitFact]:
        """The quads whose subject is this unit — what it calls / reads / writes / raises."""
        return list(self._quads_by_subject.get(unit, []))

    def resolve(self, name: str) -> bool:
        """True if ``name`` is a real entity (id or name) or a real quad object."""
        return bool(name) and name in self._resolvable

    def unit_ids(self) -> List[str]:
        """Every entity id — the coverage denominator."""
        return list(self._entities.keys())

    _OBSERVABLE_PREDS = {
        "WRITES_TO_S3", "WRITES_DATABASE", "WRITES_DYNAMODB_TABLE", "WRITES_FILE",
        "READS_FROM_S3", "QUERIES_DATABASE", "READS_DYNAMODB_TABLE", "READS_FILE",
        "READS_CONFIG_FROM_S3", "EXPOSES_ENDPOINT", "INVOKES_STEP_FUNCTION",
        "PUBLISHES_TO_SNS", "RETURNS_RESPONSE",
    }

    def observable_objects(self) -> set:
        """Every object the analyzer saw being read, written, exposed, or started —
        the app's outside-visible surface, derived from the quads themselves (no
        name rules). The story gate checks journey specs against this set."""
        out = set()
        for facts in self._quads_by_subject.values():
            for f in facts:
                if f.predicate in self._OBSERVABLE_PREDS:
                    out.add(f.object)
        return out
