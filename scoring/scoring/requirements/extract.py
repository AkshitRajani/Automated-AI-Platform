"""
Tiered extraction of testable items from requirement-agent documents.

Aligned with requirement_agent CANONICAL_SECTIONS:
  Tier A (primary): User Stories G/W/T ACs, Consolidated shall/must bullets
  Tier B (secondary): Function Spec rows, Gap Analysis actionable bullets
  Tier C (metadata): Traceability, Confidence, I/O tables, System Overview — skipped
  Tier D (fallback): only when Tier A yields nothing

Full raw_text / sections are never dropped from the document model.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set

from .contract import extraction_tier, section_key

_STORY_BLOCK = re.compile(
    r"^#{1,3}\s*(US[-\s]?\d+[^\n]*)",
    re.IGNORECASE | re.MULTILINE,
)
_AC_NUMBERED = re.compile(
    r"^\s*(?P<num>\d+)\.\s+(?P<body>.+)$",
    re.MULTILINE,
)
_AC_GWT = re.compile(r"\bgiven\b.*\bwhen\b.*\bthen\b", re.IGNORECASE | re.DOTALL)
_SHALL_BULLET = re.compile(
    r"^\s*[-*]\s+(?:The system shall|The system must)\s+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_GAP_BULLET = re.compile(
    r"^\s*[-*]\s+(?:Not documented:|Missing:|Gap:)\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_NEG_TAG = re.compile(r"negative\s*path|\(negative", re.IGNORECASE)
_CODE_TAG = re.compile(r"\[code-derived\]", re.IGNORECASE)


@dataclass(frozen=True)
class RequirementItem:
    """One testable unit extracted deterministically from a requirement document."""

    item_id: str
    doc_file: str
    unit_id: str
    unit_type: str
    story_id: str
    source_section: str
    verbatim_text: str
    provenance: str
    requirement_backed: bool
    negative_path: bool
    extraction_tier: str = "primary"


@dataclass
class ExtractionReport:
    """Counts per tier for integrity / debugging."""

    primary: int = 0
    secondary: int = 0
    fallback: int = 0
    sections_skipped_metadata: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "fallback": self.fallback,
            "sections_skipped_metadata": self.sections_skipped_metadata,
            "notes": self.notes,
        }


def _item_id(unit_id: str, section: str, suffix: str) -> str:
    safe_suffix = re.sub(r"[^\w\-]+", "-", suffix).strip("-")[:80]
    return f"{unit_id}::{section}::{safe_suffix}"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:12]


def _dedupe_items(items: Iterable[RequirementItem]) -> List[RequirementItem]:
    seen: Set[str] = set()
    out: List[RequirementItem] = []
    for item in items:
        key = _text_hash(item.verbatim_text)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _clean_ac_text(text: str) -> str:
    return _CODE_TAG.sub("", text).strip()


def _parse_table_rows(text: str) -> List[str]:
    rows: List[str] = []
    header: List[str] = []
    for line in text.splitlines():
        if not _TABLE_ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        if not header:
            header = cells
            continue
        if all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        if header:
            pairs = [
                f"{header[i]}={cells[i]}"
                for i in range(min(len(header), len(cells)))
                if cells[i] and cells[i] not in ("n/a", "N/A", "—")
            ]
            if pairs:
                rows.append(" | ".join(pairs))
    return rows


def _story_blocks(text: str) -> List[tuple[str, str]]:
    """Split User Stories section into (story_id, block_text) pairs."""
    matches = list(_STORY_BLOCK.finditer(text))
    if not matches:
        return [("US-general", text)]
    blocks: List[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        story_id = match.group(1).strip()
        blocks.append((story_id, text[start:end]))
    return blocks


def _normalized_tokens(text: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _text_overlap_ratio(left: str, right: str) -> float:
    left_tokens = _normalized_tokens(left)
    right_tokens = _normalized_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _collect_story_acs(block: str) -> List[tuple[str, str]]:
    acs: List[tuple[str, str]] = []
    for match in _AC_NUMBERED.finditer(block):
        body = _clean_ac_text(match.group("body").strip())
        if len(body) < 10:
            continue
        if not _AC_GWT.search(body):
            continue
        acs.append((match.group("num"), body))
    return acs


def _extract_user_story_items(
    text: str,
    *,
    doc_file: str,
    unit_id: str,
    unit_type: str,
    provenance: str,
    requirement_backed: bool,
    source_section: str,
    aggregate_stories: bool = False,
) -> List[RequirementItem]:
    items: List[RequirementItem] = []
    for story_id, block in _story_blocks(text):
        acs = _collect_story_acs(block)
        if not acs:
            continue
        if aggregate_stories and len(acs) > 1:
            lines = [f"AC-{num}: {body}" for num, body in acs]
            verbatim = "\n".join(lines)
            suffix = f"{story_id}-aggregated"
        else:
            num, body = acs[0] if len(acs) == 1 else acs[-1]
            if not aggregate_stories:
                for ac_num, ac_body in acs:
                    items.append(RequirementItem(
                        item_id=_item_id(unit_id, source_section, f"{story_id}-AC-{ac_num}"),
                        doc_file=doc_file,
                        unit_id=unit_id,
                        unit_type=unit_type,
                        story_id=story_id,
                        source_section=source_section,
                        verbatim_text=ac_body,
                        provenance=provenance,
                        requirement_backed=requirement_backed,
                        negative_path=bool(_NEG_TAG.search(ac_body)),
                        extraction_tier="primary",
                    ))
                continue
            verbatim = body
            suffix = f"{story_id}-AC-{num}"
        items.append(RequirementItem(
            item_id=_item_id(unit_id, source_section, suffix),
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            story_id=story_id,
            source_section=source_section,
            verbatim_text=verbatim,
            provenance=provenance,
            requirement_backed=requirement_backed,
            negative_path=any(_NEG_TAG.search(body) for _, body in acs),
            extraction_tier="primary",
        ))
    return items


def _shall_redundant_with_stories(verbatim: str, story_texts: List[str]) -> bool:
    if not story_texts:
        return False
    low = verbatim.lower()
    if re.search(r"\benforce\b.+\brule\s+\d+\b", low):
        return True
    return any(_text_overlap_ratio(verbatim, story) >= 0.55 for story in story_texts)


def _extract_shall_items(
    text: str,
    *,
    doc_file: str,
    unit_id: str,
    unit_type: str,
    provenance: str,
    requirement_backed: bool,
    source_section: str,
    story_texts: List[str] | None = None,
    dedupe_against_stories: bool = False,
) -> List[RequirementItem]:
    items: List[RequirementItem] = []
    for idx, match in enumerate(_SHALL_BULLET.finditer(text), start=1):
        body = match.group(1).strip()
        verbatim = f"The system shall {body}"
        if dedupe_against_stories and _shall_redundant_with_stories(verbatim, story_texts or []):
            continue
        items.append(RequirementItem(
            item_id=_item_id(unit_id, source_section, f"REQ-{idx}"),
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            story_id="consolidated",
            source_section=source_section,
            verbatim_text=verbatim,
            provenance=provenance,
            requirement_backed=requirement_backed,
            negative_path=bool(_NEG_TAG.search(verbatim)),
            extraction_tier="primary",
        ))
    return items


def _extract_function_spec_items(
    text: str,
    *,
    doc_file: str,
    unit_id: str,
    unit_type: str,
    provenance: str,
    requirement_backed: bool,
    source_section: str,
) -> List[RequirementItem]:
    items: List[RequirementItem] = []
    for idx, row in enumerate(_parse_table_rows(text), start=1):
        if not row.lower().startswith("function="):
            continue
        items.append(RequirementItem(
            item_id=_item_id(unit_id, source_section, f"FN-{idx}"),
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            story_id="functions",
            source_section=source_section,
            verbatim_text=row,
            provenance=provenance,
            requirement_backed=requirement_backed,
            negative_path=bool(_NEG_TAG.search(row)),
            extraction_tier="secondary",
        ))
    return items


def _extract_gap_items(
    text: str,
    *,
    doc_file: str,
    unit_id: str,
    unit_type: str,
    provenance: str,
    requirement_backed: bool,
    source_section: str,
) -> List[RequirementItem]:
    items: List[RequirementItem] = []
    for idx, match in enumerate(_GAP_BULLET.finditer(text), start=1):
        body = match.group(1).strip()
        items.append(RequirementItem(
            item_id=_item_id(unit_id, source_section, f"GAP-{idx}"),
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            story_id="gaps",
            source_section=source_section,
            verbatim_text=body,
            provenance=provenance,
            requirement_backed=requirement_backed,
            negative_path=bool(_NEG_TAG.search(body)),
            extraction_tier="secondary",
        ))
    return items


def _extract_extra_section_items(
    text: str,
    *,
    doc_file: str,
    unit_id: str,
    unit_type: str,
    provenance: str,
    requirement_backed: bool,
    source_section: str,
    aggregate_stories: bool = False,
    include_secondary: bool = True,
) -> List[RequirementItem]:
    """Non-canonical extra sections — same rules as primary where applicable."""
    items: List[RequirementItem] = []
    items.extend(_extract_user_story_items(
        text,
        doc_file=doc_file,
        unit_id=unit_id,
        unit_type=unit_type,
        provenance=provenance,
        requirement_backed=requirement_backed,
        source_section=source_section,
        aggregate_stories=aggregate_stories,
    ))
    items.extend(_extract_shall_items(
        text,
        doc_file=doc_file,
        unit_id=unit_id,
        unit_type=unit_type,
        provenance=provenance,
        requirement_backed=requirement_backed,
        source_section=source_section,
    ))
    if include_secondary:
        items.extend(_extract_gap_items(
            text,
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            provenance=provenance,
            requirement_backed=requirement_backed,
            source_section=source_section,
        ))
    return items


def _extract_section_items(
    text: str,
    *,
    doc_file: str,
    unit_id: str,
    unit_type: str,
    provenance: str,
    requirement_backed: bool,
    source_section: str,
    tier: str,
    aggregate_stories: bool = False,
    include_secondary: bool = True,
    story_texts: List[str] | None = None,
    dedupe_shall_against_stories: bool = False,
) -> List[RequirementItem]:
    key = section_key(source_section)
    if tier == "metadata":
        return []

    if key == section_key("User Stories"):
        return _extract_user_story_items(
            text,
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            provenance=provenance,
            requirement_backed=requirement_backed,
            source_section=source_section,
            aggregate_stories=aggregate_stories,
        )
    if key == section_key("Consolidated Requirements"):
        return _extract_shall_items(
            text,
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            provenance=provenance,
            requirement_backed=requirement_backed,
            source_section=source_section,
            story_texts=story_texts,
            dedupe_against_stories=dedupe_shall_against_stories,
        )
    if not include_secondary:
        return []
    if key == section_key("Function Specification"):
        return _extract_function_spec_items(
            text,
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            provenance=provenance,
            requirement_backed=requirement_backed,
            source_section=source_section,
        )
    if key == section_key("Gap Analysis"):
        return _extract_gap_items(
            text,
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            provenance=provenance,
            requirement_backed=requirement_backed,
            source_section=source_section,
        )
    if tier == "secondary":
        return _extract_extra_section_items(
            text,
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            provenance=provenance,
            requirement_backed=requirement_backed,
            source_section=source_section,
            aggregate_stories=aggregate_stories,
            include_secondary=include_secondary,
        )
    return []


def _story_texts_from_sections(
    sections: Dict,
    *,
    aggregate_stories: bool,
) -> List[str]:
    texts: List[str] = []
    for section_name, section_body in sections.items():
        if section_key(section_name) != section_key("User Stories"):
            continue
        body = str(section_body).strip()
        if not body:
            continue
        for story_id, block in _story_blocks(body):
            acs = _collect_story_acs(block)
            if not acs:
                continue
            if aggregate_stories and len(acs) > 1:
                texts.append("\n".join(body for _, body in acs))
            else:
                texts.extend(body for _, body in acs)
    return texts


def extract_items_from_doc(
    doc: Dict,
    *,
    report: ExtractionReport | None = None,
    aggregate_stories: bool = False,
    include_secondary: bool = True,
    dedupe_shall_against_stories: bool = False,
) -> List[RequirementItem]:
    """Extract tiered testable items from one requirement document."""
    doc_file = str(doc.get("_source_file") or doc.get("unit") or "requirement")
    unit_id = str(doc.get("unit") or doc_file)
    unit_type = str(doc.get("unit_type") or "")
    provenance = str(doc.get("provenance") or "code-derived")
    requirement_backed = bool(doc.get("requirement_backed", False))
    sections = doc.get("sections") or {}
    if not isinstance(sections, dict):
        sections = {}

    story_texts = (
        _story_texts_from_sections(sections, aggregate_stories=aggregate_stories)
        if dedupe_shall_against_stories
        else []
    )

    items: List[RequirementItem] = []
    for section_name, section_body in sections.items():
        body = str(section_body).strip()
        if not body or body in ("_(none)_", "(none)"):
            continue
        tier = extraction_tier(section_name)
        if tier == "metadata":
            if report is not None:
                report.sections_skipped_metadata += 1
            continue
        section_items = _extract_section_items(
            body,
            doc_file=doc_file,
            unit_id=unit_id,
            unit_type=unit_type,
            provenance=provenance,
            requirement_backed=requirement_backed,
            source_section=section_name,
            tier=tier,
            aggregate_stories=aggregate_stories,
            include_secondary=include_secondary,
            story_texts=story_texts,
            dedupe_shall_against_stories=dedupe_shall_against_stories,
        )
        items.extend(section_items)
        if report is not None:
            for item in section_items:
                if item.extraction_tier == "primary":
                    report.primary += 1
                else:
                    report.secondary += 1

    items = _dedupe_items(items)
    primary_count = sum(1 for i in items if i.extraction_tier == "primary")

    if primary_count == 0 and include_secondary and report is not None:
        report.notes.append(f"{doc_file}: no Tier-A items; applying fallback extraction")
        for section_name, section_body in sections.items():
            body = str(section_body).strip()
            if not body:
                continue
            if section_key(section_name) == section_key("Gap Analysis"):
                fallback = _extract_gap_items(
                    body,
                    doc_file=doc_file,
                    unit_id=unit_id,
                    unit_type=unit_type,
                    provenance=provenance,
                    requirement_backed=requirement_backed,
                    source_section=section_name,
                )
                for item in fallback:
                    items.append(RequirementItem(
                        item_id=item.item_id,
                        doc_file=item.doc_file,
                        unit_id=item.unit_id,
                        unit_type=item.unit_type,
                        story_id=item.story_id,
                        source_section=item.source_section,
                        verbatim_text=item.verbatim_text,
                        provenance=item.provenance,
                        requirement_backed=item.requirement_backed,
                        negative_path=item.negative_path,
                        extraction_tier="fallback",
                    ))
                    report.fallback += 1
        items = _dedupe_items(items)

    return items


def extract_items_for_agent(
    doc: Dict,
    *,
    report: ExtractionReport | None = None,
) -> List[RequirementItem]:
    """Compact primary-oracle extraction for Bedrock labelling (fast agent runs)."""
    from ..agent.config import (
        requirement_aggregate_stories,
        requirement_dedupe_shall_against_stories,
        requirement_include_secondary_for_agent,
    )

    return extract_items_from_doc(
        doc,
        report=report,
        aggregate_stories=requirement_aggregate_stories(),
        include_secondary=requirement_include_secondary_for_agent(),
        dedupe_shall_against_stories=requirement_dedupe_shall_against_stories(),
    )


def extract_items_from_docs(docs: Iterable[Dict]) -> List[RequirementItem]:
    out: List[RequirementItem] = []
    for doc in docs:
        out.extend(extract_items_from_doc(doc))
    return out


def doc_line_count(doc: Dict) -> int:
    raw = str(doc.get("raw_text") or "")
    if raw:
        return raw.count("\n") + (1 if raw else 0)
    sections = doc.get("sections") or {}
    if isinstance(sections, dict):
        return sum(str(v).count("\n") + 1 for v in sections.values())
    return 0


def doc_byte_count(doc: Dict) -> int:
    bc = doc.get("_byte_count")
    if bc:
        return int(bc)
    raw = str(doc.get("raw_text") or "")
    return len(raw.encode("utf-8"))
