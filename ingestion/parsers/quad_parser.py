"""
Quad file parser.
Opens a YAML quad file, validates each record, quarantines bad ones.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SourceLocation:
    file_path: str = ""
    line_start: Optional[int] = None
    line_end: Optional[int] = None


@dataclass
class Entity:
    id: str
    type: str
    name: str
    language: Optional[str] = None
    source: Optional[SourceLocation] = None


@dataclass
class QuadContext:
    source_language: Optional[str] = None
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    extraction_method: Optional[str] = None
    confidence: Optional[float] = None
    resolved: Optional[bool] = None
    component: Optional[str] = None
    relationship_type: Optional[str] = None


@dataclass
class Quad:
    subject: str
    predicate: str
    object: str
    context: Optional[QuadContext] = None
    relationship_type: Optional[str] = None


@dataclass
class Note:
    text: str
    subject: str = ""
    file_path: str = ""
    line: Optional[int] = None
    provenance: str = "agent"


@dataclass
class ParseResult:
    source_file: str
    metadata: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    entities: list[Entity] = field(default_factory=list)
    quads: list[Quad] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)
    bindings: dict = field(default_factory=dict)   # repo-declared token -> value (analyzer harvest)

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def quad_count(self) -> int:
        return len(self.quads)

    @property
    def quarantine_count(self) -> int:
        return len(self.quarantined)


def parse_quad_file(path: str) -> ParseResult:
    """
    Parse a quad file with per-record fault tolerance.

    - YAML parse failure = entire file skipped (raised as exception)
    - Individual entity/quad validation failure = quarantined, rest continues
    - Unknown fields = silently ignored
    - Unknown types/predicates = accepted with warning
    """
    result = ParseResult(source_file=path)

    # Load YAML (use C loader if available for 11x speed)
    raw = _load_yaml(path)

    if not isinstance(raw, dict):
        raise ValueError(f"Expected dict at top level, got {type(raw).__name__}")

    # Extract metadata and summary
    result.metadata = raw.get("metadata", {})
    result.summary = raw.get("summary", result.metadata.get("summary", {}))
    raw_bindings = raw.get("bindings") or {}
    if isinstance(raw_bindings, dict):
        result.bindings = {str(k): str(v) for k, v in raw_bindings.items()
                           if isinstance(k, str) and isinstance(v, (str, int, float, bool))}

    # Parse entities (per-record quarantine)
    for i, raw_entity in enumerate(raw.get("entities", [])):
        try:
            entity = _parse_entity(raw_entity)
            result.entities.append(entity)
        except (KeyError, TypeError, ValueError) as e:
            result.quarantined.append({
                "stage": "entity",
                "index": i,
                "error": str(e),
                "record": raw_entity,
            })

    # Parse quads (per-record quarantine)
    for i, raw_quad in enumerate(raw.get("quads", [])):
        try:
            quad = _parse_quad(raw_quad)
            result.quads.append(quad)
        except (KeyError, TypeError, ValueError) as e:
            result.quarantined.append({
                "stage": "quad",
                "index": i,
                "error": str(e),
                "record": raw_quad,
            })

    # Parse notes (behavioural prose -> pgvector); tolerant, never fatal
    for raw_note in raw.get("notes", []):
        try:
            text = (raw_note.get("text") or "").strip()
            if not text:
                continue
            result.notes.append(Note(
                text=text,
                subject=raw_note.get("subject", "") or "",
                file_path=raw_note.get("file_path", "") or "",
                line=raw_note.get("line"),
                provenance=raw_note.get("provenance", "agent") or "agent",
            ))
        except (AttributeError, TypeError):
            continue

    if result.quarantine_count > 0:
        logger.warning(f"  Quarantined {result.quarantine_count} records from {path}")

    return result


def _load_yaml(path: str) -> Any:
    """Load YAML file, using C loader when available."""
    try:
        from yaml import CSafeLoader as Loader
    except ImportError:
        from yaml import SafeLoader as Loader

    if path.startswith("s3://"):
        content = _read_s3(path)
        return yaml.load(content, Loader=Loader)
    else:
        with open(path) as f:
            return yaml.load(f, Loader=Loader)


def _read_s3(uri: str) -> str:
    """Read a file from S3."""
    import boto3
    parts = uri.replace("s3://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def _parse_entity(raw: dict) -> Entity:
    """Parse a single entity dict into an Entity dataclass."""
    source = None
    if "source" in raw and raw["source"]:
        src = raw["source"]
        source = SourceLocation(
            file_path=src.get("file_path", ""),
            line_start=src.get("line_start"),
            line_end=src.get("line_end"),
        )

    return Entity(
        id=raw["id"],
        type=raw.get("type", "Unknown"),
        name=raw.get("name", raw["id"]),
        language=raw.get("language"),
        source=source,
    )


def _parse_quad(raw: dict) -> Quad:
    """Parse a single quad dict into a Quad dataclass."""
    context = None
    if "context" in raw and raw["context"]:
        ctx = raw["context"]
        context = QuadContext(
            source_language=ctx.get("source_language"),
            file_path=ctx.get("file_path"),
            line_start=ctx.get("line_start"),
            line_end=ctx.get("line_end"),
            extraction_method=ctx.get("extraction_method"),
            confidence=ctx.get("confidence"),
            resolved=ctx.get("resolved"),
            component=ctx.get("component"),
            relationship_type=ctx.get("relationship_type"),
        )

    # Clean object field — strip stray quotes from analyzer output
    obj = raw["object"]
    if isinstance(obj, str):
        obj = obj.strip("'\"")

    return Quad(
        subject=raw["subject"],
        predicate=raw["predicate"],
        object=obj,
        context=context,
        relationship_type=raw.get("relationship_type"),
    )
