"""
The fact sink + the grounding gate, in one place.

Every ``emit_fact`` the agent makes lands here. A structural fact is **re-verified**
against the real source at its ``file:line`` by ``analyzer.verify`` (pure,
deterministic, no LLM) before it is allowed near the graph:

    verified (ok)      -> graph facts  (Postgres + Neptune)
    uncheckable (None) -> notes        (pgvector; e.g. runtime behaviour, no symbol)
    rejected (False)   -> dropped + logged   (hallucination / wrong location)

A fact the agent explicitly marks ``kind="note"`` (plain-English flow, no symbol at
a line) goes straight to notes. The verified facts serialize into the **same
``analyzer.QuadFile``** the ingestion ``quad_parser`` already consumes, so the
agent's output drops into the existing pipeline unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from analyzer.models import Note, Quad, QuadFile
from analyzer.verify import grade, verify_fact

from .canonical import is_canonical


@dataclass
class EmittedFact:
    subject: str                 # canonical "Type:qualname" id of the enclosing unit
    predicate: str               # CALLS | INVOKES_LAMBDA | READS_FROM_S3 | FEEDS | ...
    object: str                  # canonical id, or a resource literal
    file: str                    # path relative to the repo root
    line: Optional[int] = None
    kind: str = "fact"           # "fact" -> verify -> graph ; "note" -> pgvector
    note: str = ""               # plain-English description (for notes)
    provenance: str = "agent"

    def as_check(self) -> dict:
        """The dict shape ``analyzer.verify.verify_fact`` expects."""
        return {"subject": self.subject, "predicate": self.predicate,
                "object": self.object, "file": self.file, "line": self.line}


class FactStore:
    """Collects emitted facts, runs each through the grounding gate, and routes it.

    One store per run; injected into the ``emit_fact`` tool via ``tools.context``.
    """

    def __init__(self, root: str, app_id: str):
        self.root = root
        self.app_id = app_id
        self.verified: List[EmittedFact] = []
        self.notes: List[EmittedFact] = []
        self.rejected: List[Tuple[EmittedFact, str]] = []
        self._raw: List[dict] = []          # every structural fact, for grade()

    def emit(self, fact: EmittedFact) -> Tuple[str, str]:
        """Route one fact. Returns ``(destination, reason)`` so the tool can tell
        the agent honestly what happened — kept, noted, or rejected."""
        if fact.kind == "note":
            self.notes.append(fact)
            return "note", "behavioural note -> pgvector"

        self._raw.append(fact.as_check())
        ok, why = verify_fact(self.root, fact.as_check())
        if ok is True:
            self.verified.append(fact)
            return "graph", why
        if ok is None:
            self.notes.append(fact)              # can't check a symbol -> keep as note
            return "note", why
        self.rejected.append((fact, why))        # provably wrong -> dropped
        return "rejected", why

    def to_quadfile(self) -> QuadFile:
        """Verified facts -> the ingestion-compatible QuadFile (graph load)."""
        quads = [
            Quad(subject=f.subject, predicate=f.predicate, object=f.object,
                 resolved=is_canonical(f.object), confidence=1.0,
                 file_path=f.file, line=f.line,
                 extraction_method=f.provenance)   # "agent" — keep parser-vs-agent provenance
            for f in self.verified
        ]
        return QuadFile(app_id=self.app_id, entities=[], quads=quads)

    def to_notes(self) -> List[Note]:
        """Behavioural notes (explicit notes + uncheckable facts) -> pgvector. An
        uncheckable fact has no prose, so synthesize a searchable line from its triple."""
        notes = []
        for f in self.notes:
            text = f.note.strip() if f.note else f"{f.subject} {f.predicate} {f.object}".strip()
            if not text:
                continue
            notes.append(Note(text=text, subject=f.subject, file_path=f.file,
                              line=f.line, provenance=f.provenance))
        return notes

    def grade(self) -> dict:
        """Precision of the agent's structural output, via the same gate
        (kept / rejected / uncheckable / precision out of 100)."""
        return grade(self.root, self._raw)

    def stats(self) -> dict:
        g = self.grade()
        return {
            "emitted": len(self._raw) + len(self.notes),
            "graph_facts": len(self.verified),
            "notes": len(self.notes),
            "rejected": len(self.rejected),
            "precision": g["precision"],
            "rejected_samples": g["rejected_samples"],
        }
