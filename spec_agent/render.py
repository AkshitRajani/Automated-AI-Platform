"""
Render a per-unit ``RequirementDoc`` (assembled section-by-section by the emit tools)
into the client-style markdown document. Also exposes ``load_doc`` (parse + validate one
JSON doc) which the boundary reuses as its doc-validity gate.

The JSON file is the machine-readable artifact (what ingestion will load); the markdown
is the human-readable deliverable + the requirement_archive. Both can be any size — the
body is just the ``sections`` map, so rendering is a concatenation, with no field that
must fit a model response.
"""
from __future__ import annotations

import json
import os
from typing import List

from spec_agent.schemas import (CANONICAL_SECTIONS, RequirementDoc, section_key)


def load_doc(path: str) -> RequirementDoc:
    """Load + validate one requirement doc JSON. Raises on bad JSON / schema mismatch."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return RequirementDoc.model_validate(data)


def render_markdown(doc: RequirementDoc) -> str:
    """The client-style requirement document for one unit, as markdown. Renders the nine
    canonical sections in order (whatever the agent wrote), then any extra sections the
    agent added, then the grounded-identifiers footer."""
    # index the agent's sections by normalized name so "2. Input Specification" matches
    by_key = {section_key(k): (k, v) for k, v in doc.sections.items()}
    used: set = set()

    backed = "yes" if doc.requirement_backed else "no"
    conf = "n/a (code-derived)" if doc.confidence is None else f"{doc.confidence:g}"
    p: List[str] = []
    p.append(f"# Requirement Document: {doc.title or doc.unit}")
    p.append(f"\n**Unit:** `{doc.unit}`  ·  **Type:** {doc.unit_type or 'Unknown'}\n")
    p.append(f"**Provenance:** {doc.provenance}  ·  **Requirement-backed:** {backed}  ·  "
             f"**Confidence:** {conf}")
    p.append(f"**Grounding:** {doc.grounding or '_(not recorded)_'}\n")

    for i, canon in enumerate(CANONICAL_SECTIONS, 1):
        k = section_key(canon)
        body = ""
        if k in by_key:
            used.add(k)
            body = by_key[k][1].strip()
        p.append(f"## {i}. {canon}\n")
        p.append((body or "_(none)_") + "\n")

    # any extra sections the agent chose to add, after the canonical nine
    extras = [(k, kv) for k, kv in by_key.items() if k not in used]
    for n, (k, (orig, body)) in enumerate(extras, len(CANONICAL_SECTIONS) + 1):
        p.append(f"## {n}. {orig.strip()}\n")
        p.append((body.strip() or "_(none)_") + "\n")

    p.append("---\n**Grounded identifiers (re-checked at the boundary):** "
             + (", ".join(f"`{g}`" for g in doc.grounded_identifiers) or "_(none)_"))
    return "\n".join(p) + "\n"


def render_set(workspace_dir: str, doc_files: List[str], out_dir: str = "") -> List[str]:
    """Render every doc JSON to a markdown file. Returns the markdown paths written.
    Skips (and reports nothing for) docs that fail to load — the boundary's doc gate is
    what flags those; this is the cosmetic render pass."""
    out_dir = out_dir or os.path.join(workspace_dir, "requirements_md")
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    for rel in doc_files:
        path = rel if os.path.isabs(rel) else os.path.join(workspace_dir, rel)
        try:
            doc = load_doc(path)
        except Exception:
            continue
        slug = os.path.splitext(os.path.basename(path))[0]
        md_path = os.path.join(out_dir, slug + ".md")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(doc))
        written.append(md_path)
    return written
