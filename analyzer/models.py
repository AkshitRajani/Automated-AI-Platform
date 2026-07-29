"""
Analyzer output model — entities (nodes) + quads (edges), the exact shape the
ingestion `quad_parser` consumes. `emit.py` serializes this to the quad YAML.

An Entity is a code unit (function/method/class/module). A Quad is a typed
relationship whose **predicate** routes it downstream (EXPOSES_ENDPOINT →
app_endpoints, READS_FROM_S3 → app_s3_paths, CALLS → Neptune edge, …).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Source:
    file_path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None


@dataclass
class Entity:
    id: str                    # stable, unique: "<relpath>::<qualname>"
    type: str                  # Module | Class | Function | Method
    name: str
    language: str = "python"
    source: Optional[Source] = None


@dataclass
class Quad:
    subject: str               # entity id of the enclosing unit
    predicate: str             # EXPOSES_ENDPOINT | READS_FROM_S3 | CALLS | ...
    object: str                # the resource literal, or a callee entity id
    resolved: bool = True      # False when the object is a variable, not a literal
    confidence: float = 1.0
    file_path: str = ""
    line: Optional[int] = None
    extraction_method: str = "ast"   # "ast" = deterministic parser, "agent" = analyzer agent
    language: str = "python"   # source language of the fact: python | java | yaml-workflow
    symbolic: bool = False     # object carries RAW expression text (not a ${token});
                               # answering its tokens can never make it fully resolved


@dataclass
class Note:
    """A plain-English behavioural note (analyzer agent) -> pgvector similarity store.
    Carries grounding (subject/file/line) so it can be traced back to the code."""
    text: str
    subject: str = ""
    file_path: str = ""
    line: Optional[int] = None
    provenance: str = "agent"


@dataclass
class QuadFile:
    app_id: str
    entities: List[Entity] = field(default_factory=list)
    quads: List[Quad] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)
    flagged_unknown_actions: set = field(default_factory=set)
    bindings: dict = field(default_factory=dict)   # repo-declared token -> value (wiring harvest)
    pending_names: List[str] = field(default_factory=list)  # ${tokens} nobody answered — journeys withheld
    unwired: List[str] = field(default_factory=list)        # journey-shaped orphans: needs wiring, NOT journeys
    human_answers: dict = field(default_factory=dict)       # worksheet values actually applied (audit trail)
    decisions: dict = field(default_factory=dict)           # token -> {decision, reason} (skip/runtime verdicts)
    sheet_warnings: List[str] = field(default_factory=list) # stale/conflicting operator sheet entries
    analyzer_notes: List[str] = field(default_factory=list) # what was read/skipped (observability, never silent)
    handler_unlinked: List[dict] = field(default_factory=list) # lambdas whose code link could not be made — visible, never a ghost edge
    env_candidates: List[str] = field(default_factory=list) # competing environment tfvars files (A15)
    environment_file: Optional[str] = None                  # the ONE chosen to ground the map
    lambda_names_declared: List[str] = field(default_factory=list) # terraform-declared lambda names (A7)
    lambda_names_confirmed: bool = False                    # human said yes to the list
    lambda_name_corrections: dict = field(default_factory=dict) # declared -> deployed (human-supplied)
    parse_manifest: dict = field(default_factory=dict)      # what this run read, by category
